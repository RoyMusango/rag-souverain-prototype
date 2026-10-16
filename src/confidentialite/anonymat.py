"""
Ensemble d'anonymat et hierarchies de generalisation (pilier 2, section 3.3).

Ce module ne touche ni au RAG ni au reseau. Il travaille sur la population
d'entites decrite dans docs/JOURNAL_DONNEES.md (section 10) et repond a une
question : combien d'entites restent compatibles avec ce qui a ete envoye ?

Vocabulaire du rapport :
  entite (e)          l'entite enquetee, le secret a proteger
  quasi-identifiant   attribut qui, combine aux autres, re-identifie
  gabarit (G)         niveau de generalisation retenu pour chaque quasi-id
  ensemble d'anonymat les entites compatibles avec les attributs reveles
  |S|                 taille de cet ensemble

Invariant concerne : I1 (etancheite sortante), cote intention.
"""

from collections import defaultdict

# Quasi-identifiants retenus pour E2 (JOURNAL_DONNEES.md section 10).
# L'ordre compte : c'est l'ordre de lecture des gabarits.
QUASI_IDENTIFIANTS = (
    "ville",
    "cp",
    "comte",
    "genre",
    "race",
    "ethnie",
    "tranche_age",
)

# Niveau de generalisation maximal de chaque quasi-identifiant.
# Niveau 0 = valeur brute ; niveau maximal = attribut supprime (bottom).
NIVEAU_MAX = {
    "ville": 3,        # ville -> comte -> etat -> supprime
    "cp": 3,           # cp -> cp3 -> comte -> supprime
    "comte": 2,        # comte -> etat -> supprime
    "genre": 1,        # genre -> supprime
    "race": 1,
    "ethnie": 1,
    "tranche_age": 3,  # decennie -> vingtaine -> quarantaine -> supprime
}

SUPPRIME = "*"


