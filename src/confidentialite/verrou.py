"""
Verrou de sortie et masquage (sections 3.3.2 et 3.3.4 du rapport).

Le module contient deux couches differentes :

  MASQUAGE   probabiliste. Un detecteur d'entites nommees retire les donnees
             personnelles d'une requete. Il en laisse passer une partie,
             car son rappel n'est pas parfait. Il protege les donnees.

  VERROU     deterministe. Il compare la requete sortante a la liste des
             secrets connus et bloque l'envoi si l'un d'eux apparait. C'est
             possible parce que la banque connait ses propres bases. Il
             garantit qu'aucun secret connu ne sort tel quel.

Le verrou ne protege pas l'intention : une requete sans aucun secret
revele quand meme ce que l'on cherche. Ce point est traite par le pilier 2
(politique.py).

Choix du detecteur : la decision reste ouverte. Le rapport (section 3.3.2)
retient Presidio. La presentation retient une chaine souveraine
spaCy + CamemBERT et garde Presidio comme point de comparaison. Les deux
s'utilisent par la meme interface : on choisit dans la configuration, sur la
base des mesures.
"""

import re
import unicodedata

# Reconnaisseurs bancaires, en complement du detecteur generique.
# Le rapport les cite : IBAN, identifiants internes.
MOTIFS_BANCAIRES = {
    "IBAN": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"),
    "BIC": re.compile(r"\b[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?\b"),
    "ID_INTERNE": re.compile(r"\b(?:CLI|DOS|KYC|AML)-\d{6,}\b"),
    "CARTE": re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),
}


