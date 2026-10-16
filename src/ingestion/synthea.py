"""
Adaptateur Synthea -> schema commun.

CHOIX DE CONCEPTION (memoire, section 4.2.4)

  Unite documentaire  : un document = une rubrique du dossier d'un patient.
                        Un patient donne donc jusqu'a 4 documents.
                        Raison : un dossier patient a de vraies rubriques. Un
                        seul bloc par patient ne laisserait aucun niveau de
                        detail a I3, et on ne pourrait pas tester
                        l'attribution.

  rubrique            : identite | conditions | observations | medications
  page                : 1 (aucune pagination dans un dossier structure)
  pave                : rang de la rubrique dans le dossier du patient
  source              : interne
  doc_id              : synthea/<patient_id>/<rubrique>   (deterministe, A1)

  Suffixes numeriques : Synthea ajoute un nombre aux noms ('Wallace647') pour
                        les rendre uniques. Je les retire du texte : sinon le
                        rappel NER serait fausse, car aucun modele n'a vu de
                        tels noms. L'identifiant patient garde chaque patient
                        unique.

Sortie : data/synthea/synthea_schema.json(l)
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (charger_ner, extraire_entites_lot, nettoyer_nom_synthea,
                    numeroter_paves, dedupliquer, ecrire, rapport)

BASE = Path("data/synthea")
SORTIE = BASE / "synthea_schema.json"
# Pas de plafond fixe : garder une ligne par type d'observation limite deja
# la taille de la rubrique (mediane 63 lignes, p99 126). Voir journal 5.9.


def lire_csv(nom):
    chemin = BASE / nom
    if not chemin.exists():
        print(f"  (absent : {nom})")
        return []
    with open(chemin, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---- 1. Identite -----------------------------------------------------------

patients = lire_csv("patients.csv")
noms = {}
identites = {}

for p in patients:
    pid = p["Id"]
    prenom = nettoyer_nom_synthea(p.get("FIRST", ""))
    nom = nettoyer_nom_synthea(p.get("LAST", ""))
    noms[pid] = f"{prenom} {nom}".strip()

    lignes = [
        f"Patient : {noms[pid]}",
        f"Date de naissance : {p.get('BIRTHDATE','')}",
        f"Genre : {p.get('GENDER','')}",
        f"Origine : {p.get('RACE','')} / {p.get('ETHNICITY','')}",
        f"Adresse : {p.get('ADDRESS','')}, {p.get('CITY','')} "
        f"{p.get('ZIP','')}, {p.get('STATE','')}",
        f"Comte : {p.get('COUNTY','')}",
    ]
    if p.get("DEATHDATE", "").strip():
        lignes.append(f"Date de deces : {p['DEATHDATE']}")
    if p.get("MARITAL", "").strip():
        lignes.append(f"Situation familiale : {p['MARITAL']}")
    identites[pid] = "\n".join(lignes)


# ---- 2. Rubriques cliniques ------------------------------------------------

def agreger(nom_csv, cle_patient, formateur):
    par_patient = defaultdict(list)
    for ligne in lire_csv(nom_csv):
        pid = ligne.get(cle_patient, "")
        if pid:
            par_patient[pid].append(formateur(ligne))
    return par_patient


conditions = agreger(
    "conditions.csv", "PATIENT",
    lambda r: f"- {r.get('DESCRIPTION','')} (depuis le {r.get('START','')})"
)

def agreger_dernier_par_type(nom_csv, cle_patient, cle_type, formateur):
    """
    Garde, pour chaque patient, la derniere valeur de chaque type.
    Un dossier clinique se lit par ses valeurs a jour. Garder les N premieres
    lignes donnerait plusieurs mesures d'une meme consultation et ferait
    perdre des types d'examens. Le CSV Synthea est trie par date, donc il
    suffit d'ecraser la valeur precedente pour chaque type.
    """
    par_patient = {}
    for ligne in lire_csv(nom_csv):
        pid = ligne.get(cle_patient, "")
        if pid:
            par_patient.setdefault(pid, {})[ligne.get(cle_type, "")] = formateur(ligne)
    return {p: list(v.values()) for p, v in par_patient.items()}


observations = agreger_dernier_par_type(
    "observations.csv", "PATIENT", "DESCRIPTION",
    lambda r: f"- {r.get('DATE','')} : {r.get('DESCRIPTION','')} = "
              f"{r.get('VALUE','')} {r.get('UNITS','')}".rstrip()
)
medications = agreger(
    "medications.csv", "PATIENT",
    lambda r: f"- {r.get('DESCRIPTION','')} (prescrit le {r.get('START','')})"
)


# ---- 3. Construction des documents ----------------------------------------

RUBRIQUES = [
    ("identite",     lambda pid: identites.get(pid, "")),
    ("conditions",   lambda pid: "\n".join(conditions.get(pid, []))),
    ("observations", lambda pid: "\n".join(observations.get(pid, []))),
    ("medications",  lambda pid: "\n".join(medications.get(pid, []))),
]

records = []
filtres = 0

for p in patients:
    pid = p["Id"]
    for rubrique, constructeur in RUBRIQUES:
        corps = constructeur(pid)
        if not corps.strip():
            filtres += 1
            continue
        entete = f"Dossier de {noms[pid]} — rubrique : {rubrique}\n"
        records.append({
            "doc_id":   f"synthea/{pid}/{rubrique}",
            "text":     entete + corps,
            "source":   "interne",
            "entities": [],
            "rubrique": f"synthea/{pid}",
            "page":     1,
            "pave":     0,
        })

records, doublons = dedupliquer(records)
records = numeroter_paves(records)

# ---- 4. NER ---------------------------------------------------------------

print("Extraction NER (en_core_web_lg, composant ner seul)...")
nlp = charger_ner("en_core_web_lg")
entites, troncatures = extraire_entites_lot([r["text"] for r in records], nlp)
for r, e in zip(records, entites):
    r["entities"] = e

chemin = ecrire(records, SORTIE)
rapport("synthea", records, chemin, doublons, troncatures, filtres)

print("Repartition par rubrique :")
from collections import Counter
for rub, n in Counter(r["doc_id"].split("/")[-1] for r in records).most_common():
    print(f"  {rub:14s} : {n}")

