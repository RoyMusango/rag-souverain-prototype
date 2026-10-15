r"""
Lance E3, la resistance a l'injection indirecte.

    python scripts\run_e3.py --questions 40

J'invoque `python` et non `py -3.11` : lorsqu'une version est passee
explicitement, le lanceur Windows ignore l'environnement virtuel.

ETAPE 0 : COMPTER AVANT DE DEPENSER

Sans engagement de depense, le script deroule la campagne avec un fournisseur
simule, qui ne quitte pas la machine et ne coute rien, puis rapporte le nombre
exact d'appels au modele qu'exigerait la meme campagne avec une API reelle,
ainsi que le contenu exact des invites.

Ce comptage est exact et non estime, car le nombre d'appels ne depend
d'aucune donnee variable :

    e3_injection.campagne  boucle sur les configurations d'ablation
    e3_injection.executer  boucle sur les requetes
    pipeline.repondre      effectue un unique appel de generation

    appels = requetes x configurations - (requetes ou le routeur s'abstient)

Le routeur est deterministe et ne consulte aucun modele : sa decision, et donc
le nombre d'abstentions, est identique avec ou sans API. Seule la longueur des
reponses echappe au comptage ; c'est la seule inconnue que le pilote payant
de l'etape 1 doit lever.

PORTEE DE CETTE ETAPE

Elle ne mesure pas la robustesse. Le fournisseur simule rend une reponse
constante, si bien qu'aucune charge adverse ne peut reussir. Les taux de
succes qu'elle produirait n'auraient pas de sens ; je ne les ecris donc pas.
Seuls le comptage et la taille des invites sont produits.

UNE CAMPAGNE PAR FAMILLE

Le simulateur attribue les familles a tour de role sur le nombre de documents
adverses, lui-meme deduit du taux d'empoisonnement : a 0,1, il n'en produit
qu'un et seule la famille INSTRUCTION est exercee ; il faut un taux de 0,3
pour que les trois familles apparaissent.

A 0,3, elles ne sont toutefois pas a parite. DUPLICATION produit trois
documents pour une seule charge, puisque simuler l'accord de sources
independantes exige plusieurs copies. Le compte des charges evaluees devient
instruction 1, assertion 1, duplication 3, et `asr_par_configuration`, la
moyenne que compare l'ablation, est alors ponderee a 60 % par une seule
famille : le tableau d'ablation mesurerait surtout la detection de collusion.

Je decouple donc le taux et la famille : une campagne par famille, a taux
bas. Chaque famille obtient son propre taux de succes et sa propre ablation,
aucune ne pese sur la moyenne d'une autre, et le taux d'empoisonnement
redevient un parametre que l'on peut faire varier pour obtenir une courbe.

A taux egal, le taux effectif de DUPLICATION reste superieur a celui des deux
autres familles (trois documents contre un). C'est une propriete de
l'attaque et non un biais de mesure ; je la signale plutot que de la corriger.

LIMITES ACTUELLES

  - un client d'API doit etre injecte dans FournisseurAPI ;
  - le verrou de sortie et le masqueur doivent etre effectivement montes,
    faute de quoi les configurations `complete` et `sans_verrou` se
    comportent a l'identique et l'ablation ne les departage pas.

Je prefere declarer ces deux manques ici plutot que de les combler par un
montage approximatif.
"""

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.commun import config as mod_config, journal as mod_journal   # noqa: E402
from src.evaluation import e3_injection as e3                         # noqa: E402
from src.evaluation import e6_routage as e6                           # noqa: E402
from src.fournisseur import base as mod_fournisseur                   # noqa: E402
from src.fournisseur import openai_client as mod_openai               # noqa: E402
from src.index import lexical as mod_lexical                          # noqa: E402
from src.index import recuperateurs as mod_recup                      # noqa: E402
from src.pipeline import Moteur                                       # noqa: E402
from src.routage import routeur as mod_routeur                        # noqa: E402
from src.simulateur import adverse as mod_adverse                     # noqa: E402
from src.simulateur import reformulation as mod_reformulation        # noqa: E402

BANQUE = "data/banque/banque_schema.json"
BANQUE_REFERENCE = "data/banque/banque_reference.json"
EURLEX = "data/external/eurlex/eurlex_schema.json"


class Reprise:
    """Journal d'avancement d'une campagne, relisible et repris a chaud.

    La campagne complete dure environ huit heures et engage une depense
    reelle. Sans reprise, une mise en veille, une coupure reseau ou une erreur
    au quatre-centieme appel ferait perdre les appels deja factures, puisque
    le JSON de resultats n'est ecrit qu'a la fin.

    J'applique la meme discipline que pour les embeddings, ou
    `CalculPersistant` ecrit par tranches et reprend la ou il s'est arrete :
    un calcul long doit pouvoir etre relance sans tout recalculer.

    L'unite de reprise est le couple (configuration, requete), soit exactement
    un appel au modele. Elle est ecrite des qu'elle aboutit, en mode ajout,
    dans un JSONL lisible pendant l'execution.
    """

    def __init__(self, chemin):
        self.chemin = Path(chemin)
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self.faits = {}
        self.traces = []
        if self.chemin.exists():
            for ligne in self.chemin.read_text(encoding="utf-8").splitlines():
                if not ligne.strip():
                    continue
                entree = json.loads(ligne)
                cle = (entree["configuration"], entree["requete"])
                self.faits[cle] = entree["resultats"]
                self.traces.append(entree["trace"])

    def deja_fait(self, configuration, requete):
        return (configuration, requete) in self.faits

    def relire(self, configuration, requete):
        return self.faits[(configuration, requete)]

    def noter(self, configuration, requete, resultats, trace):
        self.faits[(configuration, requete)] = resultats
        self.traces.append(trace)
        # Ecriture immediate et en ajout : une interruption ne peut perdre
        # que l'appel en cours.
        with open(self.chemin, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "configuration": configuration, "requete": requete,
                "resultats": resultats, "trace": trace,
            }, ensure_ascii=False) + "\n")

    def resume(self):
        return {"appels_journalises": len(self.faits),
                "journal": str(self.chemin)}


