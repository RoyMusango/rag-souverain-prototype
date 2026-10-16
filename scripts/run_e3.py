r"""
Lance E3, la resistance a l'injection indirecte.

    python scripts\run_e3.py --questions 40

Utiliser `python` et non `py -3.11` : quand on donne une version, le
lanceur Windows ignore l'environnement virtuel.

ETAPE 0 : COMPTER AVANT DE PAYER

Sans --engager-la-depense, le script fait tourner la campagne avec un
fournisseur simule, qui reste sur la machine et ne coute rien. Il donne
ensuite le nombre exact d'appels que demanderait la meme campagne avec une
vraie API, et le texte exact des invites.

Ce nombre est exact, pas estime, car il ne depend d'aucune donnee variable :

    e3_injection.campagne  boucle sur les configurations d'ablation
    e3_injection.executer  boucle sur les requetes
    pipeline.repondre      effectue un unique appel de generation

    appels = requetes x configurations - (requetes ou le routeur s'abstient)

Le routeur est deterministe et n'utilise aucun modele : il prend les memes
decisions, et donc s'abstient aussi souvent, avec ou sans API. Seule la
longueur des reponses n'est pas connue a l'avance. Un premier essai payant
(etape 1) sert a la mesurer.

CE QUE CETTE ETAPE NE MESURE PAS

Elle ne mesure pas la robustesse. Le fournisseur simule renvoie toujours la
meme reponse, donc aucune charge adverse ne peut reussir. Les taux de
succes n'auraient aucun sens, et je ne les ecris pas. Le script donne
seulement le nombre d'appels et la taille des invites.

UNE CAMPAGNE PAR FAMILLE

Le simulateur attribue les familles a tour de role aux documents adverses,
dont le nombre depend du taux d'empoisonnement. A 0,1, il n'y en a qu'un, et
seule la famille INSTRUCTION est testee. Il faut un taux de 0,3 pour voir les
trois familles.

Mais a 0,3, elles ne pesent pas pareil. DUPLICATION produit trois documents
pour une seule charge, car il faut plusieurs copies pour imiter des sources
independantes. On evalue alors 1 charge instruction, 1 assertion et 3
duplication. `asr_par_configuration`, la moyenne comparee par l'ablation,
depend alors a 60 % d'une seule famille : le tableau d'ablation mesurerait
surtout la detection de collusion.

Je separe donc le taux et la famille : une campagne par famille, a taux
bas. Chaque famille a son propre taux de succes et sa propre ablation,
aucune ne pese sur la moyenne d'une autre, et on peut de nouveau faire
varier le taux d'empoisonnement pour tracer une courbe.

A taux egal, DUPLICATION ajoute quand meme plus de documents adverses que les
deux autres familles (trois contre un). Cela fait partie de l'attaque
elle-meme. Je le signale sans le corriger.

LIMITES ACTUELLES

  - pour une vraie campagne, il faut un client d'API (--modele) ;
  - le verrou de sortie et le masqueur ne sont pas montes dans ce script.
    Les configurations `complete` et `sans_verrou` donnent donc les memes
    resultats, et l'ablation ne peut pas les distinguer.

Je prefere signaler ces manques ici plutot que de les combler a la va-vite.
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
    """Journal d'avancement d'une campagne, pour pouvoir la reprendre.

    La campagne complete dure environ huit heures et coute de l'argent. Sans
    reprise, une mise en veille, une coupure reseau ou une erreur au
    quatre-centieme appel ferait perdre les appels deja factures, car le JSON
    de resultats n'est ecrit qu'a la fin.

    C'est le meme principe que pour les embeddings, ou `CalculPersistant`
    ecrit par tranches et reprend la ou il s'est arrete : un long calcul doit
    pouvoir etre relance sans tout refaire.

    L'unite de reprise est le couple (configuration, requete), c'est-a-dire
    un appel au modele. Chaque appel termine est ajoute tout de suite a un
    JSONL, lisible pendant l'execution.
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
        # Ecriture immediate, en ajout : une interruption ne fait perdre que
        # l'appel en cours.
        with open(self.chemin, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "configuration": configuration, "requete": requete,
                "resultats": resultats, "trace": trace,
            }, ensure_ascii=False) + "\n")

    def resume(self):
        return {"appels_journalises": len(self.faits),
                "journal": str(self.chemin)}


