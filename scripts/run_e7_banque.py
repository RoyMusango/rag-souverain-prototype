r"""
E7b : detecteurs sur le corpus interne bancaire, resultats par categorie.

    python scripts\run_e7_banque.py --moteurs spacy,presidio

Ce script est volontairement separe de run_e7.py, qui fonctionne et mesure
Synthea, pour ne pas risquer de le casser.

CE QU'IL APPORTE PAR RAPPORT A run_e7.py

Synthea ne contient aucun identifiant bancaire. Le rappel mesure par E7 sur
Synthea (0,895) porte donc seulement sur la partie statistique (noms,
lieux, organisations). On ne peut pas le prendre pour la performance de
toute la chaine.

Le corpus bancaire contient les deux familles. Le detail par categorie
montre qu'elles se completent :

    PERSONNE, LIEU, ORGANISATION   le modele statistique, rappel partiel
    IBAN, CARTE, IDENTIFIANT       les motifs deterministes, rappel attendu 1

Le resultat utile est le tableau par categorie. Le rappel global melange
les deux familles.

METHODE

La verite terrain vient du generateur : chaque note est ecrite a partir
d'un enregistrement structure, donc on connait exactement les chaines
sensibles et leur categorie. On ne les cherche pas apres coup.

Pour mesurer une categorie, on ne garde que ses entites dans la reference.
Les detections des autres categories comptent alors comme faux positifs, et
la precision par categorie ne voudrait rien dire. Je donne donc le rappel
par categorie, et la precision seulement au niveau global.
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

    Regrouper par client plutot que par note ne fausse rien :
    `positions_attendues` cherche les chaines dans le texte, donc une chaine
    absente d'une note n'y est simplement pas trouvee.
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
        description="E7b : detecteurs sur le corpus bancaire")
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
          f"trouvees dans les notes, plus grand que ce compte)")
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
                # global, on veut savoir si l'entite a ete masquee. Une entite
                # masquee avec la mauvaise etiquette ne franchit pas la
                # frontiere. La mesure porte donc sur `reference_totale`,
                # toutes categories confondues, sans exiger l'etiquette.
                mesure = e7.evaluer_moteur(documents, reference_totale, nom,
                                           arguments.langue, arguments.seuil)
            except Exception as erreur:
                print(f"{nom:<12} INDISPONIBLE : {str(erreur)[:60]}")
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

        # ---- detail par categorie ------------------------------------------
        # Resultat principal de cette campagne. Le rappel global melange deux
        # familles de detection qui ne fonctionnent pas pareil et n'offrent
        # pas la meme garantie. Seul le detail permet de les separer.
        print(f"\n{'categorie':<16} {'attendus':>9} "
              + " ".join(f"{n:>10}" for n in disponibles))
        print("-" * (26 + 11 * len(disponibles)))

        par_categorie = {}
        for categorie in categories:
            reference_cat = reference_par_client(reference_brute, {categorie})
            # `reference_par_client` enleve les doublons (chaine, categorie)
            # par client : il compte les chaines distinctes, 2400 sur ce
            # corpus. Or `positions_attendues` trouve chaque occurrence dans
            # chacune des cinq notes du dossier, et c'est ce second compte
            # (6900) qui sert de denominateur au rappel. Publier le premier
            # rendait le detail incoherent avec le global : la moyenne
            # ponderee des rappels par categorie donnait 0,890 pour un global
            # de 0,923. On publie maintenant le compte de la mesure, et les
            # chaines distinctes a part.
            chaines_distinctes = sum(len(r["attendus"]) for r in reference_cat)
            attendus = None
            ligne = {}
            for nom in disponibles:
                # `categorie_stricte=True` ici, et seulement ici. Ce tableau
                # est par categorie : l'etiquette fait partie de ce qu'on
                # mesure, il faut donc l'exiger. Sans cela, Presidio etait
                # credite de 76 ORGANISATION sur 600 alors qu'il n'en
                # produisait aucune : les empans etaient couverts par des
                # detections d'un autre type.
                mesure = e7.evaluer_moteur(documents, reference_cat, nom,
                                           arguments.langue, arguments.seuil,
                                           categorie_stricte=True)
                ligne[nom] = mesure["rappel"]
                # `reference` ne depend pas du moteur : le texte et la
                # reference sont les memes. Si la valeur change selon le
                # moteur, il y a un probleme plus haut.
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
                f"{ligne[n]:>10.3f}" if ligne[n] is not None else f"{'-':>10}"
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
                "modele statistique pour les noms, lieux et organisations, "
                "des motifs deterministes pour les identifiants. Seul le "
                "detail par categorie les separe, et montre que les deux se "
                "completent. La precision n'est donnee qu'au niveau global : "
                "si on ne garde qu'une categorie dans la reference, les "
                "detections des autres comptent comme faux positifs."
            ),
        }
        with open(ex.dossier / "e7b_banque.json", "w", encoding="utf-8") as f:
            json.dump(rapport, f, ensure_ascii=False, indent=2)
        print(f"\necrit : {ex.dossier}")


if __name__ == "__main__":
    main()
