"""
Assemblage de la chaine complete pour les campagnes qui ont besoin de
l'index dense.

E1b, E4 et E5 utilisent le meme assemblage : un vectoriseur local, l'index
Qdrant, l'index BM25 et, selon la configuration, un re-classeur. Ce module
le construit, pour ne pas le repeter dans trois scripts.

POURQUOI UN MODULE COMMUN

E5 doit utiliser exactement les memes configurations qu'E1b, sinon le cout
mesure par E5 ne correspond plus a la qualite mesuree par E1b. Avec deux
definitions separees, un changement de parametre a un seul endroit les
ferait diverger sans qu'on le voie.

LA MACHINE NE CHANGE RIEN A LA SOUVERAINETE

Les embeddings sont calcules sur la machine qui execute ce code. Une machine
louee fait seulement du calcul, aucun service d'embeddings distant
n'intervient : aucun vecteur ne franchit la Frontiere A (section 3.3.1). Louer un
GPU reste donc compatible avec le principe du projet.

CE QUE LE MODULE NE FAIT PAS

Le module ne construit pas l'index. Cette etape, la plus lourde, a son
propre script, `scripts/build_index.py`, qui sait reprendre apres une
interruption. Ici, l'index doit deja exister. Sinon le module s'arrete avec
une erreur claire, sans reconstruire l'index en cachette.
"""

from pathlib import Path

from ..index import lexical as mod_lexical
from ..index import qdrant_index as mod_qdrant
from ..index import recuperateurs as mod_recup

# Les quatre configurations d'ablation du chapitre 5, dans l'ordre de la
# cascade.
DENSE = "dense"
LEXICAL = "lexical"
FUSION = "fusion"
COMPLET = "complet"
CONFIGURATIONS = (DENSE, LEXICAL, FUSION, COMPLET)


class ChaineIndisponible(RuntimeError):
    """Levee quand un index attendu n'existe pas.

    Je prefere une erreur a une chaine incomplete : une campagne sans index
    dense donnerait des chiffres qui ressemblent a ceux d'E1b mais qui
    mesurent autre chose.
    """


def charger_vectoriseur(config, peripherique=None, taille_lot=None):
    """Vectoriseur local, sur le peripherique demande ou detecte automatiquement."""
    from ..index import embeddings as mod_emb
    return mod_emb.Vectoriseur(
        modele=config.recherche.modele_embeddings,
        peripherique=peripherique,
        taille_lot=taille_lot,
    )


def charger_index_dense(config, hote=None, chemin_local=None):
    """Index Qdrant, sur serveur ou sur fichier.

    `chemin_local` sert quand l'index a ete construit ailleurs puis copie en
    fichier, par exemple apres une campagne sur machine louee.
    """
    index = mod_qdrant.IndexQdrant(
        collection=config.recherche.collection,
        hote=hote or "http://localhost:6333",
        chemin_local=chemin_local,
    )
    try:
        if not index.client.collection_exists(index.collection):
            raise ChaineIndisponible(
                f"la collection Qdrant '{index.collection}' n'existe pas.\n"
                f"Construisez d'abord l'index :\n"
                f"  python scripts\\build_index.py --corpus tous")
    except ChaineIndisponible:
        raise
    except Exception as erreur:
        raise ChaineIndisponible(
            f"impossible de joindre Qdrant : {erreur}\n"
            f"Verifiez que le serveur tourne, ou passez --index-fichier "
            f"pour un index transporte en fichier.") from erreur
    return index


def charger_index_lexical(chemin):
    """Index BM25 sauvegarde, construit par build_index.py."""
    chemin = Path(chemin)
    if not chemin.exists():
        raise ChaineIndisponible(
            f"index lexical introuvable : {chemin}\n"
            f"Construisez-le :\n"
            f"  python scripts\\build_index.py --corpus tous")
    return mod_lexical.IndexLexical.charger(chemin)


def charger_reclasseur(config, peripherique=None):
    """Cross-encodeur du dernier etage. Renvoie None s'il n'est pas disponible.

    Sans lui, la campagne continue sans la configuration `complet`, et
    l'appelant le signale.
    """
    try:
        return mod_lexical.Reclasseur(
            modele=config.recherche.modele_reclasseur,
            peripherique=peripherique,
        )
    except Exception:
        return None


def fabrique(config, index_dense, index_lexical, vectoriseur,
             reclasseur=None, source=None, corpus=None):
    """Renvoie une fonction configuration -> RecuperateurHybride.

    `corpus` limite la voie dense au meme corpus que la voie lexicale. Sans
    cette limite, la mesure est faussee.

    L'index dense est une seule collection avec les sept corpus (422 189
    passages), alors qu'il y a un index lexical par corpus. Sans filtre, la
    voie dense chercherait parmi 422 189 candidats et la voie lexicale parmi
    73 772. La voie dense aurait cinq fois plus de documents parasites, et
    l'ecart mesure par E1b viendrait du nombre de documents au lieu de la
    qualite de la recherche.

    C'est la fonction qu'attend `e1_hybridation.campagne`. Les
    configurations :

        dense     l'index vectoriel seul
        lexical   BM25 seul, aucun calcul vectoriel
        fusion    les deux, fusionnes par rangs reciproques
        complet   la fusion, puis re-classement du top-k

    Si un composant manque, la configuration renvoie None. La campagne la
    saute et le note, au lieu de tout arreter.
    """
    def construire(configuration):
        if configuration == DENSE:
            if index_dense is None or vectoriseur is None:
                return None
            return mod_recup.monter_chaine(
                index_qdrant=index_dense, index_lexical=None,
                vectoriseur=vectoriseur, reclasseur=None,
                source=source, corpus=corpus, config=config)

        if configuration == LEXICAL:
            if index_lexical is None:
                return None
            return mod_recup.monter_chaine(
                index_qdrant=None, index_lexical=index_lexical,
                vectoriseur=None, reclasseur=None,
                source=source, corpus=corpus, config=config)

        if configuration == FUSION:
            if index_dense is None or index_lexical is None:
                return None
            return mod_recup.monter_chaine(
                index_qdrant=index_dense, index_lexical=index_lexical,
                vectoriseur=vectoriseur, reclasseur=None,
                source=source, corpus=corpus, config=config)

        if configuration == COMPLET:
            if index_dense is None or index_lexical is None:
                return None
            if reclasseur is None:
                # Sans cross-encodeur, `complet` serait identique a `fusion`.
                # Le tableau d'ablation aurait deux lignes identiques, qu'on
                # lirait a tort comme un re-classement sans effet, alors qu'il
                # n'a pas eu lieu.
                return None
            return mod_recup.monter_chaine(
                index_qdrant=index_dense, index_lexical=index_lexical,
                vectoriseur=vectoriseur, reclasseur=reclasseur,
                source=source, corpus=corpus, config=config)

        return None

    return construire


def decrire(vectoriseur=None, index_dense=None, index_lexical=None,
            reclasseur=None):
    """Etat de l'assemblage, a enregistrer dans le journal de campagne."""
    return {
        "vectoriseur": (vectoriseur.decrire()
                        if vectoriseur is not None else None),
        "index_dense": (index_dense.collection
                        if index_dense is not None else None),
        "index_lexical": (len(index_lexical.documents)
                          if index_lexical is not None else None),
        "reclasseur": (reclasseur.nom_modele
                       if reclasseur is not None else None),
    }
