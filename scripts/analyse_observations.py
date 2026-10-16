"""
Dimensionnement du corpus Synthea : nombre d'observations par patient.

Outil d'analyse ecrit pour une question de conception : fallait-il garder
toutes les lignes d'observation, ou seulement la derniere valeur de chaque
type ? La distribution affichee a fait choisir la seconde option : quelques
patients avec enormement de lignes suffisaient a gonfler le corpus, sans
rien apporter a la recherche.

Aucune mesure du rapport ne vient de ce script, et aucune campagne ne
l'utilise. Je le garde car la question peut revenir si le corpus Synthea
est regenere.

    .venv\\Scripts\\python.exe scripts\\analyse_observations.py
"""

import csv, statistics
from collections import defaultdict

dernier = defaultdict(dict)
with open('data/synthea/observations.csv', encoding='utf-8') as f:
    for r in csv.DictReader(f):
        dernier[r['PATIENT']][r['DESCRIPTION']] = r

n = sorted(len(v) for v in dernier.values())
print('Lignes conservees par patient (derniere valeur de chaque type) :')
for q in (10, 25, 50, 75, 90, 99):
    print(f'  p{q:2d} : {n[int(len(n)*q/100)-1]:4d}')
print(f'  max : {max(n)}  |  moy : {statistics.mean(n):.0f}')
print()

tailles = []
for p, obs in dernier.items():
    t = 0
    for r in obs.values():
        ligne = '- ' + r['DATE'] + ' : ' + r['DESCRIPTION'] + ' = ' + r['VALUE'] + ' ' + r['UNITS']
        t += len(ligne) + 1
    tailles.append(t)
tailles.sort()
print('Taille du texte de la rubrique observations :')
print(f'  mediane : {tailles[len(tailles)//2]} caracteres')
print(f'  p90     : {tailles[int(len(tailles)*0.9)]} caracteres')
print(f'  max     : {tailles[-1]} caracteres')
