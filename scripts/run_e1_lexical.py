r"""
E1a : recherche lexicale seule (BM25), premier etage de la cascade hybride.

    python scripts\run_e1_lexical.py --corpus enronqa --questions 200

Ce script n'a besoin ni de GPU, ni d'API, ni de modele de langue. Il mesure
ce que donne la recherche lexicale seule, avant toute fusion. C'est le
niveau minimum de la chaine de recherche : un passage manque ici ne sera
pas rattrape par la generation.

Deux metriques :

  RAPPEL@k   le bon passage a-t-il ete trouve ?
  nDCG@k     a-t-il ete bien classe ?

Le rappel ne tient pas compte du rang : il ne voit pas l'effet d'un
re-classement. Le nDCG tient compte de la position de chaque document et
montre cet effet. Il faut donc les deux.

Verite terrain : chaque paire question-reponse designe un seul document par
son doc_id. La pertinence vaut 0 ou 1 et le nDCG ideal vaut 1, ce qui
simplifie le calcul sans le rendre moins juste.
"""

import argparse
import json
import random
import statistics
import sys
import time
from math import log2
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.index import lexical as mod_lex   # noqa: E402

SCHEMAS = {
    "synthea": "data/synthea/synthea_schema.json",
    "finqa": "data/finqa/finqa_schema.json",
    "tatqa": "data/tatqa/tatqa_schema.json",
    "eurlex": "data/external/eurlex/eurlex_schema.json",
    "pubmedqa": "data/pubmedqa/pubmedqa_schema.jsonl",
    "enronqa": "data/enronqa/enronqa_schema.jsonl",
}

QA = {
    "enronqa": "data/enronqa/enronqa_qa.jsonl",
}

# Langue de segmentation : elle determine la liste de mots vides appliquee.
LANGUES = {
    "synthea": "fr", "eurlex": "fr",
    "finqa": "en", "tatqa": "en", "pubmedqa": "en", "enronqa": "en",
}


def resoudre(chemin):
    p = Path(chemin)
    if p.exists():
        return p
    autre = p.with_suffix(".jsonl" if p.suffix == ".json" else ".json")
    return autre if autre.exists() else None


def lire(chemin):
    chemin = Path(chemin)
    if chemin.suffix == ".jsonl":
        with open(chemin, encoding="utf-8") as f:
            return [json.loads(ligne) for ligne in f if ligne.strip()]
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def ndcg_binaire(rang, k):
    """Pertinence 0 ou 1, un seul document pertinent : IDCG = 1."""
    if rang is None or rang > k:
        return 0.0
    return 1.0 / log2(rang + 1)


