"""
Routage reflexif et abstention (pilier 1, section 3.2 du rapport).

Le routeur ne compare pas un score de similarite a un seuil : il produit un
jugement de suffisance, dans l'esprit de Self-RAG et du correcteur de qualite
de CRAG. Cinq issues en decoulent.

    INTERNE    la recuperation interne suffit ; rien ne franchit A (I1 tenu
               sans effort)
    CORRIGER   recuperation interne de faible qualite ; elle est corrigee
               avant d'aller chercher a l'exterieur ce qu'une meilleure
               recuperation interne aurait fourni
    ENRICHIR   couverture partielle ; franchissement controle de A, sous la
               politique du pilier 2
    ESCALADER  budget epuise ; franchissement sous validation humaine tracee
    ABSTENIR   ni l'interne ni l'externe ne soutiennent une reponse fiable

L'abstention n'est pas un echec du routage mais une issue a part entiere : en
conformite bancaire, repondre sans fondement constitue un risque.
"""

from dataclasses import dataclass

INTERNE = "interne"
CORRIGER = "corriger"
ENRICHIR = "enrichir"
ESCALADER = "escalader"
ABSTENIR = "abstenir"

SUFFISANTE = "suffisante"
PARTIELLE = "partielle"
FAIBLE = "faible"


@dataclass
class Jugement:
    """Evaluation reflexive de la couverture interne.

    `designants` et `couverture_vocabulaire` sont facultatifs : un evaluateur
    qui ne sait pas les produire les laisse a None, et le routeur retrouve
    alors son comportement d'origine, ce qui permet de rejouer a l'identique
    les campagnes anterieures.
    """
    etat: str
    pertinence: float
    completude: float
    motif: str = ""
    designants: int = None
    couverture_vocabulaire: float = None


@dataclass
class DecisionRoutage:
    issue: str
    jugement: Jugement
    motif: str = ""


