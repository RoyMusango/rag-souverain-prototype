"""
E2 et E2b : effondrement de l'ensemble d'anonymat.

C'est le resultat central de ce travail. Il ne depend ni du modele de langue,
ni de l'index, ni du materiel : |S| est un decompte sur une population
exactement enumeree, et non une mesure de temps. L'experience peut donc etre
executee sur un ultraportable, avant toute construction d'index.

E2  : au sein d'une meme session, que revele une suite de requetes ?
E2b : a travers plusieurs sessions, le gabarit fige resiste-t-il a la
      composition ?

Je compare trois configurations. C2 porte l'essentiel de la demonstration :
son echec etablit que la resistance a l'intersection tient au determinisme
du gabarit, et non a la comptabilite du budget. Une comparaison C1 contre C3
montrerait seulement que la solution vaut mieux que rien.

    C1  gabarit retire par session   budget remis a zero par session
    C2  gabarit retire par session   budget indexe sur l'entite
    C3  gabarit fige sur l'entite    budget indexe sur l'entite

Trois scalaires resument chaque courbe et en font une mesure :
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

    Chaque etape est un couple (session, attributs reveles). Le decoupage en
    sessions est ce qui distingue E2 (une seule session) de E2b (plusieurs).
    """
    cle_entite: str
    etapes: list = field(default_factory=list)

    @property
    def sessions(self):
        return sorted({s for s, _ in self.etapes})


