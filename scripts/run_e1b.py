r"""
Lance E1b, l'apport de l'hybridation.

    python scripts\run_e1b.py
    python scripts\run_e1b.py --questions 200 --k 10

Utiliser `python` et non `py -3.11` : quand on donne une version, le
lanceur Windows ignore l'environnement virtuel.

BUT DE LA CAMPAGNE

Le chapitre 2 fait l'hypothese que les recherches lexicale et dense se
completent : BM25 retrouve les mots exacts, le bi-encodeur gere les
reformulations. E1b teste cette hypothese sur quatre configurations, avec
les memes questions :

    dense       le bi-encodeur seul
    lexical     BM25 seul
    fusion      les deux, fusionnes par rangs reciproques
    complet     la fusion, puis re-classement par cross-encodeur

Si la fusion n'apporte rien sur ces corpus, c'est aussi un resultat : une
seule des deux voies suffirait, et le deploiement serait plus simple.

PREREQUIS

L'index dense doit exister. On le construit une fois, sur GPU :

    python scripts\build_index.py --corpus tous --tranche 5000

C'est la partie la plus lourde du calcul : environ 235 heures de processeur
sans GPU pour les 422 189 passages. C'est pour elle qu'on loue une machine.
E1b ne prend que quelques minutes une fois l'index pret, sans le
cross-encodeur. Avec lui, sur processeur, compter environ une minute par
question (voir JOURNAL_DONNEES, E1b complet).

Les embeddings sont calcules sur la machine qui execute ce code. Une machine
louee fait seulement du calcul, aucun service d'embeddings distant
n'intervient : aucun vecteur ne franchit la Frontiere A.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.commun import config as mod_config, journal as mod_journal   # noqa: E402
from src.evaluation import e1_hybridation as e1                       # noqa: E402
from src.evaluation import montage_gpu as montage                     # noqa: E402

# Un corpus mesurable a des paires question-reponse et un index. EUR-Lex n'a
# pas de paires : si j'ecrivais moi-meme les questions, je deciderais si
# elles reprennent les mots du passage cible, et donc le resultat avant de le
# mesurer. (Les douze questions de run_recherche_questions.py sont une
# exception, mesuree a part.)
CORPUS = {
    "enronqa": ("data/enronqa/enronqa_qa.jsonl",
                "data/index_lexical/enronqa.pkl"),
    "finqa": ("data/finqa/finqa_qa.jsonl",
              "data/index_lexical/finqa.pkl"),
    "banque": ("data/banque/banque_qa.jsonl",
               "data/index_lexical/banque.pkl"),
}
DEFAUT = "enronqa"

# Le corpus choisi limite aussi la voie dense aux memes documents que la voie
# lexicale. L'index Qdrant contient les sept corpus, un index BM25 un seul.
# Sans ce filtre, la voie dense aurait cinq fois plus de documents parasites,
# et l'ecart mesure viendrait du nombre de documents, pas de la qualite de
# la recherche.


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
            f"Ce fichier vient de l'ingestion (EnronQA) ou de "
            f"build_paires_banque.py (banque). Verifiez le chemin, ou "
            f"passez --paires vers un autre jeu de paires.")

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
        print("  'complet' manquera dans le tableau, et ce sera indique.")
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
            print("\nUn apport positif de 'fusion' sur 'dense' confirme que")
            print("les deux voies se completent (hypothese du chapitre 2).")
            print("Un apport nul la contredit et se rapporte tel quel.")
            print("Comparer aussi la fusion a la meilleure voie seule.")
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
