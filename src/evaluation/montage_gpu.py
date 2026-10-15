"""
Montage de la chaine complete pour les campagnes qui exigent l'index dense.

Trois experiences en dependent (E1b, E4 et E5), et toutes trois requierent le
meme assemblage : un vectoriseur local, l'index Qdrant, l'index BM25 et, selon
la configuration, un re-classeur. Ce module realise cet assemblage une seule
fois, au lieu de le repeter dans les trois scripts de lancement.

CHOIX D'UN MODULE COMMUN

Les quatre configurations d'ablation d'E1b doivent etre exactement celles
qu'emploie E5, faute de quoi le cout mesure par E5 ne se rapporte pas a la
qualite mesuree par E1b. Les definir a deux endroits exposerait a une
divergence silencieuse au premier changement de parametre.

PERIMETRE, INDEPENDANT DE LA MACHINE

Les embeddings sont calcules localement, sur la machine qui execute ce code.
Une machine louee est un substrat de calcul et non un service d'embeddings
distant : aucun vecteur ne franchit la Frontiere A, quelle que soit la
machine (section 3.3.1). La location d'un GPU ne contredit donc pas le
principe directeur.

HORS PERIMETRE

Le module ne construit pas l'index. Cette etape, la plus lourde, dispose de
son propre script, `scripts/build_index.py`, qui peut reprendre apres
interruption. Ici, l'index est suppose deja construit ; s'il ne l'est pas,
le module echoue explicitement plutot que de le reconstruire a l'insu de
l'appelant.
"""

from pathlib import Path

from ..index import lexical as mod_lexical
from ..index import qdrant_index as mod_qdrant
from ..index import recuperateurs as mod_recup

# Les quatre configurations d'ablation du chapitre 5. L'ordre est celui de la
# cascade : chaque etage s'ajoute au precedent.
DENSE = "dense"
LEXICAL = "lexical"
FUSION = "fusion"
COMPLET = "complet"
CONFIGURATIONS = (DENSE, LEXICAL, FUSION, COMPLET)


class ChaineIndisponible(RuntimeError):
    """Levee lorsqu'un index attendu n'existe pas.

    J'echoue explicitement plutot que de rendre une chaine degradee : une
    campagne executee sans index dense produirait des chiffres semblables a
    ceux d'E1b, mais mesurant tout autre chose.
    """


def charger_vectoriseur(config, peripherique=None, taille_lot=None):
    """Vectoriseur local, sur le peripherique demande ou detecte."""
    from ..index import embeddings as mod_emb
    return mod_emb.Vectoriseur(
        modele=config.recherche.modele_embeddings,
        peripherique=peripherique,
        taille_lot=taille_lot,
    )


def charger_index_dense(config, hote=None, chemin_local=None):
    """Index Qdrant, sur serveur ou sur fichier.

    `chemin_local` sert lorsque l'index a ete construit ailleurs puis
    transfere sous forme de fichier, par exemple apres une campagne sur
    machine louee.
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
    """Index BM25 persiste, construit par build_index.py."""
    chemin = Path(chemin)
    if not chemin.exists():
        raise ChaineIndisponible(
            f"index lexical introuvable : {chemin}\n"
            f"Construisez-le :\n"
            f"  python scripts\\build_index.py --corpus tous")
    return mod_lexical.IndexLexical.charger(chemin)


def charger_reclasseur(config, peripherique=None):
    """Cross-encodeur du dernier etage. Rend None s'il est indisponible.

    Son absence n'interrompt pas la campagne : elle retire simplement la
    configuration `complet`, ce que l'appelant rapporte.
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
    """Rend une fonction configuration -> RecuperateurHybride.

    `corpus` restreint la voie dense au meme corpus que la voie lexicale ;
    cette restriction est une condition de validite de la mesure.

    L'index dense est une collection unique contenant les sept corpus, soit
    422 189 passages, alors qu'un index lexical est construit par corpus. Sans
    ce filtre, la voie dense chercherait parmi 422 189 candidats et la voie
    lexicale parmi 73 772 : la premiere affronterait cinq fois plus de
    distracteurs, et l'ecart mesure par E1b tiendrait a la taille du vivier
    plutot qu'a la qualite de la recuperation, alors qu'E1b a precisement
    pour objet de departager les deux voies.

    C'est l'objet qu'attend `e1_hybridation.campagne`. Chaque configuration
    retire un etage de la cascade :

        dense     l'index vectoriel seul
        lexical   BM25 seul, aucun calcul vectoriel
        fusion    les deux, fusionnes par rangs reciproques
        complet   la fusion, puis re-classement du top-k

    Une configuration dont un composant manque rend None, et la campagne
    l'ignore en le consignant, ce qui est preferable a un echec global.
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
                # Sans cross-encodeur, `complet` serait identique a `fusion` :
                # la conserver produirait deux lignes identiques dans le
                # tableau d'ablation, lues a tort comme un apport nul du
                # re-classement alors que celui-ci n'a pas eu lieu.
                return None
            return mod_recup.monter_chaine(
                index_qdrant=index_dense, index_lexical=index_lexical,
                vectoriseur=vectoriseur, reclasseur=reclasseur,
                source=source, corpus=corpus, config=config)

        return None

    return construire


def decrire(vectoriseur=None, index_dense=None, index_lexical=None,
            reclasseur=None):
    """Etat du montage, a consigner au journal de campagne."""
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
