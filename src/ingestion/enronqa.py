"""
Adaptateur EnronQA -> schema commun.

DECISIONS DE CONCEPTION (reprises dans le memoire)

  Unite documentaire : un courriel unique, identifie par son champ 'path'.
  rubrique           : boite aux lettres ('user'), qui reproduit le
                       cloisonnement d'une organisation ; 150 boites
                       distinctes.
  page               : 1. Un courriel n'a pas de pagination naturelle. C'est
                       la limite de ce corpus au regard de I3, et la raison
                       pour laquelle EUR-Lex sert de corpus de demonstration
                       de la chaine complete.
  pave               : rang du courriel dans sa boite.
  source             : interne

  Deduplication necessaire : le jeu compte 221 316 lignes pour environ
  103 638 courriels, chaque courriel apparaissant une fois par question
  posee. Sans deduplication, chaque courriel serait indexe plusieurs fois et
  tout denominateur de rappel serait faux. Les questions sont regroupees et
  conservees a part (fichier QA), hors du schema documentaire.

  Analyse : les champs 'questions', 'gold_answers', etc. sont des chaines
  contenant une representation de liste Python. ast.literal_eval est
  requis ; json.loads echoue (guillemets simples).

  Filtrage : les courriels reduits a une signature ou a une citation sont
  ecartes (< 40 caracteres de corps utile). Le nombre de courriels filtres
  est rapporte dans le memoire.

Sortie : data/enronqa/enronqa_schema.jsonl
         data/enronqa/enronqa_qa.jsonl
"""

import ast
import json
import sys
from collections import defaultdict
from pathlib import Path
from datasets import load_dataset

sys.path.insert(0, str(Path(__file__).parent))
from common import (charger_ner, extraire_entites_lot, numeroter_paves,
                    ecrire, rapport)

SORTIE = Path("data/enronqa/enronqa_schema.json")
SORTIE_QA = Path("data/enronqa/enronqa_qa.jsonl")
LONGUEUR_MIN = 40


def en_liste(valeur):
    """Les champs sont des chaines contenant des listes Python."""
    if isinstance(valeur, list):
        return valeur
    if not valeur:
        return []
    try:
        r = ast.literal_eval(valeur)
        return r if isinstance(r, list) else [r]
    except (ValueError, SyntaxError):
        return [valeur]


def corps_utile(email):
    """Retire les lignes d'en-tete pour juger de la longueur reelle."""
    lignes = [l for l in email.split("\n")
              if not l.startswith(("Subject:", "Sender:", "Recipients:",
                                   "File:", "=====")) and l.strip()]
    return "\n".join(lignes)


print("Chargement...")
ds = load_dataset("parquet", data_files="data/enronqa/**/*.parquet")["train"]
print(f"  {len(ds)} lignes brutes")

par_path = {}
questions_par_path = defaultdict(list)

for item in ds:
    chemin = item.get("path", "")
    if not chemin:
        continue
    if chemin not in par_path:
        par_path[chemin] = item
    for q, a in zip(en_liste(item.get("questions")),
                    en_liste(item.get("gold_answers"))):
        questions_par_path[chemin].append({"question": q, "reponse": a})

print(f"  {len(par_path)} courriels uniques apres deduplication "
      f"({len(ds) - len(par_path)} lignes redondantes)")

records = []
filtres = 0

for chemin, item in par_path.items():
    email = item.get("email", "") or ""
    if len(corps_utile(email)) < LONGUEUR_MIN:
        filtres += 1
        continue
    user = item.get("user", "inconnu")
    identifiant = chemin.replace("/", "_").rstrip(".")
    records.append({
        "doc_id":   f"enronqa/{identifiant}",
        "text":     email,
        "source":   "interne",
        "entities": [],
        "rubrique": f"enronqa/{user}",
        "page":     1,
        "pave":     0,
    })

records = numeroter_paves(records)

print(f"Extraction NER sur {len(records)} courriels (comptez ~15 min)...")
nlp = charger_ner("en_core_web_lg")
entites, troncatures = extraire_entites_lot(
    [r["text"] for r in records], nlp, batch_size=128)
for r, e in zip(records, entites):
    r["entities"] = e

chemin_sortie = ecrire(records, SORTIE, forcer_jsonl=True)
rapport("enronqa", records, chemin_sortie, 0, troncatures, filtres)

with open(SORTIE_QA, "w", encoding="utf-8") as f:
    n = 0
    for chemin, qas in questions_par_path.items():
        identifiant = chemin.replace("/", "_").rstrip(".")
        for qa in qas:
            f.write(json.dumps({"doc_id": f"enronqa/{identifiant}", **qa},
                               ensure_ascii=False) + "\n")
            n += 1
print(f"Paires QA conservees : {n} -> {SORTIE_QA}")

boites = len({r["rubrique"] for r in records})
print(f"Boites aux lettres representees : {boites}  (attendu : 150)")