class Routeur:
    """Decide du sort d'une requete avant toute sortie.

    `evaluateur` est une fonction (requete, fragments) -> Jugement, injectee
    plutot que figee : dans le prototype, elle s'appuie sur le modele de
    langue via l'abstraction de fournisseur, mais elle doit pouvoir etre
    remplacee par une regle deterministe pour les tests, condition de la
    reproductibilite des experiences.
    """

    def __init__(self, evaluateur, seuil_pertinence=0.55,
                 seuil_completude=0.70, deja_corrige=False,
                 seuil_vocabulaire=None):
        self.evaluateur = evaluateur
        self.seuil_pertinence = seuil_pertinence
        self.seuil_completude = seuil_completude
        self.deja_corrige = deja_corrige
        # A None, le routeur conserve son comportement d'origine : les
        # campagnes anterieures restent rejouables a l'identique.
        self.seuil_vocabulaire = seuil_vocabulaire

    def apres_correction(self):
        """Le meme routeur, pour le second passage.

        CORRIGER n'est pas une issue terminale : c'est une instruction de
        reprendre la recuperation interne avant de conclure. Le second
        passage juge donc avec `deja_corrige`, ce qui interdit une nouvelle
        correction et impose une issue terminale.

        Cette methode evite a l'appelant de reconstruire un routeur a partir
        des attributs de celui-ci : le pipeline ne connait que des interfaces.
        """
        return type(self)(self.evaluateur, self.seuil_pertinence,
                          self.seuil_completude, deja_corrige=True,
                          seuil_vocabulaire=self.seuil_vocabulaire)

    def juger(self, requete, fragments):
        """Traduit la sortie de l'evaluateur en l'un des trois etats.

        CAS DES REQUETES QUI NE NOMMENT RIEN

        La pertinence est definie comme la part des jetons designants
        couverts (noms propres et identifiants). Une requete qui decrit au
        lieu de nommer n'en contient aucun, et la grandeur n'a alors pas
        d'objet. L'evaluateur se rabat sur l'ensemble des jetons, mots outils
        compris, ce qui produit une fraction diluee, inferieure au seuil :
        dans la mesure effectuee, six requetes descriptives sur six etaient
        envoyees a l'exterieur alors que le corpus interne contenait la
        reponse.

        La completude ne suffit pas a corriger ce biais. Son denominateur ne
        compte que les jetons connus du corpus, si bien qu'une question
        reglementaire, dont le vocabulaire est etranger aux notes, obtient
        elle aussi 1,000 sur le faible residu de mots communs. Les deux
        classes descriptives y sont indiscernables.

        Ce qui les separe est la part du vocabulaire de la requete connue du
        corpus, mesuree sur le jeu d'E6 : de 0,273 a 0,545 pour les questions
        descriptives a reponse interne, de 0,071 a 0,182 pour celles a reponse
        reglementaire. Je tranche donc sur cette grandeur, et seulement
        lorsque la requete ne nomme rien.

        RESERVE IMPORTANTE. Le seuil de 0,25 est cale sur l'ecart observe dans
        ce jeu, et il n'a pas ete valide.

        Un rejeu sur trois graines differentes fait passer le taux de
        decision correcte de 96,5 % a 100 % a chaque fois. Ce resultat n'est
        pas probant sur le point essentiel : les deux classes descriptives
        comptent exactement six gabarits chacune, tous employes a chaque
        tirage, si bien que les douze requetes concernees sont identiques
        d'une graine a l'autre. Le seuil est donc cale et eprouve sur les
        memes douze phrases.

        Ces rejeux etablissent en revanche l'absence d'effet de bord : les
        160 autres cas, tires au hasard et donc differents a chaque graine,
        restent a 100 % de decisions correctes.

        Valider le gain exigerait d'elargir les deux familles de gabarits
        descriptifs, en les redigeant sans consulter cette mesure.
        """
        jugement = self.evaluateur(requete, fragments)
        if jugement.etat:
            return jugement

        sans_designant = (self.seuil_vocabulaire is not None
                          and jugement.designants == 0
                          and jugement.couverture_vocabulaire is not None)

        if sans_designant:
            if jugement.couverture_vocabulaire < self.seuil_vocabulaire:
                jugement.etat = FAIBLE
            elif jugement.completude >= self.seuil_completude:
                jugement.etat = SUFFISANTE
            else:
                jugement.etat = PARTIELLE
            return jugement

        if jugement.pertinence < self.seuil_pertinence:
            jugement.etat = FAIBLE
        elif jugement.completude >= self.seuil_completude:
            jugement.etat = SUFFISANTE
        else:
            jugement.etat = PARTIELLE
        return jugement

    def decider(self, requete, fragments, politique=None, cle_entite=None,
                entite=None, attributs=(), enrichissement_possible=True):
        """Issue du routage pour cette requete.

        `politique` est la PolitiqueConfidentialite du pilier 2. Le routage et
        la confidentialite ne sont pas deux modules independants mais deux
        facettes d'une meme politique, reliees par le budget d'exposition ;
        c'est pourquoi le routeur interroge celui-ci avant de conclure a
        l'enrichissement.
        """
        jugement = self.juger(requete, fragments)

        if jugement.etat == SUFFISANTE:
            return DecisionRoutage(
                INTERNE, jugement,
                "couverture interne suffisante ; aucune sortie",
            )

        if jugement.etat == FAIBLE and not self.deja_corrige:
            return DecisionRoutage(
                CORRIGER, jugement,
                "recuperation interne de faible qualite ; correction avant sortie",
            )

        if not enrichissement_possible:
            return DecisionRoutage(
                ABSTENIR, jugement,
                "enrichissement externe indisponible ou interdit",
            )

        if politique is None or cle_entite is None:
            # Pas de secret d'enquete a proteger : la requete n'est pas
            # elle-meme le secret, seule la sanitisation des donnees
            # s'applique.
            return DecisionRoutage(ENRICHIR, jugement,
                                   "enrichissement sous sanitisation")

        decision = politique.evaluer(cle_entite, entite, attributs)
        if decision.issue == "emettre":
            return DecisionRoutage(ENRICHIR, jugement, decision.motif)
        if decision.issue == "privee":
            return DecisionRoutage(
                ENRICHIR, jugement,
                "bascule vers la recuperation privee : " + decision.motif,
            )
        # Budget epuise sur une source ouverte : l'escalade est proposee,
        # mais jamais decidee par le systeme seul.
        return DecisionRoutage(
            ESCALADER, jugement,
            "budget epuise ; escalade humaine requise sinon abstention : "
            + decision.motif,
        )


def evaluateur_deterministe(pertinence_par_requete=None, defaut=(0.9, 0.9)):
    """Evaluateur de test : rend le routage reproductible sans modele.

    Il est necessaire aux experiences E6 : un routeur dont le jugement varie
    d'une execution a l'autre ne permet pas de mesurer la justesse du routage.
    """
    table = pertinence_par_requete or {}

    def evaluer(requete, fragments):
        pertinence, completude = table.get(requete, defaut)
        return Jugement(etat="", pertinence=pertinence, completude=completude,
                        motif="evaluateur deterministe")

    return evaluer
