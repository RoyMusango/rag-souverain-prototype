"""
Adaptateur FinQA -> schema commun.

DECISIONS DE CONCEPTION

  Unite documentaire : un contexte financier (pre_text + table + post_text)
  rubrique           : rapport source (champ 'filename')
  page               : 1
  pave               : rang du contexte dans le rapport
  source             : interne

  Le split 'test' est exclu et reserve a une evaluation finale non
  contaminee. Les programmes de raisonnement annotes (champ qa.program) sont
  conserves hors schema, dans un fichier separe, pour la verification du
  chemin de calcul en E5.

Sortie : data/finqa/finqa_schema.json
         data/finqa/finqa_programmes.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (charger_ner, extraire_entites_lot, numeroter_paves,
                    dedupliquer, ecrire, rapport)

SPLITS = {"train": Path("data/finqa/dataset/train.json"),
          "dev":   Path("data/finqa/dataset/dev.json")}
SORTIE = Path("data/finqa/finqa_schema.json")
SORTIE_PROG = Path("data/finqa/finqa_programmes.json")


def table_en_texte(table):
    if not table:
        return ""
    return "\n".join(" | ".join(str(c) for c in ligne) for ligne in table)


records = []
programmes = []

for split, chemin in SPLITS.items():
    if not chemin.exists():
        print(f"  (absent : {chemin})")
        continue
    with open(chemin, encoding="utf-8") as f:
        data = json.load(f)

    for i, item in enumerate(data):
        pre = " ".join(item.get("pre_text", []))
        post = " ".join(item.get("post_text", []))
        table = table_en_texte(item.get("table", []))
        texte = "\n".join(part for part in (pre, table, post) if part.strip())

        rapport_source = item.get("filename") or f"finqa_inconnu/{split}"
        identifiant = item.get("id") or f"{split}_{i}"

        records.append({
            "doc_id":   f"finqa/{split}/{identifiant}",
            "text":     texte,
            "source":   "interne",
            "entities": [],
            "rubrique": f"finqa/{rapport_source}",
            "page":     1,
            "pave":     0,
        })

        qa = item.get("qa", {})
        if qa.get("program"):
            programmes.append({
                "doc_id":  f"finqa/{split}/{identifiant}",
                "question": qa.get("question", ""),
                "reponse":  qa.get("answer", ""),
                "programme": qa.get("program", ""),
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
rapport("finqa", records, chemin, doublons, troncatures)

SORTIE_PROG.write_text(
    json.dumps(programmes, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Programmes de raisonnement conserves : {len(programmes)} -> {SORTIE_PROG}")
