"""
Adaptateur PubMedQA -> schema commun.

CHOIX DE CONCEPTION

  Unite documentaire : un resume (concatenation des sections du contexte)
  rubrique           : configuration (pqa_labeled / unlabeled / artificial)
  page               : 1
  pave               : rang du resume dans la configuration
  source             : externe (seul corpus dont l'etiquette ne correspond
                       pas a sa vraie nature)

  PubMedQA remplace le web biomedical, de facon controlee. Il est donc
  etiquete 'externe' et traite comme non fiable par la couche d'isolation
  (I2), meme si son contenu est fiable. C'est voulu : il faut tester le
  pipeline sur du contenu externe, et un corpus fixe se reproduit mieux que
  le web, qui change.

  pqa_artificial (211 269 resumes) est optionnel : --sans-artificial
  l'exclut si l'extraction NER prend trop de temps.

Sortie : data/pubmedqa/pubmedqa_schema.jsonl  (plus de documents que le seuil JSONL)
"""

import sys
from pathlib import Path
from datasets import load_from_disk

sys.path.insert(0, str(Path(__file__).parent))
from common import (charger_ner, extraire_entites_lot, numeroter_paves,
                    dedupliquer, ecrire, rapport)

SORTIE = Path("data/pubmedqa/pubmedqa_schema.json")

CONFIGS = ["pqa_labeled", "pqa_unlabeled"]
if "--sans-artificial" not in sys.argv:
    CONFIGS.append("pqa_artificial")

records = []

for cfg in CONFIGS:
    chemin = Path(f"data/pubmedqa/{cfg}")
    if not chemin.exists():
        print(f"  (absent : {cfg})")
        continue
    ds = load_from_disk(str(chemin))["train"]

    for item in ds:
        ctx = item.get("context", {})
        sections = ctx.get("contexts", []) if isinstance(ctx, dict) else []
        etiquettes = ctx.get("labels", []) if isinstance(ctx, dict) else []

        if etiquettes and len(etiquettes) == len(sections):
            texte = "\n".join(f"{lab}: {sec}"
                              for lab, sec in zip(etiquettes, sections))
        else:
            texte = "\n".join(sections)

        if not texte.strip():
            continue

        records.append({
            "doc_id":   f"pubmedqa/{cfg}/{item['pubid']}",
            "text":     texte,
            "source":   "externe",
            "entities": [],
            "rubrique": f"pubmedqa/{cfg}",
            "page":     1,
            "pave":     0,
        })

    print(f"  {cfg} : traite")

records, doublons = dedupliquer(records)
records = numeroter_paves(records)

print(f"Extraction NER sur {len(records)} abstracts (patientez)...")
nlp = charger_ner("en_core_web_lg")
entites, troncatures = extraire_entites_lot(
    [r["text"] for r in records], nlp, batch_size=128)
for r, e in zip(records, entites):
    r["entities"] = e

chemin = ecrire(records, SORTIE)
rapport("pubmedqa", records, chemin, doublons, troncatures)
