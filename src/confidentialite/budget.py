"""
Budget d'exposition et registre (sections 3.2.4 et 3.3.5 du rapport).

L'unite de comptabilite est le secret, et non l'interaction. Un budget remis
a zero a la cloture d'une session ne bornerait rien : il suffirait de fermer
puis de rouvrir la session. Le budget est donc attache a l'entite enquetee,
persiste sur disque et survit aux frontieres de session, selon la meme
discipline qu'en confidentialite differentielle, ou le budget est attache a
l'individu protege et non au lot de requetes.

Mesure de la fuite retenue, en bits :

    fuite = log2( N / |S| )

C'est la reduction d'incertitude de l'adversaire sur l'entite : nulle quand
|S| = N, maximale quand |S| = 1. Le budget plafonne cette quantite, ce qui
donne une composition additive analogue a la composition differentielle.

Le registre produit par ce module sert aussi de substrat a la piste d'audit
(invariant I3, journalisation attendue par le reglement europeen sur l'IA).
"""

import json
import math
import time
from pathlib import Path

CHEMIN_REGISTRE = Path("data/registre_exposition.json")

# Valeurs par defaut du deploiement. A fixer en configuration, jamais en dur
# dans le corps du moteur (le coeur ne porte aucune regle sectorielle).
K_DEFAUT = 50
BUDGET_BITS_DEFAUT = 6.0


def fuite_bits(taille_population, taille_ensemble):
    """Fuite cumulee, en bits, pour un ensemble d'anonymat donne."""
    if taille_ensemble <= 0:
        return float("inf")
    return math.log2(taille_population / taille_ensemble)


class Registre:
    """Registre d'exposition, indexe par entite et persiste.

    Une instance couvre tout un deploiement : elle est chargee au demarrage
    et reecrite a chaque mise a jour. Le format est volontairement du JSON
    lisible, afin de pouvoir etre relu par un auditeur.
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
        """Fige le gabarit d'une entite. Operation idempotente, ce qui est essentiel.

        Un second appel sur la meme entite ne retire pas de nouveau gabarit :
        il retourne celui deja enregistre, ce qui neutralise le contournement
        du budget par reinitialisation de session.
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
        """Trace une escalade sous validation humaine (section 3.2).

        L'escalade n'est pas un relachement de la politique mais une sortie
        legitime, explicitement autorisee, motivee et journalisee. Son
        enregistrement alimente la piste d'audit.
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
        """Purge, reservee aux campagnes de mesure et jamais au deploiement.

        C'est volontairement la seule voie de remise a zero, et son nom evite
        un appel accidentel depuis le pipeline.
        """
        if cle_entite is None:
            self.entrees = {}
        else:
            self.entrees.pop(cle_entite, None)
        return self
