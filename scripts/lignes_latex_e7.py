"""Produit les lignes de tableau LaTeX d'E7 et E7b depuis les JSON de mesure.

La generation automatique evite les erreurs de recopie manuelle.
"""

import argparse
import json


def fr(x, n=3):
    return f"{x:.{n}f}".replace(".", ",")


def ligne(libelle, bloc, precision_detection):
    # Depuis le correctif A3, `precision` est deja la precision au niveau des
    # detections : la recalculer ici introduisait un arrondi divergent
    # (0,893 contre 0,892). Le champ est donc lu tel quel.
    rappel = bloc["rappel"]
    precision = (bloc["precision"] if precision_detection
                 else bloc["precision_par_reference"])
    f1 = 2 * rappel * precision / (rappel + precision)
    debit = f"{bloc['debit_car_s']:,}".replace(",", "\\,")
    return (f"    {libelle} & {fr(rappel)} & {fr(precision)} & "
            f"{fr(f1)} & {debit} \\\\")


ap = argparse.ArgumentParser()
ap.add_argument("--fichier", required=True)
ap.add_argument("--cle", default="resultats",
                help="'resultats' pour e7_masquage.json, 'global' pour e7b")
ap.add_argument("--par-reference", action="store_true",
                help="conserver l'ancienne definition VP/(VP+FP)")
a = ap.parse_args()

with open(a.fichier, encoding="utf-8") as f:
    donnees = json.load(f)[a.cle]

print(ligne("Chaine souveraine (spaCy)", donnees["spacy"], not a.par_reference))
print(ligne("Presidio                 ", donnees["presidio"], not a.par_reference))