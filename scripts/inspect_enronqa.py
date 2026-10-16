"""
Affiche la structure du jeu EnronQA, avant l'ingestion.

Le script montre les colonnes du jeu et leur format. Il faut les connaitre
pour ecrire la conversion vers le schema commun de `src/ingestion/`.

Il essaie d'abord le jeu deja telecharge sur disque, sinon il lit les
fichiers parquet bruts. Aucun resultat de ce script n'est cite dans le
rapport.

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
