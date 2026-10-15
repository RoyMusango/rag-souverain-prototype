# Recherche hybride sécurisée pour un RAG souverain

Prototype développé dans le cadre de mon mémoire de stage (Roy Ebwelle,
UMONS / CETIC, 2026). Il met en œuvre une chaîne de génération augmentée par
recherche (RAG) destinée à un contexte bancaire, dans laquelle le recours à
des sources externes est contrôlé par quatre piliers :

1. **Routage réflexif** (`src/routage/`) : décider, avant toute sortie, si le
   corpus interne suffit, s'il faut corriger, enrichir, escalader ou
   s'abstenir.
2. **Confidentialité de la requête sortante** (`src/confidentialite/`) :
   gabarit de généralisation figé sur l'entité, budget d'exposition,
   masquage des entités nommées et verrou de sortie déterministe.
3. **Isolation et corroboration** (`src/isolation/`) : le contenu externe est
   balisé comme donnée, teinté selon sa fiabilité, et la collusion entre
   sources est détectée.
4. **Provenance et attribution** (`src/provenance/`) : chaque assertion est
   rattachée à sa source jusqu'au niveau du pavé.

Principe directeur : aucun embedding ne franchit la frontière de
l'organisation. Les vecteurs sont calculés localement ; seule une requête
texte, assainie, peut sortir.

## Organisation du dépôt

| Dossier | Contenu |
|---|---|
| `src/ingestion/` | adaptateurs des corpus vers un schéma commun (EUR-Lex, EnronQA, FinQA, TAT-QA, PubMedQA, Synthea, corpus bancaire synthétique) |
| `src/index/` | embeddings BGE-M3 locaux, index Qdrant, BM25, fusion RRF et re-classement |
| `src/routage/`, `src/confidentialite/`, `src/isolation/`, `src/provenance/` | les quatre piliers décrits ci-dessus |
| `src/fournisseur/` | abstraction des trois paliers de modèle (local, API UE, API hors UE) |
| `src/simulateur/` | simulateur de sources adverses pour l'évaluation de l'injection indirecte |
| `src/evaluation/` | protocoles des expériences E1 à E7 et métriques |
| `src/pipeline.py` | enchaînement de bout en bout |
| `scripts/` | lanceurs de campagnes (`run_e*.py`), construction d'index, tracé des figures, outils d'exploitation |
| `docs/` | journal des données et des résultats, licences des corpus |

Chaque module commence par une docstring qui en expose l'objet, les choix
de conception et les limites connues.

## Expériences

| Expérience | Objet | Lanceur |
|---|---|---|
| E1 / E1b | apport de l'hybridation lexicale et dense | `scripts/run_e1_lexical.py`, `scripts/run_e1b.py` |
| E2 / E2b | effondrement de l'ensemble d'anonymat | `scripts/run_e2.py` |
| E3 | résistance à l'injection indirecte, avec ablation par couche | `scripts/run_e3.py` |
| E4 | attribuabilité et intégrité de la chaîne de provenance | `scripts/run_e4.py` |
| E5 | coût en précision de la protection | `scripts/run_e5.py` |
| E6 / E6b | justesse du routage réflexif et abstention | `scripts/run_e6.py`, `scripts/run_e6b.py` |
| E7 / E7b | comparaison des détecteurs d'entités nommées | `scripts/run_e7.py`, `scripts/run_e7_banque.py` |

Les résultats chiffrés et leur interprétation sont consignés dans
`docs/JOURNAL_DONNEES.md`.

## Reproduction

Depuis PowerShell, à la racine du dépôt :

    py -3.11 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt -r requirements-poc.txt
    .\scripts\ingest_all.ps1

Une fois l'environnement activé, les scripts s'invoquent avec `python` (et
non `py -3.11`, qui ignorerait l'environnement virtuel). La construction de
l'index dense (`scripts/build_index.py`) est l'étape la plus coûteuse et
gagne à être exécutée sur GPU ; E2, E6 et E7 n'en dépendent pas.

## Données

Le dossier `data/` n'est pas versionné : ce dépôt ne redistribue aucun
corpus (voir `NOTICE.md` et `docs/DATA_README.md`). Synthea et le corpus
bancaire sont générés localement à graine fixe ; les autres corpus sont
téléchargés depuis leurs sources publiques.
