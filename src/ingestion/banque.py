r"""
Corpus interne bancaire synthetique (section 4.3.1 du rapport).

    python -m src.ingestion.banque --clients 300 --graine 42

Le rapport prevoit un corpus interne contenant des « identifiants realistes
mais fictifs (noms, IBAN, identifiants) ». L'ensemble des secrets est tire de
ce corpus. Ce module le genere.

POURQUOI CE CORPUS

Synthea est genere a partir de regles cliniques : il ne contient ni IBAN, ni
numero de compte, ni reference de dossier. Sans ce corpus, aucune experience
ne testerait les reconnaisseurs deterministes de `confidentialite/verrou.py`
(MOTIFS_BANCAIRES). E7 ne mesurerait que la partie statistique, et on la
prendrait pour la performance de toute la chaine.

Avec ce corpus, on mesure les deux parties separement, et on peut voir
qu'elles se completent. C'est le resultat le plus utile d'E7.

CHOIX DE CONCEPTION

  Unite documentaire : une note (KYC, AML, procedure, position).
  rubrique           : le dossier client (identifiant CLI-xxxxxx).
  page               : 1. Une note n'a pas de pages ; meme limite que pour
                       EnronQA et Synthea.
  pave               : rang de la note dans le dossier.
  source             : interne

  IBAN valides. Les IBAN generes respectent le controle modulo 97. Avec des
  IBAN invalides, on mesurerait seulement si le detecteur reconnait la
  forme, et on ne pourrait pas tester plus tard une validation par somme
  de controle.

  Cartes valides. Pour la meme raison, elles respectent la cle de Luhn.

  Verite terrain exacte. Chaque note est ecrite a partir d'un
  enregistrement structure : on connait exactement les chaines sensibles et
  leur categorie. Meme principe que pour E2 et E7.

  Aucune donnee reelle. Les noms, entreprises et villes viennent de listes
  fixes, combinees avec une graine. Les IBAN fictifs utilisent des codes
  pays qui n'existent pas. Le module ne lit aucune source externe.

Sorties :
    data/banque/banque_schema.json       schema commun
    data/banque/banque_reference.json    verite terrain par document
    data/banque/banque_secrets.json      ensemble des secrets (verrou de sortie)
"""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from common import ecrire, numeroter_paves, rapport
except ImportError:  # execution depuis la racine
    from src.ingestion.common import ecrire, numeroter_paves, rapport

SORTIE = Path("data/banque/banque_schema.json")
SORTIE_REFERENCE = Path("data/banque/banque_reference.json")
SORTIE_SECRETS = Path("data/banque/banque_secrets.json")

# --------------------------------------------------------------------------
# Vocabulaire. Listes fixes combinees avec une graine : aucune donnee reelle.
# --------------------------------------------------------------------------

PRENOMS = [
    "Camille", "Antoine", "Fatima", "Youssef", "Ingrid", "Marek", "Sofia",
    "Diederik", "Anaïs", "Lucas", "Élodie", "Bastien", "Naïma", "Thibault",
    "Margot", "Rachid", "Klara", "Vincent", "Astrid", "Pieter",
]

NOMS = [
    "Verhaegen", "Dubois", "Lemoine", "Vandeputte", "Ferrara", "Brichaux",
    "Nowak", "Delvaux", "Marchand", "Steenackers", "Bourgeois", "Haddad",
    "Peeters", "Cornil", "Wauters", "Lombaerts", "Grosjean", "Timmermans",
]

VILLES = [
    "Mons", "Charleroi", "Namur", "Liège", "Bruxelles", "Louvain-la-Neuve",
    "Luxembourg", "Esch-sur-Alzette", "Differdange", "Arlon", "Tournai",
]

SOCIETES = [
    "Ardennes Holding", "Meuse Invest", "Sambre Participations",
    "Kirchberg Capital", "Escaut Immobilier", "Zenobe Trading",
    "Borinage Logistics", "Alzette Property", "Hainaut Développement",
]

