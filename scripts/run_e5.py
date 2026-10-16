r"""
Lance E5, le cout en precision de la protection.

    python scripts\build_paires_banque.py     une seule fois, avant
    python scripts\run_e5.py
    python scripts\run_e5.py --corpus enronqa --sans-generalisation

Utiliser `python` et non `py -3.11`.

BUT DE LA CAMPAGNE

E2 mesure ce que la protection apporte, E5 mesure ce qu'elle coute. Il faut
les deux pour juger la protection.

QUATRE REGIMES, SUR LES MEMES QUESTIONS

    brut            la requete part telle quelle (reference)
    masque          entites nommees retirees, protection des donnees
    generalise-1    ville remplacee par sa region, identifiants retires
    generalise-2    ville remplacee par le pays, secteur egalement retire

Deux niveaux de generalisation donnent une courbe de cout, et pas un seul
point. Le chapitre 5 peut ainsi donner le prix de chaque niveau de
protection.

POURQUOI LE CORPUS BANCAIRE ET PAS ENRONQA

Une premiere version melangeait les questions d'EnronQA et la population
Synthea. Le resultat n'aurait rien voulu dire : generaliser un patient
synthetique dans une question sur un courriel d'entreprise mesure l'effet
du bruit ajoute, pas le cout de la protection.

Le corpus bancaire est le seul qui a a la fois des questions dont on connait
la reponse et des entites dont on connait les quasi-identifiants. Les deux
fichiers sont produits par `scripts/build_paires_banque.py`.

LE GENERALISEUR REMPLACE LES TERMES

La requete generalisee est la meme requete, dont les termes precis sont
remplaces par des termes plus larges. Si on ajoutait des termes larges en
gardant les termes precis, ceux-ci sortiraient quand meme, sans aucune
protection, et on mesurerait le cout du bruit.

    brut          Quel motif de vigilance a été retenu pour Youssef Verhaegen,
                  client du secteur négoce de matières premières à Bruxelles ?
    generalise-1  Quel motif de vigilance a été retenu pour un client,
                  client du secteur négoce de matières premières
                  dans la région Bruxelles-Capitale ?
    generalise-2  Quel motif de vigilance a été retenu pour un client,
                  client d'un secteur non précisé en Belgique ?

PREREQUIS. L'index dense doit exister (voir scripts\build_index.py).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.commun import config as mod_config, journal as mod_journal   # noqa: E402
from src.confidentialite import verrou as mod_verrou                  # noqa: E402
from src.evaluation import e1_hybridation as e1                       # noqa: E402
from src.evaluation import e5_cout as e5                              # noqa: E402
from src.evaluation import montage_gpu as montage                     # noqa: E402

PAIRES = {
    "banque": "data/banque/banque_qa.jsonl",
    "enronqa": "data/enronqa/enronqa_qa.jsonl",
}
ENTITES = "data/banque/banque_entites.json"

# Un index lexical par corpus, produit par build_index.py. Le corpus sert
# aussi a limiter la voie dense aux memes documents : l'index Qdrant contient
# les sept corpus, l'index lexical un seul. Sinon les deux voies ne
# chercheraient pas dans le meme ensemble, et on ne pourrait pas les comparer.
INDEX_LEXICAL = {
    "banque": "data/index_lexical/banque.pkl",
    "enronqa": "data/index_lexical/enronqa.pkl",
}

GENERALISE_1 = "generalise-1"
GENERALISE_2 = "generalise-2"

# Le pays, un niveau au-dessus de la region, avec la bonne preposition. La
# table des regions est dans build_paires_banque.py ; j'ajoute ici seulement
# le dernier niveau.
#
# La preposition est dans la table au lieu d'etre deduite : un analyste
# n'ecrirait jamais « a Belgique », et une requete mal ecrite ferait baisser
# le rappel pour une raison qui n'a rien a voir avec la protection.
PAYS = {
    "Hainaut": ("Belgique", "en"),
    "Namur": ("Belgique", "en"),
    "Liège": ("Belgique", "en"),
    "Bruxelles-Capitale": ("Belgique", "en"),
    "Brabant wallon": ("Belgique", "en"),
    "Luxembourg belge": ("Belgique", "en"),
    "Grand-Duché": ("Luxembourg", "au"),
}


def charger_entites(chemin):
    """Population des clients, indexee par identifiant."""
    with open(chemin, encoding="utf-8") as f:
        donnees = json.load(f)
    return donnees.get("entities", donnees), donnees.get("meta", {})


def fabriquer_generaliseur(entites, niveau):
    """Renvoie un transformateur (requete, paire) -> requete generalisee.

    Il remplace des mots dans le texte de la question. Chaque paire contient
    les valeurs qu'elle cite et leur attribut, enregistres a la construction
    du jeu : le remplacement est donc exact.

    Niveau 1 : la ville devient sa region, les identifiants directs
               disparaissent. C'est le niveau que la politique choisirait
               pour une entite ordinaire.
    Niveau 2 : la region devient le pays, et le secteur disparait aussi.
               C'est le niveau pour une entite atypique, que sa region
               suffirait deja a reconnaitre.
    """
    def transformer(requete, paire):
        texte = requete
        cites = paire.get("attributs_cites", {})

        ville = cites.get("ville")
        if ville:
            entite = entites.get(paire.get("entite"), {})
            region = entite.get("region", "région non précisée")
            if niveau >= 2:
                pays, preposition = PAYS.get(region, (region, "à"))
                large, avec_preposition = pays, f"{preposition} {pays}"
            else:
                large, avec_preposition = region, f"dans la région {region}"

            # Je remplace « à Bruxelles » en entier, preposition comprise,
            # pour que la requete reste une phrase correcte. Je ne remplace la
            # ville seule que si cette forme est absente. Faire les deux
            # donnerait « Bruxelles-Capitale-Capitale », car le second
            # remplacement modifierait le resultat du premier.
            if f"à {ville}" in texte:
                texte = texte.replace(f"à {ville}", avec_preposition)
            else:
                texte = texte.replace(ville, large)

        secteur = cites.get("secteur")
        if secteur and niveau >= 2:
            texte = texte.replace(f"du secteur {secteur}",
                                  "d'un secteur non précisé")
            texte = texte.replace(secteur, "activité non précisée")

        # Les identifiants directs designent la personne a eux seuls. Aucun
        # niveau ne les garde : ils sont retires des le premier.
        #
        # Je remplace le nom complet par « un client » au lieu de le
        # supprimer. Sinon il resterait « retenu pour, client », une phrase
        # cassee : le rappel mesurerait la phrase cassee, pas la
        # generalisation.
        identifiants = paire.get("identifiants_cites", [])
        if identifiants:
            complet = " ".join(identifiants)
            if complet in texte:
                texte = texte.replace(complet, "un client")
            else:
                for rang, identifiant in enumerate(identifiants):
                    texte = texte.replace(
                        identifiant, "un client" if rang == 0 else "")

        texte = " ".join(texte.split()).replace(" ,", ",")
        # Elision : « de un client » est incorrect. Cela ne change rien pour
        # BM25, pour qui « de » est un mot vide, mais la requete doit rester
        # lisible quand elle est citee dans le memoire.
        return texte.replace("de un client", "d'un client")

    return transformer


def main():
    parseur = argparse.ArgumentParser(
        description="E5, cout de la protection")
    parseur.add_argument("--corpus", choices=("banque", "enronqa"),
                         default="banque")
    parseur.add_argument("--paires", default=None,
                         help="par defaut, deduit du corpus")
    parseur.add_argument("--entites", default=ENTITES)
    parseur.add_argument("--index-lexical", default=None,
                         help="par defaut, deduit du corpus")
    parseur.add_argument("--index-fichier", default=None)
    parseur.add_argument("--hote", default=None)
    parseur.add_argument("--questions", type=int, default=200)
    parseur.add_argument("--k", type=int, default=10)
    parseur.add_argument("--graine", type=int, default=42)
    parseur.add_argument("--peripherique", default=None)
    parseur.add_argument("--moteur-masquage", default="spacy",
                         help="spacy, camembert ou presidio")
    parseur.add_argument("--langue", default=None,
                         help="par defaut, fr pour la banque, en pour EnronQA")
    parseur.add_argument("--sans-generalisation", action="store_true")
    parseur.add_argument("--sortie", default="resultats/e5")
    arguments = parseur.parse_args()

    config = mod_config.Config()
    chemin_paires = Path(arguments.paires or PAIRES[arguments.corpus])
    langue = arguments.langue or ("fr" if arguments.corpus == "banque"
                                  else "en")

    if not chemin_paires.exists():
        message = f"introuvable : {chemin_paires}"
        if arguments.corpus == "banque":
            message += ("\nConstruisez d'abord les paires :\n"
                        "  python scripts\\build_paires_banque.py")
        raise SystemExit(message)

    paires = e1.charger_paires(chemin_paires)
    echantillon = e1.echantillonner(paires, arguments.questions,
                                    arguments.graine)
    print(f"corpus             : {arguments.corpus} ({langue})")
    print(f"questions retenues : {len(echantillon)}")

    # --- la chaine, en configuration fusion, la meme qu'en E1b -------------
    try:
        vectoriseur = montage.charger_vectoriseur(
            config, peripherique=arguments.peripherique)
        index_dense = montage.charger_index_dense(
            config, hote=arguments.hote,
            chemin_local=arguments.index_fichier)
        index_lexical = montage.charger_index_lexical(
            arguments.index_lexical or INDEX_LEXICAL[arguments.corpus])
    except montage.ChaineIndisponible as erreur:
        raise SystemExit(f"\n{erreur}")

    fabrique = montage.fabrique(config, index_dense, index_lexical,
                                vectoriseur, reclasseur=None,
                                corpus=arguments.corpus)
    recuperateur = fabrique(montage.FUSION)
    if recuperateur is None:
        raise SystemExit("la configuration 'fusion' n'a pas pu etre montee.")

    print(f"peripherique       : {vectoriseur.peripherique} / "
          f"{vectoriseur.precision}")
    print("chaine mesuree     : fusion, la meme qu'en E1b")

    masqueur = mod_verrou.Masqueur(moteur=arguments.moteur_masquage,
                                   langue=langue)
    print(f"masqueur           : {arguments.moteur_masquage}")

    generaliseurs = {}
    if not arguments.sans_generalisation and arguments.corpus == "banque":
        chemin_entites = Path(arguments.entites)
        if not chemin_entites.exists():
            print(f"  population introuvable : {chemin_entites}")
            print("  les regimes generalises seront absents.")
        else:
            entites, meta = charger_entites(chemin_entites)
            generaliseurs = {
                GENERALISE_1: fabriquer_generaliseur(entites, 1),
                GENERALISE_2: fabriquer_generaliseur(entites, 2),
            }
            print(f"population         : {len(entites)} clients, "
                  f"quasi-identifiants "
                  f"{', '.join(meta.get('quasi_identifiants', []))}")
    elif arguments.corpus == "enronqa":
        print("  EnronQA n'a pas de liste d'entites : seuls les regimes brut")
        print("  et masque sont mesurables sur ce corpus.")
    print()

    # --- campagne -----------------------------------------------------------
    with mod_journal.Execution("e5-cout", config,
                               manifeste=[str(chemin_paires)]) as ex:
        ex.evenement("montage", **montage.decrire(
            vectoriseur, index_dense, index_lexical, None))
        ex.evenement("masqueur", **masqueur.decrire())

        resultats = {
            e5.BRUT: e5.evaluer(recuperateur, echantillon, None,
                                arguments.k, e5.BRUT),
            e5.MASQUE: e5.evaluer(recuperateur, echantillon,
                                  lambda q, _: masqueur.masquer(q),
                                  arguments.k, e5.MASQUE),
        }
        for nom, generaliseur in generaliseurs.items():
            resultats[nom] = e5.evaluer(recuperateur, echantillon,
                                        generaliseur, arguments.k, nom)

        cle = f"recall@{arguments.k}"
        reference = resultats[e5.BRUT][cle]["moyenne"]
        couts = {}
        for nom, mesure in resultats.items():
            if nom == e5.BRUT:
                continue
            valeur = mesure[cle]["moyenne"]
            couts[nom] = {
                "recall_absolu": round(valeur - reference, 4),
                "recall_relatif": round((valeur - reference) / reference, 4)
                if reference else None,
            }

        print(f"{'regime':<16} {'rappel@' + str(arguments.k):>10} "
              f"{'nDCG@' + str(arguments.k):>10} {'mots req.':>10} "
              f"{'latence ms':>11}")
        print("-" * 60)
        for nom in (e5.BRUT, e5.MASQUE, GENERALISE_1, GENERALISE_2):
            mesure = resultats.get(nom)
            if mesure is None:
                continue
            print(f"{nom:<16} "
                  f"{mesure[cle]['moyenne']:>10.4f} "
                  f"{mesure[f'ndcg@{arguments.k}']['moyenne']:>10.4f} "
                  f"{mesure['longueur_requete_mots']['moyenne']:>10.1f} "
                  f"{mesure['latence_mediane_ms']:>11.1f}")
            ex.mesure(f"{nom}.{cle}", mesure[cle]["moyenne"])

        print("\ncout de chaque protection, en rappel :")
        for nom, cout in couts.items():
            absolu, relatif = cout["recall_absolu"], cout["recall_relatif"]
            part = f"{relatif:+.1%}" if relatif is not None else "indefini"
            print(f"  {nom:<16} {absolu:+.4f}  ({part})")

        print("\nLe cout des regimes generalises est le prix de la protection")
        print("de l'intention, celui de 'masque' le prix de la protection des")
        print("donnees. En production, les deux s'additionnent.")

        rapport = {
            "corpus": arguments.corpus,
            "k": arguments.k,
            "resultats": resultats,
            "cout_par_regime": couts,
            "lecture": (
                "Les deux niveaux de generalisation donnent une courbe de "
                "cout, et pas un seul point : on voit le prix de chaque "
                "niveau de protection. Le generaliseur REMPLACE les termes "
                "precis par des termes plus larges ; s'il en ajoutait a "
                "cote, les termes precis sortiraient quand meme et rien ne "
                "serait protege."
            ),
        }

        chemin = Path(arguments.sortie)
        chemin.mkdir(parents=True, exist_ok=True)
        for destination in (chemin, ex.dossier):
            with open(destination / "e5_cout.json", "w",
                      encoding="utf-8") as f:
                json.dump({"parametres": vars(arguments), **rapport},
                          f, ensure_ascii=False, indent=2)
        print(f"\necrit : {chemin}/ et {ex.dossier}/")


if __name__ == "__main__":
    main()
