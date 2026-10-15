r"""
Affiche des extraits d'un corpus, pour rediger des questions a partir du texte.

    .venv\Scripts\python.exe scripts\parcourir_corpus.py --corpus banque
    .venv\Scripts\python.exe scripts\parcourir_corpus.py --corpus eurlex --n 8
    .venv\Scripts\python.exe scripts\parcourir_corpus.py --corpus eurlex --texte DORA

MOTIVATION

Les corpus sont des JSON de plusieurs megaoctets, difficiles a lire dans un
editeur. Rediger des questions pertinentes suppose pourtant d'avoir le texte
reel sous les yeux ; sinon, les questions risquent de ne pas trouver de
reponse dans le corpus, et la mesure porterait sur des cas impossibles
plutot que sur le routeur.

Le script n'affiche volontairement aucune mesure, aucun score ni aucune
statistique de vocabulaire : il sert a preparer un jeu de validation, dont
le redacteur ne doit pas voir la grandeur que le jeu servira a eprouver.
"""

import argparse
import io
import json
import random
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

CORPUS = {
    "banque": "data/banque/banque_schema.json",
    "eurlex": "data/external/eurlex/eurlex_schema.json",
}


def charger(nom):
    chemin = Path(CORPUS[nom])
    if not chemin.exists():
        raise SystemExit(
            "introuvable : %s\nCe fichier vient de l'ingestion." % chemin)
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def main():
    parseur = argparse.ArgumentParser(
        description="Parcourt un corpus pour en lire des extraits")
    parseur.add_argument("--corpus", choices=tuple(CORPUS), default="banque")
    parseur.add_argument("--n", type=int, default=5,
                         help="nombre d'extraits")
    parseur.add_argument("--rubrique", default=None,
                         help="banque : identite, kyc, aml, position, "
                              "procedure")
    parseur.add_argument("--texte", default=None,
                         help="eurlex : RGPD, DORA, AI_Act, MiFID2")
    parseur.add_argument("--langue", default="FR",
                         help="eurlex : FR ou EN, defaut FR")
    parseur.add_argument("--longueur", type=int, default=700,
                         help="caracteres affiches par extrait")
    parseur.add_argument("--graine", type=int, default=None,
                         help="pour retrouver le meme tirage")
    arguments = parseur.parse_args()

    documents = charger(arguments.corpus)

    if arguments.corpus == "banque" and arguments.rubrique:
        documents = [d for d in documents
                     if d["doc_id"].rsplit("/", 1)[-1] == arguments.rubrique]
    if arguments.corpus == "eurlex":
        documents = [d for d in documents
                     if ("/%s/" % arguments.langue) in d["doc_id"]]
        if arguments.texte:
            documents = [d for d in documents
                         if ("/%s/" % arguments.texte) in d["doc_id"]]

    if not documents:
        raise SystemExit("aucun document ne correspond a ces filtres.")

    alea = random.Random(arguments.graine)
    echantillon = alea.sample(documents, min(arguments.n, len(documents)))

    print("corpus   : %s (%d passages correspondants)"
          % (arguments.corpus, len(documents)))
    print("affiches : %d\n" % len(echantillon))

    for rang, doc in enumerate(echantillon, start=1):
        print("-" * 70)
        print("[%d] %s" % (rang, doc["doc_id"]))
        if doc.get("rubrique"):
            print("    rubrique : %s   page %s   pave %s"
                  % (doc["rubrique"], doc.get("page"), doc.get("pave")))
        print()
        texte = " ".join(str(doc.get("text", "")).split())
        print(texte[:arguments.longueur]
              + ("..." if len(texte) > arguments.longueur else ""))
        print()


if __name__ == "__main__":
    main()
