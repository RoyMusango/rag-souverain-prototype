"""
Politique de confidentialite de la requete sortante (pilier 2, section 3.3).

Ce module assemble les elements du pilier : gabarit fige sur l'entite,
budget d'exposition et verrou de sortie. Il repond a la question posee a la
Frontiere A :

    la requete peut-elle sortir, et sous quelle forme ?

Quatre issues possibles, les memes que pour le routage (section 3.2) :
    EMETTRE    la requete generalisee franchit A
    PRIVEE     passage a la recuperation privee sur corpus fixe
    ESCALADE   sortie validee par un humain et enregistree
    ABSTENIR   rien ne sort

La regle "aucun embedding ne franchit A" n'est pas verifiee ici : elle
decoule de l'architecture. Le contenu externe est rapatrie en texte puis
vectorise en local (voir src/index/).
"""

from dataclasses import dataclass, field

from . import anonymat, budget as mod_budget, gabarit as mod_gabarit

EMETTRE = "emettre"
PRIVEE = "privee"
ESCALADE = "escalade"
ABSTENIR = "abstenir"


@dataclass
class Decision:
    """Verdict de la politique pour une requete sortante."""
    issue: str
    requete: str = ""
    attributs: tuple = ()
    gabarit: dict = field(default_factory=dict)
    taille_ensemble: int = 0
    fuite_bits: float = 0.0
    budget_restant: float = 0.0
    motif: str = ""

    @property
    def emise(self):
        return self.issue in (EMETTRE, ESCALADE)


class PolitiqueConfidentialite:
    """Applique le pilier 2 a une population d'entites donnee."""

    def __init__(self, population, registre=None, k=None,
                 source_structuree=False):
        self.population = list(population)
        self.registre = registre or mod_budget.Registre()
        self.k = k if k is not None else self.registre.k
        # La recuperation privee est possible sur une source structuree a
        # corpus fixe, pas sur une source ouverte (section 3.3.3).
        self.source_structuree = source_structuree

    # ------------------------------------------------------------ gabarit

    def gabarit_de(self, cle_entite, entite):
        """Recupere le gabarit fige de l'entite, ou le calcule et le fige.

        Le calcul n'a lieu qu'une fois par entite et par deploiement. Les
        sessions suivantes sur la meme entite reutilisent ce gabarit. C'est
        pour cela que croiser deux sessions n'apprend rien a l'adversaire.
        """
        existant = self.registre.entree(cle_entite)["gabarit"]
        if existant is not None:
            return existant
        calcule = mod_gabarit.calculer(
            self.population, entite, self.k, self.registre.kappa
        )
        return self.registre.fixer_gabarit(cle_entite, calcule)

    # ------------------------------------------------------------ decision

    def evaluer(self, cle_entite, entite, attributs, session=None):
        """Decide du sort d'une requete revelant `attributs` sur `entite`.

        La fuite est calculee sur l'union des attributs deja reveles et de
        ceux qu'ajoute la requete. C'est ce cumul qui fait la difference entre
        une protection par session et une protection par entite.
        """
        gabarit = self.gabarit_de(cle_entite, entite)
        entree = self.registre.entree(cle_entite)

        cumules = tuple(sorted(set(entree["attributs_reveles"]) | set(attributs)))
        taille = anonymat.taille_ensemble(
            self.population, entite, gabarit, cumules
        )
        fuite = mod_budget.fuite_bits(len(self.population), taille)
        restant = self.registre.budget_bits - fuite

        commun = {
            "attributs": cumules,
            "gabarit": gabarit,
            "taille_ensemble": taille,
            "fuite_bits": fuite,
            "budget_restant": restant,
        }

        if taille < self.k:
            return Decision(
                issue=PRIVEE if self.source_structuree else ABSTENIR,
                motif=f"|S| = {taille} < k = {self.k}",
                **commun,
            )

        if restant < 0:
            return Decision(
                issue=PRIVEE if self.source_structuree else ABSTENIR,
                motif=(f"budget epuise : fuite {fuite:.2f} bits > "
                       f"{self.registre.budget_bits:.2f}"),
                **commun,
            )

        self.registre.consommer(cle_entite, attributs, fuite, session)
        return Decision(issue=EMETTRE, motif="seuil et budget respectes",
                        **commun)

    def escalader(self, cle_entite, entite, attributs, motif, operateur,
                  session=None):
        """Force l'emission sous validation humaine tracee.

        A appeler seulement apres l'accord explicite d'un operateur habilite.
        L'appel est enregistre dans le registre et peut donc etre audite.
        Cette sortie autorisee est utile : sans elle, les utilisateurs
        finiraient par contourner le systeme en dehors de tout controle.
        """
        decision = self.evaluer(cle_entite, entite, attributs, session)
        self.registre.journaliser_escalade(
            cle_entite, motif, operateur, session
        )
        self.registre.consommer(
            cle_entite, attributs, decision.fuite_bits, session
        )
        return Decision(
            issue=ESCALADE,
            requete=decision.requete,
            attributs=decision.attributs,
            gabarit=decision.gabarit,
            taille_ensemble=decision.taille_ensemble,
            fuite_bits=decision.fuite_bits,
            budget_restant=decision.budget_restant,
            motif=f"escalade autorisee par {operateur} : {motif}",
        )

    # ------------------------------------------------------------ rendu

    def formuler(self, entite, decision):
        """Construit la requete generalisee qui sort par la Frontiere A.

        La valeur brute d'un quasi-identifiant ne sort jamais : seule sa
        forme generalisee selon le gabarit franchit la frontiere.
        """
        if not decision.emise:
            return ""
        termes = []
        for attribut in decision.attributs:
            valeur = anonymat.generaliser(
                attribut, entite.get(attribut),
                decision.gabarit.get(attribut, 0), entite,
            )
            if valeur != anonymat.SUPPRIME:
                termes.append(f"{attribut}:{valeur}")
        return " ".join(termes)
