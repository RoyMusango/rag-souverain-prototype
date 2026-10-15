r"""
Construction de l'index, etape la plus lourde, a executer sur GPU.

    set RAG_MATERIEL=shadow
    py -3.11 scripts\build_index.py --corpus tous --tranche 5000

Le script peut reprendre apres interruption : il ecrit son avancement a
chaque tranche. Une session interrompue se relance par la meme commande et
repart du dernier lot complet, ce qui est necessaire sur une machine louee,
ou une interruption couterait sinon la totalite du calcul.

Perimetre : les embeddings sont calcules localement, sur la machine qui
execute ce script. Aucun vecteur ne franchit la Frontiere A, quelle que soit
la machine employee (section 3.3.1) : une machine louee est un substrat de
calcul, et non un service d'embeddings distant.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "ingestion"))

from src.commun import config as mod_config, journal as mod_journal  # noqa: E402
from src.index import embeddings as mod_emb, lexical as mod_lex      # noqa: E402
from src.index import qdrant_index as mod_qdrant                     # noqa: E402

SCHEMAS = {
    "synthea": "data/synthea/synthea_schema.json",
    "finqa": "data/finqa/finqa_schema.json",
    "tatqa": "data/tatqa/tatqa_schema.json",
    "eurlex": "data/external/eurlex/eurlex_schema.json",
    "pubmedqa": "data/pubmedqa/pubmedqa_schema.jsonl",
    "enronqa": "data/enronqa/enronqa_schema.jsonl",
    # Corpus bancaire synthetique. Absent jusqu'au 07/09, ce qui rendait E5
    # impossible : elle interroge ce corpus, et un rappel mesure sur un index
    # qui ne le contient pas serait nul par construction.
    "banque": "data/banque/banque_schema.json",
}

# Palier d'origine : emplacement reel de la donnee, a distinguer du champ
# `source` du schema, qui indique comment le moteur la traite. PubMedQA est
# etiquete externe alors que son contenu est fiable : il sert de substitut
# controle du web biomedical (JOURNAL_DONNEES section 5.5).
PALIERS = {
    "synthea": "interne", "finqa": "interne", "tatqa": "interne",
    "enronqa": "interne", "eurlex": "externe", "pubmedqa": "externe",
    "banque": "interne",
}


def resoudre(chemin):
    p = Path(chemin)
    if p.exists():
        return p
    autre = p.with_suffix(".jsonl" if p.suffix == ".json" else ".json")
    return autre if autre.exists() else None


def lire(chemin):
    """Lecture du schema commun. Reprend la convention de src/ingestion."""
    try:
        from common import lire as lire_ingestion
        return lire_ingestion(chemin)
    except Exception:
        pass
    chemin = Path(chemin)
    if chemin.suffix == ".jsonl":
        with open(chemin, encoding="utf-8") as f:
            return [json.loads(ligne) for ligne in f if ligne.strip()]
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def main():
    parseur = argparse.ArgumentParser(description="Construction de l'index")
    parseur.add_argument("--corpus", default="tous",
                         help="'tous' ou une liste separee par des virgules")
    parseur.add_argument("--tranche", type=int, default=5000)
    parseur.add_argument("--taille-lot", type=int, default=None,
                         help="par defaut : deduite du peripherique")
    parseur.add_argument("--peripherique", default=None,
                         help="cuda, cpu, mps — par defaut : detecte")
    parseur.add_argument("--sans-qdrant", action="store_true",
                         help="calcule et persiste les vecteurs, sans verser")
    parseur.add_argument("--sans-lexical", action="store_true")
    parseur.add_argument("--recreer", action="store_true")
    arguments = parseur.parse_args()

    config = mod_config.Config()
    noms = (list(SCHEMAS) if arguments.corpus == "tous"
            else [c.strip() for c in arguments.corpus.split(",")])
    manifeste = [SCHEMAS[n] for n in noms if n in SCHEMAS]

    vectoriseur = mod_emb.Vectoriseur(
        modele=config.recherche.modele_embeddings,
        peripherique=arguments.peripherique,
        taille_lot=arguments.taille_lot,
    )

    print(f"materiel     : {config.materiel.nom} (role : {config.materiel.role})")
    print(f"peripherique : {vectoriseur.peripherique} / {vectoriseur.precision}")
    if vectoriseur.peripherique == "cpu":
        print("  ATTENTION — sans accelerateur, le calcul sur les six corpus")
        print("  se compte en heures. Declarez RAG_MATERIEL et un GPU.")
    print()

    with mod_journal.Execution("construction-index", config,
                               manifeste=manifeste) as execution:
        execution.evenement("vectoriseur", **vectoriseur.decrire())

        for nom in noms:
            chemin = resoudre(SCHEMAS.get(nom, ""))
            if chemin is None:
                print(f"[ABSENT]   {nom}")
                continue

            documents = lire(chemin)
            print(f"[{nom}] {len(documents)} documents")

            calcul = mod_emb.CalculPersistant(
                vectoriseur, dossier=f"data/embeddings/{nom}",
                taille_tranche=arguments.tranche,
            )
            calcul.executer(documents, corpus=nom, journal=execution)
            vecteurs, identifiants = calcul.charger_tout()
            execution.mesure(f"{nom}.documents", len(documents))

            if not arguments.sans_qdrant and vecteurs is not None:
                index = mod_qdrant.IndexQdrant(
                    collection=config.recherche.collection,
                    dimension=config.recherche.dimension,
                    hote=config.recherche.hote_qdrant,
                )
                index.creer(recreer=arguments.recreer and nom == noms[0])
                index.verser(documents, vecteurs, corpus=nom,
                             palier_origine=PALIERS.get(nom, "externe"))
                print(f"  verse dans Qdrant : {index.volumetrie()}")

            if not arguments.sans_lexical:
                lexique = mod_lex.IndexLexical(
                    langue="fr" if nom in ("synthea", "eurlex", "banque")
                    else "en"
                )
                lexique.construire(documents)
                chemin_lex = lexique.enregistrer(f"data/index_lexical/{nom}.pkl")
                print(f"  index lexical : {chemin_lex}")

        print("\nA reporter dans JOURNAL_DONNEES.md section 9 (encore vide) :")
        print("  temps d'embedding par 1000 docs, taille de l'index Qdrant,")
        print("  latence de recuperation dense / BM25 / fusion.")


if __name__ == "__main__":
    main()
