# Le dossier data/ n'est pas dans le dépôt

Ce dossier est volontairement exclu du dépôt (voir `.gitignore`).

On peut le reconstruire entièrement avec les adaptateurs de `src/ingestion/`
(`scripts/ingest_all.ps1`, puis `python -m src.ingestion.banque` pour le
corpus bancaire). Pour Synthea, la graine utilisée est notée dans
`docs/JOURNAL_DONNEES.md`.

C'est un choix lié aux licences (voir `NOTICE.md`) : on peut reproduire les
résultats sans que le dépôt redistribue les corpus.