SECTEURS = [
    "immobilier", "négoce de matières premières", "conseil en gestion",
    "import-export", "services numériques", "holding de participations",
]

MOTIFS_VIGILANCE = [
    "flux entrants sans justification économique apparente",
    "structure de détention à plusieurs niveaux",
    "opérations fractionnées sous le seuil de déclaration",
    "bénéficiaire effectif résidant hors Union",
    "activité déclarée sans substance vérifiable",
]

# Codes pays fictifs pour les IBAN : aucun n'existe.
CODES_BANQUE = ["ZQ", "XV", "QW"]

CATEGORIES = {
    "prenom": "PERSONNE",
    "nom": "PERSONNE",
    "ville": "LIEU",
    "societe": "ORGANISATION",
    "iban": "IBAN",
    "carte": "CARTE",
    "client": "IDENTIFIANT",
    "dossier": "IDENTIFIANT",
}


# --------------------------------------------------------------------------
# Identifiants valides (controle IBAN et cle de Luhn)
# --------------------------------------------------------------------------

def _reste_97(chaine):
    """Reste modulo 97 d'une chaine alphanumerique, chiffre par chiffre.

    Je ne convertis pas tout en un seul entier : un IBAN peut avoir 34
    caracteres, et la norme decrit ce calcul pas a pas.
    """
    reste = 0
    for caractere in chaine:
        valeur = (str(int(caractere, 36)) if caractere.isalpha()
                  else caractere)
        for chiffre in valeur:
            reste = (reste * 10 + int(chiffre)) % 97
    return reste


def iban_belge(alea):
    """IBAN belge (16 caracteres) qui respecte le controle modulo 97.

    Format : BE + 2 chiffres de controle + 12 chiffres. La cle nationale
    belge (3 derniers chiffres) n'est pas simulee : la validation IBAN ne
    l'utilise pas et aucun detecteur ne la verifie.
    """
    corps = "".join(str(alea.randint(0, 9)) for _ in range(12))
    # Controle calcule sur corps + "BE00", dans l'ordre fixe par la norme.
    reste = _reste_97(corps + "BE00")
    controle = 98 - reste
    return f"BE{controle:02d}{corps}"


def iban_fictif(alea):
    """IBAN avec un code pays fictif, pour tester la detection hors Belgique.

    Le code pays n'existe pas, donc aucun compte reel ne peut correspondre.
    La structure reste valide pour le motif de detection.
    """
    pays = alea.choice(CODES_BANQUE)
    corps = "".join(str(alea.randint(0, 9)) for _ in range(14))
    reste = _reste_97(corps + pays + "00")
    controle = 98 - reste
    return f"{pays}{controle:02d}{corps}"


def carte_luhn(alea):
    """Numero a 16 chiffres qui respecte la cle de Luhn.

    Le prefixe 4 (Visa) est garde, pour qu'un detecteur qui filtre par
    emetteur puisse fonctionner. Le premier chiffre vaut 4, les quatorze
    suivants sont aleatoires et le seizieme est calcule.
    """
    base = [4] + [alea.randint(0, 9) for _ in range(14)]
    somme = 0
    # Le chiffre de controle sera ajoute a droite. En lisant la base a
    # l'envers, je double donc les chiffres de rang pair (0, 2, 4...).
    for rang, chiffre in enumerate(reversed(base)):
        if rang % 2 == 0:
            chiffre *= 2
            if chiffre > 9:
                chiffre -= 9
        somme += chiffre
    controle = (10 - somme % 10) % 10
    return "".join(str(c) for c in base + [controle])


