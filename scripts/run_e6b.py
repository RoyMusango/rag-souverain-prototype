r"""
E6b : abstention par ignorance, lorsque la reponse n'existe nulle part.

    python scripts\run_e6b.py

MOTIVATION

Comme l'indique `e6_routage.py`, l'abstention y est, dans l'implementation
actuelle, un interrupteur de disponibilite et non un jugement reflexif : le
routeur ne s'abstient que lorsque la sortie lui est fermee. Il n'evalue
jamais le soutien externe, si bien que sur les 40 requetes dont la reponse
n'existe nulle part, il decide de sortir 40 fois sur 40, ce qu'E6 compte
comme correct puisque rien ne permet de savoir avant de sortir qu'une
reponse est introuvable.

Ce script mesure l'autre moitie de la question : une fois sorti, le systeme
reconnait-il qu'il n'a rien trouve, et s'abstient-il plutot que d'inventer ?

La difference est la suivante : E6 indexe le seul corpus interne et utilise
EUR-Lex comme verite terrain, alors qu'ici EUR-Lex est indexe et soumis au
meme evaluateur de couverture.

AUCUN NOUVEAU SEUIL

Le jugement externe reutilise les seuils du jugement interne (pertinence
0,55, vocabulaire 0,25). Introduire un seuil propre a l'externe et le regler
sur ce jeu reviendrait a caler un chiffre sur les donnees qui servent a le
mesurer.

VERITE TERRAIN

    absente              -> ABSTENIR   (la reponse n'est nulle part)
    externe, implicite   -> ENRICHIR   (elle est dans EUR-Lex)
    interne, decrit      -> INTERNE
    enrichissement-interdit -> ABSTENIR

Deux erreurs, que je n'agrege pas davantage que celles d'E6 :

    INVENTION       le systeme poursuit alors que rien ne porte la reponse
    SILENCE INDU    il s'abstient alors que la reponse etait a l'exterieur

La seconde est la plus couteuse en usage : un assistant qui refuse de
repondre a des questions legitimes finit par ne plus etre utilise.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.commun import config as mod_config, journal as mod_journal  # noqa: E402
from src.evaluation import e6_routage as e6                          # noqa: E402
from src.index import lexical as mod_lexical                         # noqa: E402
from src.routage import routeur as mod_routeur                       # noqa: E402

BANQUE = "data/banque/banque_schema.json"
REFERENCE = "data/banque/banque_reference.json"
EURLEX = "data/external/eurlex/eurlex_schema.json"

# Issues attendues une fois l'externe consulte. Seule `absente` change par
# rapport a E6 : c'est precisement la question que ce script ajoute.
ATTENDU = {
    e6.INTERNE: mod_routeur.INTERNE,
    e6.INTERNE_DECRIT: mod_routeur.INTERNE,
    e6.EXTERNE: mod_routeur.ENRICHIR,
    e6.EXTERNE_IMPLICITE: mod_routeur.ENRICHIR,
    e6.ABSENTE: mod_routeur.ABSTENIR,
    e6.INTERDIT: mod_routeur.ABSTENIR,
}


def lire(chemin):
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def main():
    p = argparse.ArgumentParser(description="E6b, abstention par ignorance")
    p.add_argument("--banque", default=BANQUE)
    p.add_argument("--reference", default=REFERENCE)
    p.add_argument("--eurlex", default=EURLEX)
    p.add_argument("--par-classe", type=int, default=40)
    p.add_argument("--fragments", type=int, default=5)
    p.add_argument("--seuil-pertinence", type=float, default=0.55)
    p.add_argument("--seuil-completude", type=float, default=0.70)
    p.add_argument("--seuil-vocabulaire", type=float, default=0.25)
    # A None, le jugement externe reutilise exactement le seuil interne.
    # L'option sert a tracer l'arbitrage, et non a caler une valeur sur ce
    # jeu (voir l'en-tete du fichier).
    p.add_argument("--seuil-externe", type=float, default=None,
                   help="seuil de pertinence applique a l'externe ; "
                        "par defaut celui de l'interne")
    p.add_argument("--graine", type=int, default=20260902)
    # Couper le jeu en deux est le seul moyen de choisir un seuil sans le
    # caler sur les donnees qui servent a le mesurer. Le partage est
    # deterministe et effectue au sein de chaque classe, afin que les deux
    # moities conservent la meme composition.
    p.add_argument("--echantillon", default="tout",
                   choices=("tout", "calage", "epreuve"),
                   help="calage : la moitie ou l'on CHOISIT le seuil. "
                        "epreuve : celle ou on le MESURE, jamais vue par le "
                        "reglage.")
    p.add_argument("--sortie", default="resultats/e6b")
    a = p.parse_args()

    interne = lire(a.banque)
    externe = lire(a.eurlex)
    reference = lire(a.reference)

    print(f"corpus interne : {len(interne)} notes")
    print(f"corpus externe : {len(externe)} documents — INDEXE ici")

    cas = e6.construire_jeu(reference, externe, par_classe=a.par_classe,
                            graine=a.graine)
    if a.echantillon != "tout":
        # Melange prealable a la coupe. `construire_jeu` produit les cas
        # d'une classe en alternant ses gabarits : une coupe pair/impair
        # placait donc un gabarit entier d'un cote et l'autre gabarit de
        # l'autre. Les deux moities n'etaient pas deux echantillons d'une
        # meme population mais deux types de questions, avec pour effet
        # mesure 0 % d'abstention d'un cote et 100 % de l'autre au meme seuil.
        import random as _random
        par_classe = {}
        for entree in cas:
            par_classe.setdefault(entree["classe"], []).append(entree)
        moitie = []
        for classe in sorted(par_classe):
            lot = list(par_classe[classe])
            _random.Random(f"{a.graine}|{classe}").shuffle(lot)
            for rang, entree in enumerate(lot):
                if (rang % 2 == 0) == (a.echantillon == "calage"):
                    moitie.append(entree)
        cas = moitie
    print(f"jeu etiquete   : {len(cas)} cas ({a.echantillon})\n")

    print("construction des deux index BM25...")
    index_interne = mod_lexical.IndexLexical(langue="fr").construire(interne)
    index_externe = mod_lexical.IndexLexical(langue="fr").construire(externe)

    ev_interne = e6.EvaluateurCouverture(index_interne, n=a.fragments)
    ev_externe = e6.EvaluateurCouverture(index_externe, n=a.fragments)
    routeur = mod_routeur.Routeur(ev_interne, a.seuil_pertinence,
                                  a.seuil_completude,
                                  seuil_vocabulaire=a.seuil_vocabulaire)
    # Le second routeur sert uniquement a reutiliser `juger` sur l'externe :
    # memes seuils, meme code de decision, seule la source des fragments
    # change.
    seuil_externe = (a.seuil_pertinence if a.seuil_externe is None
                     else a.seuil_externe)
    juge_externe = mod_routeur.Routeur(ev_externe, seuil_externe,
                                       a.seuil_completude,
                                       seuil_vocabulaire=a.seuil_vocabulaire)

    details = []
    for entree in cas:
        decision, corrige = e6.router_jusqu_au_bout(
            routeur, ev_interne, entree, index_interne,
            a.seuil_pertinence, a.seuil_completude)
        issue = decision.issue
        etat_externe = None

        if issue == mod_routeur.ENRICHIR:
            fragments = [d for d, _ in index_externe.rechercher(
                entree["requete"], n=a.fragments)]
            jugement = juge_externe.juger(entree["requete"], fragments)
            etat_externe = jugement.etat
            # Rien a l'exterieur non plus : le cas qu'E6 ne pouvait pas voir.
            if jugement.etat == mod_routeur.FAIBLE:
                issue = mod_routeur.ABSTENIR

        attendu = ATTENDU[entree["classe"]]
        details.append({
            "requete": entree["requete"],
            "classe": entree["classe"],
            "issue_attendue": attendu,
            "issue_obtenue": issue,
            "correcte": issue == attendu,
            "etat_interne": decision.jugement.etat,
            "etat_externe": etat_externe,
            "passe_par_correction": corrige,
        })

    def part(sous_ensemble, predicat):
        if not sous_ensemble:
            return None
        return round(sum(1 for d in sous_ensemble if predicat(d))
                     / len(sous_ensemble), 4)

    absentes = [d for d in details if d["classe"] == e6.ABSENTE]
    dehors = [d for d in details
              if d["classe"] in (e6.EXTERNE, e6.EXTERNE_IMPLICITE)]

    mesures = {
        "taux_decision_correcte": part(details, lambda d: d["correcte"]),
        # Abstention lorsque rien ne porte la reponse : grandeur principale.
        "abstention_par_ignorance": part(
            absentes, lambda d: d["issue_obtenue"] == mod_routeur.ABSTENIR),
        # Poursuite alors que rien ne porte la reponse.
        "invention": part(
            absentes, lambda d: d["issue_obtenue"] != mod_routeur.ABSTENIR),
        # Abstention alors que la reponse etait a l'exterieur (erreur
        # couteuse).
        "silence_indu": part(
            dehors, lambda d: d["issue_obtenue"] == mod_routeur.ABSTENIR),
        "par_classe": {},
    }
    for classe in sorted({d["classe"] for d in details}):
        lot = [d for d in details if d["classe"] == classe]
        mesures["par_classe"][classe] = {
            "cas": len(lot),
            "taux_correct": part(lot, lambda d: d["correcte"]),
        }

    rapport = {
        "parametres": dict(vars(a), seuil_externe_effectif=seuil_externe),
        "cas": len(details),
        "mesures": mesures,
        "details": details,
        "lecture": (
            "L'abstention par ignorance est mesuree une fois l'externe "
            "consulte : c'est la moitie de la question que E6 ne pouvait pas "
            "voir, EUR-Lex n'y etant pas indexe. Les deux erreurs ne "
            "s'agregent pas : inventer trompe l'utilisateur, se taire a tort "
            "le prive d'une reponse qui existait."
        ),
    }

    config = mod_config.Config()
    with mod_journal.Execution("e6b-abstention", config,
                               manifeste=[a.banque, a.reference,
                                          a.eurlex]) as ex:
        print("\n=== ABSTENTION PAR IGNORANCE ===")
        print(f"  se tait quand la reponse n'est nulle part : "
              f"{mesures['abstention_par_ignorance']:.1%} "
              f"({len(absentes)} cas)")
        print(f"  invente au lieu de se taire               : "
              f"{mesures['invention']:.1%}")
        print(f"  se tait alors que la reponse etait dehors : "
              f"{mesures['silence_indu']:.1%} ({len(dehors)} cas)")
        print(f"  decision correcte, toutes classes         : "
              f"{mesures['taux_decision_correcte']:.1%}")
        print("\n  par classe :")
        for classe, v in mesures["par_classe"].items():
            print(f"    {classe:<24} {v['cas']:>3} cas  "
                  f"{v['taux_correct']:.1%}")

        chemin = Path(a.sortie)
        chemin.mkdir(parents=True, exist_ok=True)
        fichier = chemin / "e6b_abstention.json"
        with open(fichier, "w", encoding="utf-8") as f:
            json.dump(rapport, f, ensure_ascii=False, indent=2)
        ex.mesure("abstention_par_ignorance",
                  mesures["abstention_par_ignorance"], "securite")
        ex.mesure("silence_indu", mesures["silence_indu"], "qualite")
        ex.evenement("sortie ecrite", fichier=str(fichier))
        print(f"\necrit : {fichier}")


if __name__ == "__main__":
    main()
