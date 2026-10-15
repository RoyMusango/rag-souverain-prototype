r"""
Exploration interactive de la recuperation, pour constituer des exemples
issus de recuperations reelles.

Affiche, pour une ou plusieurs questions d'un corpus : la question, la
reponse ou le document attendu, les documents effectivement recuperes par le
systeme classes par rang, et la presence ou non du bon document dans le
top-k pour chaque valeur de k demandee.

USAGE

    python scripts\explorer_retrieval.py --corpus enronqa --n 3 --k 5,10
    python scripts\explorer_retrieval.py --corpus enronqa --index 0,14,23 --k 5
    python scripts\explorer_retrieval.py --corpus banque --n 5 --k 5,10 --graine 7

--n            nombre de questions tirees au hasard (graine fixee, reproductible)
--index        indices precis a afficher plutot qu'un tirage (prioritaire sur --n)
--k            une ou plusieurs valeurs de k, separees par des virgules
--graine       graine du tirage aleatoire, defaut 42
--longueur     nombre de caracteres affiches par document recupere (defaut 220)

DETECTION DU FORMAT

Le format du fichier de paires question -> document attendu differe d'un
corpus a l'autre (EnronQA, FinQA, TAT-QA, banque). Le script essaie plusieurs
conventions de nommage et de champs, et s'arrete avec un message explicite
s'il ne trouve aucune correspondance fiable, plutot que d'inventer un
appariement. En cas d'echec, l'option --diagnostiquer indique ce qui a ete
cherche et ou ; la constante FICHIERS_REFERENCE ci-dessous permet alors de
fixer le bon chemin.
"""

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ---------------------------------------------------------------------------
# Chemins candidats. Ce sont des conventions, a confirmer avec --diagnostiquer
# en cas de doute.
# ---------------------------------------------------------------------------
SCHEMAS = {
    "enronqa": "data/enronqa/enronqa_schema.jsonl",
    "finqa": "data/finqa/finqa_schema.json",
    "tatqa": "data/tatqa/tatqa_schema.json",
    "eurlex": "data/external/eurlex/eurlex_schema.json",
    "synthea": "data/synthea/synthea_schema.json",
    "banque": "data/banque/banque_schema.json",
}

# Candidats pour le fichier de paires (question, doc_id attendu), par corpus.
# Chemins confirmes le 07/09 par inspection directe du disque. Le premier qui
# existe est utilise.
CANDIDATS_REFERENCE = {
    "enronqa": [
        "data/enronqa/enronqa_qa.jsonl",
    ],
    "finqa": [
        "data/finqa/finqa_qa.jsonl",
    ],
    "tatqa": [
        "data/tatqa/tatqa_qa.jsonl",
    ],
    "banque": [
        "data/banque/banque_qa.jsonl",
        # banque_reference.json est un autre fichier : la verite terrain des
        # entites sensibles pour E7b (masquage), et non des paires question ->
        # document. Il ne doit pas etre utilise ici.
    ],
}


