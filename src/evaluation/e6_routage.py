"""
E6 : routage reflexif. Le systeme sort-il quand il le faut, et seulement alors ?

Le pilier 1 (section 3.2) decide quoi faire d'une requete avant toute
sortie. Cette experience verifie ces decisions avec trois mesures, que je
garde separees :

    taux de decision correcte      l'issue choisie est-elle la bonne ?
    taux de franchissement injustifie   sortie alors que l'interne suffisait
    taux d'abstention              abstention quand il le faut ?

La deuxieme compte le plus pour ce travail. Rater une source externe donne
une moins bonne reponse. Sortir pour rien expose la requete sans aucun
benefice. Un score unique melangerait ces deux erreurs, que le memoire veut
distinguer.

VERITE TERRAIN

Le risque est le meme que dans e7_masquage. Si j'ecrivais a la fois les
requetes et la table de jugement de `routeur.evaluateur_deterministe`, le
routeur aurait 100 % d'office, et on ne mesurerait que le branchement de
`decider()`.

Comme pour E2 et E7, la verite terrain vient donc de la facon dont le jeu
est construit. Le label d'un cas depend d'un fait que le routeur ne voit
pas : l'endroit ou se trouve vraiment la reponse.

    interne   la reponse est un champ d'une note du corpus bancaire
              (source « interne ») : l'interne suffit et rien ne doit
              franchir la Frontiere A
    externe   la reponse se trouve dans EUR-Lex (source « externe ») et le
              corpus bancaire ne contient aucun texte reglementaire :
              l'interne ne peut pas suffire
    absente   la reponse ne se trouve dans aucun des deux

L'evaluateur ne voit jamais le label. Il juge la couverture seulement a
partir d'une vraie recherche BM25 sur le corpus interne. Le routeur peut donc
se tromper, et c'est ce qu'on veut mesurer.

CE QUI N'EST PAS MESURE

`routeur.py` annonce cinq issues, mais `decider()` n'en renvoie que quatre a
partir du jugement de couverture. On n'arrive a ABSTENIR que par
`if not enrichissement_possible` : le routeur ne juge jamais le soutien
externe. Dans le code actuel, l'abstention depend donc seulement du fait
que la sortie soit autorisee ou non. E6b mesure l'autre cas, quand la
reponse n'existe nulle part.

Je mesure le comportement reel du code : l'abstention est testee sur des
cas ou l'enrichissement est interdit (source fermee, ou politique de
deploiement restrictive).

ESCALADER n'est pas mesure ici. Cette issue depend du budget d'exposition,
etudie dans E2, et la population d'entites d'E2 n'a rien a voir avec le
corpus bancaire.
"""

import random
import re

from ..index import lexical as mod_lexical
from ..routage import routeur as mod_routeur

# Classes de verite terrain. Le nom dit ou se trouve la reponse, et pas ce que
# le routeur devrait decider. Le label reste ainsi independant du routeur.
INTERNE = "interne"
EXTERNE = "externe"
ABSENTE = "absente"
INTERDIT = "enrichissement-interdit"

# Les deux classes difficiles, et pourquoi elles existent.
#
# La premiere version du jeu n'avait que les classes ci-dessus. Elle donnait
# 100 % de bonnes decisions, ce qui ne prouvait rien : les requetes internes
# citaient la cle du dossier, que BM25 retrouve mot pour mot. La pertinence
# valait donc 1,000 pour l'interne et 0,000 ailleurs, et le jeu etait trop
# facile.
#
# Les deux classes suivantes retirent cet indice : elles decrivent le dossier
# sans le nommer, comme dans la realite (un analyste demande rarement une
# fiche par sa cle). C'est la que le routeur peut se tromper.
INTERNE_DECRIT = "interne-decrit"
EXTERNE_IMPLICITE = "externe-implicite"