def normaliser(texte):
    """Forme de comparaison : sans accent, sans majuscule, sans ponctuation.

    Sans cette normalisation, il suffirait de changer un accent ou une
    majuscule pour passer le verrou.
    """
    decompose = unicodedata.normalize("NFKD", str(texte))
    sans_accent = "".join(c for c in decompose if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", sans_accent.lower()).strip()


class EnsembleSecrets:
    """Ensemble des secrets connus, tire des bases internes.

    En production, il est construit a l'ingestion depuis les referentiels de
    la banque. Dans le prototype, il contient les identifiants synthetiques
    places dans le corpus interne (section 4.3.1).
    """

    def __init__(self, secrets=(), longueur_min=4):
        self.longueur_min = longueur_min
        self.secrets = {}
        for secret in secrets:
            self.ajouter(secret)

    def ajouter(self, secret, categorie="inconnu"):
        forme = normaliser(secret)
        # Les chaines trop courtes donneraient beaucoup de faux positifs : un
        # prenom de trois lettres bloquerait des requetes legitimes.
        if len(forme) >= self.longueur_min:
            self.secrets[forme] = categorie
        return self

    def charger_depuis_documents(self, documents, champs=("entities",)):
        """Remplit l'ensemble a partir du schema commun d'ingestion.

        On reprend les entites nommees deja extraites a l'ingestion (champ
        `entities`). Elles ont ete calculees une fois, en local, inutile de
        les recalculer.
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
        "LABEL:texte", par exemple "PERSON:Stephanie Panus". Sans ce
        decoupage, le verrou chercherait la chaine "PERSON:..." dans les
        requetes sortantes. Elle n'y apparait jamais, donc le verrou ne
        bloquerait rien, et sans aucun message.
        """
        if isinstance(entite, dict):
            return entite.get("text", ""), entite.get("label", "inconnu")
        texte = str(entite)
        if ":" in texte:
            categorie, _, valeur = texte.partition(":")
            # Le texte peut lui-meme contenir un deux-points. Je ne decoupe
            # que si la partie gauche ressemble a une etiquette spaCy.
            if categorie.isupper() and 2 <= len(categorie) <= 12:
                return valeur.strip(), categorie
        return texte, "inconnu"

    def __len__(self):
        return len(self.secrets)


class VerrouDeSortie:
    """Dernier controle avant la Frontiere A.

    Deterministe, il verifie tous les secrets connus. Il vient en plus du
    masquage, parce qu'un detecteur statistique laisse passer une partie des
    entites.
    """

    def __init__(self, ensemble_secrets):
        self.ensemble = ensemble_secrets

    def inspecter(self, charge):
        """Renvoie la liste des secrets trouves dans la requete sortante."""
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
        """Vrai ou faux. Un seul secret trouve suffit a bloquer."""
        return not self.inspecter(charge)


# Etiquettes retenues comme sensibles, par famille de detecteur.
#
# Chaque modele a ses propres etiquettes : les modeles francais de spaCy
# produisent PER, LOC, ORG, MISC ; les modeles anglais PERSON, GPE, ORG, DATE,
# MONEY... ; Presidio ses propres types (PERSON, LOCATION, DATE_TIME...). Je
# les ramene a un vocabulaire commun. Sinon un detecteur semblerait meilleur
# simplement parce qu'il nomme ses categories autrement.
NORMALISATION = {
    # spaCy francais
    "PER": "PERSONNE", "LOC": "LIEU", "ORG": "ORGANISATION", "MISC": "DIVERS",
    # spaCy anglais
    "PERSON": "PERSONNE", "GPE": "LIEU", "FAC": "LIEU", "NORP": "DIVERS",
    "DATE": "DATE", "MONEY": "MONTANT", "CARDINAL": "NOMBRE",
    # Presidio
    # ORGANIZATION (orthographe americaine) manquait dans la table. Presidio
    # produit cette etiquette ; `NORMALISATION.get(c, c)` la laissait telle
    # quelle, puis le filtre `t[2] in self.categories` l'ecartait, car
    # CATEGORIES_SENSIBLES ne contient qu'ORGANISATION. Le rappel de 0,127
    # venait donc de cette entree manquante. Corrige le 01/09/2026.
    "LOCATION": "LIEU", "ORGANIZATION": "ORGANISATION",
    "DATE_TIME": "DATE", "NRP": "DIVERS",
    "IBAN_CODE": "IBAN", "CREDIT_CARD": "CARTE",
    "PHONE_NUMBER": "TELEPHONE", "EMAIL_ADDRESS": "COURRIEL",
    "US_SSN": "IDENTIFIANT", "IP_ADDRESS": "RESEAU", "URL": "RESEAU",
    # motifs bancaires internes
    "IBAN": "IBAN", "BIC": "IBAN", "ID_INTERNE": "IDENTIFIANT",
    "CARTE": "CARTE",
}

# Etiquettes ecartees volontairement. Une etiquette qui n'est ni sensible ni
# listee ici signale un oubli dans la table NORMALISATION.
#
# Les deux premiers groupes ne sont pas sensibles. Le troisieme l'est : AGE,
# EMAIL et ID sont des donnees personnelles, et un vrai deploiement doit les
# masquer. Je les retire de la mesure parce qu'un seul des deux moteurs les
# produit et qu'aucune verite terrain ne les liste. Les compter comme
# sensibles ferait passer des detections correctes pour des faux positifs,
# au detriment du moteur qui detecte le plus. C'est une convention de
# mesure, mentionnee dans le rapport.
ETIQUETTES_ATTENDUES_NON_SENSIBLES = frozenset({
    # non sensibles par nature
    "DIVERS", "NOMBRE", "RESEAU",
    # spaCy anglais, hors perimetre
    "PRODUCT", "WORK_OF_ART",
    # Presidio uniquement, absentes de toute verite terrain
    "AGE", "CRYPTO", "EMAIL", "ID", "MAC_ADDRESS", "MEDICAL_LICENSE",
})

# Categories considerees comme sensibles en sortie. DATE et MONTANT en font
# partie : dans une banque, une date de naissance ou un montant exact aident a
# re-identifier quelqu'un autant qu'un nom.
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

    Trois moteurs interchangeables, tous mesures :

      spacy      modeles fr_core_news_lg / en_core_web_lg, deja installes
                 (JOURNAL_DONNEES section 1). Reseau convolutif, rapide sur
                 processeur.
      camembert  transformeur francais, plus lent, souvent plus precis sur
                 les noms de personnes.
      presidio   outil de reference du domaine, garde comme point de
                 comparaison.

    Pour le deploiement, je choisis un moteur souverain (spacy ou camembert).
    Ce composant voit toutes les requetes avant qu'elles soient nettoyees :
    c'est l'endroit ou dependre d'un acteur non europeen est le plus
    difficile a justifier. Presidio reste mesure pour connaitre le cout de ce
    choix.
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
            # Meme liste d'exclusion que common.charger_ner. Si l'ingestion et
            # le masquage chargeaient des pipelines differents, ils ne
            # trouveraient pas les memes entites.
            self._detecteur = spacy.load(
                MODELES_SPACY.get(self.langue, MODELES_SPACY["en"]),
                exclude=["parser", "lemmatizer", "attribute_ruler",
                         "tagger", "textcat"],
            )

        elif self.moteur == CAMEMBERT:
            from transformers import pipeline
            # `aggregation_strategy` recolle les sous-mots. Sans elle, un nom
            # sort en morceaux et les positions sont inutilisables.
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

        `AnalyzerEngine()` sans configuration ne gere que l'anglais et leve
        une erreur pour `language="fr"`. Il faut declarer le moteur
        linguistique, qui utilise les memes modeles spaCy que la voie
        souveraine. La comparaison mesure donc seulement ce que Presidio
        ajoute par-dessus spaCy (reconnaisseurs et contexte). Le memoire le
        precise.
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
        """Entites trouvees : liste de (debut, fin, categorie, moteur)."""
        trouvees = []

        # Les motifs bancaires s'appliquent avec tous les moteurs. Ce sont des
        # formats fixes, qu'une expression reguliere trouve mieux qu'un modele
        # statistique. Comme ils sont les memes pour tous, l'ecart mesure
        # entre moteurs vient du modele appris.
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
            # Une etiquette absente de NORMALISATION reste telle quelle et
            # disparait au filtre suivant, sans message. C'est comme cela
            # qu'ORGANIZATION a ete perdue pendant toute une campagne. Je
            # l'affiche une fois par etiquette et par instance.
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
        """Parmi des empans qui se chevauchent, garde le plus long.

        Un simple tri par (debut, fin) gardait le plus court a position egale :
        « Jean » passait avant « Jean Dupont » et le nom de famille restait en
        clair.
        """
        ordonnes = sorted(spans, key=lambda t: (t[0], -(t[1] - t[0])))
        retenus = []
        fin_courante = -1
        for span in ordonnes:
            if span[0] >= fin_courante:
                retenus.append(span)
                fin_courante = span[1]
            elif span[1] > fin_courante:
                # Chevauchement partiel : j'etends l'empan au lieu de
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