def lire_jsonl_ou_json(chemin):
    chemin = Path(chemin)
    if not chemin.exists():
        return None
    if chemin.suffix == ".jsonl":
        with open(chemin, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def trouver_reference(corpus, diagnostiquer=False):
    candidats = CANDIDATS_REFERENCE.get(corpus, [])
    for chemin in candidats:
        p = Path(chemin)
        if diagnostiquer:
            print(f"  essai : {chemin}  -> {'existe' if p.exists() else 'absent'}")
        if p.exists():
            return chemin, lire_jsonl_ou_json(chemin)
    return None, None


def normaliser_paires(donnees, corpus):
    """Essaie plusieurs noms de champs usuels. Retourne une liste de dicts
    {"question": str, "doc_id_attendu": str, "reponse": str|None}, ou None si
    la structure n'est pas reconnue."""
    if donnees is None:
        return None

    # Cas de repli : e1_lexical_enronqa.json ne contient que des rangs, sans
    # texte de question ni doc_id attendu ; il est inutilisable ici.
    if isinstance(donnees, dict) and "rangs_bruts" in donnees:
        return "RANGS_SEULS"

    if not isinstance(donnees, list):
        return None

    paires = []
    for entree in donnees:
        if not isinstance(entree, dict):
            return None
        question = (entree.get("question") or entree.get("query")
                   or entree.get("q"))
        doc_id = (entree.get("doc_id") or entree.get("document_id")
                 or entree.get("doc_id_attendu") or entree.get("gold_doc_id")
                 or entree.get("answer_doc_id"))
        reponse = entree.get("reponse") or entree.get("answer")
        if question is None or doc_id is None:
            return None
        paires.append({"question": question, "doc_id_attendu": doc_id,
                       "reponse": reponse})
    return paires


def charger_recuperateur_lexical(corpus):
    """Construit un RecuperateurLexical sur l'index BM25 deja construit."""
    from src.index.recuperateurs import RecuperateurLexical

    chemin_index = Path(f"data/index_lexical/{corpus}.pkl")
    if not chemin_index.exists():
        print(f"  index lexical introuvable : {chemin_index}")
        return None

    # Le nom de la classe qui charge un .pkl BM25 a varie selon les versions
    # de src/index/lexical.py : j'essaie successivement les noms possibles.
    try:
        from src.index import lexical as mod_lexical
    except ImportError as e:
        print(f"  src/index/lexical.py introuvable ou en erreur : {e}")
        return None

    index = None
    for nom_classe in ("IndexLexical", "IndexBM25", "BM25Index"):
        classe = getattr(mod_lexical, nom_classe, None)
        if classe is not None:
            try:
                index = classe.charger(chemin_index)
                break
            except AttributeError:
                try:
                    index = classe(chemin_index)
                    break
                except Exception:
                    continue
    if index is None:
        print("  aucune classe d'index lexical reconnue dans src/index/lexical.py")
        print("  envoyer ce fichier pour completer l'ancre")
        return None

    return RecuperateurLexical(index, source=None)


def afficher_question(numero, paire, recuperateur, documents_par_id, ks,
                      longueur):
    k_max = max(ks)
    print(f"\n{'=' * 70}")
    print(f"QUESTION #{numero}")
    print(f"{'=' * 70}")
    print(f"Q : {paire['question']}")
    if paire.get("reponse"):
        print(f"Reponse attendue : {paire['reponse']}")
    print(f"Document attendu (doc_id) : {paire['doc_id_attendu']}")

    fragments = recuperateur(paire["question"], n=k_max)

    print(f"\nDocuments recuperes (top {k_max}) :")
    rang_trouve = None
    for rang, fragment in enumerate(fragments, start=1):
        marque = ""
        if str(fragment.doc_id) == str(paire["doc_id_attendu"]):
            marque = "  <-- CORRESPOND AU DOCUMENT ATTENDU"
            rang_trouve = rang
        extrait = fragment.text[:longueur].replace("\n", " ")
        print(f"  [{rang:>2}] score={fragment.score:.4f}  {fragment.doc_id}{marque}")
        print(f"        {extrait}...")

    print("\nRecall par k :")
    for k in sorted(ks):
        trouve = rang_trouve is not None and rang_trouve <= k
        print(f"  recall@{k} : {'OUI' if trouve else 'non'}"
              + (f"  (rang {rang_trouve})" if trouve else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True, choices=list(SCHEMAS))
    ap.add_argument("--n", type=int, default=3,
                    help="nombre de questions tirees au hasard")
    ap.add_argument("--index", default=None,
                    help="indices precis, separes par des virgules, "
                         "prioritaire sur --n")
    ap.add_argument("--k", default="5,10",
                    help="valeurs de k separees par des virgules")
    ap.add_argument("--graine", type=int, default=42)
    ap.add_argument("--longueur", type=int, default=220)
    ap.add_argument("--diagnostiquer", action="store_true",
                    help="affiche les chemins essayes sans lancer de requete")
    args = ap.parse_args()

    ks = [int(x) for x in args.k.split(",")]

    print(f"Recherche du fichier de paires pour '{args.corpus}'...")
    chemin_ref, donnees = trouver_reference(args.corpus,
                                            diagnostiquer=args.diagnostiquer)
    if chemin_ref is None:
        print(f"\nAUCUN fichier de paires trouve parmi les candidats connus "
              f"pour '{args.corpus}' :")
        for c in CANDIDATS_REFERENCE.get(args.corpus, []):
            print(f"  - {c}")
        print("\nEnvoie le nom exact du fichier qui contient question + "
              "doc_id attendu pour ce corpus, ou lance run_e1_lexical.py "
              "--aide pour verifier son chemin de sortie.")
        return 1
    print(f"  trouve : {chemin_ref}")

    paires = normaliser_paires(donnees, args.corpus)
    if paires == "RANGS_SEULS":
        print(f"\n{chemin_ref} ne contient que des rangs agreges "
              "(rangs_bruts), pas les questions ni les doc_id attendus en "
              "clair. Ce fichier ne permet pas d'afficher des exemples "
              "question/reponse. Il faut le fichier de paires source utilise "
              "par run_e1_lexical.py pour produire ces rangs.")
        return 1
    if paires is None:
        print(f"\nStructure de {chemin_ref} non reconnue automatiquement. "
              "Colle les 3 premieres lignes de ce fichier pour que "
              "normaliser_paires() soit ajuste sur les vrais noms de champs.")
        return 1
    print(f"  {len(paires)} paires question/reponse chargees")

    if args.diagnostiquer:
        return 0

    print(f"Chargement de l'index lexical pour '{args.corpus}'...")
    recuperateur = charger_recuperateur_lexical(args.corpus)
    if recuperateur is None:
        return 1

    if args.index:
        indices = [int(x) for x in args.index.split(",")]
    else:
        alea = random.Random(args.graine)
        indices = sorted(alea.sample(range(len(paires)),
                                     min(args.n, len(paires))))

    print(f"\nQuestions affichees (indices {indices}) :")
    for i, idx in enumerate(indices, start=1):
        afficher_question(i, paires[idx], recuperateur, None, ks,
                          args.longueur)

    return 0


if __name__ == "__main__":
    sys.exit(main())
