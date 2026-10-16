"""
Embeddings BGE-M3 calcules localement (principe directeur, section 3.3.1).

    AUCUN EMBEDDING NE FRANCHIT LA FRONTIERE A.

On peut inverser un embedding de texte : il revele les mots du texte et,
pour un texte court, permet de retrouver presque l'original. Confier la
vectorisation a un service distant revient donc a lui envoyer la requete en
clair. Ce module ne doit jamais se connecter a une API d'embeddings.

Il gere aussi un probleme que le rapport n'aborde pas : il y a 419 342
documents a vectoriser. Sur processeur seul, je ne l'ai pas tente (voir
JOURNAL_DONNEES.md section 6 : l'extraction NER seule prend plus de neuf
heures). Sur GPU, cela prend quelques dizaines de minutes. Le module doit
donc :

  - choisir explicitement le peripherique et la precision ;
  - traiter les textes par lots, selon la memoire disponible ;
  - savoir reprendre apres une interruption, sans tout recalculer.

Le dernier point compte sur une machine louee : la session peut etre coupee,
et sans reprise il faudrait tout recommencer.
"""

import json
import os
import time
from pathlib import Path

try:
    import numpy as np
except ImportError:  # numpy est requis ; une erreur claire est levee plus loin
    np = None


def peripherique_disponible(prefere=None):
    """Detecte le peripherique de calcul disponible.

    Renvoie (nom, precision). La demi-precision (fp16) divise par deux la
    memoire utilisee et accelere nettement le calcul sur GPU. Sur processeur
    elle le ralentit, donc je ne l'utilise pas.
    """
    if prefere:
        return prefere, ("float16" if prefere.startswith("cuda") else "float32")
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", "float16"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps", "float32"
    except ImportError:
        pass
    return "cpu", "float32"


def taille_lot_recommandee(peripherique, longueur_moyenne=1500):
    """Taille de lot prudente selon le peripherique et la longueur des textes.

    Les valeurs sont volontairement basses : un lot trop grand peut provoquer
    une erreur de memoire apres vingt minutes de calcul, ce qui coute cher
    sur une machine louee a l'heure.
    """
    if peripherique == "cpu":
        return 8
    if longueur_moyenne > 4000:
        return 16
    if longueur_moyenne > 1500:
        return 32
    return 64


class Vectoriseur:
    """BGE-M3 et le calcul par lots.

    La reprise apres interruption est geree par `CalculPersistant`.
    """

    def __init__(self, modele="BAAI/bge-m3", peripherique=None,
                 taille_lot=None, longueur_max=8192, normaliser=True):
        self.nom_modele = modele
        self.peripherique, self.precision = peripherique_disponible(peripherique)
        self.taille_lot = taille_lot
        self.longueur_max = longueur_max
        self.normaliser = normaliser
        self._modele = None

    def charger(self):
        """Charge le modele au premier usage (importer torch prend plusieurs secondes)."""
        if self._modele is None:
            from sentence_transformers import SentenceTransformer
            self._modele = SentenceTransformer(
                self.nom_modele, device=self.peripherique
            )
            self._modele.max_seq_length = self.longueur_max
            if self.precision == "float16" and self.peripherique == "cuda":
                self._modele = self._modele.half()
        return self._modele

    def encoder(self, textes, taille_lot=None, progression=None):
        """Vectorise une liste de textes. Aucun appel reseau."""
        modele = self.charger()
        lot = taille_lot or self.taille_lot or taille_lot_recommandee(
            self.peripherique,
            sum(len(t) for t in textes[:100]) / max(1, len(textes[:100])),
        )
        return modele.encode(
            textes, batch_size=lot, normalize_embeddings=self.normaliser,
            show_progress_bar=progression is None, convert_to_numpy=True,
        )

    def decrire(self):
        return {
            "modele": self.nom_modele,
            "peripherique": self.peripherique,
            "precision": self.precision,
            "taille_lot": self.taille_lot,
            "longueur_max": self.longueur_max,
        }


