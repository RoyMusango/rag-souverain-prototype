r"""
Construit les paires question-reponse du corpus bancaire, ainsi que la
population d'entites associee.

    python scripts\build_paires_banque.py

Deux fichiers en sortie :

    data/banque/banque_qa.jsonl        les paires, une par ligne
    data/banque/banque_entites.json    la population, avec ses quasi-identifiants

POURQUOI

E5 mesure le cout de la protection de l'intention. Il faut pour cela, sur
le meme corpus, des questions dont on connait la reponse et des entites dont
on connait les quasi-identifiants. Aucun corpus du projet n'avait les deux.

EnronQA a des questions mais pas de liste d'entites. Synthea a une
population mais pas de questions. Melanger les deux reviendrait a
generaliser un patient synthetique dans une question sur un courriel
d'entreprise : on mesurerait l'effet du bruit ajoute, pas le cout de la
protection.

Le corpus bancaire permet d'avoir les deux : 300 dossiers clients dont on
connait chaque champ, puisque les notes sont ecrites a partir d'un
enregistrement structure.

UNE QUESTION, UNE SEULE NOTE

Chaque question porte sur un fait present dans une seule des cinq notes du
dossier. Ainsi le rappel vaut 0 ou 1, et Recall@k a un sens. Avec deux notes
correctes, on mesurerait laquelle le moteur prefere, au lieu de savoir s'il
trouve la bonne.

Les cinq faits retenus, un par nature de note :

    identite    le numero de carte de paiement
    kyc         l'absence de piece sur le beneficiaire effectif
    aml         le motif de vigilance retenu
    position    l'absence d'operation depuis le dernier examen
    procedure   l'exigence de validation par un second analyste

QUASI-IDENTIFIANTS RETENUS

Quatre attributs, tous presents dans les notes ou deduits des notes :

    ville            la ville de domiciliation, telle qu'ecrite dans la note
    region           la province ou le pays, deduit de la ville
    secteur          le secteur d'activite declare
    tranche_encours  l'encours consolide, par paliers de 100 000 EUR

`anonymat.generaliser` sait generaliser `ville` d'un niveau. Il n'a pas de
hierarchie pour les trois autres attributs et les supprime des le premier
niveau. C'est une generalisation grossiere mais correcte, et je le signale.

CE QUE LE SCRIPT NE FAIT PAS

Le script ne regenere pas le corpus bancaire. Il lit les notes existantes
pour en tirer les questions et la population, sans les modifier : E7b reste
donc valide.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SCHEMA = "data/banque/banque_schema.json"
REFERENCE = "data/banque/banque_reference.json"
SORTIE_QA = "data/banque/banque_qa.jsonl"
SORTIE_ENTITES = "data/banque/banque_entites.json"

# Province belge ou pays, deduit de la ville. C'est la vraie geographie, ce
# qui rend la generalisation credible.
REGIONS = {
    "Mons": "Hainaut",
    "Tournai": "Hainaut",
    "Charleroi": "Hainaut",
    "Namur": "Namur",
    "Liège": "Liège",
    "Bruxelles": "Bruxelles-Capitale",
    "Louvain-la-Neuve": "Brabant wallon",
    "Arlon": "Luxembourg belge",
    "Luxembourg": "Grand-Duché",
    "Esch-sur-Alzette": "Grand-Duché",
    "Differdange": "Grand-Duché",
}

# Un gabarit de question par type de note. Le fait demande n'apparait que dans
# cette note, donc la reponse est unique.
QUESTIONS = {
    "identite": "Quel numéro de carte de paiement est rattaché au dossier "
                "de {prenom} {nom}, domicilié à {ville} ?",
    "kyc": "Quelle pièce manque encore sur le bénéficiaire effectif dans la "
           "note de connaissance client de {prenom} {nom} à {ville} ?",
    "aml": "Quel motif de vigilance a été retenu pour {prenom} {nom}, "
           "client du secteur {secteur} à {ville} ?",
    "position": "Quelles opérations ont été signalées depuis le dernier "
                "examen périodique sur le dossier de {prenom} {nom} "
                "à {ville} ?",
    "procedure": "Quelle validation la procédure interne exige-t-elle pour "
                 "{prenom} {nom}, client du secteur {secteur} ?",
}

MOTIF_MONTANT = re.compile(r"(\d[\d\s]*) EUR")
MOTIF_SECTEUR = re.compile(r"secteur (?:déclaré est )?([^.]+?)(?:\.| requiert)")
MOTIF_ACTIVITE = re.compile(r"activité de ([^.]+)\.")


def lire(chemin):
    chemin = Path(chemin)
    if not chemin.exists():
        chemin = chemin.with_suffix(".jsonl")
    if chemin.suffix == ".jsonl":
        with open(chemin, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def tranche(montant, pas=100000):
    """Palier de 100 000 EUR. Un montant exact serait un identifiant."""
    if montant is None:
        return None
    debut = (int(montant) // pas) * pas
    return f"{debut}-{debut + pas - 1}"


def reconstruire_clients(documents, reference):
    """Reconstitue l'enregistrement de chaque client a partir de ses notes.

    La reference donne les chaines sensibles et leur champ. Les notes donnent
    le reste (secteur et montant), qui n'est pas sensible et n'est donc pas
    dans la reference. Je lis les deux au lieu de regenerer le corpus.
    """
    clients = {}

    for entree in reference:
        morceaux = entree["doc_id"].split("/")
        if len(morceaux) < 2:
            continue
        fiche = clients.setdefault(morceaux[1], {"client": morceaux[1]})
        for attendu in entree["attendus"]:
            champ = attendu.get("champ")
            if champ and champ not in fiche:
                fiche[champ] = attendu["chaine"]

    for document in documents:
        morceaux = str(document.get("doc_id", "")).split("/")
        if len(morceaux) < 3:
            continue
        fiche = clients.get(morceaux[1])
        if fiche is None:
            continue
        texte = document.get("text", "")

        if "secteur" not in fiche:
            trouve = MOTIF_SECTEUR.search(texte) or MOTIF_ACTIVITE.search(texte)
            if trouve:
                fiche["secteur"] = trouve.group(1).strip()
        if "montant" not in fiche:
            trouve = MOTIF_MONTANT.search(texte)
            if trouve:
                fiche["montant"] = int(trouve.group(1).replace(" ", ""))

    return clients


def entite_depuis_client(fiche):
    """Les quasi-identifiants d'un client, et rien d'autre.

    Le nom, l'IBAN et la carte sont exclus : ce sont des identifiants
    directs. Chacun designe deja une personne a lui seul, donc les inclure
    rendrait la mesure de l'ensemble d'anonymat inutile.
    """
    ville = fiche.get("ville")
    return {
        "id": fiche["client"],
        "ville": ville,
        "region": REGIONS.get(ville, "inconnue"),
        "secteur": fiche.get("secteur"),
        "tranche_encours": tranche(fiche.get("montant")),
    }


def main():
    parseur = argparse.ArgumentParser(
        description="Paires QR et population du corpus bancaire")
    parseur.add_argument("--schema", default=SCHEMA)
    parseur.add_argument("--reference", default=REFERENCE)
    parseur.add_argument("--sortie-qa", default=SORTIE_QA)
    parseur.add_argument("--sortie-entites", default=SORTIE_ENTITES)
    arguments = parseur.parse_args()

    documents = lire(arguments.schema)
    reference = lire(arguments.reference)
    print(f"notes lues        : {len(documents)}")

    clients = reconstruire_clients(documents, reference)
    print(f"clients reconstitués : {len(clients)}")

    incomplets = [c for c, f in clients.items()
                  if not all(f.get(k) for k in ("prenom", "nom", "ville"))]
    if incomplets:
        print(f"  {len(incomplets)} clients incomplets, ignorés")

    # --- les paires ---------------------------------------------------------
    paires = []
    for cle in sorted(clients):
        fiche = clients[cle]
        if cle in incomplets:
            continue
        for nature, gabarit in QUESTIONS.items():
            try:
                question = gabarit.format(**fiche)
            except KeyError:
                # Un champ utile a ce gabarit manque (par exemple le
                # secteur) : on saute la question au lieu de la poser
                # incomplete.
                continue
            paires.append({
                "doc_id": f"banque/{cle}/{nature}",
                "question": question,
                "entite": cle,
                # Les valeurs citees dans la question, avec leur attribut.
                # Elles permettent a E5 de les remplacer par leur forme
                # generalisee, au lieu d'ajouter des termes.
                "attributs_cites": {
                    champ: fiche[champ]
                    for champ in ("ville", "secteur")
                    if champ in fiche and str(fiche[champ]) in question
                },
                "identifiants_cites": [
                    fiche[champ] for champ in ("prenom", "nom")
                    if champ in fiche and str(fiche[champ]) in question
                ],
            })

    sortie_qa = Path(arguments.sortie_qa)
    sortie_qa.parent.mkdir(parents=True, exist_ok=True)
    with open(sortie_qa, "w", encoding="utf-8") as f:
        for paire in paires:
            f.write(json.dumps(paire, ensure_ascii=False) + "\n")
    print(f"paires écrites    : {len(paires)} dans {sortie_qa}")

    # --- la population ------------------------------------------------------
    entites = {}
    for cle in sorted(clients):
        if cle in incomplets:
            continue
        entite = entite_depuis_client(clients[cle])
        entites[cle] = {k: v for k, v in entite.items() if k != "id"}

    quasi = ("ville", "region", "secteur", "tranche_encours")
    signatures = {}
    for valeurs in entites.values():
        cle_sig = tuple(valeurs.get(a) for a in quasi)
        signatures[cle_sig] = signatures.get(cle_sig, 0) + 1
    uniques = sum(1 for n in signatures.values() if n == 1)

    sortie_entites = Path(arguments.sortie_entites)
    with open(sortie_entites, "w", encoding="utf-8") as f:
        json.dump({
            "meta": {
                "source": "corpus bancaire synthetique, deduit des notes",
                "quasi_identifiants": list(quasi),
                "entites": len(entites),
                "taux_uniques": round(uniques / len(entites), 4)
                if entites else 0.0,
                "note": ("le taux d'uniques est eleve parce que la "
                         "population est petite (300 clients) et que quatre "
                         "quasi-identifiants suffisent a la decouper "
                         "finement. C'est une propriete du corpus, a "
                         "signaler."),
            },
            "entities": entites,
        }, f, ensure_ascii=False, indent=2)

    print(f"entités écrites   : {len(entites)} dans {sortie_entites}")
    print(f"classes distinctes : {len(signatures)}")
    print(f"taux d'uniques     : {uniques / len(entites):.4f}"
          if entites else "")
    print()
    print("Le taux d'uniques est élevé : avec 300 clients et quatre")
    print("quasi-identifiants, la population se découpe finement. C'est une")
    print("propriété du corpus, à signaler. E5 mesure ce que coûte la")
    print("généralisation : ce taux ne fausse donc pas la mesure.")


if __name__ == "__main__":
    main()
