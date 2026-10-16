r"""
Figure : rang auquel chaque question trouve sa reponse, selon la voie.

    .venv\Scripts\python.exe scripts\tracer_recherche_questions.py

Lit `resultats/recherche_questions_rangs.json`, qui regroupe les rangs des
trois campagnes (lexicale, dense, fusion) de run_recherche_questions.py
sur les douze questions reglementaires ecrites a la main.

CE QUE LA FIGURE APPORTE PAR RAPPORT A UN TAUX

Un rappel de 0,92 ne dit pas si la reponse arrive au premier ou au
vingt-cinquieme rang, ni si les trois voies echouent sur les memes
questions. La figure le montre : on voit si les deux voies se completent ou
font les memes erreurs.

ECHELLE LOGARITHMIQUE

Les rangs vont de 1 a 14, plus un cas absent. En echelle lineaire, la
difference entre les rangs 1 et 3, la plus importante pour un utilisateur,
serait invisible a cote d'un rang 14.
"""

import io
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

SOURCE = "resultats/recherche_questions_rangs.json"
SORTIE = "figures"
ABSENT = 30          # position d'affichage des cas non trouves

VOIES = [
    ("lexical", "lexicale (BM25)", "#2b6cb0", "o"),
    ("dense", "dense (BGE-M3)", "#c05621", "s"),
    ("fusion", "fusion des deux", "#2f855a", "D"),
]


def main():
    if not os.path.exists(SOURCE):
        raise SystemExit(
            "introuvable : %s\nLancez run_recherche_questions.py pour les "
            "trois configurations, puis regroupez les rangs." % SOURCE)
    with open(SOURCE, encoding="utf-8") as f:
        donnees = json.load(f)

    questions = sorted(int(n) for n in donnees["lexical"])
    figure, axes = plt.subplots(figsize=(9.0, 5.6))

    # Bande des cinq premiers rangs : ce qu'un utilisateur regarde vraiment
    # avant de reformuler sa question.
    axes.axvspan(0.9, 5, color="#f0fff4", zorder=0)
    # L'axe des ordonnees est inverse plus bas : le haut du graphique
    # correspond donc aux valeurs negatives.
    axes.text(2.2, -0.85, "cinq premiers résultats",
              fontsize=9, color="#2f855a", ha="center")

    decalage = {"lexical": 0.24, "dense": 0.0, "fusion": -0.24}
    for cle, libelle, couleur, marque in VOIES:
        x, y = [], []
        for rang, numero in enumerate(questions):
            valeur = donnees[cle][str(numero)]
            x.append(ABSENT if valeur is None else valeur)
            y.append(rang + decalage[cle])
        axes.scatter(x, y, color=couleur, marker=marque, s=46,
                     label=libelle, zorder=3, edgecolors="white",
                     linewidths=0.6)

    axes.axvline(ABSENT * 0.72, color="#a0aec0", linestyle=":", linewidth=1)
    axes.text(ABSENT, -0.85, "non trouvé", fontsize=8.5,
              color="#718096", ha="center")

    axes.set_yticks(range(len(questions)))
    axes.set_yticklabels(["Q%d" % n for n in questions], fontsize=9.5)
    axes.invert_yaxis()
    axes.set_xscale("log")
    axes.set_xticks([1, 2, 3, 5, 10, 25, ABSENT])
    axes.set_xticklabels(["1", "2", "3", "5", "10", "25", "absent"],
                         fontsize=9.5)
    axes.minorticks_off()
    axes.set_xlim(0.85, ABSENT * 1.35)
    axes.set_xlabel("rang auquel le passage attendu est rapporté "
                    "(échelle logarithmique)", fontsize=10.5)
    axes.grid(alpha=0.3, axis="x", zorder=1)
    axes.set_axisbelow(True)
    axes.legend(fontsize=9.5, loc="lower right", frameon=False)

    figure.subplots_adjust(left=0.08, right=0.98, top=0.94, bottom=0.11)
    os.makedirs(SORTIE, exist_ok=True)
    for extension in ("png", "pdf"):
        chemin = os.path.join(SORTIE, "recherche_par_question.%s" % extension)
        figure.savefig(chemin, dpi=300, bbox_inches="tight")
        print("  ecrit :", chemin)
    plt.close(figure)

    print()
    for cle, libelle, _, _ in VOIES:
        valeurs = [donnees[cle][str(n)] for n in questions]
        for k in (5, 10, 25):
            atteint = sum(1 for v in valeurs if v is not None and v <= k)
            print("  %-18s rappel@%-3d %.4f  (%d sur %d)"
                  % (libelle if k == 5 else "", k, atteint / len(questions),
                     atteint, len(questions)))
        print()


if __name__ == "__main__":
    main()