class CalculPersistant:
    """Calcul d'embeddings sur un corpus entier, repris apres interruption.

    Les vecteurs sont ecrits par tranches dans `dossier`, avec un fichier
    d'etat. Relancer la meme commande reprend la ou le calcul s'est arrete.

    C'est utile sur une machine louee, et cela correspond a la sauvegarde
    prevue a la section 4.1.3 du rapport.
    """

    def __init__(self, vectoriseur, dossier="data/embeddings",
                 taille_tranche=5000):
        self.vectoriseur = vectoriseur
        self.dossier = Path(dossier)
        self.taille_tranche = taille_tranche
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.chemin_etat = self.dossier / "etat.json"

    def _etat(self):
        if self.chemin_etat.exists():
            with open(self.chemin_etat, encoding="utf-8") as f:
                return json.load(f)
        return {"tranches_faites": [], "corpus": None,
                "vectoriseur": self.vectoriseur.decrire()}

    def _ecrire_etat(self, etat):
        with open(self.chemin_etat, "w", encoding="utf-8") as f:
            json.dump(etat, f, ensure_ascii=False, indent=2)

    def executer(self, documents, corpus="corpus", cle_texte="text",
                 journal=None):
        """Vectorise `documents`, en reprenant les tranches deja faites."""
        if np is None:
            raise RuntimeError("numpy est requis pour la persistance")

        etat = self._etat()
        if etat.get("corpus") not in (None, corpus):
            raise RuntimeError(
                f"le dossier {self.dossier} contient deja le corpus "
                f"'{etat['corpus']}' ; utilisez un dossier distinct"
            )
        etat["corpus"] = corpus
        faites = set(etat["tranches_faites"])

        total = (len(documents) + self.taille_tranche - 1) // self.taille_tranche
        debut_global = time.time()

        for numero in range(total):
            if numero in faites:
                continue
            debut = numero * self.taille_tranche
            tranche = documents[debut:debut + self.taille_tranche]
            textes = [str(d.get(cle_texte, "")) for d in tranche]

            t0 = time.time()
            vecteurs = self.vectoriseur.encoder(textes)
            duree = time.time() - t0

            np.save(self.dossier / f"vecteurs-{numero:05d}.npy", vecteurs)
            with open(self.dossier / f"identifiants-{numero:05d}.json",
                      "w", encoding="utf-8") as f:
                json.dump([str(d.get("doc_id")) for d in tranche], f)

            faites.add(numero)
            etat["tranches_faites"] = sorted(faites)
            self._ecrire_etat(etat)

            debit = len(tranche) / duree if duree else 0
            restant = (total - len(faites)) * self.taille_tranche / debit \
                if debit else 0
            message = (f"  tranche {numero + 1}/{total} : "
                       f"{len(tranche)} docs en {duree:.1f}s "
                       f"({debit:.0f} docs/s, reste ~{restant / 60:.0f} min)")
            print(message)
            if journal is not None:
                journal.evenement("tranche", numero=numero,
                                  documents=len(tranche),
                                  duree_s=round(duree, 2))

        total_s = time.time() - debut_global
        print(f"  termine en {total_s / 60:.1f} min "
              f"({len(faites)}/{total} tranches)")
        return self

    def charger_tout(self):
        """Relit les vecteurs sauvegardes, dans l'ordre des tranches."""
        etat = self._etat()
        vecteurs, identifiants = [], []
        for numero in sorted(etat["tranches_faites"]):
            vecteurs.append(np.load(self.dossier / f"vecteurs-{numero:05d}.npy"))
            with open(self.dossier / f"identifiants-{numero:05d}.json",
                      encoding="utf-8") as f:
                identifiants.extend(json.load(f))
        if not vecteurs:
            return None, []
        return np.concatenate(vecteurs, axis=0), identifiants
