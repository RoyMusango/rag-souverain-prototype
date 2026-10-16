r"""
Examine la fusion par rangs reciproques : y a-t-il quelque chose a gagner ?

    python scripts\sonder_fusion.py --corpus banque

TROIS QUESTIONS, DANS L'ORDRE

    1. PLAFOND   combien de questions sont trouvees par au moins une des deux
                 voies ? Aucune fusion ne peut faire mieux.
    2. MARGE     ce plafond depasse-t-il la meilleure voie seule ? Sinon, inutile
                 de chercher une ponderation : il n'y a rien a gagner.
    3. POIDS     s'il y a une marge, quel poids la recupere, et ce poids
                 marche-t-il sur les deux corpus ?

POURQUOI COMMENCER PAR LE PLAFOND

Tester plusieurs poids et garder le meilleur reviendrait a regler la fusion
sur les donnees qui servent a mesurer le gain. Le plafond ne depend d'aucun
reglage : c'est une borne haute, valable pour toute ponderation. S'il ne
laisse aucune marge, pas besoin de tester des poids, et la reponse ne
depend d'aucun ajustement.

Aucun appel facture : les deux voies tournent en local.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.commun import config as mod_config                 # noqa: E402
from src.evaluation import e1_hybridation as e1             # noqa: E402
from src.evaluation import montage_gpu as montage           # noqa: E402

CORPUS = {
    "enronqa": ("data/enronqa/enronqa_qa.jsonl",
                "data/index_lexical/enronqa.pkl"),
    "finqa": ("data/finqa/finqa_qa.jsonl",
              "data/index_lexical/finqa.pkl"),
    "banque": ("data/banque/banque_qa.jsonl",
               "data/index_lexical/banque.pkl"),
}

K_RRF = 60


def rang_de(resultats, attendu):
    """Rang (a partir de 1) du document attendu, ou None s'il est absent."""
    for rang, fragment in enumerate(resultats, start=1):
        if fragment.doc_id == attendu:
            return rang
    return None


def rrf_trouve(rangs_lex, rangs_den, attendu, poids_dense, k_final):
    """Le document attendu est-il dans le top-k de la fusion ponderee ?"""
    scores = defaultdict(float)
    for doc, rang in rangs_lex.items():
        scores[doc] += 1.0 / (K_RRF + rang)
    for doc, rang in rangs_den.items():
        scores[doc] += poids_dense / (K_RRF + rang)
    ordonnes = sorted(scores.items(), key=lambda t: -t[1])[:k_final]
    return any(doc == attendu for doc, _ in ordonnes)


def main():
    p = argparse.ArgumentParser(description="Sonde de la fusion RRF")
    p.add_argument("--corpus", choices=tuple(CORPUS), default="banque")
    p.add_argument("--questions", type=int, default=200)
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--profondeur", type=int, default=100,
                   help="candidats recuperes par voie avant fusion")
    p.add_argument("--graine", type=int, default=42)
    p.add_argument("--sortie", default=None)
    a = p.parse_args()

    chemin_paires, chemin_lexical = CORPUS[a.corpus]
    paires = e1.charger_paires(chemin_paires)
    echantillon = e1.echantillonner(paires, nombre=a.questions,
                                    graine=a.graine)
    print(f"corpus {a.corpus} : {len(echantillon)} questions, "
          f"profondeur {a.profondeur}\n")

    config = mod_config.Config()
    vectoriseur = montage.charger_vectoriseur(config)
    index_dense = montage.charger_index_dense(config)
    index_lexical = montage.charger_index_lexical(chemin_lexical)
    fabrique = montage.fabrique(config, index_dense, index_lexical,
                                vectoriseur, corpus=a.corpus)
    rec_lex = fabrique("lexical")
    rec_den = fabrique("dense")
    if rec_lex is None or rec_den is None:
        raise SystemExit("une des deux voies est indisponible")

    par_question = []
    for i, paire in enumerate(echantillon, start=1):
        if i % 25 == 0:
            print(f"  {i}/{len(echantillon)}")
        attendu = paire["doc_id"]
        lex = rec_lex.rechercher(paire["question"], n=a.profondeur)
        den = rec_den.rechercher(paire["question"], n=a.profondeur)
        par_question.append({
            "attendu": attendu,
            "rangs_lex": {f.doc_id: r for r, f in enumerate(lex, start=1)},
            "rangs_den": {f.doc_id: r for r, f in enumerate(den, start=1)},
            "rang_lex": rang_de(lex, attendu),
            "rang_den": rang_de(den, attendu),
        })

    n = len(par_question)
    dans = lambda r: r is not None and r <= a.k   # noqa: E731
    lex_seul = sum(1 for q in par_question if dans(q["rang_lex"]))
    den_seul = sum(1 for q in par_question if dans(q["rang_den"]))
    union = sum(1 for q in par_question
                if dans(q["rang_lex"]) or dans(q["rang_den"]))
    den_sauve = sum(1 for q in par_question
                    if not dans(q["rang_lex"]) and dans(q["rang_den"]))

    print("\n" + "=" * 68)
    print(f"1. LE PLAFOND, a k = {a.k}")
    print("=" * 68)
    print(f"  lexical seul            {lex_seul:4d} / {n}   "
          f"{lex_seul / n:.4f}")
    print(f"  dense seul              {den_seul:4d} / {n}   "
          f"{den_seul / n:.4f}")
    print(f"  UNION des deux          {union:4d} / {n}   {union / n:.4f}")
    meilleur = max(lex_seul, den_seul)
    print(f"\n  marge au-dessus de la meilleure voie seule : "
          f"{(union - meilleur) / n:+.4f}  ({union - meilleur} questions)")
    print(f"  questions que SEUL le dense rapporte       : {den_sauve}")

    print("\n" + "=" * 68)
    print("2. CE QUE DONNE VRAIMENT UNE PONDERATION")
    print("=" * 68)
    print("  poids du dense | rappel@%d | ecart au meilleur seul" % a.k)
    lignes = []
    for poids in (0.0, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 4.0):
        trouve = sum(1 for q in par_question
                     if rrf_trouve(q["rangs_lex"], q["rangs_den"],
                                   q["attendu"], poids, a.k))
        lignes.append((poids, trouve))
        print(f"  {poids:>13.2f} | {trouve / n:>8.4f} | "
              f"{(trouve - meilleur) / n:+.4f}")

    print(f"""
  LECTURE. Avec un poids nul, la fusion EST le lexical seul ; avec un poids
  tres grand, elle revient au dense seul. Avec le bon poids, elle ne fait
  donc jamais pire que la meilleure voie. Ce qui compte, c'est le plafond
  ci-dessus : {union / n:.4f}.
""")

    if a.sortie:
        chemin = Path(a.sortie)
        chemin.mkdir(parents=True, exist_ok=True)
        with open(chemin / "sonde_fusion.json", "w", encoding="utf-8") as f:
            json.dump({
                "corpus": a.corpus, "questions": n, "k": a.k,
                "profondeur": a.profondeur,
                "lexical": lex_seul / n, "dense": den_seul / n,
                "union": union / n,
                "marge": (union - meilleur) / n,
                "sauvees_par_le_dense": den_sauve,
                "balayage": [{"poids_dense": p, "rappel": t / n}
                             for p, t in lignes],
            }, f, ensure_ascii=False, indent=2)
        print(f"  ecrit : {chemin / 'sonde_fusion.json'}")


if __name__ == "__main__":
    main()
