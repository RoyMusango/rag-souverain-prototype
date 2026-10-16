"""
E2 et E2b : effondrement de l'ensemble d'anonymat.

C'est le resultat principal du travail. Il ne depend ni du modele de langue,
ni de l'index, ni du materiel : |S| se compte sur une population connue en
entier, sans mesure de temps. L'experience tourne donc sur un ultraportable,
sans index.

E2  : dans une meme session, que revele une suite de requetes ?
E2b : sur plusieurs sessions, le gabarit fige tient-il quand on cumule les
      requetes ?

Je compare trois configurations. C2 est la plus importante : elle garde le
budget par entite mais tire un nouveau gabarit a chaque session, et elle
echoue. Cela montre que c'est le gabarit fige qui protege contre
l'intersection. Comparer seulement C1 et C3 montrerait juste que la solution
fait mieux que rien.

    C1  gabarit retire par session   budget remis a zero par session
    C2  gabarit retire par session   budget indexe sur l'entite
    C3  gabarit fige sur l'entite    budget indexe sur l'entite

Trois valeurs resument chaque courbe :
    |S_T|   taille finale de l'ensemble d'anonymat
    t*      nombre de requetes emises avant le passage sous le seuil k
    aire    protection moyenne maintenue, normalisee
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from ..confidentialite import anonymat, budget as mod_budget, gabarit as mod_gabarit

C1 = "c1_session_session"
C2 = "c2_session_entite"
C3 = "c3_entite_entite"

LIBELLES = {
    C1: "Gabarit et budget par session",
    C2: "Gabarit par session, budget par entite",
    C3: "Gabarit et budget par entite",
}


@dataclass
class Trace:
    """Sequence de requetes d'enquete sur une meme entite.

    Chaque etape est un couple (session, attributs reveles). E2 utilise une
    seule session, E2b plusieurs.
    """
    cle_entite: str
    etapes: list = field(default_factory=list)

    @property
    def sessions(self):
        return sorted({s for s, _ in self.etapes})


def trace_enquete_aml(cle_entite, requetes_par_session=3, sessions=1):
    """Trace de reference : l'enquete anti-blanchiment de la section 3.3.3.

    Les attributs suivent l'ordre du rapport, du plus general au plus
    discriminant. C'est la sequence qui fait baisser |S| le plus vite, donc
    le pire cas.
    """
    ordre = ["comte", "ville", "tranche_age", "genre", "cp", "race", "ethnie"]
    etapes = []
    i = 0
    for s in range(sessions):
        for _ in range(requetes_par_session):
            etapes.append((f"session-{s + 1}", (ordre[i % len(ordre)],)))
            i += 1
    return Trace(cle_entite=cle_entite, etapes=etapes)


def trace_reprise(cle_entite, sessions=4):
    """Trace de reprise : chaque session rejoue les memes attributs.

    C'est ce qui se passe dans une enquete KYC qui dure : l'analyste revient
    sur la meme entite et repose des questions sur les memes attributs en les
    precisant. Cette trace teste si croiser les sessions aide l'adversaire
    (voir le commentaire de `executer`).
    """
    coeur = ("ville", "cp")
    etapes = []
    for s in range(sessions):
        for attribut in coeur:
            etapes.append((f"session-{s + 1}", (attribut,)))
    return Trace(cle_entite=cle_entite, etapes=etapes)


def _cle(entite):
    return str(entite.get("id") or entite.get("Id") or entite.get("patient"))


def executer(population, entite, trace, configuration, k=50,
             budget_bits=6.0, kappa="kappa-de-mesure", arret=True):
    """Deroule une trace dans une configuration et renvoie la courbe.

    L'adversaire est le meme dans les trois cas, et pessimiste : je suppose
    qu'il sait relier toutes les sessions. Il pourrait le faire par d'autres
    moyens (adresse de sortie, horaires) que l'application ne controle pas,
    donc la protection ne doit pas compter sur le fait qu'il ne le peut pas.

    `arret` choisit le mode. A True, la politique arrete d'envoyer des que le
    budget est epuise : c'est le comportement en production, qui mesure
    l'utilite. A False, toutes les requetes de la trace sont envoyees : on
    mesure la protection a effort constant.

    Il faut les deux modes. Avec le seul mode a arret, |S_T| et l'aire
    dependent du moment ou l'on s'arrete : une configuration qui bloque tot
    semble mieux proteger alors qu'elle a juste pose moins de questions.
    """
    if not isinstance(population, anonymat.Population):
        population = anonymat.Population(population)
    n = len(population)
    cle_entite = trace.cle_entite

    gabarits = {}       # session (ou 'global') -> gabarit en vigueur
    observes = []       # liste de [gabarit, attributs reveles sous lui]
    fuite_cumulee = 0.0
    budget_par_session = {}
    points = []

    def gabarit_pour(session):
        if configuration == C3:
            # Un seul gabarit pour toute l'enquete, tire avec une graine qui
            # ne depend que de l'entite et du sel : G(e) = f(e, kappa).
            #
            # C'est un tirage, comme en C1 et C2 : la methode de choix est la
            # meme dans les trois configurations, seule la cle change. On
            # compare donc la facon de compter le budget, a generalisation
            # egale.
            # En pratique, je fige le gabarit tire par la premiere session.
            # Les trois configurations partent du meme gabarit et donnent les
            # memes resultats pendant la premiere session. Elles different a
            # partir de la deuxieme, et c'est ce qu'on veut mesurer. L'ecart
            # observe ne vient donc pas du tirage.
            if "global" not in gabarits:
                premiere = trace.etapes[0][0] if trace.etapes else "session-1"
                gabarits["global"] = mod_gabarit.choisir_aleatoire(
                    population, entite, k, f"{kappa}|{premiere}"
                )
            return gabarits["global"]
        # C1 et C2 : un nouveau gabarit a chaque session.
        #
        # Il faut un vrai tirage au hasard parmi les gabarits admissibles.
        # Recalculer le gabarit minimal avec un autre sel ne suffit pas : ce
        # gabarit ne depend que de l'entite et de la population, donc il
        # retombe toujours sur le meme. Je l'ai decouvert pendant
        # l'experience. Pour que le changement de gabarit ait un effet (comme
        # dans une implementation qui voudrait effacer l'empreinte du
        # gabarit), on tire au hasard parmi les gabarits acceptables.
        if session not in gabarits:
            gabarits[session] = mod_gabarit.choisir_aleatoire(
                population, entite, k, f"{kappa}|{session}"
            )
        return gabarits[session]

    def enregistrer_observation(gabarit, attributs):
        """Ajoute les attributs a l'observation portant ce meme gabarit."""
        for observation in observes:
            if observation[0] == gabarit:
                observation[1] |= set(attributs)
                return
        observes.append([dict(gabarit), set(attributs)])

    for rang, (session, attributs) in enumerate(trace.etapes, start=1):
        gabarit = gabarit_pour(session)
        enregistrer_observation(gabarit, attributs)

        # L'adversaire croise les ensembles observes sous chaque gabarit.
        # Avec un seul gabarit (C3), il n'y a qu'une observation et le
        # croisement ne change rien : S_e inter S_e = S_e.
        courant = None
        for gab, attrs in observes:
            ensemble = population.membres(entite, gab, tuple(sorted(attrs)))
            courant = ensemble if courant is None else (courant & ensemble)

        taille = max(1, len(courant or ()))
        fuite_reelle = mod_budget.fuite_bits(n, taille)

        # Point cle de l'experience, et raison d'etre de C2.
        #
        # `fuite_reelle` est ce que l'adversaire apprend. Elle se calcule sur
        # le croisement de toutes les observations, tous gabarits confondus.
        #
        # `fuite_comptee` est ce que le systeme croit avoir revele, selon sa
        # propre facon de compter. C'est elle qui decide de l'envoi, car le
        # systeme ne voit pas la fuite reelle.
        #
        # Les deux sont egales seulement en C3. Dans les autres cas, le
        # systeme sous-estime la fuite et continue d'envoyer alors que
        # l'ensemble d'anonymat s'est deja effondre.
        if configuration == C1:
            # Comptage par session : seuls comptent les attributs reveles
            # dans la session en cours, sous le gabarit en cours.
            attributs_session = set()
            for s, a in trace.etapes[:rang]:
                if s == session:
                    attributs_session |= set(a)
            vue = population.taille_ensemble(
                entite, gabarit, tuple(sorted(attributs_session))
            )
            fuite_comptee = mod_budget.fuite_bits(n, max(1, vue))
        elif configuration == C2:
            # Budget par entite, mais nouveau gabarit par session : le systeme
            # cumule les attributs sur toute l'enquete, sans voir que changer
            # de gabarit permet une attaque par intersection.
            tous = set()
            for _, a in trace.etapes[:rang]:
                tous |= set(a)
            vue = population.taille_ensemble(
                entite, gabarit, tuple(sorted(tous))
            )
            fuite_comptee = mod_budget.fuite_bits(n, max(1, vue))
        else:
            # C3 : un seul gabarit, donc le systeme compte exactement ce que
            # voit l'adversaire. C'est le but recherche.
            fuite_comptee = fuite_reelle

        fuite_cumulee = max(fuite_cumulee, fuite_comptee)
        if configuration == C1:
            budget_par_session[session] = fuite_comptee
            restant = budget_bits - fuite_comptee
        else:
            restant = budget_bits - fuite_cumulee

        taille_comptee = max(1, round(n / (2 ** fuite_comptee)))
        bloque = taille_comptee < k or restant < 0

        points.append({
            "rang": rang,
            "session": session,
            "attributs": sorted(attributs),
            "taille_ensemble": taille,
            "fuite_bits": round(fuite_reelle, 4),
            "taille_comptee": taille_comptee,
            "fuite_comptee": round(fuite_comptee, 4),
            "budget_restant": round(restant, 4),
            "emise": not bloque,
            "gabarit": mod_gabarit.decrire(gabarit),
        })

        if bloque and arret:
            # Le systeme arrete d'envoyer : |S| ne baisse plus, puisqu'il n'y
            # a plus de nouvelle requete a croiser. D'ou le plateau de C3.
            for suite in range(rang + 1, len(trace.etapes) + 1):
                points.append({
                    "rang": suite,
                    "session": trace.etapes[suite - 1][0],
                    "attributs": sorted(trace.etapes[suite - 1][1]),
                    "taille_ensemble": taille,
                    "fuite_bits": round(fuite_reelle, 4),
                    "taille_comptee": taille_comptee,
                    "fuite_comptee": round(fuite_comptee, 4),
                    "budget_restant": round(restant, 4),
                    "emise": False,
                    "gabarit": mod_gabarit.decrire(gabarit),
                })
            break

    return {
        "configuration": configuration,
        "libelle": LIBELLES[configuration],
        "entite": cle_entite,
        "population": n,
        "k": k,
        "budget_bits": budget_bits,
        "points": points,
        "mode": "reel" if arret else "effort-constant",
        "scalaires": scalaires(points, n, k, budget_bits),
    }


