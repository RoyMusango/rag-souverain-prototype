"""
Budget d'exposition et registre (sections 3.2.4 et 3.3.5 du rapport).

Le budget se compte par secret protege, pas par session. Un budget remis a
zero a la fin de chaque session ne limiterait rien : il suffirait de fermer
puis de rouvrir la session. Le budget est donc attache a l'entite enquetee
et enregistre sur disque, d'une session a l'autre. C'est le meme principe
qu'en confidentialite differentielle, ou le budget est attache a l'individu
protege.

La fuite est mesuree en bits :

    fuite = log2( N / |S| )

Elle vaut 0 quand |S| = N et atteint son maximum quand |S| = 1. Le budget
plafonne cette valeur. Les fuites s'additionnent d'une requete a l'autre,
comme en confidentialite differentielle.

Le registre sert aussi de base a la piste d'audit (invariant I3,
journalisation demandee par le reglement europeen sur l'IA).
"""

import json
import math
import time
from pathlib import Path

CHEMIN_REGISTRE = Path("data/registre_exposition.json")

# Valeurs par defaut. Au deploiement, elles se reglent dans la configuration
# et pas dans le code du moteur.
K_DEFAUT = 50
BUDGET_BITS_DEFAUT = 6.0


def fuite_bits(taille_population, taille_ensemble):
    """Fuite cumulee, en bits, pour un ensemble d'anonymat donne."""
    if taille_ensemble <= 0:
        return float("inf")
    return math.log2(taille_population / taille_ensemble)


class Registre:
    """Registre d'exposition par entite, enregistre sur disque.

    Une instance couvre tout un deploiement : elle est chargee au demarrage
    et reecrite a chaque mise a jour. Le fichier est un JSON lisible, pour
    qu'un auditeur puisse le relire.
    """

    def __init__(self, chemin=CHEMIN_REGISTRE, budget_bits=BUDGET_BITS_DEFAUT,
                 k=K_DEFAUT, kappa="kappa-de-developpement"):
        self.chemin = Path(chemin)
        self.budget_bits = budget_bits
        self.k = k
        self.kappa = kappa
        self.entrees = {}
        self.charger()

    # ---------------------------------------------------------------- E/S

    def charger(self):
        if self.chemin.exists():
            with open(self.chemin, encoding="utf-8") as f:
                donnees = json.load(f)
            self.entrees = donnees.get("entrees", {})
            self.kappa = donnees.get("kappa", self.kappa)
        return self

    def enregistrer(self):
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        with open(self.chemin, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "kappa": self.kappa,
                    "budget_bits": self.budget_bits,
                    "k": self.k,
                    "entrees": self.entrees,
                },
                f, ensure_ascii=False, indent=2,
            )
        return self

    # ------------------------------------------------------------- lecture

    def entree(self, cle_entite):
        """Etat courant d'une entite. Cree l'entree si elle n'existe pas."""
        if cle_entite not in self.entrees:
            self.entrees[cle_entite] = {
                "gabarit": None,
                "attributs_reveles": [],
                "fuite_bits": 0.0,
                "requetes": 0,
                "sessions": [],
                "escalades": [],
                "cree": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        return self.entrees[cle_entite]

    def budget_restant(self, cle_entite):
        return self.budget_bits - self.entree(cle_entite)["fuite_bits"]

    def epuise(self, cle_entite):
        return self.budget_restant(cle_entite) <= 0

    # ------------------------------------------------------------ ecriture

    def fixer_gabarit(self, cle_entite, gabarit):
        """Fige le gabarit d'une entite. Rappeler la fonction ne change rien.

        Un second appel sur la meme entite ne tire pas de nouveau gabarit : il
        renvoie celui deja enregistre. Ouvrir une nouvelle session ne permet
        donc pas de contourner le budget.
        """
        entree = self.entree(cle_entite)
        if entree["gabarit"] is None:
            entree["gabarit"] = dict(gabarit)
        return entree["gabarit"]

    def consommer(self, cle_entite, attributs, fuite, session=None):
        """Enregistre une emission et sa fuite cumulee."""
        entree = self.entree(cle_entite)
        reveles = set(entree["attributs_reveles"]) | set(attributs)
        entree["attributs_reveles"] = sorted(reveles)
        entree["fuite_bits"] = float(fuite)
        entree["requetes"] += 1
        if session and session not in entree["sessions"]:
            entree["sessions"].append(session)
        return entree

    def journaliser_escalade(self, cle_entite, motif, operateur, session=None):
        """Enregistre une escalade validee par un humain (section 3.2).

        Une escalade est une sortie autorisee explicitement, avec un motif,
        et enregistree. Elle figure dans la piste d'audit.
        """
        entree = self.entree(cle_entite)
        entree["escalades"].append({
            "horodatage": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "motif": motif,
            "operateur": operateur,
            "session": session,
        })
        return entree

    def reinitialiser(self, cle_entite=None):
        """Vide le registre. Reserve aux campagnes de mesure, jamais en production.

        C'est le seul moyen de remettre le registre a zero. Son nom explicite
        evite de l'appeler par erreur depuis le pipeline.
        """
        if cle_entite is None:
            self.entrees = {}
        else:
            self.entrees.pop(cle_entite, None)
        return self