# Issue attendue pour chaque classe, avec le code actuel.
ISSUE_ATTENDUE = {
    INTERNE: mod_routeur.INTERNE,
    EXTERNE: mod_routeur.ENRICHIR,
    # Avant de sortir, le routeur ne peut pas savoir que la reponse n'existe
    # nulle part. Sortir pour verifier est raisonnable, c'est donc l'issue
    # attendue. Je rapporte a part que ces sorties ne trouvent rien.
    ABSENTE: mod_routeur.ENRICHIR,
    INTERDIT: mod_routeur.ABSTENIR,
    INTERNE_DECRIT: mod_routeur.INTERNE,
    EXTERNE_IMPLICITE: mod_routeur.ENRICHIR,
}


# ----------------------------------------------------------------- le jeu

def _champs_par_client(reference):
    """Regroupe les chaines de la reference bancaire par client et par champ.

    La reference contient un `champ` (prenom, nom, ville, societe, iban...).
    Je m'en sers pour ecrire des questions dont la reponse est forcement un
    fait du corpus interne.
    """
    clients = {}
    for entree in reference:
        morceaux = entree["doc_id"].split("/")
        if len(morceaux) < 2:
            continue
        champs = clients.setdefault(morceaux[1], {})
        for attendu in entree["attendus"]:
            champ = attendu.get("champ")
            if champ and champ not in champs:
                champs[champ] = attendu["chaine"]
    return clients


MOTIF_ARTICLE = re.compile(r"\bArticle\s+(\d{1,3})\b", re.IGNORECASE)

MOTIF_MOT = re.compile(r"[\w'-]+", re.UNICODE)


def jetons_designants(requete, langue="fr"):
    """Jetons par lesquels la requete nomme quelque chose.

    Noms propres et identifiants : nom de client, numero de dossier, sigle
    d'un reglement, numero d'article. En francais, on les reconnait a une
    majuscule (hors premier mot) ou a la presence d'un chiffre.

    Cette regle ne regarde que la requete, ni le corpus ni le label. Elle
    traite « Verhaegen » et « DORA » de la meme facon, donc on ne peut pas
    l'ajuster pour favoriser une classe.

    La premiere version prenait tous les jetons rares du corpus. Elle
    retenait alors les mots de la question (« domiciliation », « titulaire »,
    absents des notes) au lieu de ce que la requete cherche : les requetes
    internes tombaient a une pertinence de 0,40 alors que leur cible etait
    presente mot pour mot.
    """
    mots = MOTIF_MOT.findall(str(requete))
    designants = []
    for rang, mot in enumerate(mots):
        noyau = mot.strip("'-")
        if not noyau:
            continue
        # La majuscule du premier mot vient de la phrase et ne nomme rien
        # (« Quelle »).
        if any(c.isdigit() for c in noyau) or (rang > 0 and noyau[:1].isupper()):
            designants.extend(mod_lexical.jetons(noyau, langue))
    return sorted(set(designants))


MOTIF_RUBRIQUE_ARTICLE = re.compile(r"^eurlex/([^/]+)/[^/]+/art_0*(\d+)$")


def _sujets_eurlex(documents, limite=400, depuis_rubrique=True):
    """Couples (texte reglementaire, numero d'article) qui existent vraiment.

    Je n'invente aucun numero d'article : je ne garde que ceux d'un vrai
    document EUR-Lex. Sinon la classe `externe` contiendrait des questions
    sans reponse, comme la classe `absente`.

    CORRECTION DE LA PREMIERE VERSION

    La premiere version cherchait `Article <n>` dans le texte du document et
    associait ce numero au reglement du document. Mais un texte de MiFID 2
    cite des articles d'autres reglements : on obtenait par exemple
    (MiFID2, 201) a partir d'un renvoi, alors que MiFID 2 n'a pas d'article
    201. Mesure du 25/09 : 6 % des sujets, 4 questions sur 40 tirees.

    La rubrique donne l'article auquel le document appartient, donc toujours
    un article qui existe. `depuis_rubrique=False` remet l'ancien
    comportement, pour rejouer une ancienne campagne.
    """
    sujets = []
    vus = set()
    for doc in documents:
        if depuis_rubrique:
            trouve = MOTIF_RUBRIQUE_ARTICLE.match(str(doc.get("rubrique", "")))
            couples = ([(trouve.group(1).replace("_", " "), trouve.group(2))]
                       if trouve else [])
        else:
            morceaux = str(doc.get("doc_id", "")).split("/")
            if len(morceaux) < 3:
                continue
            texte_reg = morceaux[1].replace("_", " ")
            couples = [(texte_reg, n)
                       for n in MOTIF_ARTICLE.findall(doc.get("text", "") or "")]
        for cle in couples:
            if cle in vus:
                continue
            vus.add(cle)
            sujets.append(cle)
            if len(sujets) >= limite:
                return sujets
    return sujets


