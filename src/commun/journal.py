"""
Reproductibilite : manifeste, empreintes, journal d'execution (section 4.1.5).

Le rapport s'engage sur une discipline precise : versions epinglees, graines
fixees, index persiste, et chaque execution estampillee par une empreinte du
manifeste et du commit. Cette discipline conditionne l'auditabilite attendue
par le reglement europeen sur l'IA et la resilience visee par DORA. Ce module
la rend effective.

Une execution non estampillee ne doit pas figurer au chapitre 5.
"""

import hashlib
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

from . import config as mod_config


def hash_fichier(chemin, blocs=1 << 20):
    """Empreinte SHA-256 d'un fichier, calculee par blocs (corpus volumineux)."""
    empreinte = hashlib.sha256()
    with open(chemin, "rb") as f:
        while True:
            bloc = f.read(blocs)
            if not bloc:
                break
            empreinte.update(bloc)
    return empreinte.hexdigest()


def hash_manifeste(chemins):
    """Empreinte d'un ensemble de fichiers : le manifeste de donnees.

    Deux executions portant la meme empreinte de manifeste ont vu exactement
    les memes corpus, ce qui permet d'attribuer un ecart de resultat au
    moteur et non aux donnees.
    """
    entrees = {}
    for chemin in sorted(str(c) for c in chemins):
        p = Path(chemin)
        entrees[chemin] = hash_fichier(p) if p.exists() else "ABSENT"
    condense = hashlib.sha256(
        json.dumps(entrees, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return condense, entrees


def hash_commit():
    """Empreinte du commit courant, ou 'non-versionne'."""
    try:
        sortie = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        propre = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        suffixe = "" if not propre.stdout.strip() else "-modifie"
        return sortie.stdout.strip()[:12] + suffixe
    except Exception:
        return "non-versionne"


def versions_paquets(paquets=("torch", "sentence_transformers", "qdrant_client",
                              "spacy", "rank_bm25", "numpy")):
    """Versions effectivement chargees, pour le tableau du chapitre 4.

    Le rapport prevoit un tableau des versions exactes issu d'un `pip freeze`.
    Ce releve le complete en indiquant ce qui a effectivement ete importe
    pendant l'execution, ce qu'un `pip freeze` de fin de projet n'indique pas.
    """
    releve = {}
    for nom in paquets:
        try:
            module = __import__(nom)
            releve[nom] = getattr(module, "__version__", "inconnue")
        except Exception:
            releve[nom] = "absent"
    return releve


class Execution:
    """Une execution estampillee, de bout en bout.

    Usage :

        with Execution("e1-hybridation", config) as ex:
            ex.mesure("recall@10", 0.72)
            ...
    """

    def __init__(self, nom, config=None, racine="resultats",
                 manifeste=()):
        self.nom = nom
        self.config = config or mod_config.Config()
        self.racine = Path(racine)
        self.debut = None
        self.mesures = {}
        self.evenements = []
        self.avertissements = []
        self.manifeste_hash, self.manifeste_detail = hash_manifeste(manifeste)
        self.commit = hash_commit()
        self.identifiant = None

    def __enter__(self):
        self.debut = time.time()
        horodatage = time.strftime("%Y%m%d-%H%M%S")
        self.identifiant = f"{self.nom}-{horodatage}-{self.commit[:8]}"
        self.dossier = self.racine / self.identifiant
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.evenement("debut", materiel=self.config.materiel.nom)
        return self

    def __exit__(self, *args):
        self.evenement("fin", duree_s=round(time.time() - self.debut, 2))
        self.ecrire()
        return False

    # ------------------------------------------------------------- releves

    def evenement(self, libelle, **details):
        self.evenements.append({
            "horodatage": time.strftime("%H:%M:%S"),
            "libelle": libelle, **details,
        })
        return self

    def mesure(self, nom, valeur, grandeur="qualite"):
        """Consigne une mesure, en verifiant qu'elle est opposable.

        Une latence relevee sur un materiel de developpement est enregistree
        avec un avertissement : elle ne doit pas figurer telle quelle au
        chapitre 5. Ce garde-fou evite de decouvrir tardivement que des
        chiffres de latence sont a refaire.
        """
        opposable, motif = self.config.materiel.valider_pour(grandeur)
        self.mesures[nom] = {
            "valeur": valeur,
            "grandeur": grandeur,
            "opposable": opposable,
            "materiel": self.config.materiel.nom,
        }
        if not opposable and motif not in self.avertissements:
            self.avertissements.append(motif)
        return self

    # -------------------------------------------------------------- sortie

    def ecrire(self):
        rapport = {
            "identifiant": self.identifiant,
            "nom": self.nom,
            "commit": self.commit,
            "manifeste_hash": self.manifeste_hash,
            "manifeste": self.manifeste_detail,
            "materiel": {
                **self.config.materiel.__dict__,
                **mod_config.empreinte_machine(),
            },
            "versions": versions_paquets(),
            "configuration": self.config.en_dict(),
            "mesures": self.mesures,
            "evenements": self.evenements,
            "avertissements": self.avertissements,
        }
        with open(self.dossier / "execution.json", "w", encoding="utf-8") as f:
            json.dump(rapport, f, ensure_ascii=False, indent=2, default=str)

        if self.avertissements:
            print("\n  AVERTISSEMENTS", file=sys.stderr)
            for a in self.avertissements:
                print("   - " + a, file=sys.stderr)
        return self.dossier
