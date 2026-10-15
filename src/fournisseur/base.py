"""
Abstraction de fournisseur : trois paliers de souverainete (section 3.1.5).

Interface unique derriere laquelle les trois paliers sont interchangeables.
Le palier est journalise, et c'est a cette frontiere que sont instrumentes la
latence, le cout et le volume de jetons sortants exploites au chapitre 5.

Choix de conception : supprimer la Frontiere B en choisissant le palier local
ne supprime pas le risque, il le deplace. Un modele local, souvent plus petit,
peut se reveler plus vulnerable aux injections (invariant I2) et moins fidele
aux sources qu'une API adossee a un modele de grande taille. Le benefice reel
d'un deploiement entierement souverain ne peut donc etre tenu pour acquis et
doit etre mesure ; c'est la raison d'etre du champ `palier` dans chaque trace.
"""

import time
from dataclasses import dataclass, field

LOCAL = "local"
API_UE = "api-ue"
API_HORS_UE = "api-hors-ue"

# La Frontiere B n'existe qu'aux paliers a API. Le palier local la supprime.
FRONTIERE_B = {LOCAL: False, API_UE: True, API_HORS_UE: True}


@dataclass
class Trace:
    """Instrumentation d'un appel, pour le chapitre 5."""
    palier: str
    latence_ms: float = 0.0
    jetons_entree: int = 0
    jetons_sortie: int = 0
    cout_eur: float = 0.0
    frontiere_b_franchie: bool = False
    etapes: dict = field(default_factory=dict)


class Fournisseur:
    """Interface commune aux trois paliers.

    Les implementations concretes surchargent `_appeler`. Elles ne doivent
    jamais etre instanciees directement par le pipeline : celui-ci ne connait
    que cette interface, ce qui rend le palier commutable par configuration.
    """

    def __init__(self, palier, modele, tarif_entree=0.0, tarif_sortie=0.0):
        self.palier = palier
        self.modele = modele
        self.tarif_entree = tarif_entree
        self.tarif_sortie = tarif_sortie
        self.traces = []

    def _appeler(self, prompt, systeme=None, max_jetons=1024):
        raise NotImplementedError

    def generer(self, prompt, systeme=None, max_jetons=1024, etapes_amont=None):
        """Appel instrumente. Toute generation passe par ici."""
        debut = time.perf_counter()
        texte, jetons_entree, jetons_sortie = self._appeler(
            prompt, systeme, max_jetons
        )
        latence = (time.perf_counter() - debut) * 1000

        trace = Trace(
            palier=self.palier,
            latence_ms=round(latence, 2),
            jetons_entree=jetons_entree,
            jetons_sortie=jetons_sortie,
            cout_eur=round(
                jetons_entree * self.tarif_entree
                + jetons_sortie * self.tarif_sortie, 6
            ),
            frontiere_b_franchie=FRONTIERE_B[self.palier],
        )
        if etapes_amont:
            trace.etapes.update(etapes_amont)
        trace.etapes["generation_ms"] = trace.latence_ms
        self.traces.append(trace)
        return texte, trace

    def resume(self):
        """Agregats pour le chapitre 5, ventiles par palier."""
        if not self.traces:
            return {}
        latences = sorted(t.latence_ms for t in self.traces)
        return {
            "palier": self.palier,
            "modele": self.modele,
            "appels": len(self.traces),
            "latence_mediane_ms": latences[len(latences) // 2],
            "latence_p90_ms": latences[int(len(latences) * 0.9)],
            "jetons_sortants": sum(t.jetons_sortie for t in self.traces),
            "cout_total_eur": round(sum(t.cout_eur for t in self.traces), 4),
            "frontiere_b": FRONTIERE_B[self.palier],
        }


class FournisseurLocal(Fournisseur):
    """Palier souverain : modele ouvert servi localement. Supprime B."""

    def __init__(self, modele="mistral-small", hote="http://localhost:11434"):
        super().__init__(LOCAL, modele)
        self.hote = hote

    def _appeler(self, prompt, systeme=None, max_jetons=1024):
        # A connecter au serveur local (Ollama). Laisse explicitement non
        # implemente ; le contrat de retour est (texte, jetons_in, jetons_out).
        raise NotImplementedError(
            "brancher le client local ; voir JOURNAL_DONNEES.md section 9"
        )


class FournisseurAPI(Fournisseur):
    """Paliers a API. Maintient ou non B dans l'espace juridique europeen."""

    def __init__(self, palier=API_UE, modele="mistral-large",
                 tarif_entree=0.0, tarif_sortie=0.0, client=None):
        super().__init__(palier, modele, tarif_entree, tarif_sortie)
        self.client = client

    def _appeler(self, prompt, systeme=None, max_jetons=1024):
        if self.client is None:
            raise NotImplementedError("injecter le client d'API")
        return self.client(prompt, systeme, max_jetons)


class FournisseurSimule(Fournisseur):
    """Fournisseur deterministe, pour les tests et les ablations.

    Il conditionne le rejeu a l'identique des experiences du chapitre 5.
    """

    def __init__(self, reponses=None, palier=LOCAL):
        super().__init__(palier, "simule")
        self.reponses = reponses or {}
        self.defaut = "je ne sais pas"

    def _appeler(self, prompt, systeme=None, max_jetons=1024):
        texte = self.reponses.get(prompt, self.defaut)
        return texte, len(prompt.split()), len(texte.split())