# Gabarits de questions. Le champ demande est toujours un fait du corpus
# vise : c'est le gabarit qui donne la classe, sans annotation a la main.
GABARITS_INTERNES = [
    ("Quelle est la ville de domiciliation du client {nom} au dossier {cli} ?",
     ("nom", "ville")),
    ("Quelle societe {prenom} {nom} declare-t-il comme intermediaire au "
     "dossier {cli} ?", ("societe",)),
    ("Quel IBAN est rattache au dossier {cli} du client {nom} ?", ("iban",)),
    ("Quel est le titulaire du dossier {cli} ?", ("nom",)),
]

GABARITS_EXTERNES = [
    "Que prevoit l'article {numero} du {reglement} et quelles obligations "
    "en decoulent pour un etablissement bancaire ?",
    "Quel est le champ d'application de l'article {numero} du {reglement} ?",
]

GABARITS_ABSENTS = [
    "Quel est le montant de la sanction prononcee le 14 mars 2019 contre "
    "l'etablissement {faux} par le regulateur de {lieu} ?",
    "Quelles conclusions le rapport interne {faux} formule-t-il sur la "
    "contrepartie {lieu} ?",
]

# Requetes qui decrivent un fait du corpus interne sans nommer de dossier.
# Elles utilisent les mots des notes (encours, vigilance, entree en relation,
# examen periodique) mais aucun identifiant : le routeur ne peut plus
# s'appuyer sur une correspondance exacte.
GABARITS_INTERNES_DECRITS = [
    "Quel motif de vigilance a ete retenu pour les mouvements au credit en "
    "provenance d'une contrepartie liee ?",
    "Quelle validation la procedure interne exige-t-elle pour une entree en "
    "relation avec une contrepartie du secteur negoce de matieres premieres ?",
    "Quel encours consolide est constate sur les comptes principaux depuis le "
    "dernier examen periodique ?",
    "Quels dossiers portent une structure de detention a plusieurs niveaux "
    "relevee lors de la vigilance ?",
    "Quel secteur d'activite est declare par les clients entres en relation "
    "au titre d'une activite de negoce ?",
    "Quelles operations ont ete signalees depuis le dernier examen periodique "
    "sur les comptes principaux ?",

    # Onze questions ecrites le 13/09/2026, avant que le routeur utilise la
    # couverture de vocabulaire. Elles n'ont donc pas pu etre ecrites pour
    # lui, et servent de jeu de validation.
    #
    # Elles sont accentuees, et c'est important : `lexical.jetons` ne retire
    # pas les accents, donc « beneficiaire » et « benéficiaire » sont deux
    # jetons differents, et le corpus bancaire est accentue. Une premiere
    # version sans accents, comme les gabarits ci-dessus, faisait passer deux
    # questions sous le seuil pour cette seule raison.
    #
    # Trois questions restent sous le seuil. Ce sont celles qui emploient des
    # synonymes : « exercice professionnel » pour « secteur declare »,
    # « instrument de paiement » pour « carte de paiement », « avoirs
    # financiers » pour « encours consolide ». Compter des mots ne gere pas
    # les synonymes : ces trois echecs vont dans le sens d'un jugement de
    # couverture semantique.
    "Quelle mesure de suivi le document indique-t-il concernant l'état actuel du dossier client ?",
    "Quel élément est désigné comme bénéficiaire du mouvement financier atypique consigné dans la note ?",
    "Quelles indications le document livre-t-il sur les modalités d'exercice professionnel de la personne physique identifiée ?",
    "Quel état des lieux le dossier dresse-t-il concernant la production des pièces justificatives relatives au bénéficiaire effectif ?",
    "Quel domaine professionnel est déclaré dans le dossier pour justifier l'entrée en relation ?",
    "Quel instrument de paiement le document indique-t-il comme étant rattaché au dossier ?",
    "Quel élément de référence interne est attribué pour assurer le suivi de ce dossier client ?",
    "Quelle condition de validation la procédure impose-t-elle pour l'entrée en relation avec ce type de contrepartie ?",
    "Quel lien la note établit-elle entre le dossier du client mentionné et la directive énoncée ?",
    "Quelle étape précise de la relation commerciale nécessite l'intervention d'un autre intervenant ?",
    "Quelle précision la note apporte-t-elle sur le niveau global des avoirs financiers domiciliés dans l'établissement ?",
]

