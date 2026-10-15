# -*- coding: utf-8 -*-
"""Existence d'une famille de generalisations a intersection bornee.

Trois verifications, dans l'ordre logique :

  1. EMBOITEMENT   convenir au niveau L implique-t-il convenir au niveau L+1 ?
                   C'est l'hypothese sur laquelle repose la suite.
  2. TREILLIS      S(G1) inter ... inter S(Gn) vaut-il S(min composante) ?
  3. DOMINATION    la famille adaptative fait-elle mieux que son minimum ?
"""
import io
import itertools
import json
import random
import sys

import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from src.confidentialite import anonymat, gabarit as G   # noqa: E402

d = json.load(open("data/synthea/entities.json",
                   encoding="utf-8"))["entities"]
pop = anonymat.Population(list(d.values()))
QI = tuple(sorted(anonymat.QUASI_IDENTIFIANTS))
N = pop.n
print(f"population {N}, quasi-identifiants {len(QI)}\n")


def classes(gab):
    """index -> signature, pour toute la population."""
    return pop.signatures(gab, QI)


def ens(gab, i):
    """Indices de la population partageant la signature de l'individu i."""
    sigs = classes(gab)
    cible = sigs[i]
    return {j for j, s in enumerate(sigs) if s == cible}


# ---------------------------------------------------------------- 1
print("=" * 70)
print("1. EMBOITEMENT DES NIVEAUX")
print("=" * 70)
print("   convenir au niveau L doit impliquer convenir au niveau L+1.\n")
rupture = False
for attribut in QI:
    maxi = anonymat.NIVEAU_MAX.get(attribut, 1)
    for niveau in range(maxi):
        fin = pop.colonne(attribut, niveau)
        gros = pop.colonne(attribut, niveau + 1)
        # Deux individus egaux au niveau fin doivent l'etre au niveau gros.
        par_valeur = {}
        casse = 0
        for k in range(N):
            par_valeur.setdefault(fin[k], set()).add(gros[k])
        casse = sum(1 for v in par_valeur.values() if len(v) > 1)
        etat = "OK " if casse == 0 else f"ROMPU ({casse} classes)"
        if casse:
            rupture = True
        print(f"   {attribut:<14} niveau {niveau} -> {niveau + 1}   {etat}")
print(f"\n   => emboitement {'VIOLE' if rupture else 'VERIFIE partout'}\n")

# ---------------------------------------------------------------- 2
print("=" * 70)
print("2. L'INTERSECTION VAUT-ELLE LE MINIMUM COMPOSANTE PAR COMPOSANTE ?")
print("=" * 70)
alea = random.Random(20260924)
echecs = 0
essais = 0
for _ in range(40):
    i = alea.randrange(N)
    entite = pop.entites[i]
    famille = []
    for _ in range(alea.randint(2, 4)):
        famille.append({a: alea.randint(0, anonymat.NIVEAU_MAX.get(a, 1))
                        for a in QI})
    inter = None
    for gab in famille:
        e = ens(gab, i)
        inter = e if inter is None else (inter & e)
    minimum = {a: min(g[a] for g in famille) for a in QI}
    attendu = ens(minimum, i)
    essais += 1
    if inter != attendu:
        echecs += 1
        if echecs <= 3:
            print(f"   CONTRE-EXEMPLE : |inter| = {len(inter)}, "
                  f"|S(min)| = {len(attendu)}")
print(f"\n   {essais - echecs}/{essais} familles verifient "
      f"S(G1)∩…∩S(Gn) = S(min)")
print(f"   => theoreme {'FAUX' if echecs else 'VERIFIE sur 40 familles'}\n")

# ---------------------------------------------------------------- 3
print("=" * 70)
print("3. LA FAMILLE ADAPTATIVE BAT-ELLE SON PROPRE MINIMUM ?")
print("=" * 70)
print("   protection = |S(min)| ; utilite = finesse de chaque requete.")
print("   Une requete plus grossiere que le minimum ne protege rien de plus.\n")
alea = random.Random(7)
lignes = []
for _ in range(6):
    i = alea.randrange(N)
    entite = pop.entites[i]
    adm = G.admissibles(pop, entite, 50)
    if len(adm) < 3:
        continue
    famille = alea.sample(adm, 3)
    minimum = {a: min(g[a] for g in famille) for a in QI}
    tailles = [len(ens(g, i)) for g in famille]
    inter = None
    for gab in famille:
        e = ens(gab, i)
        inter = e if inter is None else (inter & e)
    lignes.append((tailles, len(inter), len(ens(minimum, i)),
                   G.cout(minimum), [G.cout(g) for g in famille]))

print(f"   {'|S| de chaque requete':<26} {'inter':>6} {'|S(min)|':>9} "
      f"{'cout min':>9} {'couts famille':>20}")
for t, ii, mm, cm, cf in lignes:
    print(f"   {str(t):<26} {ii:>6} {mm:>9} {cm:>9} {str(cf):>20}")

print("""
   LECTURE. L'intersection egale toujours |S(min)|. La protection
   effective est donc celle de la requete LA PLUS FINE jamais emise.
   Les requetes plus grossieres de la famille coutent du rappel sans
   rien ajouter : elles sont strictement dominees.
""")

# ---------------------------------------------------------------- 4
print("=" * 70)
print("4. LE CAS QUI ECHAPPE : LA REQUETE SANS QUASI-IDENTIFIANT")
print("=" * 70)
i = alea.randrange(N)
vide = {a: anonymat.NIVEAU_MAX.get(a, 1) for a in QI}   # tout supprime
fin = G.calculer(pop, pop.entites[i], 50, "kappa-de-mesure")
print(f"   |S| sous gabarit maximal (tout supprime) : {len(ens(vide, i))}")
print(f"   |S| sous gabarit minimal admissible      : {len(ens(fin, i))}")
inter = ens(vide, i) & ens(fin, i)
print(f"   intersection des deux                    : {len(inter)}")
print("""
   Le gabarit maximal rend S = toute la population : c'est l'element
   neutre de l'intersection. Emettre une requete qui ne porte aucun
   quasi-identifiant ne contraint donc RIEN, et peut sortir en clair.
   C'est la seule variation licite, et le treillis la demontre.
""")
