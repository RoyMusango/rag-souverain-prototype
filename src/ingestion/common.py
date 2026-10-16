"""
Fonctions communes aux adaptateurs d'ingestion.

Elles garantissent les invariants A1 a A5 :
  A1 doc_id deterministe
  A2 pave numerote dans sa rubrique
  A3 aucune troncature silencieuse
  A4 deduplication explicite
  A5 JSONL au-dela de 50 000 documents
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

SEUIL_JSONL = 50_000
LIMITE_SPACY = 900_000   # limite dure de spaCy : 1 000 000 caracteres

CHAMPS = ["doc_id", "text", "source", "entities", "rubrique", "page", "pave"]


# --------------------------------------------------------------------------
# NER
# --------------------------------------------------------------------------

def charger_ner(modele="en_core_web_lg"):
    """Charge spaCy en ne gardant que le composant NER (3 a 5 fois plus rapide)."""
    import spacy
    nlp = spacy.load(modele, exclude=["parser", "lemmatizer", "attribute_ruler",
                                      "tagger", "textcat"])
    return nlp


def extraire_entites_lot(textes, nlp, batch_size=64, n_process=1):
    """
    Extraction NER par lot avec nlp.pipe.
    Renvoie (liste_d_entites, nb_troncatures) : chaque troncature est
    comptee et signalee (A3).
    """
    troncatures = 0
    prepares = []
    for t in textes:
        if len(t) > LIMITE_SPACY:
            troncatures += 1
            t = t[:LIMITE_SPACY]
        prepares.append(t)

    resultats = []
    for doc in nlp.pipe(prepares, batch_size=batch_size, n_process=n_process):
        vues = set()
        ents = []
        for e in doc.ents:
            texte = " ".join(e.text.split())
            if not texte:
                continue
            cle = f"{e.label_}:{texte}"
            if cle not in vues:
                vues.add(cle)
                ents.append(cle)
        resultats.append(ents)

    return resultats, troncatures


def nettoyer_nom_synthea(nom):
    """
    Synthea ajoute un nombre a la fin des noms pour les rendre uniques
    (ex. 'Wallace647 Effertz744'). Ces nombres viennent du generateur. Les
    garder fausserait le rappel NER, car le modele n'a jamais vu de tels
    noms. Je les retire pour evaluer le masquage. L'identifiant patient
    suffit a garder chaque patient unique.
    """
    return re.sub(r"\d+", "", nom).strip()


# --------------------------------------------------------------------------
# Numerotation et ecriture
# --------------------------------------------------------------------------

def numeroter_paves(records):
    """
    A2 : renumerote 'pave' de 1 a n dans chaque rubrique.
    Modifie les enregistrements sur place et les renvoie.
    """
    compteurs = defaultdict(int)
    for r in records:
        cle = (r["rubrique"], r.get("page", 1))
        compteurs[cle] += 1
        r["pave"] = compteurs[cle]
    return records


def dedupliquer(records, cle=lambda r: r["doc_id"]):
    """A4 : deduplication explicite, avec le nombre de doublons retires."""
    vus = {}
    doublons = 0
    for r in records:
        k = cle(r)
        if k in vus:
            doublons += 1
        else:
            vus[k] = r
    return list(vus.values()), doublons


def ecrire(records, chemin, forcer_jsonl=None):
    """
    A5 : JSON lisible sous le seuil, JSONL au-dessus.
    Renvoie le chemin du fichier ecrit.
    """
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)

    jsonl = forcer_jsonl if forcer_jsonl is not None else len(records) > SEUIL_JSONL
    if jsonl:
        chemin = chemin.with_suffix(".jsonl")
        with open(chemin, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    else:
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    return chemin


def lire(chemin):
    """Lit un fichier JSON ou JSONL."""
    chemin = Path(chemin)
    if chemin.suffix == ".jsonl":
        with open(chemin, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# Compte rendu
# --------------------------------------------------------------------------

def rapport(nom, records, chemin, doublons=0, troncatures=0, filtres=0):
    """Compte rendu au meme format pour tous les corpus, chiffres a reporter au journal."""
    total = len(records)
    if total == 0:
        print(f"[{nom}] AUCUN DOCUMENT PRODUIT")
        return

    vides = sum(1 for r in records if not r["text"].strip())
    entites = sum(len(r["entities"]) for r in records)
    rubriques = len({r["rubrique"] for r in records})
    taille = sum(len(r["text"]) for r in records)

    print(f"[{nom}]")
    print(f"  documents      : {total}")
    print(f"  rubriques      : {rubriques}")
    print(f"  entites        : {entites} ({entites/total:.1f} par doc)")
    print(f"  texte moyen    : {taille/total:.0f} caracteres")
    print(f"  vides          : {vides} ({100*vides/total:.2f} %)")
    if filtres:
        print(f"  filtres        : {filtres}")
    if doublons:
        print(f"  doublons ecart.: {doublons}")
    if troncatures:
        print(f"  TRONCATURES    : {troncatures}  <-- a signaler dans le memoire")
    print(f"  sortie         : {chemin}")
    print()
