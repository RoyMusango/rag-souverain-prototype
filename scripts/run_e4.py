r"""
Lance E4, l'attribuabilite.

    python scripts\run_e4.py
    python scripts\run_e4.py --questions 200 --corpus eurlex

Utiliser `python` et non `py -3.11`.

OBJET DE LA CAMPAGNE

L'invariant I3 exige que toute assertion soit rattachable a sa source, avec
un niveau de confiance. E4 mesure dans quelle proportion cette exigence est
satisfaite, et a quelle profondeur : document, rubrique, page, pave.

DEUX MESURES DISTINCTES

La premiere ne requiert aucun modele de langue. Elle verifie que la chaine de
provenance n'est pas rompue entre l'index et la recherche : chaque fragment
rapporte porte-t-il ses quatre niveaux d'adresse ? Elle couvre la menace de
« rupture de chaine », perte silencieuse du lien vers la source, sans
adversaire actif, qui viole I3 sans aucun signal. Elle peut etre executee
des que l'index existe.

La seconde requiert le moteur complet, donc un modele de langue. Elle mesure
la part des assertions produites rattachees a un pave. Elle est activee par
--avec-generation.

Par defaut, seule la premiere est executee : elle conditionne la seconde, et
un taux d'integrite degrade rendrait celle-ci ininterpretable.

LIMITE

Cinq corpus sur six ont page = 1, un courriel ou un resume d'article n'ayant
pas de pagination native. Seul EUR-Lex instancie effectivement les quatre
niveaux : la mesure a quatre niveaux repose sur lui, celle a trois niveaux
sur les autres. Le module les separe plutot que de melanger des chiffres non
comparables, et ce script rapporte les deux.

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
# Un index lexical par corpus. Le corpus choisi restreint aussi la voie
# dense au meme vivier.
#
# EUR-Lex ne dispose pas de paires question-reponse, ce qui n'est pas un
# obstacle ici : les questions servent uniquement a provoquer des
# recuperations, et la mesure porte sur les fragments rapportes, non sur leur
# pertinence. C'est le seul corpus dont la pagination est native, donc le
# seul ou la profondeur d'adresse soit reellement discriminante.
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
                         help="corpus inspecte ; eurlex est le seul dont "
                              "la pagination soit native")
    parseur.add_argument("--avec-generation", action="store_true",
                         help="mesurer aussi les assertions produites ; "
                              "exige un modele de langue configure")
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
        print("Chaque fragment rapporte porte-t-il ses quatre niveaux")
        print("d'adresse ? Une perte a cet endroit viole I3 en silence.\n")

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
        print("Le niveau 4 suppose une pagination reelle. Cinq corpus sur")
        print("six ont page = 1 par nature, ce n'est pas un defaut.\n")
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
                "survit au passage de l'index a la recherche. Le taux a "
                "quatre niveaux n'est interpretable que sur les corpus a "
                "pagination reelle, EUR-Lex en pratique ; ailleurs, trois "
                "niveaux sont le maximum atteignable et ce n'est pas une "
                "defaillance."
            ),
        }

        # --- mesure 2 : assertions produites, si demandee -------------------
        if arguments.avec_generation:
            print("\n=== ATTRIBUABILITE DES ASSERTIONS PRODUITES ===")
            try:
                from src import pipeline as mod_pipeline
            except ImportError as erreur:
                raise SystemExit(f"pipeline indisponible : {erreur}")

            # Le moteur recoit toutes ses dependances par injection. Seuls la
            # recuperation interne et le fournisseur sont utiles ici : le
            # routage et la politique de confidentialite sont mesures par E6
            # et E2, et les inclure rendrait le taux d'attribuabilite
            # dependant de decisions qui lui sont etrangeres.
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
            print("Elle exige un modele de langue : relancez avec")
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
