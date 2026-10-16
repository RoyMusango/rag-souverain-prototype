r"""
Lance E6, la justesse du routage reflexif.

    python scripts\run_e6.py
    python scripts\run_e6.py --par-classe 60 --sortie resultats\e6

Utiliser `python` et non `py -3.11` : quand on donne une version, le
lanceur Windows ignore l'environnement virtuel.

L'experience n'a besoin ni de GPU ni d'index dense. La recherche interne
utilise BM25 sur le corpus bancaire, indexe au lancement : 1500 notes
s'indexent en quelques secondes. C'est aussi plus reproductible, car on
mesure l'index que l'execution vient de construire, et pas un fichier
d'une ancienne campagne.

Le corpus EUR-Lex n'est pas indexe. Il sert seulement a construire la
verite terrain de la classe « externe » (les numeros d'article qui
existent vraiment). Le routeur ne voit que l'interne, comme en vrai au
moment ou il decide s'il faut sortir.
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
    parseur = argparse.ArgumentParser(description="E6 : routage reflexif")
    parseur.add_argument("--banque", default=BANQUE)
    parseur.add_argument("--reference", default=REFERENCE)
    parseur.add_argument("--eurlex", default=EURLEX)
    parseur.add_argument("--par-classe", type=int, default=40,
                         help="cas etiquetes par classe de verite terrain")
    parseur.add_argument("--fragments", type=int, default=5,
                         help="nombre de resultats rapportes par BM25")
    parseur.add_argument("--seuil-pertinence", type=float, default=0.55)
    parseur.add_argument("--seuil-completude", type=float, default=0.70)
    parseur.add_argument("--seuil-vocabulaire", type=float, default=None,
                         help="part minimale des mots de la requete que le "
                              "corpus doit connaitre, appliquee SEULEMENT aux "
                              "requetes qui ne nomment rien. Sans ce "
                              "parametre, le routeur fonctionne comme avant.")
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
    print(f"jeu etiquete    : {len(cas)} cas : "
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
            return "-" if valeur is None else f"{valeur:.1%}"

        print("=== LES TROIS MESURES ===")
        print("Elles restent separees : rater une source externe donne une")
        print("moins bonne reponse, sortir pour rien expose la requete.\n")
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

        print("\n=== LES MEMES, SUR LES REQUETES DIFFICILES SEULEMENT ===")
        print("Celles qui DECRIVENT sans nommer. BM25 retrouve mot pour mot")
        print("une requete qui cite la cle de son dossier : le routage y est")
        print("facile, et le chiffre global le cache.\n")
        print(f"  franchissement injustifie    : "
              f"{pourcent(mesures['franchissement_injustifie_sur_decrit'])}"
              f"   (interne decrit sans etre nomme)")
        print(f"  franchissement manque        : "
              f"{pourcent(mesures['franchissement_manque_sur_implicite'])}"
              f"   (reglementaire, texte non nomme)")

        print("\n=== PAR CLASSE DE VERITE TERRAIN ===")
        print("Le label dit OU se trouve la reponse, pas ce que le routeur")
        print("devrait decider.\n")
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