def scalaires(points, taille_population, k, budget_bits=None):
    """Les trois valeurs qui resument la courbe.

    |S_T|  taille finale : ce que l'adversaire sait a la fin
    t*     rang de la premiere requete passant sous k ; None si jamais
    aire   moyenne de log|S| rapportee a log N, entre 0 et 1
    """
    if not points:
        return {"S_T": 0, "t_etoile": None, "aire_normalisee": 0.0,
                "aire_emises": 0.0, "requetes_emises": 0,
                "deficit_max_bits": 0.0, "deficit_final_bits": 0.0,
                "violation": False, "rang_violation": None}

    tailles = [p["taille_ensemble"] for p in points]
    t_etoile = next(
        (p["rang"] for p in points if p["taille_ensemble"] < k), None
    )
    reference = math.log(taille_population) if taille_population > 1 else 1.0
    aire = sum(math.log(max(1, t)) for t in tailles) / (len(tailles) * reference)

    # Aire calculee seulement sur les requetes envoyees. L'aire globale compte
    # aussi les points recopies apres le blocage, ce qui avantage les
    # configurations qui s'arretent tot.
    emis = [p for p in points if p["emise"]]
    if emis:
        aire_emises = sum(
            math.log(max(1, p["taille_ensemble"])) for p in emis
        ) / (len(emis) * reference)
    else:
        aire_emises = 0.0

    # Deficit de comptage : ecart entre ce que l'adversaire apprend et ce que
    # le systeme croit avoir revele. Il vaut toujours 0 en C3. C'est la seule
    # valeur qui mesure ce que le systeme ne voit pas, et elle ne depend pas
    # de la regle d'arret.
    deficits = [p["fuite_bits"] - p["fuite_comptee"] for p in points]
    deficit_max = max(deficits) if deficits else 0.0

    # Violation : le systeme a continue d'envoyer alors que la fuite reelle
    # depassait deja le plafond (cas d'echec de la section 3.3.5).
    violation = False
    rang_violation = None
    if budget_bits is not None:
        for p in points:
            if p["emise"] and p["fuite_bits"] > budget_bits:
                violation = True
                rang_violation = p["rang"]
                break

    return {
        "S_T": tailles[-1],
        "t_etoile": t_etoile,
        "aire_normalisee": round(aire, 4),
        "aire_emises": round(aire_emises, 4),
        "requetes_emises": len(emis),
        "deficit_max_bits": round(deficit_max, 4),
        "deficit_final_bits": round(deficits[-1] if deficits else 0.0, 4),
        "violation": violation,
        "rang_violation": rang_violation,
    }


