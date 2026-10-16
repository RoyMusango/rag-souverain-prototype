"""
Recherche lexicale BM25, la partie "mots exacts" de la recherche hybride.

BM25 reste la reference : fiable, sans apprentissage, tres bon sur les
correspondances exactes et les termes rares. Dans une banque, il est
indispensable : les textes reglementaires sont pleins de termes exacts
(numeros d'articles, termes definis) qu'il faut retrouver mot pour mot. La
recherche dense, elle, gere les reformulations des questions metier.

Ce module n'a pas besoin de GPU et donne les memes resultats sur
l'ultraportable et sur la machine de campagne.
"""

import pickle
import re
from pathlib import Path

MOTIF_JETON = re.compile(r"\w+", re.UNICODE)

# Liste de mots vides volontairement courte : sur un corpus reglementaire,
# une liste trop longue supprimerait des termes definis.
VIDES_FR = {
    "le", "la", "les", "de", "des", "du", "un", "une", "et", "ou", "a", "au",
    "aux", "en", "dans", "sur", "pour", "par", "que", "qui", "est", "sont",
    "ce", "cette", "ces", "il", "elle", "se", "ne", "pas", "plus",
}
VIDES_EN = {
    "the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "by",
    "that", "which", "is", "are", "be", "as", "with", "this", "these",
}


def jetons(texte, langue="fr", garder_chiffres=True):
    """Decoupage en jetons, simple et reproductible.

    Les chiffres sont gardes par defaut : un numero d'article ou un montant
    est ce que la recherche lexicale doit retrouver.
    """
    vides = VIDES_FR if langue == "fr" else VIDES_EN
    bruts = MOTIF_JETON.findall(str(texte).lower())
    return [
        j for j in bruts
        if j not in vides and (garder_chiffres or not j.isdigit())
    ]


MOTIF_RUBRIQUE = re.compile(r"^eurlex/([^/]+)/([^/]+)/art_0*(\d+)$")


def enrichir_par_rubrique(documents, langues=None):
    """Ajoute en tete de chaque passage l'en-tete de son article.

    POURQUOI

    Le numero d'article est dans la rubrique, mais l'index BM25 ne lit que le
    champ `text`. Mesure du 25/09 : sur les 5 208 documents dont la rubrique
    a un numero, seulement 9 % contiennent « Article <n> » dans leur texte
    (en pratique le premier pave de l'article). Une question qui nommait un
    article ne le retrouvait donc presque jamais : 8 sur 40 au rang 10 (voir
    JOURNAL_DONNEES, section 11).

    On n'invente rien : chaque pave appartient bien a cet article, et un
    lecteur voit l'en-tete en haut de la page. On met simplement cette
    information la ou le moteur peut la lire.

    `langues` permet aussi de ne garder qu'une langue, par exemple ("FR",).
    EUR-Lex contient chaque texte en deux langues. Sans ce filtre, une
    question en francais cherche dans un corpus a moitie anglais, et chaque
    doublon anglais prend une des dix places.

    Renvoie une nouvelle liste. Les documents d'origine ne sont jamais
    modifies, sinon une campagne changerait le corpus des suivantes.
    """
    enrichis = []
    for doc in documents:
        trouve = MOTIF_RUBRIQUE.match(str(doc.get("rubrique", "")))
        if langues is not None and trouve and trouve.group(2) not in langues:
            continue
        if not trouve:
            enrichis.append(doc)
            continue
        entete = "{} Article {}.".format(trouve.group(1).replace("_", " "),
                                         trouve.group(3))
        copie = dict(doc)
        copie["text"] = "{} {}".format(entete, doc.get("text", "") or "")
        enrichis.append(copie)
    return enrichis


class IndexLexical:
    """Index BM25 sauvegardable, au format du schema commun."""

    def __init__(self, langue="fr"):
        self.langue = langue
        self.documents = []
        self._bm25 = None

    def construire(self, documents, cle_texte="text"):
        from rank_bm25 import BM25Okapi
        self.documents = list(documents)
        corpus = [jetons(d.get(cle_texte, ""), self.langue)
                  for d in self.documents]
        self._bm25 = BM25Okapi(corpus)
        return self

    def rechercher(self, requete, n=50, source=None):
        """Renvoie des couples (document, score) tries par pertinence decroissante."""
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(jetons(requete, self.langue))
        paires = [
            (d, float(s)) for d, s in zip(self.documents, scores)
            if source is None or d.get("source") == source
        ]
        paires.sort(key=lambda t: -t[1])
        return paires[:n]

    def enregistrer(self, chemin):
        """Sauvegarde l'index sur disque, a cote de l'index vectoriel."""
        chemin = Path(chemin)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with open(chemin, "wb") as f:
            pickle.dump(
                {"langue": self.langue, "documents": self.documents,
                 "bm25": self._bm25}, f
            )
        return chemin

    @classmethod
    def charger(cls, chemin):
        with open(chemin, "rb") as f:
            donnees = pickle.load(f)
        index = cls(langue=donnees["langue"])
        index.documents = donnees["documents"]
        index._bm25 = donnees["bm25"]
        return index


class Reclasseur:
    """Cross-encodeur applique au top-k seulement.

    Le cross-encodeur traite la requete et le passage ensemble. Il ameliore
    beaucoup la precision mais coute cher, donc on ne l'applique qu'aux
    premiers resultats.

    Avec les embeddings, c'est la seule etape qui gagne vraiment a tourner
    sur GPU.
    """

    def __init__(self, modele="BAAI/bge-reranker-v2-m3", peripherique=None,
                 longueur_max=512):
        self.nom_modele = modele
        self.peripherique = peripherique
        # Longueur maximale
        #
        # Sans ce parametre, sentence-transformers prend la longueur maximale
        # du modele, soit 8192 jetons pour bge-reranker-v2-m3. Le cout de
        # l'attention croit avec le carre de la longueur. Le 08/09, une
        # campagne E1b a tourne plus de sept heures sur processeur sans
        # finir le quart de ses 200 questions, soit plus de trente heures
        # prevues pour 4 000 paires.
        #
        # 512 est la valeur habituelle pour le re-classement. Les passages les
        # plus longs sont coupes (limite connue et signalee), mais l'etape
        # devient utilisable sur processeur.
        self.longueur_max = longueur_max
        self._modele = None

    def charger(self):
        if self._modele is None:
            from sentence_transformers import CrossEncoder
            from .embeddings import peripherique_disponible
            peripherique = self.peripherique or peripherique_disponible()[0]
            self._modele = CrossEncoder(self.nom_modele, device=peripherique,
                                        max_length=self.longueur_max)
            self.peripherique = peripherique
        return self._modele

    def __call__(self, paires):
        """`paires` est une liste de (requete, passage)."""
        if not paires:
            return []
        return self.charger().predict(paires)