def main():
    parseur = argparse.ArgumentParser(
        description="E1a : recherche lexicale BM25 seule")
    parseur.add_argument("--corpus", default="enronqa",
                         choices=sorted(SCHEMAS))
    parseur.add_argument("--questions", type=int, default=200,
                         help="nombre de questions echantillonnees")
    parseur.add_argument("--rangs", default="1,3,5,10,20,50",
                         help="valeurs de k, separees par des virgules")
    parseur.add_argument("--graine", type=int, default=42)
    parseur.add_argument("--cle-texte", default="text",
                         help="champ du schema qui contient le texte a indexer")
    parseur.add_argument("--sortie", default="resultats/e1_lexical")
    arguments = parseur.parse_args()

    rangs = sorted(int(r) for r in arguments.rangs.split(","))
    k_max = max(rangs)

    # --- lecture -----------------------------------------------------------
    chemin_schema = resoudre(SCHEMAS[arguments.corpus])
    if chemin_schema is None:
        raise SystemExit(f"schema introuvable : {SCHEMAS[arguments.corpus]}")
    if arguments.corpus not in QA:
        raise SystemExit(
            f"aucune verite-terrain declaree pour '{arguments.corpus}'. "
            f"Corpus disponibles : {', '.join(QA)}")
    chemin_qa = resoudre(QA[arguments.corpus])
    if chemin_qa is None:
        raise SystemExit(f"paires introuvables : {QA[arguments.corpus]}")

    documents = lire(chemin_schema)
    paires = lire(chemin_qa)

    # --- verifications, avant tout calcul ----------------------------------
    if not documents:
        raise SystemExit("schema vide")
    if arguments.cle_texte not in documents[0]:
        raise SystemExit(
            f"champ '{arguments.cle_texte}' absent du schema. "
            f"Champs presents : {sorted(documents[0])}")

    connus = {d.get("doc_id") for d in documents}
    paires = [p for p in paires if p.get("doc_id") in connus]
    if not paires:
        raise SystemExit(
            "aucune paire ne pointe vers un doc_id du schema : la "
            "verite-terrain et le corpus ne sont pas alignes.")

    langue = LANGUES[arguments.corpus]
    print(f"corpus      : {arguments.corpus} ({len(documents)} documents)")
    print(f"paires      : {len(paires)} exploitables")
    print(f"langue      : {langue}")
    print(f"rangs       : {rangs}\n")

    alea = random.Random(arguments.graine)
    echantillon = alea.sample(paires, min(arguments.questions, len(paires)))

    # --- construction ------------------------------------------------------
    debut = time.time()
    index = mod_lex.IndexLexical(langue=langue)
    index.construire(documents, cle_texte=arguments.cle_texte)
    duree_index = time.time() - debut
    print(f"index construit en {duree_index:.1f} s")

    # --- interrogation -----------------------------------------------------
    rangs_trouves = []
    latences = []
    debut = time.time()
    for numero, paire in enumerate(echantillon, start=1):
        t = time.perf_counter()
        resultats = index.rechercher(paire["question"], n=k_max)
        latences.append((time.perf_counter() - t) * 1000)

        rang = None
        for position, (document, _score) in enumerate(resultats, start=1):
            if document.get("doc_id") == paire["doc_id"]:
                rang = position
                break
        rangs_trouves.append(rang)
        print(f"  question {numero}/{len(echantillon)}", end="\r")

    duree_requetes = time.time() - debut
    print(f"\n{len(echantillon)} questions en {duree_requetes:.1f} s\n")

    # --- agregation --------------------------------------------------------
    mesures = {}
    for k in rangs:
        atteints = sum(1 for r in rangs_trouves if r is not None and r <= k)
        mesures[f"rappel@{k}"] = round(atteints / len(rangs_trouves), 4)
        mesures[f"ndcg@{k}"] = round(
            statistics.mean(ndcg_binaire(r, k) for r in rangs_trouves), 4)

    reciproques = [1.0 / r for r in rangs_trouves if r is not None]
    mesures["mrr"] = round(sum(reciproques) / len(rangs_trouves), 4)
    mesures["jamais_trouve"] = sum(1 for r in rangs_trouves if r is None)
    mesures["latence_mediane_ms"] = round(statistics.median(latences), 1)
    mesures["latence_p90_ms"] = round(
        sorted(latences)[int(len(latences) * 0.9)], 1)

    print(f"{'k':>4} {'rappel@k':>10} {'nDCG@k':>10}")
    print("-" * 26)
    for k in rangs:
        print(f"{k:>4} {mesures[f'rappel@{k}']:>10.3f} "
              f"{mesures[f'ndcg@{k}']:>10.3f}")
    print(f"\nMRR                : {mesures['mrr']:.3f}")
    print(f"jamais trouve      : {mesures['jamais_trouve']} "
          f"sur {len(echantillon)}")
    print(f"latence mediane    : {mesures['latence_mediane_ms']} ms")
    print(f"latence p90        : {mesures['latence_p90_ms']} ms")

    # --- ecriture ----------------------------------------------------------
    dossier = Path(arguments.sortie)
    dossier.mkdir(parents=True, exist_ok=True)
    sortie = {
        "parametres": vars(arguments),
        "corpus": {
            "nom": arguments.corpus,
            "documents": len(documents),
            "paires_exploitables": len(paires),
            "questions_evaluees": len(echantillon),
            "langue": langue,
        },
        "durees_s": {
            "construction_index": round(duree_index, 1),
            "interrogation": round(duree_requetes, 1),
        },
        "mesures": mesures,
        "rangs_bruts": rangs_trouves,
        # Latences une par une : la mediane cache la forme de la
        # distribution, et c'est elle qui nous interesse ici.
        "latences_ms": [round(valeur, 2) for valeur in latences],
    }
    chemin = dossier / f"e1_lexical_{arguments.corpus}.json"
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False, indent=2)
    print(f"\necrit : {chemin}")


if __name__ == "__main__":
    main()