def _pop(population):
    """Enveloppe la population dans l'index si ce n'est pas deja fait."""
    if isinstance(population, anonymat.Population):
        return population
    return anonymat.Population(population)


def campagne(population, entite, trace, k=50, budget_bits=6.0,
             kappa="kappa-de-mesure"):
    """Execute les trois configurations, dans les deux modes de mesure."""
    population = _pop(population)
    return {
        "population": len(population),
        "entite": trace.cle_entite,
        "k": k,
        "budget_bits": budget_bits,
        "taux_uniques_initial": round(_pop(population).taux_uniques(), 4),
        # Deux modes par configuration. Le mode reel mesure l'utilite et les
        # violations. Le mode a effort constant mesure la protection sur des
        # traces de meme longueur, donc comparables.
        "resultats": [
            executer(population, entite, trace, configuration,
                     k, budget_bits, kappa, arret=arret)
            for configuration in (C1, C2, C3)
            for arret in (True, False)
        ],
    }


def charger_population(chemin="data/synthea/entities.json"):
    """Charge la population produite par src/ingestion/build_entities.py.

    Ce fichier a la forme :

        {"meta": {...}, "entities": {"<patient_id>": {"ville": ..., ...}}}

    c'est-a-dire un dictionnaire indexe par identifiant patient. L'identifiant
    n'est pas repete dans la valeur, donc je le rajoute. Sinon le registre
    d'exposition ne pourrait pas distinguer les entites.
    """
    with open(chemin, encoding="utf-8") as f:
        donnees = json.load(f)

    if isinstance(donnees, dict) and "entities" in donnees:
        brut = donnees["entities"]
    elif isinstance(donnees, dict) and "entites" in donnees:
        brut = donnees["entites"]
    else:
        brut = donnees

    if isinstance(brut, dict):
        population = []
        for identifiant, attributs in brut.items():
            entite = dict(attributs)
            entite["id"] = identifiant
            population.append(entite)
        return population
    return list(brut)


def charger_meta(chemin="data/synthea/entities.json"):
    """Metadonnees de la population : graine, palier d'age, quasi-identifiants.

    Elles sont enregistrees avec chaque campagne. Sans elles, on ne peut pas
    reproduire la courbe ni savoir quels quasi-identifiants ont servi.
    """
    with open(chemin, encoding="utf-8") as f:
        donnees = json.load(f)
    return donnees.get("meta", {}) if isinstance(donnees, dict) else {}


def enregistrer(resultat, chemin):
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(resultat, f, ensure_ascii=False, indent=2)
    return chemin
