"""
Construction de la population d'entites pour E2 (courbe d'effondrement de |S|).

Distinct de synthea_schema.json : ce fichier ne sert pas a la recherche mais
au calcul exact de la taille de l'ensemble d'anonymat.

Sortie : data/synthea/entities.json
"""

import csv
import json
from collections import Counter
from datetime import date
from pathlib import Path

INPUT = Path("data/synthea/patients.csv")
OUTPUT = Path("data/synthea/entities.json")

GRAINE = 42
ETAT = "Massachusetts"
DATE_REFERENCE = date(2026, 8, 3)
PALIER_AGE = 10


def tranche_age(birthdate, deathdate):
    if not birthdate:
        return "INCONNU"
    an, mois, jour = (int(x) for x in birthdate.split("-"))
    fin = DATE_REFERENCE
    if deathdate:
        an_d, mois_d, jour_d = (int(x) for x in deathdate.split("-"))
        fin = date(an_d, mois_d, jour_d)
    age = fin.year - an - ((fin.month, fin.day) < (mois, jour))
    base = (age // PALIER_AGE) * PALIER_AGE
    return f"{base}-{base + PALIER_AGE - 1}"


entities = {}
with open(INPUT, encoding="utf-8") as f:
    for row in csv.DictReader(f):
        entities[row["Id"]] = {
            "ville":   row.get("CITY", "").strip(),
            "cp":      row.get("ZIP", "").strip(),
            "comte":   row.get("COUNTY", "").strip(),
            "genre":   row.get("GENDER", "").strip(),
            "race":    row.get("RACE", "").strip(),
            "ethnie":  row.get("ETHNICITY", "").strip(),
            "tranche_age": tranche_age(
                row.get("BIRTHDATE", ""), row.get("DEATHDATE", "")
            ),
            "decede":  bool(row.get("DEATHDATE", "").strip()),
        }

ATTRIBUTS = ["ville", "cp", "comte", "genre", "race", "ethnie", "tranche_age"]

sortie = {
    "meta": {
        "source": "Synthea",
        "graine": GRAINE,
        "etat": ETAT,
        "population_demandee": 1000,
        "population_obtenue": len(entities),
        "date_reference_age": DATE_REFERENCE.isoformat(),
        "palier_age": PALIER_AGE,
        "quasi_identifiants": ATTRIBUTS,
        "exclus": ["Id", "SSN", "DRIVERS", "PASSPORT", "LAT", "LON",
                   "INCOME", "HEALTHCARE_EXPENSES", "HEALTHCARE_COVERAGE"],
        "motif_exclusion": "identifiants directs ou continus : |S| = 1 immediat, "
                           "mesure triviale plutot que representative",
    },
    "entities": entities,
}

OUTPUT.write_text(json.dumps(sortie, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"Entites : {len(entities)}")
print()
print("Cardinalite par attribut (nb de modalites distinctes) :")
for a in ATTRIBUTS:
    modalites = Counter(e[a] for e in entities.values())
    print(f"  {a:12s} : {len(modalites):4d} modalites | "
          f"plus frequente = {modalites.most_common(1)[0][1]} patients")

print()
combinaison = Counter(
    tuple(e[a] for a in ATTRIBUTS) for e in entities.values()
)
uniques = sum(1 for n in combinaison.values() if n == 1)
print(f"Combinaisons completes distinctes : {len(combinaison)}")
print(f"Patients uniques sur la combinaison complete : {uniques} "
      f"({100*uniques/len(entities):.1f} %)")
print()
print("Lecture : ce pourcentage est le point de depart de la courbe E2 — "
      "la proportion de patients deja re-identifiables sans aucune protection.")
