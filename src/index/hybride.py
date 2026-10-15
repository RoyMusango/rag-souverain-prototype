"""
Recherche hybride : fusion RRF et re-classement (section 2.2 et pilier 3).

La cascade retenue est la reference standard et reproductible du rapport :
BM25 et recuperation dense en parallele, fusion par rangs reciproques, puis
re-classement par cross-encodeur sur le seul top-k.

Deux choix de conception structurants :

1. La fusion se fait par rangs et non par scores. Les scores de BM25 et d'un
   bi-encodeur relevent d'echelles non comparables ; les normaliser exigerait
   un calage arbitraire, que RRF evite entierement.

2. La couche de recuperation est le seul endroit ou attacher les metadonnees
   de provenance. La recherche hybride n'est donc pas seulement un choix de
   qualite : c'est le point d'insertion de l'invariant I3.

PRINCIPE DIRECTEUR : aucun embedding ne franchit la Frontiere A. Les vecteurs
sont calcules localement ; le contenu externe est rapatrie en texte, puis
vectorise et indexe ici. Ce module ne doit jamais ouvrir de client vers un
service vectoriel distant.
"""

from collections import defaultdict

K_RRF = 60  # constante d'amortissement usuelle de la fusion par rangs


def fusion_rrf(classements, k=K_RRF, cle=lambda f: f.doc_id):
    """Combine plusieurs classements par somme de rangs inverses.

    `classements` est une liste de listes de fragments, chacune deja ordonnee
    par pertinence decroissante selon un recuperateur.
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

    Le cross-encodeur encode conjointement la requete et chaque passage : il
    ameliore nettement la precision, au prix d'un cout eleve, d'ou son
    application au seul top-k et jamais a l'ensemble des candidats.
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

    Une fusion naive traiterait interne et externe a egalite de rang. La
    ponderation retablit l'asymetrie : l'interne verifie prime, la source
    externe unique est retrogradee, et un signal de collusion l'est davantage
    (sa fiabilite a deja ete penalisee par `teinte.teinter`).
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

    `dense` et `lexical` sont des callables (requete, n) -> liste de Fragment,
    injectes plutot que figes : dans le prototype, `dense` s'appuie sur
    Qdrant et BGE-M3 et `lexical` sur un index BM25 local, mais les tests et
    les ablations du chapitre 5 doivent pouvoir les remplacer.
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