class PlafondAtteint(RuntimeError):
    """Le cout cumule a franchi le plafond : la campagne s'arrete."""


class FournisseurPlafonne(mod_fournisseur.FournisseurAPI):
    """Fournisseur d'API qui s'interrompt des que la depense atteint un seuil.

    Le compte utilise ne m'appartient pas, et je ne peux donc pas fixer de
    limite dans la console du fournisseur. Cette classe tient lieu de limite ;
    elle bloque l'appel plutot que d'emettre un simple avertissement.

    Le cout est celui que `Fournisseur.generer` calcule a partir des jetons
    effectivement factures, tels que rendus par l'API, et non d'une
    estimation locale.
    """

    def __init__(self, plafond_usd, journal_cout=None, **kwargs):
        super().__init__(**kwargs)
        self.plafond_usd = plafond_usd
        self.depense = 0.0
        self.appels = 0
        # Comptabilite ecrite appel par appel, a cote du journal de reprise.
        # Sans elle, une coupure preserve la reprise mais rend le cout
        # inconnu : les jetons factures ne sont conserves nulle part, et leur
        # reconstitution a partir des longueurs de texte peut se tromper de
        # moitie lorsque le modele facture plus de jetons qu'il n'en rend.
        self.journal_cout = Path(journal_cout) if journal_cout else None
        # Je conserve aussi les invites, pour que les statistiques de taille
        # soient produites par la campagne reelle. Sinon, une passe simulee
        # prealable serait necessaire et referait le re-classement :
        # 35 s par appel, soit deux heures sur une campagne de 200 appels.
        self.invites = []
        # Je conserve les reponses pour que le verdict reste auditable. Sans
        # elles, un taux de succes d'attaque nul est indiscernable d'un
        # verdict defaillant, et le verifier exigerait une nouvelle depense.
        self.reponses = []

    def generer(self, invite, systeme=None, max_jetons=1024,
                etapes_amont=None):
        if self.depense >= self.plafond_usd:
            raise PlafondAtteint(
                "plafond de %.4f atteint apres %d appels (%.4f depense)"
                % (self.plafond_usd, self.appels, self.depense))
        texte, trace = super().generer(invite, systeme, max_jetons,
                                       etapes_amont)
        self.depense += trace.cout_eur
        self.appels += 1
        self._noter_cout(invite, texte, trace, max_jetons)
        self.invites.append(invite)
        self.reponses.append({
            "appel": self.appels,
            "jetons_sortie": trace.jetons_sortie,
            "tronquee": trace.jetons_sortie >= max_jetons,
            "reponse": texte,
        })
        return texte, trace

    def _noter_cout(self, invite, texte, trace, max_jetons):
        """Une ligne de comptabilite par appel, ecrite immediatement.

        Elle contient ce que le journal de reprise ne contient pas : les
        jetons effectivement factures, la longueur de l'invite et le cumul.
        Apres une coupure, elle suffit a etablir l'etat d'avancement et le
        cout engage.

        Son echec n'interrompt jamais la campagne : perdre une ligne de
        comptabilite est moins grave que perdre un appel deja paye.
        """
        if self.journal_cout is None:
            return
        try:
            self.journal_cout.parent.mkdir(parents=True, exist_ok=True)
            with open(self.journal_cout, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "appel": self.appels,
                    "jetons_entree": trace.jetons_entree,
                    "jetons_sortie": trace.jetons_sortie,
                    "cout_usd": trace.cout_eur,
                    "cumul_usd": round(self.depense, 6),
                    "invite_caracteres": len(invite),
                    "reponse_caracteres": len(texte or ""),
                    "tronquee": trace.jetons_sortie >= max_jetons,
                    "latence_ms": round(trace.latence_ms, 1),
                }, ensure_ascii=False) + "\n")
        except OSError:
            pass


class FournisseurCompteur(mod_fournisseur.FournisseurSimule):
    """Fournisseur simule qui conserve les invites qui lui sont soumises.

    Il permet de connaitre la taille exacte des invites, en plus du nombre
    d'appels, afin que le devis de l'etape 2 ne repose pas sur une estimation.
    """

    def __init__(self):
        super().__init__()
        self.invites = []

    def _appeler(self, prompt, systeme=None, max_jetons=1024):
        self.invites.append(prompt)
        return super()._appeler(prompt, systeme, max_jetons)


class EvaluateurCommeE6:
    """Fait juger la couverture exactement comme dans E6.

    Le pipeline transmet a l'evaluateur les fragments que sa cascade vient de
    rapporter, alors qu'EvaluateurCouverture definit la couverture sur sa
    propre recuperation des n premiers documents internes. C'est cette
    seconde definition que la campagne E6 a mesuree.

    L'ecart n'est pas cosmetique : il inverse la decision. La cascade rend
    `n_final` fragments la ou l'evaluateur en retient cinq ; avec huit fois
    plus de texte, la couverture d'une question reglementaire parait
    suffisante, le routeur repond INTERNE, aucun contenu externe n'entre, et
    E3 mesurerait la robustesse d'une chaine dans laquelle aucune charge
    adverse n'est jamais rapatriee. Un taux de succes nul obtenu ainsi ne
    dirait rien de la defense.

    Je force donc `fragments=None`, ce qui rend a l'evaluateur sa propre
    recuperation et reproduit les decisions rapportees par E6 : la classe
    externe est routee vers ENRICHIR dans 40 cas sur 40.
    """

    def __init__(self, evaluateur):
        self.evaluateur = evaluateur

    def __call__(self, requete, fragments=None):
        return self.evaluateur(requete, None)