def verifier_identifiants():
    """Verifie que les generateurs produisent des identifiants valides.

    Appele au lancement. Avec des identifiants invalides, E7 mesurerait
    seulement la reconnaissance de la forme, et rien ne le signalerait.
    """
    alea = random.Random(0)
    for _ in range(200):
        iban = iban_belge(alea)
        if _reste_97(iban[4:] + iban[:4]) != 1:
            raise AssertionError(f"IBAN invalide produit : {iban}")
        iban = iban_fictif(alea)
        if _reste_97(iban[4:] + iban[:4]) != 1:
            raise AssertionError(f"IBAN fictif invalide : {iban}")
        carte = carte_luhn(alea)
        somme = 0
        for rang, caractere in enumerate(reversed(carte)):
            chiffre = int(caractere)
            if rang % 2 == 1:
                chiffre *= 2
                if chiffre > 9:
                    chiffre -= 9
            somme += chiffre
        if somme % 10 != 0:
            raise AssertionError(f"carte invalide produite : {carte}")
    return True


# --------------------------------------------------------------------------
# Clients et notes
# --------------------------------------------------------------------------

def engendrer_client(alea, rang):
    """Un enregistrement structure, qui sert de verite terrain."""
    return {
        "client": f"CLI-{100000 + rang}",
        "dossier": f"KYC-{200000 + rang}",
        "prenom": alea.choice(PRENOMS),
        "nom": alea.choice(NOMS),
        "ville": alea.choice(VILLES),
        "societe": alea.choice(SOCIETES),
        "secteur": alea.choice(SECTEURS),
        "iban": iban_belge(alea) if alea.random() < 0.7 else iban_fictif(alea),
        "carte": carte_luhn(alea),
        "motif": alea.choice(MOTIFS_VIGILANCE),
        "montant": alea.randrange(15, 950) * 1000,
    }


GABARITS = [
    ("identite",
     "Dossier {dossier}. Le client {prenom} {nom}, domicilié à {ville}, est "
     "entré en relation au titre d'une activité de {secteur}. Le compte "
     "principal porte l'IBAN {iban}. Une carte de paiement {carte} est "
     "rattachée au dossier. Référence interne : {client}."),
    ("kyc",
     "Note de connaissance client — dossier {dossier}. {prenom} {nom} déclare "
     "exercer par l'intermédiaire de {societe}, dont le siège est établi à "
     "{ville}. Le secteur déclaré est {secteur}. Aucune pièce complémentaire "
     "n'a été produite à ce jour concernant le bénéficiaire effectif."),
    # Corrige le 18/09/2026. Ce gabarit etait le seul des cinq a ne citer le
    # client que par son identifiant de dossier, sans prenom, nom, ville ni
    # secteur. Or les questions sur cette rubrique citent le nom et le
    # secteur : les mots utiles de la question manquaient dans la note
    # attendue, et se trouvaient dans les quatre autres notes du dossier.
    #
    # Avant correction, sur 200 questions (graine 42), les 37 questions `aml`
    # de l'echantillon echouaient toutes, de la meme facon pour la voie
    # lexicale, la voie dense et leur fusion. Pourtant le bon dossier client
    # etait dans les dix premiers resultats 37 fois sur 37 : le systeme
    # trouvait le client mais pas la bonne note. Le rappel de 0,8150 mesure
    # par E1b et E5 sur ce corpus etait donc une limite du jeu de test.
    #
    # La correction n'ajoute aucun tirage aleatoire : la suite des tirages
    # reste la meme, et les 1 200 notes des quatre autres rubriques sont
    # identiques au caractere pres.
    ("aml",
     "Note de vigilance — {client}. Le client {prenom} {nom}, domicilié à "
     "{ville} et actif dans le secteur {secteur}, fait l'objet d'un examen "
     "renforcé. Un mouvement de {montant} EUR au crédit de {iban} a été "
     "relevé, en provenance d'une contrepartie liée à {societe}. Motif "
     "retenu : {motif}. Le dossier {dossier} est maintenu sous surveillance "
     "renforcée."),
    ("position",
     "Position au dossier {dossier}. Titulaire : {prenom} {nom}. Encours "
     "consolidé de {montant} EUR sur le compte {iban}. Aucune opération "
     "signalée depuis le dernier examen périodique."),
    ("procedure",
     "Procédure interne applicable au dossier {dossier}. L'entrée en relation "
     "avec une contrepartie du secteur {secteur} requiert la validation d'un "
     "second analyste. Le dossier de {prenom} {nom} relève de cette "
     "catégorie."),
]