# Requetes reglementaires qui ne nomment pas le texte applicable. La reponse
# est dans EUR-Lex et le corpus interne n'a aucun texte reglementaire : le
# label reste « externe ». Mais leurs mots (etablissement, obligations,
# prestataire) se retrouvent aussi dans les notes, ce qui peut pousser le
# routeur a croire que l'interne suffit.
GABARITS_EXTERNES_IMPLICITES = [
    "Quelles obligations de notification pesent sur un etablissement "
    "financier en cas d'incident majeur affectant ses prestataires "
    "informatiques ?",
    "Quelles exigences de transparence s'appliquent a la fourniture d'un "
    "systeme d'intelligence artificielle a haut risque ?",
    "Quelles informations doivent etre communiquees au client avant la "
    "fourniture d'un service d'investissement ?",
    "Dans quel delai un traitement de donnees a caractere personnel doit-il "
    "etre notifie a l'autorite de controle apres une violation ?",
    "Quelles mesures de gestion du risque lie aux technologies de "
    "l'information un etablissement doit-il mettre en place ?",
    "Quelles obligations de tenue de registre s'imposent au fournisseur d'un "
    "systeme a haut risque ?",

    # Douze questions ecrites le 13/09/2026 dans les memes conditions, et
    # accentuees pour la meme raison. Huit n'ont aucun jeton designant et
    # passent donc par la nouvelle regle de decision. Les quatre autres ont
    # un chiffre ou une majuscule (« demande 6 », « comite IA », « Etat
    # membre ») et sont jugees comme avant. Aucune des huit ne depasse le
    # seuil : la nouvelle regle ne garde a tort aucune question
    # reglementaire en interne.
    "Quelles procédures doivent être faites par les déployeurs avant de mettre en service ou d'utiliser un système d'IA à haut risque ?",
    "Qui doit démontrer le caractère infondé ou excessif de la demande 6 ?",
    "Quelles actions sont autorisés à effectuer des agents liés à qui une entreprise d'investissement fait appel ?",
    "Quelles conditions remplit un représentant d'un État membre du comité IA ?",
    "Que doit au moins indiquer l'alerte qualifiée ?",
    "Dans quel cas l'obligation de fournir des informations sur les sanctions et mesures imposées ne s'applique pas ?",
    "A qui les organisme d'évaluation de la conformité doivent-ils soumettre une demande de notification ?",
    "Quelle est la période maximale de conservation des données à caractère personnel du paragraphe 1 ?",
    "Quelles sont les parties prenantes du forum consultatif ?",
    "À quelles exigences sont soumises les entreprises d'investissement qui exécutent des ordres de clients ?",
    "À quelles exigences est soumis un marché réglementé qui suspend la négociation dans tout État membre ?",
    "Que précise exactement un agrément ?",
]

