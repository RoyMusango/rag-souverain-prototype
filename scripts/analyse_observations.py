"""
Dimensionnement du corpus Synthea : nombre d'observations par patient.

Outil d'analyse ponctuel, ecrit pour trancher une question de conception :
fallait-il conserver toutes les lignes d'observation, ou seulement la
derniere valeur de chaque type ? La distribution affichee a justifie le
second choix, en montrant que la queue haute suffisait a faire croitre
fortement la taille du corpus sans benefice pour la recherche.

Il ne produit aucune mesure citee dans le rapport et n'intervient dans
aucune campagne. Je le conserve car la question peut se poser de nouveau si
le corpus Synthea est regenere.

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