def composer(client, alea):
    """Ecrit les notes d'un client, avec la verite terrain de chacune."""
    documents, references = [], []
    for rang, (nature, gabarit) in enumerate(GABARITS, start=1):
        texte = gabarit.format(**client)

        # Verite terrain : on connait les chaines au moment ou on les insere,
        # pas besoin de les chercher apres. On garde seulement celles qui
        # apparaissent dans ce gabarit.
        attendus = []
        for champ, categorie in CATEGORIES.items():
            valeur = str(client[champ])
            if len(valeur) >= 4 and valeur in texte:
                attendus.append({"chaine": valeur, "categorie": categorie,
                                 "champ": champ})

        doc_id = f"banque/{client['client']}/{nature}"
        documents.append({
            "doc_id": doc_id,
            "text": texte,
            "source": "interne",
            "entities": [],
            "rubrique": f"banque/{client['client']}",
            "page": 1,
            "pave": rang,
        })
        references.append({"doc_id": doc_id, "attendus": attendus})
    return documents, references


def main():
    parseur = argparse.ArgumentParser(
        description="Corpus interne bancaire synthetique")
    parseur.add_argument("--clients", type=int, default=300)
    parseur.add_argument("--graine", type=int, default=42)
    parseur.add_argument("--sans-ner", action="store_true",
                         help="n'extrait pas les entites (plus rapide)")
    arguments = parseur.parse_args()

    verifier_identifiants()
    print("controle des identifiants : IBAN et cartes valides\n")

    alea = random.Random(arguments.graine)
    documents, references, secrets = [], [], []

    for rang in range(arguments.clients):
        client = engendrer_client(alea, rang)
        docs, refs = composer(client, alea)
        documents.extend(docs)
        references.extend(refs)
        for champ, categorie in CATEGORIES.items():
            secrets.append({"secret": str(client[champ]),
                            "categorie": categorie})

    documents = numeroter_paves(documents)

    if not arguments.sans_ner:
        # Meme chaine que les autres adaptateurs, sinon le champ `entities`
        # de ce corpus ne serait pas comparable aux autres.
        try:
            from common import charger_ner, extraire_entites_lot
        except ImportError:
            from src.ingestion.common import (charger_ner,
                                              extraire_entites_lot)
        print(f"extraction NER sur {len(documents)} notes...")
        nlp = charger_ner("fr_core_news_lg")
        entites, troncatures = extraire_entites_lot(
            [d["text"] for d in documents], nlp, batch_size=128)
        for document, liste in zip(documents, entites):
            document["entities"] = liste
    else:
        troncatures = 0

    chemin = ecrire(documents, SORTIE)
    rapport("banque", documents, chemin, 0, troncatures, 0)

    SORTIE_REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    with open(SORTIE_REFERENCE, "w", encoding="utf-8") as f:
        json.dump(references, f, ensure_ascii=False, indent=2)
    with open(SORTIE_SECRETS, "w", encoding="utf-8") as f:
        json.dump(secrets, f, ensure_ascii=False, indent=2)

    total = sum(len(r["attendus"]) for r in references)
    par_categorie = {}
    for r in references:
        for a in r["attendus"]:
            par_categorie[a["categorie"]] = par_categorie.get(
                a["categorie"], 0) + 1

    print(f"verite terrain : {total} entites attendues")
    for categorie, compte in sorted(par_categorie.items()):
        print(f"  {categorie:<14} {compte:>6}")
    print(f"\nreference : {SORTIE_REFERENCE}")
    print(f"secrets   : {SORTIE_SECRETS} ({len(secrets)} entrees)")


if __name__ == "__main__":
    main()
