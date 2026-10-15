"""
E1 : apport de l'hybridation ; E5 : cout en precision de la protection.

Verite terrain. Le format des paires question-reponse est celui que produit
`src/ingestion/enronqa.py` :

    {"doc_id": "enronqa/phanis-s_sent_items_4",
     "question": "Who are the people that Elizabeth Sager asked ...",
     "reponse":  "Elizabeth Sager asked Stephanie Panus to forward ..."}

Chaque question a un seul document pertinent, identifie par `doc_id`. Le
rappel est donc binaire : Recall@k vaut 1 si le bon document figure parmi les
k premiers. FinQA et TAT-QA suivent la meme logique, via
`finqa_programmes.json` et les paires de leurs splits respectifs.

Quatre configurations comparees, qui isolent chaque etage de la cascade :

    dense       bi-encodeur seul
    lexical     BM25 seul
    fusion      RRF des deux
    complet     RRF puis re-classement par cross-encodeur

Le rapport soutient que les versants lexical et dense sont complementaires
par nature. E1 verifie cette hypothese au lieu de la postuler ; un apport nul
de la fusion sur ces corpus serait rapporte comme tel.
"""

import json
import time
from pathlib import Path

from .metriques import mrr, ndcg_at_k, precision_at_k, recall_at_k, resumer

CONFIGURATIONS = ("dense", "lexical", "fusion", "complet")


def charger_paires(chemin, limite=None):
    """Lit un fichier de paires QR au format JSONL de l'ingestion."""
    paires = []
    chemin = Path(chemin)
    with open(chemin, encoding="utf-8") as f:
        for ligne in f:
            if not ligne.strip():
                continue
            item = json.loads(ligne)
            if item.get("question") and item.get("doc_id"):
                paires.append(item)
            if limite and len(paires) >= limite:
                break
    return paires


def echantillonner(paires, nombre=200, graine=42):
    """Echantillon reproductible, a raison d'un tirage par document.

    Une meme boite aux lettres porte plusieurs questions sur le meme
    courriel : les tirer toutes surponderait quelques documents, et le rappel
    moyen mesurerait surtout leur facilite.
    """
    import random
    alea = random.Random(graine)
    par_document = {}
    for paire in paires:
        par_document.setdefault(paire["doc_id"], []).append(paire)
    documents = sorted(par_document)
    alea.shuffle(documents)
    return [alea.choice(par_document[d]) for d in documents[:nombre]]


def evaluer_configuration(recuperateur, paires, k=10, configuration=""):
    """Mesure une configuration de recherche sur un jeu de paires."""
    rappels, precisions, ndcgs, rangs, latences = [], [], [], [], []

    for paire in paires:
        attendu = [paire["doc_id"]]
        debut = time.perf_counter()
        resultats = recuperateur.rechercher(
            paire["question"], n=max(k, 20), avec_teinte=False
        )
        latences.append((time.perf_counter() - debut) * 1000)

        cle = lambda f: f.doc_id  # noqa: E731
        rappels.append(recall_at_k(attendu, resultats, k, cle))
        precisions.append(precision_at_k(attendu, resultats, k, cle))
        ndcgs.append(ndcg_at_k({paire["doc_id"]: 1}, resultats, k, cle))
        rangs.append(mrr(attendu, resultats, cle))

    latences.sort()
    return {
        "configuration": configuration,
        "questions": len(paires),
        f"recall@{k}": resumer(rappels),
        f"precision@{k}": resumer(precisions),
        f"ndcg@{k}": resumer(ndcgs),
        "mrr": resumer(rangs),
        "latence_mediane_ms": round(latences[len(latences) // 2], 2)
        if latences else None,
    }


def campagne(fabrique_recuperateur, paires, k=10,
             configurations=CONFIGURATIONS):
    """Execute les quatre configurations sur les memes paires.

    `fabrique_recuperateur(configuration)` doit rendre un RecuperateurHybride
    dont les etages correspondent : 'dense' avec `lexical=None`, 'lexical'
    avec `dense=None`, 'fusion' avec les deux et `reclasseur=None`, 'complet'
    avec les trois.
    """
    resultats = {}
    for configuration in configurations:
        recuperateur = fabrique_recuperateur(configuration)
        if recuperateur is None:
            continue
        resultats[configuration] = evaluer_configuration(
            recuperateur, paires, k, configuration
        )

    cle_rappel = f"recall@{k}"
    apports = {}
    base = resultats.get("dense", {}).get(cle_rappel)
    if base and base.get("moyenne") is not None:
        for nom, mesure in resultats.items():
            valeur = mesure.get(cle_rappel, {}).get("moyenne")
            if valeur is not None and nom != "dense":
                apports[nom] = round(valeur - base["moyenne"], 4)

    return {
        "k": k,
        "resultats": resultats,
        "apport_sur_dense_seul": apports,
        "lecture": ("un apport positif de 'fusion' sur 'dense' etablit la "
                    "complementarite lexical/dense postulee au chapitre 2 ; "
                    "un apport nul l'infirme et doit etre rapporte tel quel"),
    }
