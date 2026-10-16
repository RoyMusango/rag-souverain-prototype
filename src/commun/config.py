"""
Configuration centrale du projet.

Tous les seuils, paliers, chemins et parametres de campagne sont definis ici.
Les autres modules ne contiennent pas de constante metier : ce qui depend du
secteur se regle dans ce fichier (section 1.4 du rapport).

Le module decrit aussi le materiel utilise. La section 4.1.1 du rapport
distingue deux usages du calcul :

  - le developpement, ou n'importe quel materiel convient (GPU loue, carnet
    cloud...), sur donnees synthetiques ;
  - les campagnes de mesure du palier local, qui doivent tourner sur un
    materiel representatif d'un deploiement sur site.

Chaque trace d'execution enregistre donc le materiel. Sans cette information,
on ne pourrait pas distinguer une latence mesuree sur un GPU loue d'une
latence mesuree sur le cluster de l'universite.
"""

import os
import platform
from dataclasses import dataclass, field, asdict

# --------------------------------------------------------------- materiel

DEV = "developpement"        # iteration rapide, latence non valable
MESURE_SOUVERAINE = "mesure-souveraine"   # valable pour le palier local
MESURE_TIERCE = "mesure-tierce"           # point de comparaison


@dataclass
class Materiel:
    """Description de la machine de calcul, enregistree avec chaque execution.

    `role` indique quelles mesures sont valables :
      DEV                -> qualite valable, latence et cout seulement indicatifs
      MESURE_SOUVERAINE  -> latence et cout du palier local valables
      MESURE_TIERCE      -> point de comparaison, hors perimetre souverain
    """
    nom: str = "inconnu"
    role: str = DEV
    accelerateur: str = "aucun"
    juridiction: str = "inconnue"
    souverain: bool = False
    note: str = ""

    def valider_pour(self, grandeur):
        """Indique si la grandeur mesuree est valable sur ce materiel.

        `grandeur` vaut 'qualite', 'latence' ou 'cout'. La qualite d'un modele
        peut se mesurer sur n'importe quel materiel. La latence et le cout du
        palier local demandent le materiel representatif.
        """
        if grandeur == "qualite":
            return True, ""
        if self.role == MESURE_SOUVERAINE:
            return True, ""
        return False, (
            f"{grandeur} relevee sur un materiel de role '{self.role}' "
            f"({self.nom}) : valeur seulement indicative pour le "
            f"palier local (section 4.1.1)."
        )


# Profils connus, a completer avec les caracteristiques reelles du materiel.
# Le profil ShadowPC a ete retire pour des raisons de souverainete, meme si
# le fournisseur est europeen.
PROFILS = {
    "ultraportable": Materiel(
        nom="ultraportable de developpement", role=DEV,
        accelerateur="aucun", juridiction="Belgique", souverain=True,
        note="ingestion et E2 ; aucun accelerateur graphique",
    ),
    "scaleway": Materiel(
        nom="instance GPU louee (Scaleway L4-1-24G, PAR-2)",
        role=MESURE_SOUVERAINE,
        accelerateur="NVIDIA L4 24 Go",
        juridiction="France (PAR-2)", souverain=True,
        note="calcul des embeddings ; machine louee, pas un service distant",
    ),
    "cluster": Materiel(
        nom="cluster de l'universite", role=MESURE_SOUVERAINE,
        accelerateur="GPU (a preciser)", juridiction="Belgique",
        souverain=True,
        note="mesure de reference pour la latence et le cout du palier local",
    ),
    "api-tierce": Materiel(
        nom="infrastructure du fournisseur d'inference", role=MESURE_TIERCE,
        accelerateur="n/a", juridiction="hors Union", souverain=False,
    ),
}


def materiel_courant():
    """Profil de materiel choisi par la variable RAG_MATERIEL.

    Sans variable, le profil "ultraportable" s'applique. Exemple :

        $env:RAG_MATERIEL = "scaleway"
    """
    cle = os.environ.get("RAG_MATERIEL", "ultraportable")
    profil = PROFILS.get(cle, PROFILS["ultraportable"])
    return profil


def empreinte_machine():
    """Elements de contexte a consigner avec chaque execution."""
    return {
        "systeme": platform.system(),
        "version": platform.release(),
        "processeur": platform.processor() or platform.machine(),
        "python": platform.python_version(),
    }


# ----------------------------------------------------------- confidentialite

@dataclass
class ConfigConfidentialite:
    """Pilier 2. Ces valeurs se reglent au deploiement."""
    k: int = 50
    budget_bits: float = 6.0
    kappa: str = "a-remplacer-au-deploiement"
    moteur_ner: str = "souverain"      # 'souverain' (spaCy) ou 'presidio'
    langue_ner: str = "fr"
    tolerance_gabarit: int = 4
    chemin_registre: str = "data/registre_exposition.json"


@dataclass
class ConfigRoutage:
    """Pilier 1."""
    seuil_pertinence: float = 0.55
    seuil_completude: float = 0.70
    correction_autorisee: bool = True
    escalade_autorisee: bool = True


@dataclass
class ConfigRecherche:
    """Cascade hybride, section 2.2."""
    modele_embeddings: str = "BAAI/bge-m3"
    dimension: int = 1024
    top_k_dense: int = 50
    top_k_lexical: int = 50
    top_k_reclassement: int = 20
    n_final: int = 10
    modele_reclasseur: str = "BAAI/bge-reranker-v2-m3"
    k_rrf: int = 60
    collection: str = "rag_souverain"
    hote_qdrant: str = "http://localhost:6333"


@dataclass
class ConfigIsolation:
    """Pilier 3."""
    seuil_corroboration: int = 2
    seuil_collusion: int = 2
    penalite_collusion: float = 0.1


@dataclass
class ConfigGeneration:
    """Abstraction de fournisseur, trois paliers."""
    palier: str = "local"          # local | api-ue | api-hors-ue
    modele: str = "mistral-small"
    max_jetons: int = 1024
    temperature: float = 0.0       # deterministe, pour pouvoir rejouer


@dataclass
class Config:
    """Configuration complete d'une execution."""
    confidentialite: ConfigConfidentialite = field(
        default_factory=ConfigConfidentialite)
    routage: ConfigRoutage = field(default_factory=ConfigRoutage)
    recherche: ConfigRecherche = field(default_factory=ConfigRecherche)
    isolation: ConfigIsolation = field(default_factory=ConfigIsolation)
    generation: ConfigGeneration = field(default_factory=ConfigGeneration)
    graine: int = 42
    materiel: Materiel = field(default_factory=materiel_courant)

    def en_dict(self):
        return asdict(self)