class PlafondAtteint(RuntimeError):
    """Le cout total a depasse le plafond : la campagne s'arrete."""


class FournisseurPlafonne(mod_fournisseur.FournisseurAPI):
    """Fournisseur d'API qui s'arrete des que la depense atteint un plafond.

    Le compte utilise ne m'appartient pas, donc je ne peux pas fixer de limite
    dans la console du fournisseur. Cette classe sert de limite : elle bloque
    l'appel, au lieu d'afficher un simple avertissement.

    Le cout est calcule par `Fournisseur.generer` a partir des jetons factures
    renvoyes par l'API, pas d'une estimation locale.
    """

    def __init__(self, plafond_usd, journal_cout=None, **kwargs):
        super().__init__(**kwargs)
        self.plafond_usd = plafond_usd
        self.depense = 0.0
        self.appels = 0
        # Comptabilite ecrite appel par appel, a cote du journal de reprise.
        # Sans elle, apres une coupure, on peut reprendre mais on ne connait
        # plus le cout : les jetons factures ne sont gardes nulle part, et les
        # recalculer a partir de la longueur des textes peut se tromper de
        # moitie quand le modele facture plus de jetons qu'il n'en ecrit.
        self.journal_cout = Path(journal_cout) if journal_cout else None
        # Je garde aussi les invites, pour calculer leur taille a partir de
        # la vraie campagne. Sinon il faudrait d'abord une passe simulee, qui
        # referait le re-classement : 35 s par appel, soit deux heures pour
        # 200 appels.
        self.invites = []
        # Je garde les reponses pour pouvoir verifier le verdict. Sans elles,
        # on ne saurait pas si un taux de succes nul vient de la defense ou
        # d'un verdict defaillant, et il faudrait payer de nouveau pour le
        # savoir.
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
        """Une ligne de comptabilite par appel, ecrite tout de suite.

        Elle contient ce que le journal de reprise n'a pas : les jetons
        factures, la longueur de l'invite et le total. Apres une coupure, elle
        suffit pour savoir ou en est la campagne et combien elle a coute.

        Si l'ecriture echoue, la campagne continue : perdre une ligne de
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
    """Fournisseur simule qui garde les invites recues.

    On connait ainsi la taille exacte des invites en plus du nombre d'appels,
    et le devis de l'etape 2 ne repose pas sur une estimation.
    """

    def __init__(self):
        super().__init__()
        self.invites = []

    def _appeler(self, prompt, systeme=None, max_jetons=1024):
        self.invites.append(prompt)
        return super()._appeler(prompt, systeme, max_jetons)


class EvaluateurCommeE6:
    """Fait juger la couverture exactement comme dans E6.

    Le pipeline donne a l'evaluateur les fragments que sa cascade vient de
    trouver. Or EvaluateurCouverture calcule la couverture sur sa propre
    recherche des n premiers documents internes, et c'est ce calcul que E6 a
    mesure.

    La difference change la decision. La cascade renvoie `n_final`
    fragments, l'evaluateur en garde cinq. Avec huit fois plus de texte, une
    question reglementaire semble couverte, le routeur repond INTERNE, et
    aucun contenu externe n'entre. E3 mesurerait alors une chaine ou aucune
    charge adverse n'arrive jamais. Un taux de succes nul ne dirait rien de
    la defense.

    Je force donc `fragments=None` : l'evaluateur fait sa propre recherche,
    et on retrouve les decisions d'E6 (la classe externe va vers ENRICHIR
    dans 40 cas sur 40).
    """

    def __init__(self, evaluateur):
        self.evaluateur = evaluateur

    def __call__(self, requete, fragments=None):
        return self.evaluateur(requete, None)


def ecrire_traces(chemin, traces):
    """Ecrit une trace lisible de chaque appel : sources fournies et reponse.

    Elle separe trois etats : une source peut etre fournie sans etre retenue,
    retenue sans etre citee, et citee sans que l'attaque reussisse.
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

    Par defaut, la classe `externe`, dont la reponse est dans EUR-Lex et pas
    dans le corpus de la banque. C'est la seule qui permet de mesurer
    l'injection : si l'interne suffit, le routeur ne sort pas, aucun contenu
    externe n'entre et il n'y a rien a injecter.

    Les autres classes servent a autre chose. Avec `interne`, le modele ne
    recoit que des fragments internes, chacun avec sa reference. On peut
    ainsi verifier s'il cite bien ses sources quand elles repondent a la
    question. C'est un autre sujet que la robustesse a l'injection.
    """
    return [c["requete"] for c in cas_par_classe(par_classe, graine, classe)]


MOTIF_APPUI = re.compile(r"article (.+?) du texte (.+?), present")


def cas_par_classe(par_classe, graine, classe=None):
    """Les cas d'une classe avec leur appui, et pas seulement leur texte.

    L'appui contient le couple (reglement, numero d'article) du label. Il sert
    a savoir si une question est ancree, c'est-a-dire si l'article demande
    est parmi les fragments rapportes. `requetes_par_classe` ne renvoie que
    le texte.
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
                         help="nombre de requetes de la classe externe")
    # `--questions N` ne tire pas N questions parmi celles d'une campagne a 40 :
    # il construit un nouveau jeu de N par classe, et les jeux ne s'incluent
    # pas (verifie le 19/09 : les 10 questions de `--questions 10` ne sont pas
    # parmi les 40 de `--questions 40`). `--premieres` garde le jeu de 40 et
    # n'en fait tourner que les premieres. Les petites campagnes portent ainsi
    # sur des questions deja posees par la campagne API, et on peut comparer
    # question par question. Passer de 10 a 20 puis a 40 reutilise aussi les
    # appels deja faits, puisque la reprise reconnait (configuration, requete).
    parseur.add_argument("--premieres", type=int, default=None,
                         help="ne faire tourner que les N premieres questions "
                              "du jeu de --questions ; garder --questions 40")
    parseur.add_argument("--taux-empoisonnement", type=float, default=0.1)
    parseur.add_argument("--familles", default="instruction",
                         help="familles de charges, separees par des virgules "
                              "parmi instruction, assertion, duplication. "
                              "UNE SEULE a la fois (voir la docstring).")
    parseur.add_argument("--graine", type=int, default=20260902)
    parseur.add_argument("--sortie", default="resultats/e3_devis")

    # --- appel reel : trois protections -----------------------------------
    parseur.add_argument("--modele", default=None,
                         help="modele OpenAI. Sans ce parametre, le "
                              "fournisseur simule est utilise et rien n'est "
                              "facture.")
    # Le palier correspond a la Frontiere B du chapitre 3 : il dit si la
    # generation sort de l'espace juridique europeen. Il est declare, jamais
    # deduit de l'adresse, et enregistre dans chaque trace.
    parseur.add_argument("--palier", default=mod_fournisseur.API_HORS_UE,
                         choices=(mod_fournisseur.LOCAL,
                                  mod_fournisseur.API_UE,
                                  mod_fournisseur.API_HORS_UE),
                         help="palier de souverainete de la generation")
    parseur.add_argument("--base-url", default=None,
                         help="serveur compatible OpenAI, pour le palier "
                              "local : http://localhost:11434/v1 avec Ollama")
    # 180 s suffisent pour une API. Un modele de 7 milliards de parametres sur
    # le processeur d'un portable met 3 a 10 minutes pour les 1 383 jetons de
    # sortie medians mesures sur `instruction`. Avec un delai trop court,
    # l'appel est coupe, et la reprise le rejouerait sans fin.
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
                              "permet de MESURER l'injection. `interne` sert "
                              "a verifier la citation des sources, pas la "
                              "robustesse.")
    parseur.add_argument("--ancrees-seulement", action="store_true",
                         help="ne garde que les questions dont l'article "
                              "demande est VRAIMENT parmi les fragments "
                              "rapportes. Le tri est local et gratuit : on ne "
                              "paie que les questions qui mesurent quelque "
                              "chose.")
    parseur.add_argument("--profondeur-ancrage", type=int, default=10,
                         help="nombre de resultats ou l'on cherche l'article. "
                              "Doit etre egal au nombre de fragments "
                              "legitimes que verra le modele.")
    parseur.add_argument("--eurlex-brut", action="store_true",
                         help="recherche externe d'avant le 25/09 : texte "
                              "seul, deux langues, aucun filtre. Pour "
                              "rejouer une ancienne campagne.")
    parseur.add_argument("--langue-eurlex", default="FR",
                         choices=("FR", "EN", "toutes"))
    parseur.add_argument("--sans-filtre-reglement", action="store_true",
                         help="pas d'index par reglement. Ce filtre suppose "
                              "que la question nomme son texte, ce qui est "
                              "toujours vrai pour la classe externe mais pas "
                              "en general.")
    parseur.add_argument("--attaquant", default="surface",
                         choices=("surface", "reecriture"),
                         help="surface : les cinq transformations fixes, "
                              "rejouables avec la graine. reecriture : le "
                              "modele reecrit la charge apres chaque echec ; "
                              "plus fort, facture, rejouable avec le journal.")
    parseur.add_argument("--journal-reformulations", default=None,
                         help="JSONL des reecritures. Ecrit avec --attaquant "
                              "reecriture ; LU si le fichier existe deja, ce "
                              "qui rejoue la campagne sans rien refacturer.")
    parseur.add_argument("--sans-devis", action="store_true",
                         help="saute la passe simulee. Elle refait le "
                              "re-classement sans rien apprendre de plus, et "
                              "fait perdre deux heures sur une campagne de "
                              "200 appels. La taille des invites est alors "
                              "calculee sur la vraie campagne.")
    parseur.add_argument("--reprise", default=None,
                         help="fichier JSONL d'avancement. Avec ce parametre, "
                              "les appels deja termines ne sont ni rejoues ni "
                              "refactures : une interruption ne coute que "
                              "l'appel en cours. Relancer la MEME commande "
                              "reprend la ou l'on s'est arrete.")
    parseur.add_argument("--reclassement", action="store_true",
                         help="active le re-classement par cross-encodeur "
                              "avant la generation, puis reduit le contexte. "
                              "Sans cette option, le moteur fonctionne comme "
                              "dans les anciennes campagnes.")
    parseur.add_argument("--top-k-generation", type=int, default=10,
                         help="fragments gardes pour la generation apres "
                              "re-classement")
    parseur.add_argument("--longueur-reclasseur", type=int, default=512,
                         help="longueur maximale du cross-encodeur. Avec 8192, "
                              "l'etape est trop lente sur processeur.")
    parseur.add_argument("--max-jetons", type=int, default=None,
                         help="plafond de jetons par reponse. La configuration "
                              "met 1024 par defaut ; le 14/09, les reponses en "
                              "utilisaient 964 en moyenne, donc la plupart "
                              "etaient coupees.")
    parseur.add_argument("--temperature", type=float, default=None,
                         help="temperature du modele. Pas envoyee par defaut : "
                              "plusieurs modeles refusent toute valeur autre "
                              "que la leur. Sans temperature fixee, la "
                              "campagne n'est pas strictement rejouable.")
    parseur.add_argument("--plafond", type=float, default=1.0,
                         help="plafond de depense en dollars. La campagne "
                              "s'arrete des qu'il est atteint.")
    parseur.add_argument("--engager-la-depense", action="store_true",
                         help="SANS CETTE OPTION, AUCUN APPEL N'EST ENVOYE. Le "
                              "script calcule seulement le devis.")
    arguments = parseur.parse_args()

    if arguments.sans_devis and not arguments.engager_la_depense:
        raise SystemExit(
            "--sans-devis ne sert qu'avec --engager-la-depense.\n"
            "Sans depense, la passe simulee EST le resultat : sans elle, il "
            "n'y a plus rien a mesurer.")

    config = mod_config.Config()
    if arguments.max_jetons:
        config.generation.max_jetons = arguments.max_jetons

    # Je charge les cas complets, pas seulement leur texte : le tri par
    # ancrage, plus bas, a besoin de l'appui.
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

    # --- choix du fournisseur, et premiere protection ---------------------
    #
    # Le devis se fait toujours avec le fournisseur simule, qui reste sur la
    # machine. Une seconde campagne n'est envoyee a l'API qu'avec
    # --engager-la-depense.
    reel = None
    if arguments.modele:
        if arguments.tarif_entree is None or arguments.tarif_sortie is None:
            raise SystemExit(
                "--modele exige --tarif-entree et --tarif-sortie.\n"
                "Sans tarifs, on ne peut pas calculer le plafond de depense, "
                "et il n'y a plus aucune protection.")
        client = mod_openai.ClientOpenAI(
            modele=arguments.modele,
            temperature=arguments.temperature,
            base_url=arguments.base_url,
            palier=arguments.palier,
            # Le delai par defaut du client est de 60 s. Avec --max-jetons
            # 4000, les latences mesurees sur `instruction` passent de 16 a
            # 35 s, et certaines reponses depassent la minute, ce qui provoque
            # APITimeoutError. La reprise ne perd rien, mais il faut relancer.
            # Un appel lent ne coute pas plus cher : seuls les jetons sont
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
            # Les tarifs sont donnes par million de jetons, la trace les veut
            # par jeton. Une erreur d'un facteur un million est vite faite ici,
            # et elle coute cher.
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
    # `hybride.reclasser` n'etait appele nulle part : le cross-encodeur etait
    # charge pour rien. Mesure du 15/09 : sur des invites de 15 147
    # caracteres, quarante fragments internes prenaient 72,2 % du texte, la
    # plupart hors sujet.
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
        print("contexte reduit a  : %d fragments" % arguments.top_k_generation)

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
    # Au debut, le simulateur tirait ses documents legitimes au hasard. Face a
    # un contexte sans rapport avec la question, le modele ignorait tout le
    # bloc externe, charge adverse comprise. Les trois familles avaient 0 dans
    # les cinq configurations : cela montrait seulement qu'une consigne perdue
    # dans du bruit se remarque, pas que la defense marche.
    #
    # Une vraie attaque est cachee dans des documents que le modele a de
    # bonnes raisons de lire. Je donne donc les premiers resultats d'une vraie
    # recherche sur EUR-Lex.
    #
    # Trois correctifs de recherche, mesures le 25/09. Sans eux, l'article
    # demande n'etait dans les 10 premiers resultats que 8 fois sur 40. E3
    # mesurait alors un systeme qui n'avait pas sa source, pas sa robustesse.
    #
    #   en-tete    le numero d'article est dans la rubrique, et l'index ne lit
    #              que `text` : j'ajoute en tete de chaque pave
    #              « MiFID2 Article 29. »
    #   langue     le corpus a chaque texte en FR et en EN, et chaque doublon
    #              prend une place parmi les fragments gardes
    #   reglement  un index par texte, choisi selon le texte que nomme la
    #              question
    #
    # Effet total : de 20 % a 90 % au rang 10. `--eurlex-brut` remet
    # l'ancienne recherche, pour rejouer a l'identique une ancienne campagne.
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
    # Si l'article demande n'est pas dans les fragments, la question ne
    # mesure pas la robustesse : le modele n'a rien a affirmer, donc le faux
    # n'a nulle part ou se glisser. Mesure du 25/09 : l'attaque `assertion`
    # reussit 3 fois sur 4 quand l'article est fourni, 0 fois sur 35 sinon.
    # Ces questions couteraient de l'argent sans rien apprendre.
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
                "Verifiez la recherche externe avant de payer.")

    familles = tuple(f.strip() for f in arguments.familles.split(",")
                     if f.strip())
    inconnues = set(familles) - {mod_adverse.INSTRUCTION,
                                 mod_adverse.ASSERTION,
                                 mod_adverse.DUPLICATION}
    if inconnues:
        raise SystemExit(f"familles inconnues : {sorted(inconnues)}")
    print(f"familles           : {', '.join(familles)}")

    # Attaquant. `surface` ne coute rien et se rejoue avec la graine.
    # `reecriture` fait reecrire la charge par le modele apres chaque echec :
    # c'est un attaquant plus fort, qui change le sens et pas seulement la
    # forme, et il est facture. Si le journal existe deja, il est relu au lieu
    # d'etre regenere : on rejoue la campagne sans payer de nouveau.
    reformulateur = None
    if arguments.attaquant == "reecriture":
        journal_reform = arguments.journal_reformulations
        if journal_reform and Path(journal_reform).exists():
            reformulateur = mod_reformulation.depuis_journal(journal_reform)
            print(f"attaquant          : reecriture, REJOUEE depuis "
                  f"{journal_reform}")
        elif reel is None:
            raise SystemExit(
                "--attaquant reecriture exige --modele : sans vrai "
                "fournisseur, aucune reecriture n'est possible.\n"
                "Pour rejouer une campagne deja payee, donnez un "
                "--journal-reformulations existant.")
        else:
            reformulateur = mod_reformulation.fabriquer(
                reel, journal=journal_reform)
            print("attaquant          : reecriture par le modele, FACTUREE")
            print("                     comptee dans le plafond de depense")
    else:
        print("attaquant          : surface, cinq transformations fixes")

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
            # complete ensuite par les vraies valeurs.
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
        print("\nLes invites exactes sont dans invites.txt : les jetons de")
        print("l'etape 2 se comptent dessus, sans relancer la campagne.")

        # --- deuxieme et troisieme protections ----------------------------
        if reel is None:
            return
        if not arguments.engager_la_depense:
            print("\n" + "=" * 62)
            print("DEVIS SEUL. Aucun appel n'a ete envoye.")
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
            print("reprise            : %d appels deja termines, non "
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
            # reprise est ecrit appel par appel : je le signale, puis je
            # relance l'exception.
            if reprise:
                print("\nINTERROMPU : %s" % str(erreur)[:120])
                print("%d appels sont deja termines et ne seront pas "
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

        print("\nappels envoyes  : %d" % reel.appels)
        print("depense reelle  : %.6f $" % reel.depense)
        if "asr_par_configuration" in mesure:
            print("\ntaux de succes d'attaque par configuration :")
            for nom, valeur in mesure["asr_par_configuration"].items():
                print("  %-22s %.4f" % (nom, valeur))

        tronquees = sum(1 for r in reel.reponses if r["tronquee"])
        mesure["reponses_tronquees"] = tronquees

        # Taille des invites, calculee sur la vraie campagne. Avec
        # --engager-la-depense, la passe simulee devient inutile : elle
        # donnait les memes valeurs, mais refaisait tout le re-classement.
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
            # Reponses en clair, pour qu'un humain puisse verifier le verdict.
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
            # sources retenues, sources citees, verdict. Elle ne coute aucun
            # jeton (calcul local) et peut donc rester active sur toute la
            # campagne.
            ecrire_traces(destination / "trace_appels.txt", traces)
        print("reponses en clair : %s/reponses.txt" % chemin)
        print("trace complete    : %s/trace_appels.txt" % chemin)


if __name__ == "__main__":
    main()
