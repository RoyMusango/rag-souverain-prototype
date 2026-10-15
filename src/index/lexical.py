"""
Recuperation lexicale BM25, versant exact de la recherche hybride.

BM25 demeure la reference : robuste, sans apprentissage, particulierement
efficace sur les correspondances exactes et les termes rares. En contexte
bancaire, il est indispensable : les textes reglementaires abondent en jetons
exacts (numeros d'articles, termes definis) pour lesquels l'appariement
lexical reste necessaire, tandis que la recuperation dense absorbe les
reformulations des questions metier.

Ce module ne depend d'aucun accelerateur et s'execute a l'identique sur
l'ultraportable et sur la machine de campagne.
"""

import pickle
import re
from pathlib import Path

MOTIF_JETON = re.compile(r"\w+", re.UNICODE)

# Mots vides minimaux. Volontairement courts : sur un corpus reglementaire,
# une liste agressive supprimerait des termes definis.
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
    """Segmentation simple et reproductible.

    Les chiffres sont conserves par defaut : un numero d'article ou un
    montant est precisement ce que le versant lexical doit apparier.
    """
    vides = VIDES_FR if langue == "fr" else VIDES_EN
    bruts = MOTIF_JETON.findall(str(texte).lower())
    return [
        j for j in bruts
        if j not in vides and (garder_chiffres or not j.isdigit())
    ]


MOTIF_RUBRIQUE = re.compile(r"^eurlex/([^/]+)/([^/]+)/art_0*(\d+)$")


def enrichir_par_rubrique(documents, langues=None):
    """Prefixe chaque passage par l'en-tete de l'article auquel il appartient.

    MOTIVATION

    Le numero d'article figure dans la rubrique, alors que l'index BM25 ne
    lit que le champ `text`. Mesure du 25/09 : sur les 5 208 documents dont la
    rubrique porte un numero, 9 % seulement contiennent « Article <n> » dans
    leur texte (en pratique le premier pave de l'article, jamais les
    suivants). Une question nommant un article ne pouvait donc pas le
    retrouver : l'ancrage etait de 0 sur 40 au rang 10.

    L'enrichissement n'invente rien : tout pave d'un article appartient a cet
    article, et un lecteur en voit l'en-tete en haut de la page. Je replace
    donc une information exacte la ou le moteur peut la lire.

    `langues` restreint en outre le vivier, par exemple a ("FR",). Le corpus
    EUR-Lex contient chaque texte en deux langues : une question francaise
    affronte donc un vivier a moitie anglophone, et chaque doublon occupe une
    place parmi les dix fragments retenus.

    Rend une nouvelle liste : les documents d'origine ne sont jamais
    modifies, faute de quoi une campagne alterait le corpus des suivantes.
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
    """Index BM25 persistable, aligne sur le schema commun."""

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
        """Retourne (document, score) tries par pertinence decroissante."""
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
        """Persiste l'index, qui accompagne l'index vectoriel."""
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
    """Cross-encodeur applique au seul top-k.

    Le cross-encodeur encode conjointement requete et passage : il ameliore
    nettement la precision, au prix d'un cout eleve, d'ou son application a
    une tete restreinte plutot qu'a l'ensemble des candidats.

    C'est, avec les embeddings, le second poste qui beneficie reellement d'un
    accelerateur graphique.
    """

    def __init__(self, modele="BAAI/bge-reranker-v2-m3", peripherique=None,
                 longueur_max=512):
        self.nom_modele = modele
        self.peripherique = peripherique
        # Longueur maximale
        #
        # Sans ce parametre, sentence-transformers retient la longueur
        # maximale du modele, soit 8192 jetons pour bge-reranker-v2-m3. Le
        # cout de l'attention croit avec le carre de la longueur : mesure du
        # 08/09, une campagne E1b a tourne plus de sept heures sur processeur
        # sans depasser le quart de ses 200 questions, soit plus de trente
        # heures projetees pour 4 000 paires.
        #
        # 512 est la valeur usuelle pour le re-classement. Elle tronque les
        # passages les plus longs, limite que je declare, mais rend l'etage
        # utilisable sur processeur, et donc effectivement present dans la
        # chaine.
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
