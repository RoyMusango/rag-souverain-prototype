r"""
Lance E4, l'attribuabilite.

    python scripts\run_e4.py
    python scripts\run_e4.py --questions 200 --corpus eurlex

Utiliser `python` et non `py -3.11`.

BUT DE LA CAMPAGNE

L'invariant I3 demande que chaque assertion puisse etre rattachee a sa
source, avec un niveau de confiance. E4 mesure dans quelle proportion c'est
le cas, et a quelle profondeur : document, rubrique, page, pave.

DEUX MESURES

La premiere n'a besoin d'aucun modele de langue. Elle verifie que la chaine
de provenance n'est pas cassee entre l'index et la recherche : chaque
fragment rapporte a-t-il ses quatre niveaux d'adresse ? Elle correspond a
la menace « rupture de chaine » : le lien vers la source se perd, sans
attaquant, et I3 est viole sans que rien ne le signale. On peut la lancer
des que l'index existe.

La seconde a besoin du moteur complet, donc d'un modele de langue. Elle
mesure la part des assertions produites qui sont rattachees a un pave. On
l'active avec --avec-generation.

Par defaut, seule la premiere tourne. La seconde en depend : si la chaine
est cassee, son resultat ne veut rien dire.

LIMITE

Tous les corpus sauf EUR-Lex ont page = 1, car un courriel ou un resume
d'article n'a pas de pages. Seul EUR-Lex utilise vraiment les quatre
niveaux. La mesure a quatre niveaux se fait donc sur EUR-Lex, celle a trois
niveaux sur les autres. Le module les garde separees, et ce script donne
les deux.

PREREQUIS. L'index dense doit exister (voir scripts\build_index.py).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.commun import config as mod_config, journal as mod_journal   # noqa: E402
from src.evaluation import e1_hybridation as e1                       # noqa: E402
from src.evaluation import e4_provenance as e4                        # noqa: E402
from src.evaluation import montage_gpu as montage                     # noqa: E402

PAIRES = "data/enronqa/enronqa_qa.jsonl"
# Un index lexical par corpus. Le corpus choisi limite aussi la voie dense
# aux memes documents.
#
# EUR-Lex n'a pas de paires question-reponse. Ici, cela ne gene pas : les
# questions servent seulement a declencher des recherches, et on mesure les
# fragments rapportes, pas leur pertinence. C'est le seul corpus qui a de
# vraies pages, donc le seul ou la profondeur d'adresse fait une difference.
INDEX_LEXICAL = {
    "enronqa": "data/index_lexical/enronqa.pkl",
    "eurlex": "data/index_lexical/eurlex.pkl",
    "finqa": "data/index_lexical/finqa.pkl",
    "banque": "data/index_lexical/banque.pkl",
}


def main():
    parseur = argparse.ArgumentParser(description="E4, attribuabilite")
    parseur.add_argument("--paires", default=PAIRES)
    parseur.add_argument("--index-lexical", default=None,
                         help="par defaut, deduit du corpus")
    parseur.add_argument("--index-fichier", default=None)
    parseur.add_argument("--hote", default=None)
    parseur.add_argument("--questions", type=int, default=200)
    parseur.add_argument("--n-fragments", type=int, default=10,
                         help="fragments rapportes par question")
    parseur.add_argument("--graine", type=int, default=42)
    parseur.add_argument("--peripherique", default=None)
    parseur.add_argument("--corpus", choices=tuple(INDEX_LEXICAL),
                         default="enronqa",
                         help="corpus inspecte ; eurlex est le seul qui a de "
                              "vraies pages")
    parseur.add_argument("--avec-generation", action="store_true",
                         help="mesurer aussi les assertions produites ; "
                              "demande un modele de langue configure")
    parseur.add_argument("--sortie", default="resultats/e4")
    arguments = parseur.parse_args()

    config = mod_config.Config()

    chemin_paires = Path(arguments.paires)
    if not chemin_paires.exists():
        raise SystemExit(f"introuvable : {chemin_paires}")

    paires = e1.charger_paires(chemin_paires)
    echantillon = e1.echantillonner(paires, arguments.questions,
                                    arguments.graine)
    print(f"corpus inspecte    : {arguments.corpus}")
    print(f"questions retenues : {len(echantillon)}")

    try:
        vectoriseur = montage.charger_vectoriseur(
            config, peripherique=arguments.peripherique)
        index_dense = montage.charger_index_dense(
            config, hote=arguments.hote,
            chemin_local=arguments.index_fichier)
        index_lexical = montage.charger_index_lexical(
            arguments.index_lexical or INDEX_LEXICAL[arguments.corpus])
    except montage.ChaineIndisponible as erreur:
        raise SystemExit(f"\n{erreur}")

    fabrique = montage.fabrique(config, index_dense, index_lexical,
                                vectoriseur, reclasseur=None,
                                corpus=arguments.corpus)
    recuperateur = fabrique(montage.FUSION)
    if recuperateur is None:
        raise SystemExit("la configuration 'fusion' n'a pas pu etre montee.")

    print(f"peripherique       : {vectoriseur.peripherique} / "
          f"{vectoriseur.precision}")
    print()

    with mod_journal.Execution("e4-provenance", config,
                               manifeste=[str(chemin_paires)]) as ex:
        ex.evenement("montage", **montage.decrire(
            vectoriseur, index_dense, index_lexical, None))

        # --- mesure 1 : integrite de la chaine ------------------------------
        print("=== INTEGRITE DE LA CHAINE DE PROVENANCE ===")
        print("Chaque fragment rapporte a-t-il ses quatre niveaux d'adresse ?")
        print("Une perte ici viole I3 sans aucun message.\n")

        fragments = []
        for rang, paire in enumerate(echantillon, start=1):
            fragments.extend(recuperateur.rechercher(
                paire["question"], n=arguments.n_fragments,
                avec_teinte=False))
            print(f"  question {rang}/{len(echantillon)}", end="\r")
        print(" " * 40, end="\r")

        integrite = e4.verifier_chaine(fragments)
        print(f"  fragments inspectes : {integrite['fragments']}")
        print(f"  ruptures            : {integrite['ruptures']}")
        taux = integrite["taux_integrite"]
        print(f"  taux d'integrite    : "
              f"{taux:.4f}" if taux is not None else "  taux : indefini")
        if integrite["exemples"]:
            print("\n  exemples de rupture :")
            for exemple in integrite["exemples"]:
                print(f"    {exemple['doc_id']}  manquants : "
                      f"{', '.join(exemple['manquants'])}")
        ex.mesure("integrite.taux", taux or 0.0)

        # --- profondeur reellement atteinte, par corpus ---------------------
        quatre_niveaux = e4.corpus_a_quatre_niveaux(fragments)
        repartition = {}
        for fragment in fragments:
            repartition[e4.profondeur(fragment)] = repartition.get(
                e4.profondeur(fragment), 0) + 1

        print("\n=== PROFONDEUR D'ADRESSE ATTEINTE ===")
        print("Le niveau 4 suppose de vraies pages. Tous les corpus sauf")
        print("EUR-Lex ont page = 1, c'est normal.\n")
        total = len(fragments) or 1
        for niveau in sorted(repartition):
            print(f"  {niveau} niveau(x) sur 4 : {repartition[niveau]:>6} "
                  f"fragments  ({repartition[niveau] / total:.1%})")
        print(f"\n  corpus a pagination reelle : "
              f"{', '.join(sorted(quatre_niveaux)) or 'aucun detecte'}")

        rapport = {
            "questions": len(echantillon),
            "integrite_chaine": integrite,
            "repartition_profondeur": repartition,
            "corpus_a_quatre_niveaux": sorted(quatre_niveaux),
            "attribuabilite": None,
            "lecture": (
                "L'integrite de la chaine mesure si le lien vers la source "
                "est conserve entre l'index et la recherche. Le taux a "
                "quatre niveaux n'a de sens que sur les corpus qui ont de "
                "vraies pages, EUR-Lex en pratique. Ailleurs, trois niveaux "
                "sont le maximum possible."
            ),
        }

        # --- mesure 2 : assertions produites, si demandee -------------------
        if arguments.avec_generation:
            print("\n=== ATTRIBUABILITE DES ASSERTIONS PRODUITES ===")
            try:
                from src import pipeline as mod_pipeline
            except ImportError as erreur:
                raise SystemExit(f"pipeline indisponible : {erreur}")

            # Le moteur recoit tous ses composants en argument. Ici, seuls la
            # recherche interne et le fournisseur servent : le routage et la
            # politique de confidentialite sont mesures par E6 et E2. Les
            # ajouter ferait dependre le taux d'attribuabilite de decisions
            # qui n'ont rien a voir avec lui.
            moteur = mod_pipeline.Moteur(config=config,
                                         recuperateur_interne=recuperateur)
            reponses = []
            for rang, paire in enumerate(echantillon, start=1):
                contexte = mod_pipeline.Contexte(
                    requete=paire["question"], a_enjeu=False)
                try:
                    resultat = moteur.repondre(contexte)
                    if resultat.reponse is not None:
                        reponses.append(resultat.reponse)
                except Exception as erreur:
                    print(f"\n  question {rang} en echec : "
                          f"{str(erreur)[:80]}")
                    break
                print(f"  question {rang}/{len(echantillon)}", end="\r")
            print(" " * 40, end="\r")

            if reponses:
                attribuabilite = e4.evaluer(reponses)
                rapport["attribuabilite"] = attribuabilite
                if attribuabilite.get("comparable"):
                    print(f"  assertions            : "
                          f"{attribuabilite['assertions']}")
                    print(f"  taux d'attribuabilite : "
                          f"{attribuabilite['taux_attribuabilite']:.4f}")
                    print(f"  dont a quatre niveaux : "
                          f"{attribuabilite['taux_quatre_niveaux']:.4f}")
                    ex.mesure("attribuabilite.taux",
                              attribuabilite["taux_attribuabilite"])
                else:
                    print(f"  non comparable : {attribuabilite.get('motif')}")
        else:
            print("\nLa mesure des assertions produites n'a pas ete faite.")
            print("Elle demande un modele de langue : relancez avec")
            print("--avec-generation une fois le fournisseur configure.")

        chemin = Path(arguments.sortie)
        chemin.mkdir(parents=True, exist_ok=True)
        for destination in (chemin, ex.dossier):
            with open(destination / "e4_provenance.json", "w",
                      encoding="utf-8") as f:
                json.dump({"parametres": vars(arguments), **rapport},
                          f, ensure_ascii=False, indent=2)
        print(f"\necrit : {chemin}/ et {ex.dossier}/")


if __name__ == "__main__":
    main()
