"""
Routage reflexif et abstention (pilier 1, section 3.2 du rapport).

Le routeur juge si ce que l'interne a trouve suffit pour repondre, dans
l'esprit de Self-RAG et du correcteur de qualite de CRAG. Il y a cinq issues.

    INTERNE    la recherche interne suffit ; rien ne franchit A (I1 respecte
               d'office)
    CORRIGER   recherche interne de mauvaise qualite ; on la refait avant
               d'aller chercher dehors ce qu'une meilleure recherche interne
               aurait trouve
    ENRICHIR   couverture partielle ; passage controle de A, selon la
               politique du pilier 2
    ESCALADER  budget epuise ; sortie seulement apres validation humaine,
               enregistree
    ABSTENIR   la sortie est fermee (enrichissement interdit ou impossible)
               et l'interne ne suffit pas

Dans le code actuel, le routeur ne juge pas le soutien externe : il ne
s'abstient que si la sortie est fermee. E6b mesure a part l'abstention
apres une recherche externe sans resultat.

L'abstention est une issue normale : dans une banque, repondre sans
fondement est un risque.
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

    `designants` et `couverture_vocabulaire` sont facultatifs. Un evaluateur
    qui ne les calcule pas les laisse a None, et le routeur fonctionne comme
    avant. On peut donc rejouer les anciennes campagnes a l'identique.
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
    """Decide quoi faire d'une requete avant toute sortie.

    `evaluateur` est une fonction (requete, fragments) -> Jugement, passee en
    argument. Elle peut utiliser le modele de langue via l'abstraction de
    fournisseur, ou une regle deterministe pour les tests et les experiences
    reproductibles (E6 utilise `EvaluateurCouverture`, base sur BM25).
    """

    def __init__(self, evaluateur, seuil_pertinence=0.55,
                 seuil_completude=0.70, deja_corrige=False,
                 seuil_vocabulaire=None):
        self.evaluateur = evaluateur
        self.seuil_pertinence = seuil_pertinence
        self.seuil_completude = seuil_completude
        self.deja_corrige = deja_corrige
        # A None, le routeur fonctionne comme avant, et les anciennes
        # campagnes se rejouent a l'identique.
        self.seuil_vocabulaire = seuil_vocabulaire

    def apres_correction(self):
        """Le meme routeur, pour le second passage.

        CORRIGER ne termine pas le routage : il faut refaire la recherche
        interne avant de conclure. Le second passage juge avec
        `deja_corrige`, qui interdit une nouvelle correction et oblige a
        choisir une issue finale.

        L'appelant n'a donc pas besoin de recreer un routeur a partir de ses
        attributs : le pipeline ne connait que des interfaces.
        """
        return type(self)(self.evaluateur, self.seuil_pertinence,
                          self.seuil_completude, deja_corrige=True,
                          seuil_vocabulaire=self.seuil_vocabulaire)

    def juger(self, requete, fragments):
        """Transforme la sortie de l'evaluateur en l'un des trois etats.

        CAS DES REQUETES QUI NE NOMMENT RIEN

        La pertinence est la part des jetons designants (noms propres et
        identifiants) retrouves. Une requete qui decrit sans nommer n'en a
        aucun, et la pertinence ne veut alors rien dire. L'evaluateur utilise
        a la place tous les jetons, mots outils compris, ce qui donne une
        valeur trop basse, sous le seuil. Dans la mesure faite, six requetes
        descriptives sur six partaient a l'exterieur alors que la reponse
        etait dans le corpus interne.

        La completude ne corrige pas ce probleme. Elle ne compte que les
        jetons connus du corpus : une question reglementaire, dont les mots
        sont absents des notes, obtient aussi 1,000 sur les quelques mots
        communs. Les deux classes descriptives ont donc la meme completude.

        Ce qui les separe, c'est la part des mots de la requete que le corpus
        connait. Sur le jeu d'E6 : de 0,273 a 0,545 pour les questions
        descriptives a reponse interne, de 0,071 a 0,182 pour celles a
        reponse reglementaire. Je decide donc sur cette valeur, et seulement
        quand la requete ne nomme rien.

        ATTENTION. Le seuil de 0,25 a ete choisi d'apres l'ecart observe sur
        ce jeu. Il n'a pas ete valide.

        Rejoue avec trois graines differentes, le taux de bonnes decisions
        passe a chaque fois de 96,5 % a 100 %. Mais cela ne prouve pas grand
        chose : les deux classes descriptives ont exactement six gabarits
        chacune, tous utilises a chaque tirage, donc les douze requetes
        concernees sont les memes quelle que soit la graine. Le seuil a ete
        choisi et teste sur les memes douze phrases.

        Ces rejeux montrent par contre que la regle ne casse rien ailleurs :
        les 160 autres cas, tires au hasard et donc differents a chaque
        graine, restent a 100 % de bonnes decisions.

        Pour valider le gain, il faudrait ecrire plus de gabarits
        descriptifs, sans regarder cette mesure.

        Depuis, onze et douze questions ecrites le 13/09/2026 sans voir cette
        mesure ont ete ajoutees a ces deux classes dans e6_routage.py (voir
        les commentaires de ce module). Les six gabarits dont parle ce
        paragraphe sont ceux de la version precedente.
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

        `politique` est la PolitiqueConfidentialite du pilier 2. Routage et
        confidentialite sont lies par le budget d'exposition : le routeur
        consulte donc ce budget avant de choisir l'enrichissement.
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
            # Pas d'entite enquetee a proteger : la requete n'est pas un
            # secret en soi, et seul le nettoyage des donnees s'applique.
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
        # Budget epuise sur une source ouverte : le systeme propose une
        # escalade, mais ne la decide jamais seul.
        return DecisionRoutage(
            ESCALADER, jugement,
            "budget epuise ; escalade humaine requise sinon abstention : "
            + decision.motif,
        )


def evaluateur_deterministe(pertinence_par_requete=None, defaut=(0.9, 0.9)):
    """Evaluateur de test : routage reproductible, sans modele.

    Un routeur dont le jugement change d'une execution a l'autre ne permet
    pas de mesurer la justesse du routage.
    """
    table = pertinence_par_requete or {}

    def evaluer(requete, fragments):
        pertinence, completude = table.get(requete, defaut)
        return Jugement(etat="", pertinence=pertinence, completude=completude,
                        motif="evaluateur deterministe")

    return evaluer
