r"""
Lance E6, la justesse du routage reflexif.

    python scripts\run_e6.py
    python scripts\run_e6.py --par-classe 60 --sortie resultats\e6

Utiliser `python` et non `py -3.11` : lorsqu'une version est passee
explicitement, le lanceur Windows ignore l'environnement virtuel.

L'experience ne requiert ni accelerateur ni index dense. La recuperation
interne repose sur BM25 applique au corpus bancaire, indexe a la volee :
1500 notes s'indexent en quelques secondes, et la reproductibilite y gagne,
puisque l'index mesure est celui que l'execution vient de construire et non
un artefact d'une campagne anterieure.

Le corpus EUR-Lex n'est pas indexe. Il sert uniquement a etablir la verite
terrain de la classe « externe » (les numeros d'article qui existent
reellement). Le routeur ne voit que l'interne, ce qui correspond a sa
situation reelle au moment de decider s'il faut sortir.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.commun import config as mod_config, journal as mod_journal   # noqa: E402
from src.evaluation import e6_routage as e6                          # noqa: E402
from src.index import lexical as mod_lexical                         # noqa: E402

BANQUE = "data/banque/banque_schema.json"
REFERENCE = "data/banque/banque_reference.json"
EURLEX = "data/external/eurlex/eurlex_schema.json"


def lire(chemin):
    chemin = Path(chemin)
    if not chemin.exists():
        chemin = chemin.with_suffix(".jsonl")
    if chemin.suffix == ".jsonl":
        with open(chemin, encoding="utf-8") as f:
            return [json.loads(ligne) for ligne in f if ligne.strip()]
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def main():
    parseur = argparse.ArgumentParser(description="E6 — routage reflexif")
    parseur.add_argument("--banque", default=BANQUE)
    parseur.add_argument("--reference", default=REFERENCE)
    parseur.add_argument("--eurlex", default=EURLEX)
    parseur.add_argument("--par-classe", type=int, default=40,
                         help="cas etiquetes par classe de verite terrain")
    parseur.add_argument("--fragments", type=int, default=5,
                         help="taille de la tete rapportee par BM25")
    parseur.add_argument("--seuil-pertinence", type=float, default=0.55)
    parseur.add_argument("--seuil-completude", type=float, default=0.70)
    parseur.add_argument("--seuil-vocabulaire", type=float, default=None,
                         help="part minimale du vocabulaire de la requete que "
                              "le corpus doit connaitre, appliquee AUX SEULES "
                              "requetes qui ne nomment rien. Sans ce "
                              "parametre, le routeur se comporte comme avant.")
    parseur.add_argument("--graine", type=int, default=20260902)
    parseur.add_argument("--sortie", default="resultats/e6")
    arguments = parseur.parse_args()

    interne = lire(arguments.banque)
    reference = lire(arguments.reference)
    externe = lire(arguments.eurlex)

    print(f"corpus interne  : {len(interne)} notes")
    print(f"corpus externe  : {len(externe)} documents (verite terrain "
          f"seulement, non indexe)")

    cas = e6.construire_jeu(reference, externe,
                            par_classe=arguments.par_classe,
                            graine=arguments.graine)
    repartition = {}
    for entree in cas:
        repartition[entree["classe"]] = repartition.get(entree["classe"], 0) + 1
    print(f"jeu etiquete    : {len(cas)} cas — "
          + ", ".join(f"{c} {n}" for c, n in sorted(repartition.items())))
    print(f"seuils          : pertinence {arguments.seuil_pertinence} | "
          f"completude {arguments.seuil_completude} | "
          f"fragments {arguments.fragments}\n")

    print("construction de l'index BM25 interne...")
    index = mod_lexical.IndexLexical(langue="fr").construire(interne)

    config = mod_config.Config()
    with mod_journal.Execution("e6-routage", config,
                               manifeste=[arguments.banque,
                                          arguments.reference,
                                          arguments.eurlex]) as ex:
        rapport = e6.campagne(cas, index,
                              seuil_pertinence=arguments.seuil_pertinence,
                              seuil_completude=arguments.seuil_completude,
                              n=arguments.fragments,
                              seuil_vocabulaire=arguments.seuil_vocabulaire)
        mesures = rapport["mesures"]

        def pourcent(valeur):
            return "—" if valeur is None else f"{valeur:.1%}"

        print("=== LES TROIS GRANDEURS ===")
        print("Elles ne sont pas interchangeables et ne s'agregent pas :")
        print("rater une source externe degrade la reponse, sortir")
        print("inutilement expose la requete.\n")
        print(f"  decision correcte            : "
              f"{pourcent(mesures['taux_decision_correcte'])}")
        print(f"  franchissement INJUSTIFIE    : "
              f"{pourcent(mesures['taux_franchissement_injustifie'])}"
              f"   (sort alors que l'interne suffisait)")
        print(f"  franchissement manque        : "
              f"{pourcent(mesures['taux_franchissement_manque'])}"
              f"   (reste dedans alors qu'il fallait sortir)")
        print(f"  abstention correcte          : "
              f"{pourcent(mesures['taux_abstention_correcte'])}")
        print(f"  abstention indue             : "
              f"{pourcent(mesures['taux_abstention_indue'])}")
        print(f"  passe par une correction     : "
              f"{pourcent(mesures['part_passee_par_correction'])}")
        print(f"  sorties infructueuses        : "
              f"{pourcent(mesures['sorties_infructueuses'])}"
              f"   (classe absente : sortie sans reponse au bout)")

        print("\n=== LES MEMES, SUR LES SEULES REQUETES DIFFICILES ===")
        print("Celles qui DECRIVENT au lieu de nommer. Une requete qui cite")
        print("la cle de son dossier est retrouvee mot pour mot par BM25 :")
        print("le routage y est trivial et le chiffre global le masque.\n")
        print(f"  franchissement injustifie    : "
              f"{pourcent(mesures['franchissement_injustifie_sur_decrit'])}"
              f"   (interne decrit sans etre nomme)")
        print(f"  franchissement manque        : "
              f"{pourcent(mesures['franchissement_manque_sur_implicite'])}"
              f"   (reglementaire, texte non nomme)")

        print("\n=== PAR CLASSE DE VERITE TERRAIN ===")
        print("Le label dit OU se trouve la reponse, jamais ce que le")
        print("routeur devrait decider.\n")
        for classe, valeurs in mesures["par_classe"].items():
            print(f"  {classe:<24} {valeurs['cas']:>4} cas   "
                  f"correct {valeurs['taux_correct']:.1%}")

        print("\n=== MATRICE classe -> issue ===")
        for cle, nombre in mesures["matrice"].items():
            print(f"  {cle:<46} {nombre:>4}")

        for nom, valeur in mesures.items():
            if isinstance(valeur, float):
                ex.mesure(nom, valeur)

        chemin = Path(arguments.sortie)
        chemin.mkdir(parents=True, exist_ok=True)
        with open(chemin / "e6_routage.json", "w", encoding="utf-8") as f:
            json.dump({"parametres": vars(arguments), **rapport},
                      f, ensure_ascii=False, indent=2)
        with open(ex.dossier / "e6_routage.json", "w", encoding="utf-8") as f:
            json.dump({"parametres": vars(arguments), **rapport},
                      f, ensure_ascii=False, indent=2)
        print(f"\necrit : {chemin}/ et {ex.dossier}/")


if __name__ == "__main__":
    main()
