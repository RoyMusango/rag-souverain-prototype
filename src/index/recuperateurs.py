"""
Recuperateurs concrets : le raccord entre les index et la cascade hybride.

`hybride.RecuperateurHybride` attend deux fonctions (requete, n) -> liste de
Fragment. Ce module les construit a partir d'un index Qdrant et d'un index
BM25, et assure la conversion qu'aucun des deux ne realise : transformer une
charge utile en Fragment, provenance comprise.

Sans ce module, la chaine serait interrompue entre l'indexation et la
recherche.

Perimetre : le vectoriseur employe ici est local. La requete est vectorisee
sur la machine qui execute ce code, et le vecteur ne quitte jamais le
processus. Ce qui franchit la Frontiere A, en cas d'enrichissement, est une
requete texte, jamais son embedding (section 3.3.1).
"""

from ..isolation import teinte


def fragment_depuis_charge(charge, score=0.0):
    """Convertit une charge utile Qdrant en Fragment.

    C'est ici que la provenance passe de l'index a la recherche. Toute
    metadonnee omise a cet endroit est definitivement perdue pour
    l'attribution : apres l'indexation, elle est irrecuperable.
    """
    return teinte.Fragment(
        doc_id=str(charge.get("doc_id", "")),
        text=str(charge.get("text", "")),
        source=charge.get("source", "externe"),
        rubrique=str(charge.get("rubrique", "")),
        page=int(charge.get("page", 1) or 1),
        pave=int(charge.get("pave", 1) or 1),
        origine=charge.get("origine", "") or charge.get("corpus", ""),
        score=float(score),
        entities=charge.get("entities", []) or [],
    )


def fragment_depuis_document(document, score=0.0):
    """Meme conversion depuis un document du schema commun (voie lexicale)."""
    return fragment_depuis_charge(document, score)


class RecuperateurDense:
    """Voie dense : vectorisation locale, puis voisinage dans Qdrant."""

    def __init__(self, index, vectoriseur, source=None, corpus=None):
        self.index = index
        self.vectoriseur = vectoriseur
        self.source = source     # 'interne' | 'externe' | None
        self.corpus = corpus

    def __call__(self, requete, n=50):
        # Vectorisation locale de la requete. Le vecteur reste dans ce
        # processus ; seul un identifiant de point revient de l'index.
        vecteur = self.vectoriseur.encoder([requete])[0]
        resultats = self.index.rechercher(
            vecteur, n=n, source=self.source, corpus=self.corpus
        )
        return [fragment_depuis_charge(charge, score)
                for charge, score in resultats]


class RecuperateurLexical:
    """Voie lexicale : BM25, sans aucun calcul vectoriel."""

    def __init__(self, index, source=None):
        self.index = index
        self.source = source

    def __call__(self, requete, n=50):
        resultats = self.index.rechercher(requete, n=n, source=self.source)
        return [fragment_depuis_document(document, score)
                for document, score in resultats]


class RecuperateurMemoire:
    """Recuperateur en memoire, pour les tests et les ablations.

    Il est necessaire : les experiences du chapitre 5 doivent pouvoir
    s'executer sans serveur Qdrant, faute de quoi une ablation dependrait
    d'un service externe et ne serait plus rejouable.
    """

    def __init__(self, documents, source=None):
        self.documents = [
            d for d in documents
            if source is None or d.get("source") == source
        ]

    def __call__(self, requete, n=50):
        jetons = set(str(requete).lower().split())
        notes = []
        for document in self.documents:
            mots = set(str(document.get("text", "")).lower().split())
            recouvrement = len(jetons & mots) / (len(jetons) or 1)
            notes.append((document, recouvrement))
        notes.sort(key=lambda t: -t[1])
        return [fragment_depuis_document(d, s) for d, s in notes[:n]]


def monter_chaine(index_qdrant=None, index_lexical=None, vectoriseur=None,
                  reclasseur=None, source=None, corpus=None, config=None):
    """Assemble une cascade complete a partir des index disponibles.

    Retourne un `RecuperateurHybride` pret a etre passe au Moteur. Si un seul
    des deux index est fourni, la cascade fonctionne en mode degrade, ce qui
    correspond aux configurations d'ablation d'E1 : dense seul, lexical seul,
    fusion, fusion plus re-classement.
    """
    from .hybride import RecuperateurHybride

    dense = None
    if index_qdrant is not None and vectoriseur is not None:
        dense = RecuperateurDense(index_qdrant, vectoriseur, source, corpus)

    lexical = None
    if index_lexical is not None:
        lexical = RecuperateurLexical(index_lexical, source)

    top_k = (config.recherche.top_k_reclassement if config else 20)
    return RecuperateurHybride(dense=dense, lexical=lexical,
                               reclasseur=reclasseur,
                               top_k_reclassement=top_k)
