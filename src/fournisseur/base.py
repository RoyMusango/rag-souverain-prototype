"""
Abstraction de fournisseur : trois paliers de souverainete (section 3.1.5).

Une seule interface pour les trois paliers, qui sont donc interchangeables.
Le palier est enregistre avec chaque appel. C'est ici que l'on mesure la
latence, le cout et le nombre de jetons sortants utilises au chapitre 5.

Choisir le palier local supprime la Frontiere B, mais le risque se deplace.
Un modele local, souvent plus petit, peut etre plus sensible aux injections
(invariant I2) et moins fidele aux sources qu'un grand modele servi par API.
L'interet d'un deploiement entierement souverain doit donc etre mesure.
C'est pour cela que chaque trace contient le champ `palier`.
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
    """Mesures d'un appel, pour le chapitre 5."""
    palier: str
    latence_ms: float = 0.0
    jetons_entree: int = 0
    jetons_sortie: int = 0
    cout_eur: float = 0.0
    frontiere_b_franchie: bool = False
    etapes: dict = field(default_factory=dict)


class Fournisseur:
    """Interface commune aux trois paliers.

    Les sous-classes redefinissent `_appeler`. Le pipeline ne les cree jamais
    lui-meme : il ne connait que cette interface. On change donc de palier
    dans la configuration, sans toucher au pipeline.
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
        """Appel mesure. Toute generation passe par ici."""
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
        """Totaux et medianes pour le chapitre 5, par palier."""
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
        # A brancher sur le serveur local (Ollama). Pas encore code. La
        # fonction doit renvoyer (texte, jetons_in, jetons_out).
        raise NotImplementedError(
            "brancher le client local ; voir JOURNAL_DONNEES.md section 9"
        )


class FournisseurAPI(Fournisseur):
    """Paliers a API. La Frontiere B reste en Europe ou non, selon le palier."""

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

    Il permet de rejouer a l'identique les experiences du chapitre 5.
    """

    def __init__(self, reponses=None, palier=LOCAL):
        super().__init__(palier, "simule")
        self.reponses = reponses or {}
        self.defaut = "je ne sais pas"

    def _appeler(self, prompt, systeme=None, max_jetons=1024):
        texte = self.reponses.get(prompt, self.defaut)
        return texte, len(prompt.split()), len(texte.split())
