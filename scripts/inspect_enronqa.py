"""
Inspection de la structure du jeu EnronQA, prealable a l'ingestion.

Outil de reconnaissance, et non de mesure : il indique quelles colonnes le
jeu contient et sous quelle forme. Le schema commun de `src/ingestion/`
impose une structure ; il faut donc connaitre ce que fournit la source avant
d'ecrire la conversion.

Il essaie d'abord le jeu deja telecharge sur disque, puis se rabat sur les
fichiers parquet bruts. Aucune sortie n'est citee dans le rapport.

    .venv\\Scripts\\python.exe scripts\\inspect_enronqa.py
"""

from datasets import load_from_disk, load_dataset
try:
    ds = load_from_disk("data/enronqa")
except Exception:
    ds = load_dataset("parquet", data_files="data/enronqa/**/*.parquet")
print(ds)
split = next(iter(ds.values()))
print(split.column_names)
print({k: str(v)[:200] for k, v in split[0].items()})