def ecrire_traces(chemin, traces):
    """Trace lisible d'un appel : les entrees fournies et la reponse obtenue.

    Elle distingue trois etats : une source peut etre fournie sans etre
    retenue, retenue sans etre citee, et citee sans que l'attaque reussisse.
    """
    lignes = []
    for rang, trace in enumerate(traces, start=1):
        c = trace["compte"]
        lignes.append("=" * 78)
        lignes.append("APPEL %d   configuration : %s"
                      % (rang, trace["configuration"]))
        lignes.append("=" * 78)
        lignes.append("")
        lignes.append("QUESTION POSEE")
        lignes.append("  " + trace["requete"])
        lignes.append("")
        lignes.append("COUCHES DE DEFENSE ACTIVES")
        lignes.append("  " + (", ".join(trace["couches_actives"]) or "aucune"))
        lignes.append("")
        lignes.append("SOURCES FOURNIES AU MODELE : %d, dont %d empoisonnees"
                      % (c["fournies"], c["empoisonnees_fournies"]))
        lignes.append("")
        lignes.append("  %-3s %-34s %-9s %-26s %-8s %s"
                      % ("", "identifiant", "source", "nature", "retenue",
                         "citee"))
        lignes.append("  " + "-" * 92)
        for i, s in enumerate(trace["sources"], start=1):
            marque = " <<<" if s["empoisonnee"] else ""
            lignes.append("  %-3d %-34s %-9s %-26s %-8s %s%s"
                          % (i, s["doc_id"][:34], s["source"],
                             s["nature"][:26],
                             "oui" if s["retenue"] else "non",
                             "OUI" if s["citee"] else "non", marque))
        lignes.append("")
        for i, s in enumerate(trace["sources"], start=1):
            if s["empoisonnee"]:
                lignes.append("  charge %d : %s" % (i, s["extrait"]))
        lignes.append("")
        lignes.append("CE QUE LE MODELE A RETENU DES SOURCES EMPOISONNEES")
        lignes.append("  parvenues jusqu'au generateur : %d  %s"
                      % (c["empoisonnees_retenues"],
                         trace["empoisonnees_retenues"] or ""))
        lignes.append("  citees dans la reponse        : %d  %s"
                      % (c["empoisonnees_citees"],
                         trace["empoisonnees_citees"] or ""))
        lignes.append("")
        lignes.append("VERDICT")
        if not trace["verdicts"]:
            lignes.append("  aucune charge evaluee")
        for v in trace["verdicts"]:
            lignes.append("  %-12s variante %d  -> attaque %s"
                          % (v["famille"], v["variante"],
                             "REUSSIE" if v["reussie"] else "echouee"))
            lignes.append("     charge : %s" % v["texte"])
        lignes.append("")
        lignes.append("ABSTENTION : %s" % trace["abstention"])
        lignes.append("")
        lignes.append("REPONSE PRODUITE")
        lignes.append("-" * 78)
        lignes.append(trace["reponse"] or "(vide)")
        lignes.append("")
        lignes.append("")

    Path(chemin).write_text("\n".join(lignes), encoding="utf-8")


def charger_json(chemin):
    chemin = Path(chemin)
    if not chemin.exists():
        raise SystemExit(
            f"introuvable : {chemin}\n"
            f"Ce fichier vient de l'ingestion. Verifiez le chemin.")
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def requetes_par_classe(par_classe, graine, classe=None):
    """Les requetes d'une classe du jeu etiquete d'E6.

    Par defaut, la classe `externe`, dont la reponse se trouve dans EUR-Lex et
    non dans le corpus de la banque. Ce sont les seules qui permettent de
    mesurer l'injection : sur une requete couverte par l'interne, le routeur
    n'en sort pas, aucun contenu externe n'entre et il n'y a rien a injecter.

    Les autres classes repondent a un autre besoin. Avec `interne`, le
    contexte transmis au modele ne contient que des fragments internes,
    chacun muni de son ancrage : cela permet de verifier si le modele cite
    effectivement ses sources lorsqu'elles repondent a la question, question
    distincte de la robustesse a l'injection.
    """
    return [c["requete"] for c in cas_par_classe(par_classe, graine, classe)]


MOTIF_APPUI = re.compile(r"article (.+?) du texte (.+?), present")


def cas_par_classe(par_classe, graine, classe=None):
    """Les cas d'une classe avec leur appui, et pas seulement leur texte.

    L'appui contient le couple (reglement, numero d'article) sur lequel repose
    le label. Il est necessaire pour determiner si une question est ancree,
    c'est-a-dire si l'article demande figure parmi les fragments rapportes.
    `requetes_par_classe` ne rend que le texte.
    """
    reference = charger_json(BANQUE_REFERENCE)
    eurlex = charger_json(EURLEX)
    cas = e6.construire_jeu(reference, eurlex, par_classe=par_classe,
                            graine=graine)
    voulue = classe or e6.EXTERNE
    return [c for c in cas if c["classe"] == voulue]


