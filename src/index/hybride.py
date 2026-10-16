"""
Recherche hybride : fusion RRF et re-classement (section 2.2 et pilier 3).

La cascade est la reference standard du rapport : BM25 et recherche dense
en parallele, fusion par rangs reciproques (RRF), puis re-classement par
cross-encodeur sur le top-k seulement.

Deux choix importants :

1. La fusion utilise les rangs, pas les scores. Les scores de BM25 et d'un
   bi-encodeur n'ont pas la meme echelle. Il faudrait les normaliser avec un
   reglage arbitraire ; RRF evite ce probleme.

2. C'est dans la couche de recherche qu'on attache les metadonnees de
   provenance. C'est donc ici que l'invariant I3 commence.

PRINCIPE DU PROJET : aucun embedding ne franchit la Frontiere A. Les vecteurs
sont calcules en local. Le contenu externe est rapatrie en texte, puis
vectorise et indexe ici. Ce module ne doit jamais se connecter a un service
vectoriel distant.
"""

from collections import defaultdict

K_RRF = 60  # constante d'amortissement usuelle de la fusion par rangs


def fusion_rrf(classements, k=K_RRF, cle=lambda f: f.doc_id):
    """Combine plusieurs classements par somme de rangs inverses.

    `classements` est une liste de listes de fragments, chacune deja triee
    par pertinence decroissante par un recuperateur.
    """
    scores = defaultdict(float)
    connus = {}
    for classement in classements:
        for rang, fragment in enumerate(classement, start=1):
            identifiant = cle(fragment)
            scores[identifiant] += 1.0 / (k + rang)
            connus.setdefault(identifiant, fragment)

    fusionnes = []
    for identifiant, score in sorted(scores.items(), key=lambda t: -t[1]):
        fragment = connus[identifiant]
        fragment.score = score
        fusionnes.append(fragment)
    return fusionnes


def reclasser(requete, fragments, reclasseur, top_k=20):
    """Re-classe le top-k par cross-encodeur.

    Le cross-encodeur traite la requete et chaque passage ensemble. Il
    ameliore beaucoup la precision mais coute cher, donc on ne l'applique
    qu'au top-k.
    """
    tete = fragments[:top_k]
    reste = fragments[top_k:]
    if not tete or reclasseur is None:
        return fragments

    scores = reclasseur([(requete, f.text) for f in tete])
    for fragment, score in zip(tete, scores):
        fragment.score = float(score)
    tete.sort(key=lambda f: -f.score)
    return tete + reste


def ponderer_par_confiance(fragments, poids=None):
    """Applique la teinte au classement (fusion teintee du pilier 3).

    Une fusion simple mettrait l'interne et l'externe au meme niveau. La
    ponderation corrige cela : l'interne verifie passe en premier, une source
    externe unique descend, et une source suspecte de collusion descend
    encore plus (sa fiabilite a deja ete baissee par `teinte.teinter`).
    """
    poids = poids or {
        "interne-verifie": 1.0,
        "externe-corrobore": 0.8,
        "externe-source-unique": 0.5,
    }
    for fragment in fragments:
        facteur = poids.get(fragment.confiance, 0.5)
        fragment.score *= facteur * max(fragment.fiabilite, 0.05)
    return sorted(fragments, key=lambda f: -f.score)


class RecuperateurHybride:
    """Assemble la cascade complete.

    `dense` et `lexical` sont des fonctions (requete, n) -> liste de Fragment,
    passees en argument. Dans le prototype, `dense` utilise Qdrant et BGE-M3,
    et `lexical` un index BM25 local. Les tests et les ablations du
    chapitre 5 peuvent ainsi les remplacer.
    """

    def __init__(self, dense=None, lexical=None, reclasseur=None,
                 top_k_reclassement=20):
        self.dense = dense
        self.lexical = lexical
        self.reclasseur = reclasseur
        self.top_k_reclassement = top_k_reclassement

    def rechercher(self, requete, n=50, avec_teinte=True):
        classements = []
        if self.dense is not None:
            classements.append(self.dense(requete, n))
        if self.lexical is not None:
            classements.append(self.lexical(requete, n))
        if not classements:
            return []

        fragments = fusion_rrf(classements)
        fragments = reclasser(requete, fragments, self.reclasseur,
                              self.top_k_reclassement)
        if avec_teinte:
            from ..isolation import teinte
            fragments = teinte.teinter(fragments)
            fragments = ponderer_par_confiance(fragments)
        return fragments[:n]
