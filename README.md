# Recherche hybride sécurisée pour un RAG souverain

Prototype réalisé pour mon mémoire de stage (Roy Ebwelle, UMONS / CETIC,
2026). C'est une chaîne de génération augmentée par recherche (RAG) pensée
pour une banque. Quand le corpus interne ne suffit pas, le système peut aller
chercher des sources externes, sous le contrôle de quatre piliers :

1. **Routage réflexif** (`src/routage/`) : avant toute sortie, décider si le
   corpus interne suffit, s'il faut refaire la recherche interne, aller
   chercher à l'extérieur, demander une validation humaine ou s'abstenir.
2. **Confidentialité de la requête sortante** (`src/confidentialite/`) :
   gabarit de généralisation figé par entité, budget d'exposition, masquage
   des entités nommées et verrou de sortie déterministe.
3. **Isolation et corroboration** (`src/isolation/`) : le contenu externe est
   balisé comme une donnée, reçoit une étiquette de confiance, et les copies
   d'une même source sont repérées.
4. **Provenance et attribution** (`src/provenance/`) : chaque affirmation est
   rattachée à sa source, jusqu'au paragraphe (le « pavé »).

Principe de base : aucun embedding ne sort de l'organisation. Les vecteurs
sont calculés en local, et seule une requête texte nettoyée peut sortir.

## Organisation du dépôt

| Dossier | Contenu |
|---|---|
| `src/ingestion/` | conversion des corpus vers un schéma commun (EUR-Lex, EnronQA, FinQA, TAT-QA, PubMedQA, Synthea, corpus bancaire synthétique) |
| `src/index/` | embeddings BGE-M3 en local, index Qdrant, BM25, fusion RRF et re-classement |
| `src/routage/`, `src/confidentialite/`, `src/isolation/`, `src/provenance/` | les quatre piliers décrits plus haut |
| `src/fournisseur/` | interface commune aux trois paliers de modèle (local, API dans l'UE, API hors UE) |
| `src/simulateur/` | simulateur de sources malveillantes, pour tester l'injection indirecte |
| `src/evaluation/` | protocoles des expériences E1 à E7 et métriques |
| `src/pipeline.py` | la chaîne complète, de la question à la réponse |
| `scripts/` | lanceurs des expériences (`run_e*.py`), construction des index, figures, outils divers |
| `docs/` | journal des données et des résultats, licences des corpus |
| `resultats/` | sorties brutes de chaque exécution (JSON, journaux), citées dans le journal des données |
| `figures/` | graphiques des résultats, en PDF et PNG |

Chaque module commence par une docstring qui explique ce qu'il fait, les
choix faits et ses limites.

## Expériences

| Expérience | Ce qu'elle mesure | Lanceur |
|---|---|---|
| E1 / E1b | ce qu'apporte la combinaison recherche lexicale + recherche dense | `scripts/run_e1_lexical.py`, `scripts/run_e1b.py` |
| E2 / E2b | la réduction de l'ensemble d'anonymat au fil des requêtes | `scripts/run_e2.py` |
| E3 | la résistance à l'injection indirecte, couche de défense par couche | `scripts/run_e3.py` |
| E4 | l'attribution des réponses et l'intégrité de la chaîne de provenance | `scripts/run_e4.py` |
| E5 | ce que la protection coûte en qualité de recherche | `scripts/run_e5.py` |
| E6 / E6b | la justesse du routage et de l'abstention | `scripts/run_e6.py`, `scripts/run_e6b.py` |
| E7 / E7b | la comparaison des détecteurs d'entités nommées | `scripts/run_e7.py`, `scripts/run_e7_banque.py` |

Les résultats chiffrés et leur lecture sont dans `docs/JOURNAL_DONNEES.md`.

## Installation

Depuis PowerShell, à la racine du dépôt :

    py -3.11 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt -r requirements-poc.txt
    pip install pymupdf matplotlib openai
    python -m spacy download en_core_web_lg
    python -m spacy download fr_core_news_lg

La dernière ligne `pip install` ajoute trois paquets utilisés par certains
scripts et absents des fichiers `requirements` : `pymupdf` (ingestion
EUR-Lex), `matplotlib` (figures) et `openai` (E3).

Une fois l'environnement activé, lancez les scripts avec `python`. N'utilisez
pas `py -3.11` : cette commande ignore l'environnement virtuel.

## Utilisation

Les étapes, dans l'ordre :

1. Ingestion des corpus publics (les données brutes doivent déjà être dans
   `data/`, voir plus bas) :

       .\scripts\ingest_all.ps1

2. Corpus bancaire synthétique, population d'entités pour E2, et questions
   pour E5 :

       python -m src.ingestion.banque --clients 300 --graine 42
       python src\ingestion\build_entities.py
       python scripts\build_paires_banque.py

3. Construction des index. C'est l'étape la plus longue : elle se fait de
   préférence sur GPU, avec un serveur Qdrant local sur le port 6333 :

       python scripts\build_index.py --corpus tous

4. Lancement des expériences. E2, E6 et E7 n'ont pas besoin de l'index
   dense. Exemples :

       python scripts\run_e2.py --k 50 --budget 6.0 --entites 20
       python scripts\run_e6.py
       python scripts\run_e7.py --patients 300 --langue en --moteurs spacy,presidio

Chaque lanceur décrit ses options dans sa docstring et avec `--help`.

## Données

Le dossier `data/` n'est pas dans le dépôt : le dépôt ne redistribue aucun
corpus (voir `NOTICE.md` et `docs/DATA_README.md`). Synthea et le corpus
bancaire sont générés en local avec une graine fixe. Les autres corpus se
téléchargent depuis leurs sources publiques.
