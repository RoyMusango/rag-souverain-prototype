"""
Gabarit de generalisation (section 3.3.5 du rapport).

Point de conception materialise par ce module :

    G(e) = f(e, kappa)

Le gabarit est une fonction deterministe de l'entite enquetee et d'un sel de
deploiement, jamais un tirage propre a une session. C'est ce qui rend
inoffensive la liaison de deux sessions : deux sessions portant sur la meme
entite emettent depuis le meme ensemble d'anonymat, et leur intersection
n'apporte rien a l'adversaire (S_e inter S_e = S_e).

Un gabarit retire a chaque session reproduirait, a un niveau superieur,
l'effondrement observe a l'echelle des requetes. C'est ce que met en
evidence la configuration C2 de l'experience E2b.

Effet de bord identifie (section 3.3.5) : un gabarit deterministe constitue
une empreinte stable de l'entite. Le sel `kappa` y repond ; sa rotation
re-randomise les gabarits et rouvre donc l'intersection, ce qui consomme du
budget au sens de budget.py.
"""

import hashlib
import hmac
import itertools

from . import anonymat

# Cout d'information attribue a chaque niveau de generalisation.
# Croissant : perdre la ville coute moins que perdre l'attribut entier.
COUT_NIVEAU = (0, 1, 3, 7)


def _empreinte(entite, kappa):
    """HMAC stable de l'entite, sous le sel de deploiement.

    Sert uniquement a departager des gabarits de cout egal. Sans lui, le
    gabarit serait une fonction publique de la population : un adversaire
    connaissant l'algorithme pourrait le recalculer pour chaque candidat et
    retrouver l'entite par correspondance.
    """
    cle = str(kappa).encode("utf-8")
    message = "|".join(
        f"{a}={entite.get(a, '')}" for a in anonymat.QUASI_IDENTIFIANTS
    ).encode("utf-8")
    return hmac.new(cle, message, hashlib.sha256).hexdigest()


def cout(gabarit):
    """Perte d'information d'un gabarit, toutes dimensions confondues."""
    return sum(
        COUT_NIVEAU[min(n, len(COUT_NIVEAU) - 1)] for n in gabarit.values()
    )


def _candidats(attributs):
    """Enumere les gabarits possibles sur les attributs consideres.

    L'espace reste petit : sept quasi-identifiants dont les niveaux maximaux
    valent 1 a 3, soit quelques centaines de combinaisons. Une enumeration
    exhaustive est donc preferable a une heuristique, et elle garantit le
    determinisme.
    """
    plages = [range(anonymat.NIVEAU_MAX.get(a, 1) + 1) for a in attributs]
    for combinaison in itertools.product(*plages):
        yield dict(zip(attributs, combinaison))


def calculer(population, entite, k, kappa, attributs=None):
    """Gabarit minimal garantissant |S| >= k pour cette entite.

    Retourne le gabarit de cout minimal qui atteint le seuil, les ex aequo
    etant departages par l'empreinte de l'entite sous le sel. Si aucun
    gabarit n'atteint le seuil (entite trop atypique), retourne le gabarit
    maximal, qui supprime tous les quasi-identifiants : l'appelant doit alors
    basculer vers la recuperation privee ou s'abstenir.

    La recherche procede par cout croissant et s'arrete a la fin du premier
    palier de cout qui fournit une solution, ce qui preserve la garantie de
    minimalite tout en n'evaluant qu'une fraction des candidats.
    """
    attributs = tuple(attributs or anonymat.QUASI_IDENTIFIANTS)
    if not isinstance(population, anonymat.Population):
        population = anonymat.Population(population)
    marque = _empreinte(entite, kappa)

    par_cout = {}
    for candidat in _candidats(attributs):
        par_cout.setdefault(cout(candidat), []).append(candidat)

    for valeur_cout in sorted(par_cout):
        retenus = []
        for candidat in par_cout[valeur_cout]:
            if population.taille_ensemble(entite, candidat, attributs) >= k:
                retenus.append(candidat)
        if retenus:
            # Ex aequo departages par le sel : le gabarit reste deterministe
            # en l'entite, sans etre recalculable par un adversaire qui
            # ignorerait kappa.
            return min(retenus, key=lambda g: _rang(g, marque))

    return {a: anonymat.NIVEAU_MAX.get(a, 1) for a in attributs}


def _rang(gabarit, marque):
    """Ordre stable et dependant du sel, pour departager les ex aequo."""
    empreinte = hashlib.sha256(
        (marque + "|" + repr(sorted(gabarit.items()))).encode("utf-8")
    ).hexdigest()
    return empreinte


def admissibles(population, entite, k, attributs=None, tolerance=4):
    """Tous les gabarits atteignant le seuil, a `tolerance` de cout du minimum.

    Sert au tirage aleatoire ci-dessous, et a auditer la marge de manoeuvre
    dont dispose la politique pour une entite donnee.
    """
    attributs = tuple(attributs or anonymat.QUASI_IDENTIFIANTS)
    if not isinstance(population, anonymat.Population):
        population = anonymat.Population(population)

    retenus = []
    for candidat in _candidats(attributs):
        if population.taille_ensemble(entite, candidat, attributs) >= k:
            retenus.append(candidat)
    if not retenus:
        return []
    plancher = min(cout(c) for c in retenus)
    return [c for c in retenus if cout(c) <= plancher + tolerance]


def choisir_aleatoire(population, entite, k, graine, attributs=None,
                      tolerance=4):
    """Tire un gabarit au hasard parmi les gabarits admissibles.

    Ce n'est pas la politique retenue par le rapport, mais la contre-mesure
    naive que l'experience E2b met en echec (configuration C2). Je la fournis
    parce qu'une comparaison n'a de valeur que si l'alternative est
    implementee loyalement.

    Son objectif apparent est de supprimer l'empreinte que constitue un
    gabarit deterministe (section 3.3.5, effets de bord). E2b montre qu'elle
    echange ce risque contre un risque plus grave : la reouverture de
    l'attaque par intersection.
    """
    import random

    candidats = admissibles(population, entite, k, attributs, tolerance)
    if not candidats:
        return maximal(attributs)
    tirage = random.Random(str(graine))
    return tirage.choice(
        sorted(candidats, key=lambda g: repr(sorted(g.items())))
    )


def maximal(attributs=None):
    """Gabarit qui supprime tous les attributs, utilise comme repli."""
    attributs = attributs or anonymat.QUASI_IDENTIFIANTS
    return {a: anonymat.NIVEAU_MAX.get(a, 1) for a in attributs}


def decrire(gabarit):
    """Rendu lisible d'un gabarit, pour les journaux et la piste d'audit."""
    if not gabarit:
        return "(aucune generalisation)"
    parties = []
    for attribut in anonymat.QUASI_IDENTIFIANTS:
        if attribut not in gabarit:
            continue
        niveau = gabarit[attribut]
        if niveau == 0:
            etat = "brut"
        elif niveau >= anonymat.NIVEAU_MAX.get(attribut, 1):
            etat = "supprime"
        else:
            etat = f"niveau {niveau}"
        parties.append(f"{attribut}={etat}")
    return ", ".join(parties)