def trace_enquete_aml(cle_entite, requetes_par_session=3, sessions=1):
    """Trace canonique : l'enquete anti-blanchiment de la section 3.3.3.

    L'ordre des attributs reproduit la progression decrite dans le rapport,
    du plus general au plus discriminant. C'est la sequence qui fait
    decroitre |S| le plus vite, donc le cas le plus defavorable.
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

    C'est le schema reel d'une enquete KYC qui s'etale dans le temps :
    l'analyste revient sur la meme entite et reinterroge les memes dimensions
    en les affinant. Ce schema determine si la liaison de sessions est
    exploitable (voir le commentaire de `executer`).
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
    """Deroule une trace sous une configuration et retourne la courbe.

    Le modele d'adversaire est pessimiste et identique dans les trois cas :
    je suppose qu'il relie toutes les sessions. La liaison par canal
    auxiliaire (adresse de sortie, proximite temporelle) etant hors du
    perimetre applicatif, je ne fais pas reposer la protection sur elle.

    `arret` determine l'axe mesure. A True, la politique interrompt l'emission
    des que le budget est epuise : c'est le comportement de deploiement, qui
    mesure l'utilite. A False, toutes les requetes de la trace sont emises :
    c'est un contrefactuel qui mesure la protection a effort constant.

    Les deux modes sont necessaires. Avec le seul mode a arret, |S_T| et
    l'aire sont censures par l'instant d'arret : une configuration qui bloque
    tot parait mieux protegee alors qu'elle a simplement moins interroge.
    Comparer des trajectoires interrompues a des rangs differents n'aurait
    pas de sens.
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
            # Un seul gabarit pour toute l'enquete, tire sous une graine qui
            # ne depend que de l'entite et du sel : G(e) = f(e, kappa).
            #
            # Il s'agit bien d'un tirage, comme en C1 et C2 : la politique de
            # selection est identique dans les trois configurations, seule la
            # cle sous laquelle elle est indexee varie. La comparaison porte
            # ainsi sur l'unite de comptabilite et non sur la force de la
            # generalisation.
            # En pratique, je fige le gabarit tire par la premiere session.
            # Les trois configurations partent donc du meme gabarit et sont
            # indiscernables tant qu'une seule session s'est ecoulee ; elles
            # divergent a l'ouverture de la deuxieme session, la ou porte la
            # question. La difference observee ne peut donc pas provenir du
            # tirage.
            if "global" not in gabarits:
                premiere = trace.etapes[0][0] if trace.etapes else "session-1"
                gabarits["global"] = mod_gabarit.choisir_aleatoire(
                    population, entite, k, f"{kappa}|{premiere}"
                )
            return gabarits["global"]
        # C1 et C2 : un gabarit retire a chaque session.
        #
        # Le tirage doit etre effectivement aleatoire parmi les gabarits
        # admissibles, et non un simple recalcul sous un autre sel. C'est un
        # resultat de cette experience, contre-intuitif : une generalisation
        # minimale et deterministe est deja indexee sur l'entite par
        # construction, puisqu'elle ne depend que de l'entite et de la
        # population, et la recalculer par session ne change rien. Pour que
        # le retirage ait un sens (ce que ferait une implementation cherchant
        # a effacer l'empreinte du gabarit), il faut choisir au hasard parmi
        # les gabarits acceptables.
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

        # L'adversaire intersecte les ensembles observes sous chaque gabarit
        # rencontre. Avec un gabarit unique (C3), il n'y a qu'une observation
        # et l'intersection est sans effet : S_e inter S_e = S_e.
        courant = None
        for gab, attrs in observes:
            ensemble = population.membres(entite, gab, tuple(sorted(attrs)))
            courant = ensemble if courant is None else (courant & ensemble)

        taille = max(1, len(courant or ()))
        fuite_reelle = mod_budget.fuite_bits(n, taille)

        # Distinction centrale de l'experience, et raison d'etre de C2.
        #
        # `fuite_reelle` est ce que l'adversaire apprend : elle se lit sur
        # l'intersection de toutes les observations, tous gabarits confondus.
        #
        # `fuite_comptee` est ce que le systeme estime avoir revele, selon sa
        # propre politique de comptabilite. C'est elle seule qui decide de
        # l'emission, puisqu'un systeme ne peut pas s'arreter sur une
        # quantite qu'il n'observe pas.
        #
        # Les deux coincident uniquement en C3. Ailleurs, le systeme
        # sous-estime la fuite et continue d'emettre alors que l'ensemble
        # d'anonymat s'est deja effondre.
        if configuration == C1:
            # Comptabilite par session : seuls les attributs reveles dans la
            # session courante, sous le gabarit courant, sont pris en compte.
            attributs_session = set()
            for s, a in trace.etapes[:rang]:
                if s == session:
                    attributs_session |= set(a)
            vue = population.taille_ensemble(
                entite, gabarit, tuple(sorted(attributs_session))
            )
            fuite_comptee = mod_budget.fuite_bits(n, max(1, vue))
        elif configuration == C2:
            # Budget par entite, mais gabarit retire : le systeme cumule les
            # attributs sur toute l'enquete, sans voir que le changement de
            # gabarit ouvre une attaque par intersection.
            tous = set()
            for _, a in trace.etapes[:rang]:
                tous |= set(a)
            vue = population.taille_ensemble(
                entite, gabarit, tuple(sorted(tous))
            )
            fuite_comptee = mod_budget.fuite_bits(n, max(1, vue))
        else:
            # C3 : un gabarit unique, donc la comptabilite du systeme coincide
            # exactement avec la vue de l'adversaire. C'est la propriete visee.
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
            # Le systeme cesse d'emettre : |S| ne se degrade plus, faute de
            # nouvelle requete a intersecter. C'est l'origine du plateau de C3.
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
    """Les trois grandeurs qui font de la courbe une mesure.

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

    # Aire restreinte aux requetes effectivement emises. L'aire globale inclut
    # les points de plateau recopies apres blocage : elle favorise l'arret
    # precoce, soit l'inverse de ce que je cherche a mesurer.
    emis = [p for p in points if p["emise"]]
    if emis:
        aire_emises = sum(
            math.log(max(1, p["taille_ensemble"])) for p in emis
        ) / (len(emis) * reference)
    else:
        aire_emises = 0.0

    # Deficit de comptabilite : ecart entre ce que l'adversaire apprend et ce
    # que le systeme estime avoir revele. Nul par construction en C3. C'est la
    # seule grandeur qui mesure l'aveuglement du systeme, et elle ne depend
    # d'aucune regle d'arret.
    deficits = [p["fuite_bits"] - p["fuite_comptee"] for p in points]
    deficit_max = max(deficits) if deficits else 0.0

    # Violation : le systeme a continue d'emettre alors que la fuite reelle
    # avait deja franchi le plafond (mode d'echec de la section 3.3.5).
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
        # violations ; le mode a effort constant mesure la protection sur des
        # trajectoires de meme longueur, donc comparables.
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

    c'est-a-dire un dictionnaire indexe par identifiant patient, et non une
    liste. L'identifiant n'etant pas repete dans la valeur, je le reinjecte ;
    sinon les entites seraient indiscernables pour le harnais lui-meme et le
    registre d'exposition ne pourrait pas les distinguer.
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

    Elles doivent etre consignees avec chaque campagne : sans elles, la
    courbe n'est pas reproductible et les quasi-identifiants employes restent
    implicites.
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
