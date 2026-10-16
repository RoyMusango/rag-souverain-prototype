"""
Gabarit de generalisation (section 3.3.5 du rapport).

Le gabarit se calcule ainsi :

    G(e) = f(e, kappa)

C'est une fonction deterministe de l'entite enquetee et d'un sel propre au
deploiement. Il n'est pas tire au hasard a chaque session. Deux sessions sur
la meme entite envoient donc des requetes depuis le meme ensemble
d'anonymat, et l'adversaire ne gagne rien a les croiser
(S_e inter S_e = S_e).

Si le gabarit etait tire a nouveau a chaque session, on retrouverait entre
sessions le meme effondrement qu'entre requetes. La configuration C2 de
l'experience E2b le montre.

Inconvenient (section 3.3.5) : un gabarit deterministe forme une empreinte
stable de l'entite. Le sel `kappa` limite ce risque. Changer le sel change
les gabarits, ce qui permet de nouveau de croiser les sessions : un
changement de sel consomme donc du budget (voir budget.py).
"""

import hashlib
import hmac
import itertools

from . import anonymat

# Cout d'information attribue a chaque niveau de generalisation.
# Les couts croissent : perdre la ville coute moins que perdre tout l'attribut.
COUT_NIVEAU = (0, 1, 3, 7)


def _empreinte(entite, kappa):
    """HMAC stable de l'entite, sous le sel de deploiement.

    Sert seulement a departager des gabarits de meme cout. Sans ce HMAC,
    n'importe qui connaissant l'algorithme et la population pourrait
    recalculer le gabarit de chaque candidat et retrouver l'entite par
    correspondance.
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

    Il y a peu de combinaisons : sept quasi-identifiants avec 1 a 3 niveaux
    chacun, soit quelques centaines de gabarits. On peut donc tous les
    enumerer, ce qui est plus simple qu'une heuristique et reste
    deterministe.
    """
    plages = [range(anonymat.NIVEAU_MAX.get(a, 1) + 1) for a in attributs]
    for combinaison in itertools.product(*plages):
        yield dict(zip(attributs, combinaison))


def calculer(population, entite, k, kappa, attributs=None):
    """Gabarit minimal garantissant |S| >= k pour cette entite.

    Renvoie le gabarit de cout minimal qui atteint le seuil. En cas
    d'egalite, l'empreinte de l'entite sous le sel departage. Si aucun
    gabarit n'atteint le seuil (entite trop atypique), renvoie le gabarit
    maximal, qui supprime tous les quasi-identifiants. L'appelant doit alors
    passer a la recuperation privee ou s'abstenir.

    Les candidats sont testes par cout croissant. La recherche s'arrete au
    premier cout qui donne une solution : le resultat reste minimal et on
    n'evalue qu'une partie des candidats.
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
            # Le sel departage les egalites : le gabarit reste deterministe
            # pour l'entite, mais un adversaire qui ne connait pas kappa ne
            # peut pas le recalculer.
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

    Sert au tirage aleatoire ci-dessous, et a voir combien de choix la
    politique a pour une entite donnee.
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

    Cette fonction correspond a la configuration C2 d'E2b, la contre-mesure
    naive que le rapport ecarte. Elle est implementee pour que la
    comparaison soit honnete.

    L'idee est d'eviter l'empreinte stable d'un gabarit deterministe
    (section 3.3.5). E2b montre que cela cree un risque plus grave : l'attaque
    par intersection redevient possible.
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