def generaliser(attribut, valeur, niveau, entite=None):
    """Applique un niveau de generalisation a une valeur de quasi-identifiant.

    `entite` sert aux hierarchies qui remontent vers un autre attribut du
    meme enregistrement (ville -> comte, cp -> comte). Je la passe en argument
    au lieu de construire une table de correspondance : la population est deja
    en memoire et la correspondance y est exacte.
    """
    if niveau <= 0:
        return str(valeur)
    if niveau >= NIVEAU_MAX.get(attribut, 1):
        return SUPPRIME

    if attribut == "ville":
        if niveau == 1:
            return "comte:" + str((entite or {}).get("comte", SUPPRIME))
        return "etat"

    if attribut == "cp":
        if niveau == 1:
            return str(valeur)[:3] + "xx"
        return "comte:" + str((entite or {}).get("comte", SUPPRIME))

    if attribut == "comte":
        return "etat"

    if attribut == "tranche_age":
        # tranche_age est deja un palier de 10 ans (JOURNAL section 10). On
        # elargit en regroupant des paliers.
        base = _borne_inferieure(valeur)
        if base is None:
            return SUPPRIME
        pas = 20 if niveau == 1 else 40
        debut = (base // pas) * pas
        return f"{debut}-{debut + pas - 1}"

    return SUPPRIME


def _borne_inferieure(tranche):
    """Extrait la borne basse d'une tranche du type '30-39' ou '30'."""
    texte = str(tranche).strip()
    if not texte:
        return None
    debut = texte.split("-")[0].strip()
    return int(debut) if debut.isdigit() else None


def signature(entite, gabarit, attributs):
    """Signature d'une entite sous un gabarit, restreinte aux attributs reveles.

    Deux entites de meme signature sont indistinguables pour un observateur
    qui n'aurait vu que ces attributs, generalises a ces niveaux.
    """
    return tuple(
        generaliser(a, entite.get(a), gabarit.get(a, 0), entite)
        for a in sorted(attributs)
    )


def ensemble_anonymat(population, entite, gabarit, attributs):
    """Entites de la population compatibles avec `entite` sur `attributs`.

    C'est |S| au sens de la section 3.3.3 du rapport. L'entite elle-meme en
    fait toujours partie, donc |S| >= 1.
    """
    if not attributs:
        return list(population)
    cible = signature(entite, gabarit, attributs)
    return [e for e in population
            if signature(e, gabarit, attributs) == cible]


def taille_ensemble(population, entite, gabarit, attributs):
    """|S|, calcule sans construire la liste."""
    if not attributs:
        return len(population)
    cible = signature(entite, gabarit, attributs)
    n = 0
    for e in population:
        if signature(e, gabarit, attributs) == cible:
            n += 1
    return n


def classes_equivalence(population, gabarit, attributs):
    """Regroupe la population par signature. Utile pour auditer un gabarit."""
    classes = defaultdict(list)
    for e in population:
        classes[signature(e, gabarit, attributs)].append(e)
    return classes


class Population:
    """Population indexee, avec les colonnes generalisees precalculees.

    Les fonctions ci-dessus definissent le calcul. Cette classe le rend assez
    rapide pour une campagne. La recherche de gabarit teste plusieurs
    centaines de candidats sur 11 538 entites : sans precalcul, une recherche
    prend une trentaine de secondes et E2b devient trop lent.

    Le precalcul est fait une fois par population et par couple
    attribut/niveau. Les resultats sont identiques, seul le temps change.
    """

    def __init__(self, entites):
        self.entites = list(entites)
        self.n = len(self.entites)
        self._colonnes = {}

    def colonne(self, attribut, niveau):
        """Valeurs generalisees de tous les individus, pour un attribut."""
        cle = (attribut, niveau)
        if cle not in self._colonnes:
            self._colonnes[cle] = [
                generaliser(attribut, e.get(attribut), niveau, e)
                for e in self.entites
            ]
        return self._colonnes[cle]

    def signatures(self, gabarit, attributs):
        """Signatures de toute la population, en une passe."""
        attributs = tuple(sorted(attributs))
        if not attributs:
            return [()] * self.n
        colonnes = [self.colonne(a, gabarit.get(a, 0)) for a in attributs]
        return list(zip(*colonnes))

    def taille_ensemble(self, entite, gabarit, attributs):
        """|S| pour une entite donnee, via un comptage par signature."""
        attributs = tuple(sorted(attributs))
        if not attributs:
            return self.n
        cible = signature(entite, gabarit, attributs)
        signatures = self.signatures(gabarit, attributs)
        return sum(1 for s in signatures if s == cible)

    def membres(self, entite, gabarit, attributs):
        """Indices des entites compatibles, utiles pour intersecter."""
        attributs = tuple(sorted(attributs))
        if not attributs:
            return set(range(self.n))
        cible = signature(entite, gabarit, attributs)
        signatures = self.signatures(gabarit, attributs)
        return {i for i, s in enumerate(signatures) if s == cible}

    def _comptes_signatures(self, gabarit=None, attributs=None):
        """Signature de chaque entite, et effectif de chaque classe.

        Utilise par `taux_uniques` et `entites_uniques`. Les deux cherchent les
        entites seules dans leur classe d'equivalence et doivent partir du
        meme decompte. Avec deux decomptes separes, la borne pessimiste
        pourrait porter sur d'autres entites que celles comptees par le taux,
        sans que rien ne le signale.

        Les deux valeurs sont appariees par position : `signatures[i]` est
        celle de `self.entites[i]`.
        """
        gabarit = gabarit or {}
        attributs = tuple(sorted(attributs or QUASI_IDENTIFIANTS))
        signatures = self.signatures(gabarit, attributs)
        comptes = defaultdict(int)
        for s in signatures:
            comptes[s] += 1
        return signatures, comptes

    def taux_uniques(self, gabarit=None, attributs=None):
        _, comptes = self._comptes_signatures(gabarit, attributs)
        uniques = sum(1 for n in comptes.values() if n == 1)
        return uniques / self.n if self.n else 0.0

    def entites_uniques(self, gabarit=None, attributs=None):
        """Les entites seules dans leur classe d'equivalence.

        Sans argument, ce sont les entites uniques sur les quasi-identifiants
        bruts, c'est-a-dire la liste des 46,2 % de la section 10 du JOURNAL.

        E2b tire ses cibles dans cette liste (borne pessimiste). Seules les
        cibles sont restreintes, la population reste entiere. Sinon N
        changerait, et la fuite log2(N/|S|) ne mesurerait plus la meme chose
        d'une borne a l'autre.
        """
        signatures, comptes = self._comptes_signatures(gabarit, attributs)
        return [entite for entite, s in zip(self.entites, signatures)
                if comptes[s] == 1]

    def __len__(self):
        return self.n


def taux_uniques(population, gabarit=None, attributs=None):
    """Proportion d'entites seules dans leur classe d'equivalence.

    Sans gabarit ni attributs, retourne le taux sur les quasi-identifiants
    bruts : les 46,2 % du JOURNAL_DONNEES.md (section 10), point de depart
    de la courbe d'effondrement.
    """
    gabarit = gabarit or {}
    attributs = attributs or QUASI_IDENTIFIANTS
    classes = classes_equivalence(population, gabarit, attributs)
    uniques = sum(1 for membres in classes.values() if len(membres) == 1)
    return uniques / len(population) if population else 0.0
