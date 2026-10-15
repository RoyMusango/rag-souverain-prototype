"""
Configuration centralisee : aucune regle sectorielle dans le coeur du moteur.

Le rapport (section 1.4) pose que les specificites sectorielles relevent de
la configuration. Ce module en est l'application : seuils, paliers, chemins
et parametres de campagne y sont rassembles, et aucun autre module ne doit
contenir de constante metier.

Il porte aussi la description du materiel, qui conditionne l'interpretation
des mesures. La section 4.1.1 du rapport distingue deux roles du calcul :

  - developpement et iteration rapide, ou tout materiel convient, y compris
    un GPU loue ou un carnet cloud, sur donnees synthetiques ;
  - campagne de mesure du palier local, dont l'objet est de representer un
    deploiement souverain sur site, et qui exige un materiel representatif
    et souverain.

Chaque trace d'execution indique donc le materiel employe. Sans ce champ, une
latence relevee sur un GPU loue serait indiscernable d'une latence relevee
sur le cluster de l'universite, et le chapitre 5 melangerait deux grandeurs
non comparables.
"""

import os
import platform
from dataclasses import dataclass, field, asdict

# --------------------------------------------------------------- materiel

DEV = "developpement"        # iteration rapide, ne fait pas foi pour la latence
MESURE_SOUVERAINE = "mesure-souveraine"   # fait foi pour le palier local
MESURE_TIERCE = "mesure-tierce"           # borne de comparaison


@dataclass
class Materiel:
    """Description du substrat de calcul, attachee a chaque execution.

    `role` determine la portee de la mesure :
      DEV                -> qualite oui, latence et cout non opposables
      MESURE_SOUVERAINE  -> latence et cout du palier local, opposables
      MESURE_TIERCE      -> borne de comparaison, hors perimetre souverain
    """
    nom: str = "inconnu"
    role: str = DEV
    accelerateur: str = "aucun"
    juridiction: str = "inconnue"
    souverain: bool = False
    note: str = ""

    def valider_pour(self, grandeur):
        """La grandeur mesuree est-elle opposable sur ce materiel ?

        `grandeur` vaut 'qualite', 'latence' ou 'cout'. La qualite d'un modele
        se mesure sur tout materiel, au besoin sur un echantillon ; la latence
        et le cout du palier local exigent en revanche le materiel
        representatif.
        """
        if grandeur == "qualite":
            return True, ""
        if self.role == MESURE_SOUVERAINE:
            return True, ""
        return False, (
            f"{grandeur} relevee sur un materiel de role '{self.role}' "
            f"({self.nom}) : valeur indicative, non opposable pour le "
            f"palier local (section 4.1.1)."
        )


# Profils connus, a completer avec les caracteristiques reelles du materiel.
# Le profil ShadowPC a ete ecarte pour des raisons de souverainete, bien que
# le fournisseur soit europeen.
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
        note="calcul des embeddings ; substrat de calcul, non service distant",
    ),
    
    "cluster": Materiel(
        nom="cluster de l'universite", role=MESURE_SOUVERAINE,
        accelerateur="GPU — a preciser", juridiction="Belgique",
        souverain=True,
        note="mesure de reference pour la latence et le cout du palier local",
    ),
    "api-tierce": Materiel(
        nom="infrastructure du fournisseur d'inference", role=MESURE_TIERCE,
        accelerateur="n/a", juridiction="hors Union", souverain=False,
    ),
}


def materiel_courant():
    """Materiel declare par l'environnement, avec un defaut prudent.

        set RAG_MATERIEL=shadow
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
    """Pilier 2. Ces valeurs relevent du deploiement, non du moteur."""
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
    temperature: float = 0.0       # deterministe, condition du rejeu


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
