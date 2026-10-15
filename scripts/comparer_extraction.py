"""Compare pypdf et pymupdf sur les memes PDF, avec les deux memes motifs.

Le residuel de lettres isolees avec pymupdf n'est pas du bruit : c'est le
taux de faux positifs du detecteur, mesure sur un texte propre. Sans lui, le
premier test de severite ne serait pas interpretable.
"""

import glob
import re

import pymupdf
from pypdf import PdfReader

ISOLEE = re.compile(r"(?<= )[b-hj-zB-HJ-Z](?= )")
CONNUE = re.compile(r"\b(?:ar tif|har mon|REGUL A|EUR OPEAN|P ARLIAMENT|"
                    r"te chnolog|int elligence|ev olving)\b", re.I)

print(f"{'PDF':<34}{'pypdf isol/coup':>20}{'pymupdf isol/coup':>22}")
total = [0, 0, 0, 0]
for chemin in sorted(glob.glob("data/external/eurlex/*.pdf")):
    py = "\n".join((p.extract_text() or "") for p in PdfReader(chemin).pages)
    mu = "\n".join(p.get_text() for p in pymupdf.open(chemin))
    v = [len(ISOLEE.findall(py)), len(CONNUE.findall(py)),
         len(ISOLEE.findall(mu)), len(CONNUE.findall(mu))]
    total = [a + b for a, b in zip(total, v)]
    nom = chemin.replace("\\", "/").split("/")[-1]
    print(f"{nom:<34}{v[0]:>11} /{v[1]:>7}{v[2]:>13} /{v[3]:>7}")
print(f"{'TOTAL':<34}{total[0]:>11} /{total[1]:>7}{total[2]:>13} /{total[3]:>7}")