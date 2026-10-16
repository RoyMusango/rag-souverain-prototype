r"""
Produit le document de comparaison : reponse attendue contre reponse obtenue.

    .venv\Scripts\python.exe scripts\generer_comparaison_reponses.py

Ecrit `etat_actuel_des_slides/COMPARAISON_REPONSES.md`, un document a lire.

EN PLUS DE LA FIGURE

La figure donne le rang, mais pas ce que le systeme a renvoye. Ce document
montre, pour chaque question, la reponse attendue et le texte renvoye. Par
exemple, un rang de 3 se comprend mieux quand on voit que les rangs 1 et 2
viennent du meme article.

Le texte est genere a partir des fichiers de resultats, jamais recopie a la
main : une recopie pourrait introduire des ecarts avec la mesure sans qu'on
les voie.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Chargement par chemin plutot que par `from scripts...`. Ainsi `scripts` n'a
# pas besoin d'etre un paquet. Surtout, run_recherche_questions remplace
# sys.stdout a l'import, et ce remplacement fait deux fois fermait la sortie
# des la premiere ecriture.
import importlib.util

_source = Path(__file__).with_name("run_recherche_questions.py")
_spec = importlib.util.spec_from_file_location("_rrq", _source)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
QUESTIONS = _module.QUESTIONS

EURLEX = "data/external/eurlex/eurlex_schema.json"
RANGS = "resultats/recherche_questions_rangs.json"
SORTIE = "etat_actuel_des_slides/COMPARAISON_REPONSES.md"

VOIES = [("lexical", "Voie lexicale, BM25"),
         ("dense", "Voie dense, BGE-M3"),
         ("fusion", "Fusion des deux")]

EXTRAIT_ATTENDU = 420
EXTRAIT_RENDU = 155
TOP = 5


def propre(texte, limite):
    texte = " ".join(str(texte).split())
    return texte[:limite] + ("..." if len(texte) > limite else "")


def lire_resultats(dossier, numero):
    """Relit un fichier de resultats deja ecrit et renvoie les doc_id dans l'ordre."""
    chemin = Path(dossier) / ("Resultats_recherche_question_%d.txt" % numero)
    lignes = chemin.read_text(encoding="utf-8").splitlines()
    debut = next(i for i, l in enumerate(lignes)
                 if l.startswith("rang  score")) + 2
    sortie = []
    for ligne in lignes[debut:]:
        if not ligne.strip():
            break
        morceaux = ligne.split()
        sortie.append(morceaux[2])
    return sortie


def main():
    with open(EURLEX, encoding="utf-8") as f:
        textes = {d["doc_id"]: d.get("text", "") for d in json.load(f)}
    with open(RANGS, encoding="utf-8") as f:
        rangs = json.load(f)

    lignes = []
    ajoute = lignes.append

    ajoute("# Ce que le système rapporte, question par question")
    ajoute("")
    ajoute("Douze questions réglementaires écrites à la main, dont on connaît")
    ajoute("le passage d'origine. Pour chacune : la question, le passage")
    ajoute("attendu, et ce que les trois voies de recherche ont réellement")
    ajoute("rapporté.")
    ajoute("")
    ajoute("Document produit par `scripts/generer_comparaison_reponses.py` à")
    ajoute("partir des fichiers de résultats. Aucun texte n'est recopié à la")
    ajoute("main.")
    ajoute("")
    ajoute("---")
    ajoute("")

    # ------------------------------------------------------------ synthese
    ajoute("# Le tableau d'ensemble")
    ajoute("")
    ajoute("| | Rappel@5 | Rappel@10 | Rappel@25 |")
    ajoute("|---|---|---|---|")
    for cle, libelle in VOIES:
        valeurs = [rangs[cle][str(n)] for n in range(1, len(QUESTIONS) + 1)]
        cellules = []
        for k in (5, 10, 25):
            atteint = sum(1 for v in valeurs if v is not None and v <= k)
            cellules.append("%.4f" % (atteint / len(QUESTIONS)))
        ajoute("| %s | %s |" % (libelle, " | ".join(cellules)))
    ajoute("")

    ajoute("| Question | Lexicale | Dense | Fusion |")
    ajoute("|---|---|---|---|")
    for numero in range(1, len(QUESTIONS) + 1):
        cellules = []
        for cle, _ in VOIES:
            valeur = rangs[cle][str(numero)]
            cellules.append("non trouvé" if valeur is None
                            else "rang %d" % valeur)
        ajoute("| Q%d | %s |" % (numero, " | ".join(cellules)))
    ajoute("")
    ajoute("---")
    ajoute("")

    # -------------------------------------------------------- par question
    for numero, (question, attendu) in enumerate(QUESTIONS, start=1):
        ajoute("# Question %d" % numero)
        ajoute("")
        ajoute("**La question posée**")
        ajoute("")
        ajoute("> %s" % question)
        ajoute("")
        ajoute("**Le passage attendu** : `%s`" % attendu)
        ajoute("")
        ajoute("> %s" % propre(textes.get(attendu, ""), EXTRAIT_ATTENDU))
        ajoute("")

        for cle, libelle in VOIES:
            dossier = "resultats/recherche_questions_%s" % cle
            if not os.path.isdir(dossier):
                continue
            obtenus = lire_resultats(dossier, numero)[:TOP]
            rang = rangs[cle][str(numero)]
            etat = ("trouvé au rang %d" % rang) if rang else \
                "non trouvé dans les 25 premiers"
            ajoute("### %s : %s" % (libelle, etat))
            ajoute("")
            for position, doc in enumerate(obtenus, start=1):
                marque = "  **← ATTENDU**" if doc == attendu else ""
                ajoute("**%d.** `%s`%s" % (position, doc, marque))
                ajoute("")
                ajoute("> %s" % propre(textes.get(doc, ""), EXTRAIT_RENDU))
                ajoute("")
        ajoute("---")
        ajoute("")

    Path(SORTIE).write_text("\n".join(lignes), encoding="utf-8")
    print("ecrit :", SORTIE)
    print("questions :", len(QUESTIONS))


if __name__ == "__main__":
    main()
