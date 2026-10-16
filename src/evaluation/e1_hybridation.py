"""
E1 : apport de l'hybridation ; E5 : cout en precision de la protection.

Verite terrain. Le format des paires question-reponse est celui que produit
`src/ingestion/enronqa.py` :

    {"doc_id": "enronqa/phanis-s_sent_items_4",
     "question": "Who are the people that Elizabeth Sager asked ...",
     "reponse":  "Elizabeth Sager asked Stephanie Panus to forward ..."}

Chaque question a un seul document pertinent, identifie par `doc_id`. Le
rappel vaut donc 0 ou 1 : Recall@k vaut 1 si le bon document est dans les k
premiers. FinQA et TAT-QA fonctionnent de la meme facon, avec
`finqa_programmes.json` et les paires de leurs splits.

On compare quatre configurations, pour isoler chaque etage de la cascade :

    dense       bi-encodeur seul
    lexical     BM25 seul
    fusion      RRF des deux
    complet     RRF puis re-classement par cross-encodeur

Le rapport fait l'hypothese que les recherches lexicale et dense se
completent. E1 la teste. Si la fusion n'apporte rien sur ces corpus, le
resultat est rapporte tel quel.
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
    """Echantillon reproductible, avec une seule question par document.

    Un meme courriel peut avoir plusieurs questions. Les garder toutes
    donnerait trop de poids a quelques documents, et le rappel moyen
    dependrait surtout de leur difficulte.
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
        "lecture": ("un apport positif de 'fusion' sur 'dense' confirme que "
                    "lexical et dense se completent (hypothese du chapitre 2) ; "
                    "un apport nul la contredit et se rapporte tel quel"),
    }
