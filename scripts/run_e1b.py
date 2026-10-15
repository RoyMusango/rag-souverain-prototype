r"""
Lance E1b, l'apport de l'hybridation.

    python scripts\run_e1b.py
    python scripts\run_e1b.py --questions 200 --k 10

Utiliser `python` et non `py -3.11` : lorsqu'une version est passee
explicitement, le lanceur Windows ignore l'environnement virtuel.

OBJET DE LA CAMPAGNE

Le chapitre 2 soutient que les versants lexical et dense sont
complementaires par nature : BM25 apparie les jetons exacts, le bi-encodeur
absorbe les reformulations. E1b verifie cette hypothese au lieu de la
postuler, sur quatre configurations et les memes questions :

    dense       le bi-encodeur seul
    lexical     BM25 seul
    fusion      les deux, fusionnes par rangs reciproques
    complet     la fusion, puis re-classement par cross-encodeur

Un apport nul de la fusion sur ces corpus serait un resultat a part entiere :
il signifierait que l'un des deux versants suffit, ce qui simplifierait le
deploiement.

PREREQUIS

L'index dense doit exister. Il se construit une fois, sur GPU :

    python scripts\build_index.py --corpus tous --tranche 5000

Cette construction represente l'essentiel du calcul, environ 235 heures de
processeur sans accelerateur pour les 422 189 passages du dispositif ; c'est
elle, et non cette campagne, qui justifie la location d'une machine. E1b ne
demande que quelques minutes une fois l'index en place.

PERIMETRE. Les embeddings sont calcules localement, sur la machine qui
execute ce code. Une machine louee est un substrat de calcul et non un
service d'embeddings distant : aucun vecteur ne franchit la Frontiere A.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.commun import config as mod_config, journal as mod_journal   # noqa: E402
from src.evaluation import e1_hybridation as e1                       # noqa: E402
from src.evaluation import montage_gpu as montage                     # noqa: E402

# Un corpus mesurable dispose a la fois de paires question-reponse et d'un
# index. EUR-Lex n'en a pas : construire moi-meme des questions
# reglementaires reviendrait a decider si elles reprennent le vocabulaire du
# passage cible, donc a determiner le resultat avant de le mesurer.
CORPUS = {
    "enronqa": ("data/enronqa/enronqa_qa.jsonl",
                "data/index_lexical/enronqa.pkl"),
    "finqa": ("data/finqa/finqa_qa.jsonl",
              "data/index_lexical/finqa.pkl"),
    "banque": ("data/banque/banque_qa.jsonl",
               "data/index_lexical/banque.pkl"),
}
DEFAUT = "enronqa"

# Le corpus choisi restreint aussi la voie dense au meme vivier que la voie
# lexicale. L'index Qdrant contient les sept corpus, un index BM25 un seul :
# sans ce filtre, la voie dense affronterait cinq fois plus de distracteurs
# et l'ecart mesure tiendrait a la taille du vivier, non a la qualite de la
# recuperation.


def main():
    parseur = argparse.ArgumentParser(
        description="E1b, apport de l'hybridation")
    parseur.add_argument("--corpus", choices=tuple(CORPUS), default=DEFAUT,
                         help="corpus mesure ; fixe les paires, l'index "
                              "lexical et le filtre de la voie dense")
    parseur.add_argument("--paires", default=None,
                         help="par defaut, deduit du corpus")
    parseur.add_argument("--index-lexical", default=None,
                         help="par defaut, deduit du corpus")
    parseur.add_argument("--index-fichier", default=None,
                         help="index Qdrant sur fichier plutot que serveur")
    parseur.add_argument("--hote", default=None,
                         help="hote Qdrant, defaut http://localhost:6333")
    parseur.add_argument("--questions", type=int, default=200,
                         help="nombre de questions echantillonnees")
    parseur.add_argument("--k", type=int, default=10)
    parseur.add_argument("--graine", type=int, default=42)
    parseur.add_argument("--peripherique", default=None,
                         help="cuda, cpu, mps ; par defaut detecte")
    parseur.add_argument("--source", default=None,
                         help="restreindre a 'interne' ou 'externe'")
    parseur.add_argument("--sans-reclasseur", action="store_true",
                         help="sauter la configuration 'complet'")
    parseur.add_argument("--sortie", default="resultats/e1b")
    arguments = parseur.parse_args()

    config = mod_config.Config()

    paires_defaut, lexical_defaut = CORPUS[arguments.corpus]
    chemin_paires = Path(arguments.paires or paires_defaut)
    if not chemin_paires.exists():
        raise SystemExit(
            f"introuvable : {chemin_paires}\n"
            f"Ce fichier est produit par l'ingestion EnronQA. Verifiez le "
            f"chemin, ou passez --paires vers un autre jeu de paires.")

    paires = e1.charger_paires(chemin_paires)
    echantillon = e1.echantillonner(paires, arguments.questions,
                                    arguments.graine)
    print(f"corpus             : {arguments.corpus}")
    print(f"paires disponibles : {len(paires)}")
    print(f"questions retenues : {len(echantillon)} "
          f"(un tirage par document, graine {arguments.graine})")

    # --- montage de la chaine ----------------------------------------------
    try:
        vectoriseur = montage.charger_vectoriseur(
            config, peripherique=arguments.peripherique)
        index_dense = montage.charger_index_dense(
            config, hote=arguments.hote,
            chemin_local=arguments.index_fichier)
        index_lexical = montage.charger_index_lexical(
            arguments.index_lexical or lexical_defaut)
    except montage.ChaineIndisponible as erreur:
        raise SystemExit(f"\n{erreur}")

    reclasseur = (None if arguments.sans_reclasseur
                  else montage.charger_reclasseur(
                      config, peripherique=arguments.peripherique))

    print(f"peripherique       : {vectoriseur.peripherique} / "
          f"{vectoriseur.precision}")
    print(f"index dense        : {index_dense.collection}")
    print(f"index lexical      : {len(index_lexical.documents)} passages")
    print(f"re-classeur        : "
          f"{reclasseur.nom_modele if reclasseur else 'absent'}")
    if reclasseur is None and not arguments.sans_reclasseur:
        print("  Le cross-encodeur n'a pas pu etre charge. La configuration")
        print("  'complet' sera absente du tableau, et son absence dite.")
    print()

    fabrique = montage.fabrique(
        config, index_dense, index_lexical, vectoriseur,
        reclasseur=reclasseur, source=arguments.source,
        corpus=arguments.corpus)

    # --- campagne -----------------------------------------------------------
    with mod_journal.Execution("e1b-hybridation", config,
                               manifeste=[str(chemin_paires)]) as ex:
        ex.evenement("montage", **montage.decrire(
            vectoriseur, index_dense, index_lexical, reclasseur))

        rapport = e1.campagne(fabrique, echantillon, k=arguments.k)
        rapport["questions_retenues"] = len(echantillon)
        rapport["graine"] = arguments.graine

        cle = f"recall@{arguments.k}"
        print(f"{'configuration':<12} {'rappel@' + str(arguments.k):>10} "
              f"{'nDCG@' + str(arguments.k):>10} {'MRR':>8} "
              f"{'latence ms':>11}")
        print("-" * 56)
        for nom in e1.CONFIGURATIONS:
            mesure = rapport["resultats"].get(nom)
            if mesure is None:
                print(f"{nom:<12} {'non mesuree, composant absent':>44}")
                continue
            print(f"{nom:<12} "
                  f"{mesure[cle]['moyenne']:>10.4f} "
                  f"{mesure[f'ndcg@{arguments.k}']['moyenne']:>10.4f} "
                  f"{mesure['mrr']['moyenne']:>8.4f} "
                  f"{mesure['latence_mediane_ms']:>11.1f}")
            ex.mesure(f"{nom}.{cle}", mesure[cle]["moyenne"])

        print("\napport sur le dense seul :")
        if rapport["apport_sur_dense_seul"]:
            for nom, ecart in rapport["apport_sur_dense_seul"].items():
                signe = "+" if ecart >= 0 else ""
                print(f"  {nom:<12} {signe}{ecart:.4f}")
            print("\nUn apport positif de 'fusion' sur 'dense' etablit la")
            print("complementarite postulee au chapitre 2. Un apport nul")
            print("l'infirme et doit etre rapporte tel quel.")
        else:
            print("  configuration 'dense' absente, aucun apport calculable")

        chemin = Path(arguments.sortie)
        chemin.mkdir(parents=True, exist_ok=True)
        for destination in (chemin, ex.dossier):
            with open(destination / "e1b_hybridation.json", "w",
                      encoding="utf-8") as f:
                json.dump({"parametres": vars(arguments), **rapport},
                          f, ensure_ascii=False, indent=2)
        print(f"\necrit : {chemin}/ et {ex.dossier}/")


if __name__ == "__main__":
    main()