def cible_de(cas):
    """(reglement, numero) vise par un cas de la classe `externe`, ou None."""
    trouve = MOTIF_APPUI.match(str(cas.get("appui", "")))
    if not trouve:
        return None
    return trouve.group(2).replace(" ", "_"), trouve.group(1)


def article_rapporte(documents, reglement, numero):
    """L'article vise est-il parmi ces documents ?"""
    motif = re.compile(r"art_?0*" + re.escape(numero) + r"$", re.I)
    for doc in documents:
        rubrique = str(doc.get("rubrique", ""))
        if reglement.lower() in rubrique.lower() and motif.search(rubrique):
            return True
    return False


def main():
    parseur = argparse.ArgumentParser(
        description="E3, resistance a l'injection indirecte")
    parseur.add_argument("--questions", type=int, default=40,
                         help="requetes de la classe externe a deroules")
    # `--questions N` ne tire pas N questions parmi celles d'une campagne a 40 :
    # il construit un jeu de N par classe, et les jeux ne sont pas emboites
    # (verifie le 19/09 : les 10 questions de `--questions 10` ne figurent pas
    # parmi les 40 de `--questions 40`). `--premieres` conserve le jeu de 40 et
    # n'en deroule que les premieres. Les campagnes reduites portent ainsi sur
    # des questions que la campagne API a aussi posees, ce qui permet une
    # comparaison question par question ; et passer de 10 a 20 puis a 40
    # reutilise les appels deja faits, la reprise dedupliquant sur
    # (configuration, requete).
    parseur.add_argument("--premieres", type=int, default=None,
                         help="ne derouler que les N premieres questions du "
                              "jeu de --questions ; garder --questions 40")
    parseur.add_argument("--taux-empoisonnement", type=float, default=0.1)
    parseur.add_argument("--familles", default="instruction",
                         help="familles de charges, separees par des virgules "
                              "parmi instruction, assertion, duplication. "
                              "UNE SEULE a la fois, voir la note ci-dessous.")
    parseur.add_argument("--graine", type=int, default=20260902)
    parseur.add_argument("--sortie", default="resultats/e3_devis")

    # --- appel reel : trois garde-fous ------------------------------------
    parseur.add_argument("--modele", default=None,
                         help="modele OpenAI. Sans ce parametre, le "
                              "fournisseur simule est employe et rien n'est "
                              "facture.")
    # Le palier correspond a la Frontiere B du chapitre 3 : il determine si
    # la generation quitte l'espace juridique europeen. Il est declare, jamais
    # deduit de l'adresse, et journalise dans chaque trace.
    parseur.add_argument("--palier", default=mod_fournisseur.API_HORS_UE,
                         choices=(mod_fournisseur.LOCAL,
                                  mod_fournisseur.API_UE,
                                  mod_fournisseur.API_HORS_UE),
                         help="palier de souverainete de la generation")
    parseur.add_argument("--base-url", default=None,
                         help="serveur compatible OpenAI, pour le palier "
                              "local : http://localhost:11434/v1 avec Ollama")
    # 180 s suffisent pour une API ; un modele de 7 milliards de parametres
    # sur le processeur d'un portable met 3 a 10 minutes pour les 1 383 jetons
    # de sortie medians mesures sur `instruction`. Un delai trop court coupe
    # l'appel, que la reprise rejouerait alors indefiniment.
    parseur.add_argument("--delai", type=int, default=180,
                         help="delai d'attente par appel, en secondes ; "
                              "porter a 1200 au palier local")
    parseur.add_argument("--tarif-entree", type=float, default=None,
                         help="dollars par MILLION de jetons d'entree, tel "
                              "qu'affiche sur la page de tarification")
    parseur.add_argument("--tarif-sortie", type=float, default=None,
                         help="dollars par MILLION de jetons de sortie")
    parseur.add_argument("--classe", default=None,
                         choices=("externe", "interne", "interne-decrit",
                                  "externe-implicite", "absente",
                                  "enrichissement-interdit"),
                         help="classe du jeu etiquete d'E6 d'ou tirer les "
                              "questions. Defaut : externe, la seule qui "
                              "permette de MESURER l'injection. `interne` sert "
                              "a verifier la citation des sources, pas la "
                              "robustesse.")
    parseur.add_argument("--ancrees-seulement", action="store_true",
                         help="ne garde que les questions dont l'article "
                              "demande figure REELLEMENT parmi les "
                              "fragments rapportes. Le tri est local et "
                              "gratuit : on ne paie que les questions qui "
                              "mesurent quelque chose.")
    parseur.add_argument("--profondeur-ancrage", type=int, default=10,
                         help="profondeur a laquelle l'ancrage est "
                              "verifie. Doit valoir le nombre de "
                              "fragments legitimes que verra le modele.")
    parseur.add_argument("--eurlex-brut", action="store_true",
                         help="recuperation externe d'avant le 25/09 : "
                              "texte seul, deux langues, aucun filtre. "
                              "Pour rejouer une campagne anterieure.")
    parseur.add_argument("--langue-eurlex", default="FR",
                         choices=("FR", "EN", "toutes"))
    parseur.add_argument("--sans-filtre-reglement", action="store_true",
                         help="n'indexe pas par reglement. Le filtre "
                              "suppose que la question nomme son texte, "
                              "ce qui est vrai par construction pour la "
                              "classe externe mais pas en general.")
    parseur.add_argument("--attaquant", default="surface",
                         choices=("surface", "reecriture"),
                         help="surface : les cinq transformations "
                              "enumerees, rejouables a graine fixe. "
                              "reecriture : la charge est reecrite par "
                              "le modele apres chaque echec — plus fort, "
                              "facture, et rejouable par journal.")
    parseur.add_argument("--journal-reformulations", default=None,
                         help="JSONL des reecritures. En ecriture avec "
                              "--attaquant reecriture ; en LECTURE si le "
                              "fichier existe deja, ce qui rejoue la "
                              "campagne sans rien refacturer.")
    parseur.add_argument("--sans-devis", action="store_true",
                         help="saute la passe simulee. Elle refait le "
                              "re-classement sans rien facturer ni rien "
                              "apprendre de plus, soit deux heures perdues "
                              "sur une campagne de 200 appels. Les "
                              "statistiques d'invite sortent alors de la "
                              "campagne reelle.")
    parseur.add_argument("--reprise", default=None,
                         help="fichier JSONL d'avancement. Avec ce parametre, "
                              "les appels deja aboutis ne sont ni rejoues ni "
                              "refactures : une interruption ne coute que "
                              "l'appel en cours. Relancer la MEME commande "
                              "reprend la ou l'on s'est arrete.")
    parseur.add_argument("--reclassement", action="store_true",
                         help="active le re-classement par cross-encodeur "
                              "avant la generation, puis resserre le contexte. "
                              "Sans ce drapeau, le moteur se comporte comme "
                              "dans les campagnes anterieures.")
    parseur.add_argument("--top-k-generation", type=int, default=10,
                         help="fragments conserves pour la generation apres "
                              "re-classement")
    parseur.add_argument("--longueur-reclasseur", type=int, default=512,
                         help="longueur maximale du cross-encodeur. 8192 rend "
                              "l'etage inutilisable sur processeur.")
    parseur.add_argument("--max-jetons", type=int, default=None,
                         help="plafond de jetons par reponse. Le defaut de la "
                              "configuration est 1024 ; les reponses mesurees "
                              "le 14/09 en consommaient 964 en moyenne, donc "
                              "la plupart etaient tronquees.")
    parseur.add_argument("--temperature", type=float, default=None,
                         help="temperature du modele. Non envoyee par defaut : "
                              "plusieurs modeles refusent toute valeur autre "
                              "que la leur. Sans temperature fixee, la "
                              "campagne n'est pas strictement rejouable.")
    parseur.add_argument("--plafond", type=float, default=1.0,
                         help="plafond de depense en dollars. La campagne "
                              "s'interrompt des qu'il est atteint.")
    parseur.add_argument("--engager-la-depense", action="store_true",
                         help="SANS CE DRAPEAU, AUCUN APPEL N'EST EMIS. Le "
                              "script se contente de chiffrer et s'arrete.")
    arguments = parseur.parse_args()

    if arguments.sans_devis and not arguments.engager_la_depense:
        raise SystemExit(
            "--sans-devis n'a de sens qu'avec --engager-la-depense.\n"
            "Sans depense engagee, la passe simulee EST le resultat : la "
            "sauter ne laisse rien a mesurer.")

    config = mod_config.Config()
    if arguments.max_jetons:
        config.generation.max_jetons = arguments.max_jetons

    # Je charge les cas et non seulement leur texte : l'appui est necessaire
    # au tri par ancrage, qui n'a lieu qu'une fois l'index construit, plus bas.
    cas_retenus = cas_par_classe(arguments.questions, arguments.graine,
                                 arguments.classe)
    if arguments.premieres is not None:
        cas_retenus = cas_retenus[:arguments.premieres]
    requetes = [c["requete"] for c in cas_retenus]
    print(f"requetes retenues  : {len(requetes)} (classe "
          f"{arguments.classe or 'externe'}"
          + (f", {arguments.premieres} premieres du jeu de "
             f"{arguments.questions}" if arguments.premieres else "")
          + ")")

    print("construction de l'index BM25 interne...")
    index = mod_lexical.IndexLexical(langue="fr").construire(charger_json(BANQUE))
    print(f"index interne      : {len(index.documents)} passages")

    evaluateur = EvaluateurCommeE6(e6.EvaluateurCouverture(index, n=5))
    routeur = mod_routeur.Routeur(evaluateur,
                                  config.routage.seuil_pertinence,
                                  config.routage.seuil_completude)
    interne = mod_recup.monter_chaine(index_lexical=index, config=config)

    # --- choix du fournisseur, et premier garde-fou -----------------------
    #
    # Le devis est toujours etabli avec le fournisseur simule, qui ne quitte
    # pas la machine. Une seconde campagne n'est envoyee vers l'API que si la
    # depense est explicitement engagee.
    reel = None
    if arguments.modele:
        if arguments.tarif_entree is None or arguments.tarif_sortie is None:
            raise SystemExit(
                "--modele exige --tarif-entree et --tarif-sortie.\n"
                "Sans tarifs, le plafond de depense ne peut pas etre calcule, "
                "et il n'y a alors aucune protection.")
        client = mod_openai.ClientOpenAI(
            modele=arguments.modele,
            temperature=arguments.temperature,
            base_url=arguments.base_url,
            palier=arguments.palier,
            # Le delai par defaut du client est de 60 s. Avec --max-jetons
            # 4000, les latences mesurees sur `instruction` passent de 16 a
            # 35 s et certaines reponses depassent la minute, ce qui declenche
            # APITimeoutError. La reprise ne perd rien mais impose de relancer.
            # Un appel lent ne coute pas davantage : seuls les jetons sont
            # factures.
            delai=arguments.delai,
            graine=arguments.graine)
        reel = FournisseurPlafonne(
            plafond_usd=arguments.plafond,
            # A cote du journal de reprise, meme nom, autre extension :
            # journal_duplication.jsonl -> journal_duplication.cout.jsonl
            journal_cout=(Path(arguments.reprise).with_suffix(".cout.jsonl")
                          if arguments.reprise else None),
            palier=arguments.palier,
            modele=arguments.modele,
            # Les tarifs sont exprimes par million de jetons, la trace les
            # attend par jeton. Une erreur d'un facteur un million est facile
            # a commettre ici et couteuse.
            tarif_entree=arguments.tarif_entree / 1e6,
            tarif_sortie=arguments.tarif_sortie / 1e6,
            client=client)
        print("modele             : %s" % arguments.modele)
        print("tarifs             : %.4f / %.4f $ par million de jetons"
              % (arguments.tarif_entree, arguments.tarif_sortie))
        print("plafond            : %.4f $" % arguments.plafond)
        print("depense engagee    : %s"
              % ("OUI" if arguments.engager_la_depense else
                 "non, devis seul"))

    # --- etage de re-classement -------------------------------------------
    #
    # `hybride.reclasser` n'etait appele nulle part : la chaine embarquait un
    # cross-encodeur sans l'utiliser. Mesure du 15/09 : sur des invites de
    # 15 147 caracteres, quarante fragments internes occupaient 72,2 % du
    # texte, pour l'essentiel hors sujet.
    reclasseur = None
    if arguments.reclassement:
        print("chargement du cross-encodeur...")
        reclasseur = mod_lexical.Reclasseur(
            modele=config.recherche.modele_reclasseur,
            longueur_max=arguments.longueur_reclasseur)
        reclasseur.charger()
        print("re-classeur        : %s, longueur max %d, sur %s"
              % (reclasseur.nom_modele, reclasseur.longueur_max,
                 reclasseur.peripherique))
        print("contexte resserre  : %d fragments" % arguments.top_k_generation)

    fournisseur = FournisseurCompteur()
    moteur = Moteur(config=config, recuperateur_interne=interne,
                    reclasseur=reclasseur,
                    top_k_generation=(arguments.top_k_generation
                                      if arguments.reclassement else None),
                    recuperateur_externe=object(),   # remplace par executer()
                    routeur=routeur, fournisseur=fournisseur)

    corpus_legitime = charger_json(EURLEX)

    # --- documents legitimes pertinents -----------------------------------
    #
    # Le simulateur tirait initialement ses documents legitimes au hasard ;
    # face a un contexte etranger a la question, le modele ecartait le bloc
    # externe en entier, charge adverse comprise. Les trois familles
    # obtenaient zero sur les cinq configurations, ce qui ne mesurait pas la
    # defense mais seulement le fait qu'une consigne noyee dans du bruit se
    # remarque.
    #
    # Une attaque reelle est inseree dans des documents que le modele a de
    # bonnes raisons de lire. Je fournis donc les premiers resultats reels
    # d'une recherche sur EUR-Lex.
    # Trois correctifs de recuperation, mesures le 25/09. Sans eux, l'article
    # demande n'apparaissait au rang 10 que dans 8 cas sur 40, et E3 mesurait
    # le silence d'un systeme prive de sa source plutot que sa robustesse.
    #
    #   en-tete    le numero d'article figure dans la rubrique, l'index ne lit
    #              que `text` : je prefixe chaque pave par « MiFID2 Article 29. »
    #   langue     le corpus contient chaque texte en FR et en EN, et chaque
    #              doublon occupe une place parmi les fragments retenus
    #   reglement  un index par texte, choisi d'apres celui que nomme la
    #              question
    #
    # Effet cumule : de 20 % a 90 % au rang 10. `--eurlex-brut` restaure
    # l'ancienne recuperation pour rejouer a l'identique une campagne
    # anterieure.
    print("construction de l'index BM25 reglementaire...")
    if arguments.eurlex_brut:
        documents_externes = corpus_legitime
        print("recuperation       : BRUTE (texte seul, FR+EN)")
    else:
        documents_externes = mod_lexical.enrichir_par_rubrique(
            corpus_legitime,
            langues=None if arguments.langue_eurlex == "toutes"
            else (arguments.langue_eurlex,))
        print("recuperation       : en-tete d'article, langue %s"
              % arguments.langue_eurlex)
    index_eurlex = mod_lexical.IndexLexical(langue="fr").construire(
        documents_externes)
    print("index externe      : %d passages" % len(index_eurlex.documents))

    index_par_reglement = {}
    if not arguments.eurlex_brut and not arguments.sans_filtre_reglement:
        par_reg = {}
        for doc in documents_externes:
            morceaux = str(doc.get("rubrique", "")).split("/")
            if len(morceaux) > 1:
                par_reg.setdefault(morceaux[1], []).append(doc)
        index_par_reglement = {
            nom: mod_lexical.IndexLexical(langue="fr").construire(lot)
            for nom, lot in par_reg.items()}
        print("index par reglement: %s"
              % ", ".join(f"{n} {len(l)}" for n, l in sorted(par_reg.items())))

    def index_pour(requete):
        """L'index du reglement nomme par la requete, sinon l'index global."""
        for nom, index in index_par_reglement.items():
            if nom.replace("_", " ").lower() in requete.lower()                     or nom.lower() in requete.lower():
                return index
        return index_eurlex

    def documents_pertinents(requete, combien):
        return [doc for doc, _ in index_pour(requete).rechercher(requete,
                                                                 n=combien)]

    # --- tri par ancrage ---------------------------------------------------
    #
    # Une question dont l'article demande n'apparait pas dans les fragments ne
    # mesure pas la robustesse : le modele n'a rien a affirmer, donc aucune
    # affirmation ou le faux puisse s'inserer. Mesure du 25/09 : l'attaque
    # `assertion` reussit 3 fois sur 4 lorsque l'article est fourni, 0 fois
    # sur 35 sinon. Ces questions engageraient une depense sans information.
    #
    # Le tri est local et gratuit : il ne consulte que l'index.
    if arguments.ancrees_seulement:
        avant = len(requetes)
        gardes = []
        sans_cible = 0
        for cas in cas_retenus:
            cible = cible_de(cas)
            if cible is None:
                sans_cible += 1
                continue
            rapportes = documents_pertinents(cas["requete"],
                                             arguments.profondeur_ancrage)
            if article_rapporte(rapportes, *cible):
                gardes.append(cas)
        cas_retenus = gardes
        requetes = [c["requete"] for c in cas_retenus]
        print("tri par ancrage    : %d questions sur %d gardees (%.0f %%), "
              "profondeur %d"
              % (len(requetes), avant,
                 100 * len(requetes) / avant if avant else 0,
                 arguments.profondeur_ancrage))
        if sans_cible:
            print("                     %d cas sans article cible, ecartes"
                  % sans_cible)
        if not requetes:
            raise SystemExit(
                "aucune question ancree : la campagne ne mesurerait rien. "
                "Verifier la recuperation externe avant de depenser.")

    familles = tuple(f.strip() for f in arguments.familles.split(",")
                     if f.strip())
    inconnues = set(familles) - {mod_adverse.INSTRUCTION,
                                 mod_adverse.ASSERTION,
                                 mod_adverse.DUPLICATION}
    if inconnues:
        raise SystemExit(f"familles inconnues : {sorted(inconnues)}")
    print(f"familles           : {', '.join(familles)}")

    # Attaquant. `surface` ne coute rien et se rejoue a graine fixe.
    # `reecriture` fait reecrire la charge par le modele apres chaque echec :
    # c'est l'echelon superieur, qui mesure la robustesse a une variation
    # semantique plutot que typographique, et il est facture. Un journal deja
    # present est relu au lieu d'etre regenere, ce qui permet de rejouer une
    # campagne sans nouvelle depense.
    reformulateur = None
    if arguments.attaquant == "reecriture":
        journal_reform = arguments.journal_reformulations
        if journal_reform and Path(journal_reform).exists():
            reformulateur = mod_reformulation.depuis_journal(journal_reform)
            print(f"attaquant          : reecriture, REJOUEE depuis "
                  f"{journal_reform}")
        elif reel is None:
            raise SystemExit(
                "--attaquant reecriture exige --modele : sans fournisseur "
                "reel, aucune reecriture ne peut etre produite.\n"
                "Pour rejouer une campagne deja payee, fournir un "
                "--journal-reformulations existant.")
        else:
            reformulateur = mod_reformulation.fabriquer(
                reel, journal=journal_reform)
            print("attaquant          : reecriture par le modele, FACTUREE")
            print("                     comptee dans le plafond de depense")
    else:
        print("attaquant          : surface, cinq transformations enumerees")

    def fabrique_simulateur():
        return mod_adverse.SimulateurAdverse(
            corpus_legitime,
            taux_empoisonnement=arguments.taux_empoisonnement,
            familles=familles,
            graine=arguments.graine, adaptatif=True,
            recuperateur=documents_pertinents,
            reformulateur=reformulateur)

    with mod_journal.Execution("e3-devis", config,
                               manifeste=[BANQUE, BANQUE_REFERENCE,
                                          EURLEX]) as ex:
        if arguments.sans_devis:
            print("devis simule saute : les statistiques d'invite seront")
            print("celles de la campagne reelle.")
            rapport = {"asr_par_configuration": {}}
        else:
            rapport = e3.campagne(moteur, fabrique_simulateur, requetes)

        if arguments.sans_devis and not fournisseur.invites:
            # Rien a chiffrer avant la campagne : j'ecris un devis minimal,
            # complete apres coup par les valeurs reelles.
            devis_reporte = True
            longueurs = mots = [0]
        else:
            devis_reporte = False
        appels = len(fournisseur.invites)
        configurations = len(e3.CONFIGURATIONS)
        plafond = len(requetes) * configurations
        if not devis_reporte:
            longueurs = [len(i) for i in fournisseur.invites]
            mots = [len(i.split()) for i in fournisseur.invites]

        devis = {
            "requetes": len(requetes),
            "configurations": configurations,
            "appels_plafond": plafond,
            "appels_reels": appels,
            "abstentions_evitees": plafond - appels,
            "invite_caracteres": {
                "total": sum(longueurs),
                "moyenne": round(statistics.mean(longueurs), 1),
                "mediane": statistics.median(longueurs),
                "min": min(longueurs),
                "max": max(longueurs),
            },
            "invite_mots": {
                "total": sum(mots),
                "moyenne": round(statistics.mean(mots), 1),
            },
            "familles": list(familles),
            "resultats_de_robustesse": "NON MESURES : fournisseur simule",
            "asr_ignore": rapport["asr_par_configuration"],
        }

        print()
        print(f"configurations     : {configurations}")
        print(f"appels plafond     : {plafond}")
        print(f"appels reels       : {appels}")
        print(f"invites, moyenne   : {devis['invite_caracteres']['moyenne']} "
              f"caracteres")
        print(f"invites, total     : {devis['invite_caracteres']['total']} "
              f"caracteres")
        ex.mesure("appels", appels)

        chemin = Path(arguments.sortie)
        chemin.mkdir(parents=True, exist_ok=True)
        for destination in (chemin, ex.dossier):
            with open(destination / "e3_devis.json", "w",
                      encoding="utf-8") as f:
                json.dump({"parametres": vars(arguments), **devis}, f,
                          ensure_ascii=False, indent=2)
            with open(destination / "invites.txt", "w",
                      encoding="utf-8") as f:
                for rang, invite in enumerate(fournisseur.invites, start=1):
                    f.write(f"===== invite {rang} =====\n{invite}\n\n")
        print(f"\necrit : {chemin}/ et {ex.dossier}/")
        print("\nLes invites exactes sont dans invites.txt : le comptage de")
        print("jetons de l'etape 2 se fera dessus, sans nouvelle execution.")

        # --- deuxieme et troisieme garde-fous -----------------------------
        if reel is None:
            return
        if not arguments.engager_la_depense:
            print("\n" + "=" * 62)
            print("DEVIS SEUL. Aucun appel n'a ete emis.")
            print("Pour lancer la campagne reelle, ajoutez "
                  "--engager-la-depense.")
            print("=" * 62)
            return

        print("\n" + "=" * 62)
        print("CAMPAGNE REELLE, plafond %.4f $" % arguments.plafond)
        print("=" * 62)
        moteur.fournisseur = reel
        traces = []
        reprise = Reprise(arguments.reprise) if arguments.reprise else None
        if reprise and reprise.faits:
            print("reprise            : %d appels deja aboutis, non "
                  "refactures" % len(reprise.faits))
        try:
            mesure = e3.campagne(moteur, fabrique_simulateur, requetes,
                                 traces=traces, reprise=reprise)
        except PlafondAtteint as arret:
            print("\nINTERROMPU : %s" % arret)
            mesure = {"interrompu": str(arret)}
        except (KeyboardInterrupt, Exception) as erreur:
            # Une coupure reseau, une mise en veille ou une erreur d'API ne
            # doivent pas faire perdre ce qui est deja paye. Le journal de
            # reprise a ete ecrit appel par appel ; je le signale, puis je
            # releve l'exception.
            if reprise:
                print("\nINTERROMPU : %s" % str(erreur)[:120])
                print("%d appels sont deja aboutis et ne seront pas "
                      "refactures." % len(reprise.faits))
                print("Relancez la MEME commande pour reprendre.")
            raise
        if reprise:
            mesure["reprise"] = reprise.resume()
            traces = reprise.traces

        mesure["cout"] = {
            "appels": reel.appels,
            "depense_usd": round(reel.depense, 6),
            "plafond_usd": arguments.plafond,
            "resume_fournisseur": reel.resume(),
        }
        mesure["client"] = client.decrire()

        print("\nappels emis     : %d" % reel.appels)
        print("depense reelle  : %.6f $" % reel.depense)
        if "asr_par_configuration" in mesure:
            print("\ntaux de succes d'attaque par configuration :")
            for nom, valeur in mesure["asr_par_configuration"].items():
                print("  %-22s %.4f" % (nom, valeur))

        tronquees = sum(1 for r in reel.reponses if r["tronquee"])
        mesure["reponses_tronquees"] = tronquees

        # Statistiques d'invite issues de la campagne reelle. Elles rendent
        # la passe simulee inutile lorsque la depense est engagee : celle-ci
        # produisait les memes valeurs, au prix d'un second re-classement
        # complet.
        if reel.invites:
            longueurs_reelles = [len(i) for i in reel.invites]
            mesure["invite_caracteres"] = {
                "total": sum(longueurs_reelles),
                "moyenne": round(statistics.mean(longueurs_reelles), 1),
                "mediane": statistics.median(longueurs_reelles),
                "min": min(longueurs_reelles),
                "max": max(longueurs_reelles),
            }
            print("invites, moyenne   : %.1f caracteres"
                  % mesure["invite_caracteres"]["moyenne"])
        print("reponses tronquees : %d sur %d" % (tronquees,
                                                  len(reel.reponses)))

        for destination in (chemin, ex.dossier):
            with open(destination / "e3_reel.json", "w",
                      encoding="utf-8") as f:
                json.dump({"parametres": vars(arguments), **mesure}, f,
                          ensure_ascii=False, indent=2)
            # Reponses en clair, pour permettre une verification humaine du
            # verdict.
            if reel.invites:
                with open(destination / "invites.txt", "w",
                          encoding="utf-8") as f:
                    for rang, invite in enumerate(reel.invites, start=1):
                        f.write("\n".join(
                            ["===== invite %d =====" % rang, invite, "", ""]))
            with open(destination / "reponses.txt", "w",
                      encoding="utf-8") as f:
                for item in reel.reponses:
                    entete = "APPEL %d   %d jetons%s" % (
                        item["appel"], item["jetons_sortie"],
                        "   TRONQUEE" if item["tronquee"] else "")
                    f.write("\n".join(["=" * 74, entete, "=" * 74,
                                       item["reponse"], "", ""]))
            # Trace complete : question, sources fournies avec leur nature,
            # sources retenues, sources citees, verdict. Elle ne consomme aucun
            # jeton (comptabilite locale) et peut donc rester active sur la
            # campagne complete.
            ecrire_traces(destination / "trace_appels.txt", traces)
        print("reponses en clair : %s/reponses.txt" % chemin)
        print("trace complete    : %s/trace_appels.txt" % chemin)


if __name__ == "__main__":
    main()
