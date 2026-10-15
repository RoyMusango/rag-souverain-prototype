"""
Verrou de sortie et masquage (sections 3.3.2 et 3.3.4 du rapport).

Deux couches distinctes, souvent confondues :

  MASQUAGE   probabiliste. Un detecteur d'entites nommees retire les elements
             a caractere personnel d'une requete. Son rappel est imparfait :
             il laisse passer une partie des entites. Il protege la
             confidentialite des donnees.

  VERROU     deterministe. Il confronte la charge sortante a l'ensemble des
             secrets connus et interdit l'emission en cas de correspondance.
             Cela est possible parce que le corpus interne est maitrise : la
             banque connait ses propres bases. Il fournit une borne inferieure
             garantie sur la fuite.

Le verrou ne protege pas l'intention : une requete expurgee de tout secret
litteral revele encore l'objet de la recherche. Cet aspect releve du pilier 2
(politique.py), et non de ce module.

Choix du detecteur : decision encore ouverte. Le rapport (section 3.3.2)
retient Presidio ; la presentation retient une chaine souveraine
spaCy + CamemBERT, Presidio etant conserve comme terme de comparaison
chiffree. J'ai rendu les deux interchangeables derriere une interface unique,
afin que la decision se prenne par configuration et s'appuie sur une mesure.
"""

import re
import unicodedata

# Reconnaisseurs bancaires, en complement du detecteur generique.
# Le rapport les mentionne explicitement : IBAN, identifiants internes.
MOTIFS_BANCAIRES = {
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),
    "BIC": re.compile(r"\b[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?\b"),
    "ID_INTERNE": re.compile(r"\b(?:CLI|DOS|KYC|AML)-\d{6,}\b"),
    "CARTE": re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),
}