FAUX_NOMS = ("Halvorsen Trust", "Peregrin Holding", "Vantorre Partners",
             "Osmund Federated", "Larspeak Mutual", "Kettlewell Group")
FAUX_LIEUX = ("Sarrebruck", "Ostrava", "Trondheim", "Valladolid",
              "Szczecin", "Tarragone")


def construire_jeu(reference_banque, documents_eurlex, par_classe=40,
                   graine=20260902):
    """Construit le jeu etiquete. Le label depend de l'endroit ou est la reponse.

    Renvoie une liste de cas
    {requete, classe, issue_attendue, enrichissement_possible, appui}.
    `appui` indique sur quel fait repose le label, pour qu'un relecteur
    puisse verifier un cas sans rejouer la campagne.
    """
    alea = random.Random(graine)
    clients = _champs_par_client(reference_banque)
    cles = sorted(clients)
    sujets = _sujets_eurlex(documents_eurlex)
    cas = []

    # --- classe interne : la reponse est un champ d'une note du corpus ------
    tirage = alea.sample(cles, min(par_classe, len(cles)))
    for rang, cle in enumerate(tirage):
        champs = clients[cle]
        gabarit, requis = GABARITS_INTERNES[rang % len(GABARITS_INTERNES)]
        if not all(champs.get(c) for c in requis):
            continue
        valeurs = dict(champs)
        valeurs["cli"] = cle
        try:
            requete = gabarit.format(**valeurs)
        except KeyError:
            continue
        cas.append({
            "requete": requete,
            "classe": INTERNE,
            "issue_attendue": ISSUE_ATTENDUE[INTERNE],
            "enrichissement_possible": True,
            "appui": f"champs {sorted(requis)} du dossier {cle}",
        })

    # --- classe externe : la reponse est dans EUR-Lex, jamais en interne ----
    if sujets:
        for rang in range(par_classe):
            reglement, numero = sujets[alea.randrange(len(sujets))]
            gabarit = GABARITS_EXTERNES[rang % len(GABARITS_EXTERNES)]
            cas.append({
                "requete": gabarit.format(numero=numero, reglement=reglement),
                "classe": EXTERNE,
                "issue_attendue": ISSUE_ATTENDUE[EXTERNE],
                "enrichissement_possible": True,
                "appui": f"article {numero} du texte {reglement}, "
                         f"present dans EUR-Lex et absent du corpus interne",
            })

    # --- classe absente : la reponse n'est nulle part -----------------------
    for rang in range(par_classe):
        gabarit = GABARITS_ABSENTS[rang % len(GABARITS_ABSENTS)]
        cas.append({
            "requete": gabarit.format(
                faux=FAUX_NOMS[rang % len(FAUX_NOMS)],
                lieu=FAUX_LIEUX[(rang // 2) % len(FAUX_LIEUX)]),
            "classe": ABSENTE,
            "issue_attendue": ISSUE_ATTENDUE[ABSENTE],
            "enrichissement_possible": True,
            "appui": "entites fabriquees, absentes des deux corpus",
        })

    # --- classes difficiles : decrire au lieu de nommer ---------------------
    # Limitees au nombre de gabarits distincts. Les repeter pour atteindre
    # `par_classe` ajouterait des cas sans rien apprendre de plus.
    for rang in range(min(par_classe, len(GABARITS_INTERNES_DECRITS))):
        cas.append({
            "requete": GABARITS_INTERNES_DECRITS[
                rang % len(GABARITS_INTERNES_DECRITS)],
            "classe": INTERNE_DECRIT,
            "issue_attendue": ISSUE_ATTENDUE[INTERNE_DECRIT],
            "enrichissement_possible": True,
            "appui": "fait present dans les notes du corpus interne, "
                     "interroge sans nommer aucun dossier",
        })
    for rang in range(min(par_classe, len(GABARITS_EXTERNES_IMPLICITES))):
        cas.append({
            "requete": GABARITS_EXTERNES_IMPLICITES[
                rang % len(GABARITS_EXTERNES_IMPLICITES)],
            "classe": EXTERNE_IMPLICITE,
            "issue_attendue": ISSUE_ATTENDUE[EXTERNE_IMPLICITE],
            "enrichissement_possible": True,
            "appui": "obligation reglementaire couverte par EUR-Lex, "
                     "texte applicable non nomme dans la requete",
        })

    # --- classe interdite : memes requetes externes, sortie fermee ----------
    # C'est le seul cas ou le code actuel s'abstient.
    externes = [c for c in cas if c["classe"] == EXTERNE]
    for source in externes[:par_classe]:
        cas.append({
            "requete": source["requete"],
            "classe": INTERDIT,
            "issue_attendue": ISSUE_ATTENDUE[INTERDIT],
            "enrichissement_possible": False,
            "appui": "meme requete que la classe externe, enrichissement "
                     "ferme par la politique de deploiement",
        })

    return cas


# ------------------------------------------------- l'evaluateur de couverture

class EvaluateurCouverture:
    """Juge la couverture interne a partir d'une vraie recherche BM25.

    Il ne connait ni les classes ni les labels. Il ne voit que la requete et
    ce que l'index interne renvoie.

    Il calcule les deux valeurs attendues par `Routeur.juger` :

      pertinence  part des jetons designants de la requete (noms propres et
                  identifiants, voir `jetons_designants`) presents dans les
                  fragments rapportes. Ce sont eux qui comptent, car une
                  requete porte sur ce qu'elle nomme.

      completude  part des autres jetons de contenu, connus du corpus
                  interne, presents dans les fragments. On ne garde que les
                  mots du corpus : un mot que les notes n'emploient jamais ne
                  peut pas etre retrouve en interne. Le compter melangerait
                  « le corpus n'utilise pas ce mot » et « le corpus n'a pas
                  ce contenu ».

    Si un jeton designant n'est pas dans l'index, aucun fragment ne le
    contient et la pertinence baisse. C'est le signal cherche : la requete
    porte sur quelque chose que le corpus interne ne contient pas.
    """

    def __init__(self, index, n=5):
        self.index = index
        self.n = n
        self._df = None
        self.dernier_appui = []

    def _frequences(self):
        """Frequence documentaire de chaque jeton du corpus interne."""
        if self._df is None:
            df = {}
            for doc in self.index.documents:
                for jeton in set(mod_lexical.jetons(doc.get("text", ""),
                                                    self.index.langue)):
                    df[jeton] = df.get(jeton, 0) + 1
            self._df = df
        return self._df

    def __call__(self, requete, fragments):
        df = self._frequences()
        uniques = sorted(set(mod_lexical.jetons(requete, self.index.langue)))
        if not uniques:
            return mod_routeur.Jugement(etat="", pertinence=0.0,
                                        completude=0.0,
                                        motif="requete vide")

        rapportes = fragments
        if rapportes is None:
            rapportes = [d for d, _ in self.index.rechercher(
                requete, n=self.n, source="interne")]
        self.dernier_appui = [d.get("doc_id") for d in rapportes]

        couvert = set()
        for doc in rapportes:
            couvert |= set(mod_lexical.jetons(doc.get("text", ""),
                                              self.index.langue))

        designants = [j for j in jetons_designants(requete, self.index.langue)
                      if j in uniques]
        # Une requete qui ne nomme rien ne peut pas etre jugee sur ce qu'elle
        # nomme. J'utilise alors tous ses jetons. Renvoyer 1,0 par defaut la
        # ferait passer pour couverte.
        base = designants or uniques
        pertinence = sum(1 for j in base if j in couvert) / len(base)

        connus = [j for j in uniques if df.get(j, 0) > 0 and j not in designants]
        if connus:
            completude = sum(1 for j in connus if j in couvert) / len(connus)
        else:
            completude = pertinence

        # Part des mots de la requete que le corpus interne connait, tous
        # jetons compris. C'est la seule des trois valeurs qui separe une
        # question descriptive a reponse interne d'une question
        # reglementaire : la premiere utilise les mots des notes, la seconde
        # d'autres mots. La pertinence ne sert a rien sans jeton designant, et
        # la completude ne compte pas les mots inconnus du corpus.
        vocabulaire = sum(1 for j in uniques if df.get(j, 0) > 0) / len(uniques)

        return mod_routeur.Jugement(
            etat="", pertinence=pertinence, completude=completude,
            motif=f"{len(designants)} jetons designants, "
                  f"{len(connus)} jetons de contenu connus du corpus, "
                  f"vocabulaire connu {vocabulaire:.3f}",
            designants=len(designants),
            couverture_vocabulaire=round(vocabulaire, 4),
        )


# ----------------------------------------------------------------- campagne

def router_jusqu_au_bout(routeur_initial, evaluateur, cas, index,
                         seuil_pertinence, seuil_completude):
    """Deroule le routage d'une requete, correction comprise.

    CORRIGER ne termine pas le routage : cela demande de refaire la recherche
    interne avant de conclure. Si on comparait la premiere decision a la
    verite terrain, un routage qui finit bien serait compte comme une erreur.
    Je rejoue donc une fois avec `deja_corrige` et je garde l'issue finale.
    Je note aussi le passage par la correction, qui a un cout.
    """
    requete = cas["requete"]
    fragments = [d for d, _ in index.rechercher(requete, n=evaluateur.n,
                                                source="interne")]
    decision = routeur_initial.decider(
        requete, fragments,
        enrichissement_possible=cas["enrichissement_possible"])

    corrige = False
    if decision.issue == mod_routeur.CORRIGER:
        corrige = True
        # La correction rapporte plus de resultats. Sans index dense, c'est
        # la seule facon de refaire la recherche interne ici. Je ne simule
        # pas de gain qui n'existe pas.
        # `apres_correction` reprend tous les seuils du routeur initial, y
        # compris celui du vocabulaire. Les recopier ici a la main risquerait
        # d'en oublier un sans le voir.
        second = routeur_initial.apres_correction()
        fragments = [d for d, _ in index.rechercher(
            requete, n=evaluateur.n * 4, source="interne")]
        decision = second.decider(
            requete, fragments,
            enrichissement_possible=cas["enrichissement_possible"])

    return decision, corrige


def campagne(cas, index, seuil_pertinence=0.55, seuil_completude=0.70, n=5,
             seuil_vocabulaire=None):
    """Route tout le jeu et calcule les trois mesures.

    Avec `seuil_vocabulaire` a None, on retrouve exactement la campagne
    d'origine.
    """
    evaluateur = EvaluateurCouverture(index, n=n)
    routeur = mod_routeur.Routeur(evaluateur, seuil_pertinence,
                                  seuil_completude,
                                  seuil_vocabulaire=seuil_vocabulaire)

    details = []
    for entree in cas:
        decision, corrige = router_jusqu_au_bout(
            routeur, evaluateur, entree, index,
            seuil_pertinence, seuil_completude)
        details.append({
            "requete": entree["requete"],
            "classe": entree["classe"],
            "issue_attendue": entree["issue_attendue"],
            "issue_obtenue": decision.issue,
            "correcte": decision.issue == entree["issue_attendue"],
            "passe_par_correction": corrige,
            "pertinence": round(decision.jugement.pertinence, 4),
            "completude": round(decision.jugement.completude, 4),
            "etat": decision.jugement.etat,
            "motif": decision.motif,
            "appui": entree["appui"],
        })

    return {
        "cas": len(details),
        "seuils": {"pertinence": seuil_pertinence,
                   "completude": seuil_completude, "fragments": n,
                   "vocabulaire": seuil_vocabulaire},
        "mesures": mesurer(details),
        "details": details,
        "lecture": (
            "Le taux de franchissement injustifie est la mesure principale : "
            "chaque cas est une requete envoyee a l'exterieur alors que le "
            "corpus interne suffisait, donc une exposition inutile. Le "
            "franchissement manque est une autre erreur, qui donne une moins "
            "bonne reponse sans rien exposer. Les deux restent separes. Le "
            "label d'un cas depend de l'endroit ou se trouve vraiment la "
            "reponse, et l'evaluateur de couverture ne le voit jamais."
        ),
    }


def mesurer(details):
    """Les trois mesures, plus la matrice des issues."""
    total = len(details)
    if not total:
        return {}

    def part(condition, sur=None):
        population = [d for d in details if sur(d)] if sur else details
        if not population:
            return None
        return round(sum(1 for d in population if condition(d))
                     / len(population), 4)

    sortants = (mod_routeur.ENRICHIR, mod_routeur.ESCALADER)
    # Les classes sont regroupees selon la verite terrain : une requete
    # interne reste interne, qu'elle nomme son dossier ou qu'elle le decrive.
    doit_rester = (INTERNE, INTERNE_DECRIT)
    doit_sortir = (EXTERNE, EXTERNE_IMPLICITE)

    matrice = {}
    for d in details:
        cle = f"{d['classe']} -> {d['issue_obtenue']}"
        matrice[cle] = matrice.get(cle, 0) + 1

    par_classe = {}
    for classe in (INTERNE, INTERNE_DECRIT, EXTERNE, EXTERNE_IMPLICITE,
                   ABSENTE, INTERDIT):
        population = [d for d in details if d["classe"] == classe]
        if population:
            par_classe[classe] = {
                "cas": len(population),
                "taux_correct": round(
                    sum(1 for d in population if d["correcte"])
                    / len(population), 4),
            }

    return {
        "taux_decision_correcte": part(lambda d: d["correcte"]),
        # Mesure principale : sortie alors que l'interne suffisait.
        "taux_franchissement_injustifie": part(
            lambda d: d["issue_obtenue"] in sortants,
            sur=lambda d: d["classe"] in doit_rester),
        # Erreur inverse : rester en interne alors qu'il fallait sortir. La
        # reponse est moins bonne, mais rien n'est expose.
        "taux_franchissement_manque": part(
            lambda d: d["issue_obtenue"] not in sortants,
            sur=lambda d: d["classe"] in doit_sortir),
        # Les deux memes mesures, seulement sur les requetes qui decrivent
        # sans nommer. C'est la que le routage est vraiment mis a l'epreuve.
        "franchissement_injustifie_sur_decrit": part(
            lambda d: d["issue_obtenue"] in sortants,
            sur=lambda d: d["classe"] == INTERNE_DECRIT),
        "franchissement_manque_sur_implicite": part(
            lambda d: d["issue_obtenue"] not in sortants,
            sur=lambda d: d["classe"] == EXTERNE_IMPLICITE),
        "taux_abstention_correcte": part(
            lambda d: d["issue_obtenue"] == mod_routeur.ABSTENIR,
            sur=lambda d: d["classe"] == INTERDIT),
        "taux_abstention_indue": part(
            lambda d: d["issue_obtenue"] == mod_routeur.ABSTENIR,
            sur=lambda d: d["classe"] != INTERDIT),
        "part_passee_par_correction": part(
            lambda d: d["passe_par_correction"]),
        "sorties_infructueuses": part(
            lambda d: d["issue_obtenue"] in sortants,
            sur=lambda d: d["classe"] == ABSENTE),
        "par_classe": par_classe,
        "matrice": dict(sorted(matrice.items())),
    }
