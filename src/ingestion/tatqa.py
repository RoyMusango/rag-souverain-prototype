"""
Adaptateur TAT-QA -> schema commun.

DECISIONS DE CONCEPTION

  Unite documentaire : un contexte hybride (table + paragraphes)
  rubrique           : identifiant de table (uid), qui identifie le rapport
  page               : 1
  pave               : rang du paragraphe ; le tableau porte le pave 1
  source             : interne

  Le split 'test' est exclu, ses reponses n'etant pas publiques (soumission
  au classement officiel). L'evaluation porte sur 'dev' uniquement.

  Le tableau est rendu en texte separe par des barres verticales : la
  composante lexicale BM25 doit pouvoir apparier exactement les intitules de
  postes comptables, ce qu'un aplatissement en prose empecherait.

Sortie : data/tatqa/tatqa_schema.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (charger_ner, extraire_entites_lot, numeroter_paves,
                    dedupliquer, ecrire, rapport)

SPLITS = {"train": Path("data/tatqa/tatqa_dataset_train.json"),
          "dev":   Path("data/tatqa/tatqa_dataset_dev.json")}
SORTIE = Path("data/tatqa/tatqa_schema.json")

records = []

for split, chemin in SPLITS.items():
    if not chemin.exists():
        print(f"  (absent : {chemin})")
        continue
    with open(chemin, encoding="utf-8") as f:
        data = json.load(f)

    for i, item in enumerate(data):
        table = item.get("table", {})
        uid = table.get("uid") or f"{split}_{i}"
        rubrique = f"tatqa/{uid}"

        # Le tableau : un document a part entiere, pave 1
        grille = table.get("table", [])
        if grille:
            texte_table = "\n".join(
                " | ".join(str(c) for c in ligne) for ligne in grille)
            records.append({
                "doc_id":   f"tatqa/{split}/{uid}/table",
                "text":     texte_table,
                "source":   "interne",
                "entities": [],
                "rubrique": rubrique,
                "page":     1,
                "pave":     0,
            })

        # Les paragraphes : un document chacun
        for para in item.get("paragraphs", []):
            ordre = para.get("order", 0)
            texte = para.get("text", "")
            if not texte.strip():
                continue
            records.append({
                "doc_id":   f"tatqa/{split}/{uid}/p{ordre}",
                "text":     texte,
                "source":   "interne",
                "entities": [],
                "rubrique": rubrique,
                "page":     1,
                "pave":     0,
            })

    print(f"  {split} : {len(data)} contextes lus")

records, doublons = dedupliquer(records)
records = numeroter_paves(records)

print("Extraction NER...")
nlp = charger_ner("en_core_web_lg")
entites, troncatures = extraire_entites_lot([r["text"] for r in records], nlp)
for r, e in zip(records, entites):
    r["entities"] = e

chemin = ecrire(records, SORTIE)
rapport("tatqa", records, chemin, doublons, troncatures)
