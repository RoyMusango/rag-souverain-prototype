r"""
E7b : detecteurs sur le corpus interne bancaire, ventiles par categorie.

    python scripts\run_e7_banque.py --moteurs spacy,presidio

J'ai volontairement separe ce script de run_e7.py, qui fonctionne et mesure
Synthea, afin de ne pas le fragiliser.

APPORT PAR RAPPORT A run_e7.py

Synthea ne contient aucun identifiant bancaire. Le rappel de 0,633 qu'y
mesure E7 porte donc sur le seul etage statistique (noms, lieux,
organisations) et serait lu a tort comme la performance de la chaine
complete.

Le corpus bancaire contient les deux familles. La ventilation par categorie
montre qu'elles sont complementaires et non redondantes :

    PERSONNE, LIEU, ORGANISATION   le modele statistique, rappel partiel
    IBAN, CARTE, IDENTIFIANT       les motifs deterministes, rappel attendu 1

Le resultat pertinent n'est pas le rappel global, qui melange les deux
familles, mais le tableau par categorie.

METHODE

La verite terrain provient du generateur : chaque note est composee a partir
d'un enregistrement structure, et les chaines sensibles ainsi que leur
categorie sont donc connues exactement. Les entites ne sont pas recherchees
apres coup.

La ventilation procede par restriction : pour mesurer une categorie, seules
les entites de cette categorie sont conservees dans la reference. Les
detections portant sur d'autres categories comptent alors comme faux
positifs, ce qui rendrait la precision par categorie ininterpretable ; je ne
rapporte donc que le rappel par categorie, et la precision au niveau global.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.commun import config as mod_config, journal as mod_journal   # noqa: E402
from src.evaluation import e7_masquage as e7                          # noqa: E402

SCHEMA = "data/banque/banque_schema.json"
REFERENCE = "data/banque/banque_reference.json"

STATISTIQUES = ("PERSONNE", "LIEU", "ORGANISATION")
DETERMINISTES = ("IBAN", "CARTE", "IDENTIFIANT")


def lire(chemin):
    chemin = Path(chemin)
    if not chemin.exists():
        chemin = chemin.with_suffix(".jsonl")
    if chemin.suffix == ".jsonl":
        with open(chemin, encoding="utf-8") as f:
            return [json.loads(ligne) for ligne in f if ligne.strip()]
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def reference_par_client(reference, categories=None):
    """Convertit la reference par document en reference par client.

    `e7_masquage.evaluer_moteur` attend [{"patient": cle, "attendus": [...]}]
    et retrouve la cle dans le deuxieme segment du doc_id. Le doc_id bancaire
    est `banque/<client>/<nature>` : le deuxieme segment est donc le client.

    Le regroupement par client plutot que par note ne fausse rien : les
    chaines absentes d'une note donnee ne sont pas localisees par
    `positions_attendues`, qui procede par recherche dans le texte.
    """
    groupes = defaultdict(set)
    for entree in reference:
        morceaux = entree["doc_id"].split("/")
        if len(morceaux) < 2:
            continue
        for attendu in entree["attendus"]:
            if categories and attendu["categorie"] not in categories:
                continue
            groupes[morceaux[1]].add(
                (attendu["chaine"], attendu["categorie"]))

    return [{"patient": cle, "attendus": sorted(valeurs)}
            for cle, valeurs in sorted(groupes.items())]


def main():
    parseur = argparse.ArgumentParser(
        description="E7b — detecteurs sur le corpus bancaire")
    parseur.add_argument("--moteurs", default="spacy,presidio",
                         help="spacy,camembert,presidio")
    parseur.add_argument("--langue", default="fr")
    parseur.add_argument("--seuil", type=float, default=0.5)
    parseur.add_argument("--schema", default=SCHEMA)
    parseur.add_argument("--reference", default=REFERENCE)
    parseur.add_argument("--documents", type=int, default=None,
                         help="limite le nombre de notes (mise au point)")
    arguments = parseur.parse_args()

    documents = lire(arguments.schema)
    if arguments.documents:
        documents = documents[:arguments.documents]
    reference_brute = lire(arguments.reference)

    reference_totale = reference_par_client(reference_brute)
    categories = sorted({a["categorie"] for e in reference_brute
                         for a in e["attendus"]})

    attendus_total = sum(len(r["attendus"]) for r in reference_totale)
    print(f"notes                 : {len(documents)}")
    print(f"dossiers              : {len(reference_totale)}")
    print(f"chaines distinctes    : {attendus_total}")
    print(f"   (le denominateur du rappel est le nombre d'OCCURRENCES "
          f"localisees dans les notes, superieur a ce compte)")
    print(f"categories            : {', '.join(categories)}\n")

    moteurs = tuple(m.strip() for m in arguments.moteurs.split(","))
    config = mod_config.Config()

    with mod_journal.Execution("e7b-banque", config,
                               manifeste=[arguments.schema,
                                          arguments.reference]) as ex:

        # ---- mesure globale ------------------------------------------------
        global_ = {}
        print(f"{'moteur':<12} {'rappel':>8} {'precis.':>8} {'F1':>8} "
              f"{'debit c/s':>10}")
        print("-" * 50)
        for nom in moteurs:
            try:
                # Pas de `categorie_stricte` ici, volontairement : au niveau
                # global, la question est de savoir si l'entite a ete masquee.
                # Une entite masquee sous une etiquette erronee ne franchit
                # pas la frontiere. La mesure porte donc sur
                # `reference_totale`, toutes categories confondues, avec un
                # appariement permissif.
                mesure = e7.evaluer_moteur(documents, reference_totale, nom,
                                           arguments.langue, arguments.seuil)
            except Exception as erreur:
                print(f"{nom:<12} INDISPONIBLE — {str(erreur)[:60]}")
                global_[nom] = {"erreur": str(erreur)}
                continue
            global_[nom] = mesure
            print(f"{nom:<12} {mesure['rappel']:>8.3f} "
                  f"{mesure['precision']:>8.3f} {mesure['f1']:>8.3f} "
                  f"{mesure['debit_car_s']:>10,}")
            ex.mesure(f"{nom}.rappel", mesure["rappel"])
            ex.mesure(f"{nom}.precision", mesure["precision"])

        disponibles = [n for n in moteurs if "erreur" not in global_.get(n, {})]
        if not disponibles:
            raise SystemExit(
                "\nAucun moteur disponible. Verifiez l'installation de spaCy "
                "et de Presidio, et le modele de la langue demandee.")

        # ---- ventilation par categorie -------------------------------------
        # Resultat principal de cette campagne. Le rappel global melange deux
        # familles de detection dont ni le mecanisme ni la garantie ne sont
        # les memes ; seul le detail permet de les distinguer.
        print(f"\n{'categorie':<16} {'attendus':>9} "
              + " ".join(f"{n:>10}" for n in disponibles))
        print("-" * (26 + 11 * len(disponibles)))

        par_categorie = {}
        for categorie in categories:
            reference_cat = reference_par_client(reference_brute, {categorie})
            # `reference_par_client` deduplique par (chaine, categorie) dans
            # un ensemble, et par client : il compte les chaines distinctes,
            # 2400 sur ce corpus. Or `positions_attendues` localise chaque
            # occurrence dans chacune des cinq notes du dossier, et c'est ce
            # second compte (6900) qui sert de denominateur au rappel. Publier
            # le premier rendait la ventilation incoherente avec le global :
            # la moyenne ponderee des rappels par categorie donnait 0,890 pour
            # un global de 0,923. Le compte publie est desormais celui de la
            # mesure, et les chaines distinctes sont conservees a part.
            chaines_distinctes = sum(len(r["attendus"]) for r in reference_cat)
            attendus = None
            ligne = {}
            for nom in disponibles:
                # `categorie_stricte=True` ici, et seulement ici. Ce tableau
                # attribue des categories : l'etiquette devient l'objet de la
                # mesure, et l'appariement doit donc l'exiger. Un appariement
                # permissif creditait Presidio de 76 ORGANISATION sur 600
                # alors qu'il n'en emettait aucune, les empans etant couverts
                # par des detections d'un autre type.
                mesure = e7.evaluer_moteur(documents, reference_cat, nom,
                                           arguments.langue, arguments.seuil,
                                           categorie_stricte=True)
                ligne[nom] = mesure["rappel"]
                # `reference` ne depend pas du moteur : le texte et la
                # reference sont les memes. Des valeurs differentes selon le
                # moteur signaleraient une anomalie en amont.
                if attendus is not None and mesure["reference"] != attendus:
                    raise RuntimeError(
                        f"denominateur instable sur {categorie} : "
                        f"{attendus} puis {mesure['reference']}")
                attendus = mesure["reference"]
                ex.mesure(f"{nom}.rappel.{categorie.lower()}",
                          mesure["rappel"])
            par_categorie[categorie] = {
                "attendus": attendus,
                "chaines_distinctes": chaines_distinctes,
                "rappel": ligne,
            }
            valeurs = " ".join(
                f"{ligne[n]:>10.3f}" if ligne[n] is not None else f"{'—':>10}"
                for n in disponibles)
            print(f"{categorie:<16} {attendus:>9} {valeurs}")

        # ---- lecture par famille -------------------------------------------
        print("\nrappel moyen par famille de detection :")
        for nom in disponibles:
            stat = [par_categorie[c]["rappel"][nom] for c in STATISTIQUES
                    if c in par_categorie
                    and par_categorie[c]["rappel"][nom] is not None]
            det = [par_categorie[c]["rappel"][nom] for c in DETERMINISTES
                   if c in par_categorie
                   and par_categorie[c]["rappel"][nom] is not None]
            moy_stat = sum(stat) / len(stat) if stat else None
            moy_det = sum(det) / len(det) if det else None
            print(f"  {nom:<12} statistique {moy_stat:.3f}   "
                  f"deterministe {moy_det:.3f}"
                  if moy_stat is not None and moy_det is not None
                  else f"  {nom:<12} incomplet")

        rapport = {
            "corpus": {
                "notes": len(documents),
                "dossiers": len(reference_totale),
                # Le denominateur du rappel, lu sur la mesure globale.
                "attendus": next((m["reference"] for m in global_.values()
                                  if "erreur" not in m), None),
                "chaines_distinctes": attendus_total,
            },
            "global": global_,
            "par_categorie": par_categorie,
            "lecture": (
                "Le rappel global melange deux familles de detection : un "
                "modele statistique sur les entites linguistiques, des motifs "
                "deterministes sur les identifiants. Seule la ventilation par "
                "categorie les separe, et c'est elle qui etablit que les deux "
                "etages sont complementaires plutot que redondants. La "
                "precision n'est rapportee qu'au niveau global : restreindre "
                "la reference a une categorie fait compter comme faux "
                "positives les detections des autres categories."
            ),
        }
        with open(ex.dossier / "e7b_banque.json", "w", encoding="utf-8") as f:
            json.dump(rapport, f, ensure_ascii=False, indent=2)
        print(f"\necrit : {ex.dossier}")


if __name__ == "__main__":
    main()
