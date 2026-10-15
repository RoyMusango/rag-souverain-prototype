"""
Validateur du schema commun — aligne sur les sorties reelles de src/ingestion/.
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "ingestion"))
from common import lire

REQUIRED = {"doc_id", "text", "source", "entities", "rubrique", "page", "pave"}

FICHIERS_CONNUS = [
    "data/synthea/synthea_schema.json",
    "data/finqa/finqa_schema.json",
    "data/tatqa/tatqa_schema.json",
    "data/external/eurlex/eurlex_schema.json",
    "data/pubmedqa/pubmedqa_schema.jsonl",
    "data/enronqa/enronqa_schema.jsonl",
]


def resoudre(chemin):
    p = Path(chemin)
    if p.exists():
        return p
    autre = p.with_suffix(".jsonl" if p.suffix == ".json" else ".json")
    return autre if autre.exists() else None


def valider(chemin):
    nom = Path(chemin).stem
    reel = resoudre(chemin)
    if reel is None:
        print(f"[ABSENT]   {nom}")
        return None

    records = lire(reel)
    if not records:
        print(f"[ECHEC]    {nom} — aucun enregistrement")
        return False

    erreurs = []

    manquants = Counter()
    for r in records:
        for champ in REQUIRED - set(r):
            manquants[champ] += 1
    if manquants:
        erreurs.append(f"champs manquants : {dict(manquants)}")

    ids = [r.get("doc_id") for r in records]
    doublons = [i for i, n in Counter(ids).items() if n > 1]
    if doublons:
        erreurs.append(f"{len(doublons)} doc_id dupliques, ex : {doublons[:3]}")

    sources = Counter(r.get("source") for r in records)
    invalides = set(sources) - {"interne", "externe"}
    if invalides:
        erreurs.append(f"valeurs 'source' invalides : {invalides}")

    mauvais = sum(1 for r in records
                  if not isinstance(r.get("page"), int)
                  or not isinstance(r.get("pave"), int))
    if mauvais:
        erreurs.append(f"{mauvais} page/pave non entiers")

    paves = {}
    for r in records:
        paves.setdefault(r["rubrique"], []).append(r["pave"])
    sans_un = sum(1 for v in paves.values() if 1 not in v)
    if sans_un:
        erreurs.append(f"{sans_un} rubriques sans pave 1 (invariant A2 viole)")

    vides = sum(1 for r in records if not str(r.get("text", "")).strip())
    entites = sum(len(r.get("entities", [])) for r in records)
    taux = 100 * vides / len(records)

    statut = "ECHEC" if erreurs else "OK"
    print(f"[{statut}]{' ' * (9 - len(statut))}{nom}")
    print(f"           {len(records)} docs | {len(paves)} rubriques")
    print(f"           {entites} entites ({entites/len(records):.1f}/doc)")
    print(f"           {vides} vides ({taux:.2f} %) | source : {dict(sources)}")
    for e in erreurs:
        print(f"           ERREUR : {e}")
    print()
    return not erreurs


if __name__ == "__main__":
    cibles = sys.argv[1:] or FICHIERS_CONNUS
    res = [valider(c) for c in cibles]
    testes = [r for r in res if r is not None]
    if testes and all(testes):
        print(f"Tous valides ({len(testes)}/{len(cibles)} presents).")
    elif testes:
        print(f"{sum(testes)}/{len(testes)} valides.")
        sys.exit(1)