def normaliser(texte):
    """Forme de comparaison : sans accent, sans casse, sans ponctuation.

    Sans cette normalisation, le verrou serait trivialement contournable par
    une variante d'accentuation ou de casse.
    """
    decompose = unicodedata.normalize("NFKD", str(texte))
    sans_accent = "".join(c for c in decompose if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", sans_accent.lower()).strip()


class EnsembleSecrets:
    """Ensemble des secrets connus, extrait des bases internes.

    En production, il est construit a l'ingestion depuis les referentiels de
    la banque. Au prototype, il est constitue des identifiants synthetiques
    semes dans le corpus interne (section 4.3.1).
    """

    def __init__(self, secrets=(), longueur_min=4):
        self.longueur_min = longueur_min
        self.secrets = {}
        for secret in secrets:
            self.ajouter(secret)

    def ajouter(self, secret, categorie="inconnu"):
        forme = normaliser(secret)
        # Les chaines trop courtes produiraient des faux positifs massifs :
        # un prenom de trois lettres bloquerait toute requete legitime.
        if len(forme) >= self.longueur_min:
            self.secrets[forme] = categorie
        return self

    def charger_depuis_documents(self, documents, champs=("entities",)):
        """Alimente l'ensemble depuis le schema commun d'ingestion.

        Les entites nommees deja extraites a l'ingestion (champ `entities`)
        constituent la source naturelle : elles ont ete calculees une fois,
        localement, et n'ont pas a l'etre de nouveau.
        """
        for doc in documents:
            if doc.get("source") != "interne":
                continue
            for champ in champs:
                for entite in doc.get(champ, []) or []:
                    texte, categorie = self._decomposer(entite)
                    if texte:
                        self.ajouter(texte, categorie)
        return self

    @staticmethod
    def _decomposer(entite):
        """Extrait (texte, categorie) d'une entite du schema commun.

        `common.extraire_entites_lot` produit des chaines de la forme
        "LABEL:texte", par exemple "PERSON:Stephanie Panus". Sans
        decomposition, le verrou chercherait la chaine litterale "PERSON:..."
        dans les requetes sortantes, ou elle n'apparait jamais : il ne
        bloquerait alors rien, sans le signaler.
        """
        if isinstance(entite, dict):
            return entite.get("text", ""), entite.get("label", "inconnu")
        texte = str(entite)
        if ":" in texte:
            categorie, _, valeur = texte.partition(":")
            # Un deux-points peut aussi appartenir au texte lui-meme ; je ne
            # decoupe que si la partie gauche ressemble a une etiquette spaCy.
            if categorie.isupper() and 2 <= len(categorie) <= 12:
                return valeur.strip(), categorie
        return texte, "inconnu"

    def __len__(self):
        return len(self.secrets)


class VerrouDeSortie:
    """Dernier controle avant la Frontiere A.

    Deterministe et exhaustif sur l'ensemble des secrets connus. Il ne
    remplace pas le masquage mais le double, precisement parce qu'un
    detecteur statistique laisse passer une partie des entites.
    """

    def __init__(self, ensemble_secrets):
        self.ensemble = ensemble_secrets

    def inspecter(self, charge):
        """Retourne la liste des secrets detectes dans la charge sortante."""
        forme = normaliser(charge)
        jetons = set(forme.split())
        trouves = []
        for secret, categorie in self.ensemble.secrets.items():
            mots = secret.split()
            if len(mots) == 1:
                if secret in jetons:
                    trouves.append((secret, categorie))
            elif secret in forme:
                trouves.append((secret, categorie))
        return trouves

    def autorise(self, charge):
        """Verdict binaire. Un seul secret detecte suffit a bloquer."""
        return not self.inspecter(charge)


# Etiquettes retenues comme sensibles, par famille de detecteur.
#
# Les jeux d'etiquettes different d'un modele a l'autre, et les confondre
# fausserait la comparaison : les modeles francais de spaCy emettent PER, LOC,
# ORG, MISC ; les modeles anglais PERSON, GPE, ORG, DATE, MONEY... ; Presidio
# emet ses propres types (PERSON, LOCATION, DATE_TIME...). Je les normalise
# vers un vocabulaire commun, sans quoi un detecteur paraitrait meilleur du
# seul fait qu'il nomme ses categories autrement.
NORMALISATION = {
    # spaCy francais
    "PER": "PERSONNE", "LOC": "LIEU", "ORG": "ORGANISATION", "MISC": "DIVERS",
    # spaCy anglais
    "PERSON": "PERSONNE", "GPE": "LIEU", "FAC": "LIEU", "NORP": "DIVERS",
    "DATE": "DATE", "MONEY": "MONTANT", "CARDINAL": "NOMBRE",
    # Presidio
    # ORGANIZATION (orthographe americaine) etait absent de la table. Presidio
    # l'emet ; `NORMALISATION.get(c, c)` le laissait passer tel quel, puis le
    # filtre `t[2] in self.categories` l'ecartait, CATEGORIES_SENSIBLES ne
    # connaissant qu'ORGANISATION. Le rappel de 0,127 mesurait donc une entree
    # manquante et non une propriete du detecteur. Corrige le 01/09/2026.
    "LOCATION": "LIEU", "ORGANIZATION": "ORGANISATION",
    "DATE_TIME": "DATE", "NRP": "DIVERS",
    "IBAN_CODE": "IBAN", "CREDIT_CARD": "CARTE",
    "PHONE_NUMBER": "TELEPHONE", "EMAIL_ADDRESS": "COURRIEL",
    "US_SSN": "IDENTIFIANT", "IP_ADDRESS": "RESEAU", "URL": "RESEAU",
    # motifs bancaires internes
    "IBAN": "IBAN", "BIC": "IBAN", "ID_INTERNE": "IDENTIFIANT",
    "CARTE": "CARTE",
}

# Categories normalisees considerees comme sensibles en sortie. DATE et
# MONTANT y figurent : en contexte bancaire, une date de naissance ou un
# montant exact contribuent a la re-identification autant qu'un nom.
# Categories normalisees dont l'exclusion est volontaire. Toute etiquette qui
# n'est ni sensible ni listee ici signale un oubli dans la table NORMALISATION.
# Etiquettes dont l'exclusion est volontaire, et motifs de cette exclusion.
#
# Les deux premieres familles sont non sensibles par nature. La troisieme ne
# l'est pas : AGE, EMAIL et ID sont des donnees a caractere personnel, et un
# deploiement reel doit les masquer. Je les exclus de la mesure parce qu'un
# seul des deux moteurs les produit et qu'aucune verite terrain ne les
# enumere : les rendre sensibles ferait compter comme faux positifs des
# detections correctes, de facon asymetrique et au detriment du moteur qui
# detecte le plus. Il s'agit d'une convention de mesure et non d'un choix de
# conception ; le rapport la mentionne.
ETIQUETTES_ATTENDUES_NON_SENSIBLES = frozenset({
    # non sensibles par nature
    "DIVERS", "NOMBRE", "RESEAU",
    # spaCy anglais, hors perimetre
    "PRODUCT", "WORK_OF_ART",
    # Presidio uniquement, absentes de toute verite terrain
    "AGE", "CRYPTO", "EMAIL", "ID", "MAC_ADDRESS", "MEDICAL_LICENSE",
})

CATEGORIES_SENSIBLES = frozenset({
    "PERSONNE", "LIEU", "ORGANISATION", "DATE", "MONTANT",
    "IBAN", "CARTE", "IDENTIFIANT", "TELEPHONE", "COURRIEL",
})

SPACY = "spacy"
CAMEMBERT = "camembert"
PRESIDIO = "presidio"

MODELES_SPACY = {"fr": "fr_core_news_lg", "en": "en_core_web_lg"}
MODELE_CAMEMBERT = "Jean-Baptiste/camembert-ner"


class Masqueur:
    """Interface unique devant les detecteurs d'entites nommees.

    Trois moteurs interchangeables, tous mesures, aucun n'etant fige dans le
    coeur du pipeline :

      spacy      modeles fr_core_news_lg / en_core_web_lg, deja installes
                 (JOURNAL_DONNEES section 1). Architecture convolutionnelle,
                 rapide sur processeur.
      camembert  modele transformeur francais, plus lent mais generalement
                 plus precis sur les entites de personne.
      presidio   outil de reference du domaine, conserve comme terme de
                 comparaison et non comme choix de deploiement.

    Pour le deploiement, je retiens un moteur souverain (spacy ou camembert) :
    ce composant voit l'integralite des requetes avant leur assainissement,
    ce qui en fait le point du pipeline ou une dependance envers un acteur
    non europeen est la plus difficile a justifier. Presidio reste mesure, car
    une preference de souverainete n'exempte pas d'en evaluer le cout.
    """

    def __init__(self, moteur=SPACY, langue="fr", categories=None):
        self.moteur = moteur
        self.langue = langue
        self.categories = frozenset(categories or CATEGORIES_SENSIBLES)
        self._detecteur = None
        self.duree_chargement_s = None
        self._etiquettes_signalees = set()

    # ------------------------------------------------------------ chargement

    def _charger(self):
        if self._detecteur is not None:
            return self
        import time
        debut = time.perf_counter()

        if self.moteur == SPACY:
            import spacy
            # Meme liste d'exclusion que common.charger_ner : si l'ingestion
            # et le masquage ne chargent pas le meme pipeline, ils ne
            # produisent pas les memes entites et la comparaison derive.
            self._detecteur = spacy.load(
                MODELES_SPACY.get(self.langue, MODELES_SPACY["en"]),
                exclude=["parser", "lemmatizer", "attribute_ruler",
                         "tagger", "textcat"],
            )

        elif self.moteur == CAMEMBERT:
            from transformers import pipeline
            # `aggregation_strategy` recolle les sous-mots : sans elle, un nom
            # ressort en fragments et les positions sont inexploitables.
            self._detecteur = pipeline(
                "token-classification", model=MODELE_CAMEMBERT,
                aggregation_strategy="simple",
            )

        elif self.moteur == PRESIDIO:
            self._detecteur = self._charger_presidio()

        else:
            raise ValueError(f"moteur inconnu : {self.moteur}")

        self.duree_chargement_s = round(time.perf_counter() - debut, 2)
        return self

    def _charger_presidio(self):
        """Presidio configure pour la langue voulue.

        `AnalyzerEngine()` sans configuration ne sert que l'anglais et leve
        une erreur pour `language="fr"`. Le moteur linguistique doit etre
        declare explicitement, et il repose sur les memes modeles spaCy que la
        voie souveraine. Il en resulte que la comparaison ne porte pas sur
        deux technologies de detection, mais sur la couche de reconnaisseurs
        et de contexte que Presidio ajoute au meme substrat ; je le releve
        dans le memoire.
        """
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": self.langue,
                        "model_name": MODELES_SPACY.get(
                            self.langue, MODELES_SPACY["en"])}],
        }
        moteur = NlpEngineProvider(nlp_configuration=configuration).create_engine()
        return AnalyzerEngine(nlp_engine=moteur,
                              supported_languages=[self.langue])

    # ------------------------------------------------------------ detection

    def detecter(self, texte, normaliser=True):
        """Entites detectees : liste de (debut, fin, categorie, moteur)."""
        trouvees = []

        # Les motifs bancaires s'appliquent quel que soit le moteur : ce sont
        # des formats normalises, qu'une expression reguliere detecte mieux
        # qu'un modele statistique. Ils restent constants dans la
        # comparaison, et l'ecart mesure porte bien sur la partie apprise.
        for categorie, motif in MOTIFS_BANCAIRES.items():
            for m in motif.finditer(texte):
                trouvees.append((m.start(), m.end(), categorie, "motif"))

        self._charger()

        if self.moteur == SPACY:
            for e in self._detecteur(texte).ents:
                trouvees.append((e.start_char, e.end_char, e.label_, SPACY))

        elif self.moteur == CAMEMBERT:
            for e in self._detecteur(texte):
                trouvees.append((int(e["start"]), int(e["end"]),
                                 e["entity_group"], CAMEMBERT))

        elif self.moteur == PRESIDIO:
            for r in self._detecteur.analyze(text=texte,
                                             language=self.langue):
                trouvees.append((r.start, r.end, r.entity_type, PRESIDIO))

        if normaliser:
            trouvees = [
                (d, f, NORMALISATION.get(c, c), m) for d, f, c, m in trouvees
            ]
            # Une etiquette absente de NORMALISATION ressort inchangee et
            # disparait au filtre suivant, sans message ; c'est ainsi
            # qu'ORGANIZATION a ete perdue pendant toute une campagne. Je la
            # signale une fois par etiquette et par instance.
            for _, _, categorie, _ in trouvees:
                if (categorie not in self.categories
                        and categorie not in ETIQUETTES_ATTENDUES_NON_SENSIBLES
                        and categorie not in self._etiquettes_signalees):
                    self._etiquettes_signalees.add(categorie)
                    print(f"[masqueur:{self.moteur}] etiquette non normalisee "
                          f"et donc ignoree : {categorie}")
            # Une etiquette absente de NORMALISATION ressort inchangee et
            # disparait au filtre suivant, sans message ; c'est ainsi
            # qu'ORGANIZATION a ete perdue pendant toute une campagne. Je la
            # signale une fois par etiquette et par instance.
            for _, _, categorie, _ in trouvees:
                if (categorie not in self.categories
                        and categorie not in ETIQUETTES_ATTENDUES_NON_SENSIBLES
                        and categorie not in self._etiquettes_signalees):
                    self._etiquettes_signalees.add(categorie)
                    print(f"[masqueur:{self.moteur}] etiquette non normalisee "
                          f"et donc ignoree : {categorie}")
            trouvees = [t for t in trouvees if t[2] in self.categories]

        return self._resoudre_chevauchements(trouvees)

    @staticmethod
    def _resoudre_chevauchements(spans):
        """Ne conserve, parmi des empans qui se recouvrent, que le plus long.

        Un tri simple par (debut, fin) retenait le plus court a position
        egale : « Jean » l'emportait sur « Jean Dupont », et le nom de famille
        restait en clair, soit precisement la fuite que le masquage doit
        empecher.
        """
        ordonnes = sorted(spans, key=lambda t: (t[0], -(t[1] - t[0])))
        retenus = []
        fin_courante = -1
        for span in ordonnes:
            if span[0] >= fin_courante:
                retenus.append(span)
                fin_courante = span[1]
            elif span[1] > fin_courante:
                # Recouvrement partiel : j'etends l'empan plutot que de
                # l'ignorer, sinon la fin de l'entite resterait en clair.
                debut, _, categorie, moteur = retenus[-1]
                retenus[-1] = (debut, span[1], categorie, moteur)
                fin_courante = span[1]
        return retenus

    def masquer(self, texte):
        """Remplace chaque entite detectee par un jeton de categorie."""
        detectees = self.detecter(texte)
        if not detectees:
            return texte
        morceaux, curseur = [], 0
        for debut, fin, categorie, _ in detectees:
            morceaux.append(texte[curseur:debut])
            morceaux.append(f"[{categorie}]")
            curseur = fin
        morceaux.append(texte[curseur:])
        return "".join(morceaux)

    def decrire(self):
        return {
            "moteur": self.moteur,
            "langue": self.langue,
            "modele": (MODELE_CAMEMBERT if self.moteur == CAMEMBERT
                       else MODELES_SPACY.get(self.langue)),
            "categories": sorted(self.categories),
            "duree_chargement_s": self.duree_chargement_s,
            "souverain": self.moteur in (SPACY, CAMEMBERT),
        }
