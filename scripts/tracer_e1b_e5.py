r"""
Figures E1b et E5.

    python scripts\tracer_e1b_e5.py

Deux fichiers, deux affirmations.

    e1b_deux_corpus.png   la fusion ne depasse jamais le meilleur versant seul
    e5_profondeur.png     la generalisation relegue la cible sans l'effacer

Comme pour les autres figures, aucun titre dans les images : seuls le nom des
axes, la legende et la valeur des barres y figurent.

ABSENCE DE FIGURE POUR E4

Son resultat tient en deux valeurs identiques sur les deux corpus : une
integrite de 1,0000 et 100 % de fragments a quatre niveaux. La seule
difference est binaire (la pagination est reelle ou non). Un tableau la
presente mieux qu'un graphique, ou deux barres egales masqueraient le
contraste pertinent.
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

SORTIE = Path("figures")

COULEURS = {"dense": "#2b6cb0", "lexical": "#dd6b20", "fusion": "#2f855a"}
LIBELLES = {"dense": "Dense seul", "lexical": "Lexical seul (BM25)",
            "fusion": "Fusion des deux"}

REGIMES = [
    ("brut", "requête\ntelle quelle"),
    ("masque", "nom\nmasqué"),
    ("generalise-1", "généralisée\n1er cran"),
    ("generalise-2", "généralisée\n2e cran"),
]


def enregistrer(figure, nom):
    SORTIE.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "pdf"):
        chemin = SORTIE / f"{nom}.{extension}"
        figure.savefig(chemin, dpi=300, bbox_inches="tight")
        print(f"  ecrit : {chemin}")
    plt.close(figure)


def lire(chemin):
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ figure 1

def figure_e1b():
    """Les trois configurations, sur les deux corpus mesures."""
    corpus = [
        ("EnronQA\n73 772 courriels", "resultats/e1b/e1b_hybridation.json"),
        ("FinQA\n7 134 rapports", "resultats/e1b_finqa/e1b_hybridation.json"),
    ]
    donnees = []
    for etiquette, chemin in corpus:
        if not Path(chemin).exists():
            print(f"  absent, ignore : {chemin}")
            continue
        d = lire(chemin)
        cle = f"recall@{d['k']}"
        donnees.append((etiquette, {n: m[cle]["moyenne"]
                                    for n, m in d["resultats"].items()}))
    if not donnees:
        raise SystemExit("aucun resultat E1b trouve")

    configurations = ["dense", "lexical", "fusion"]
    figure, axes = plt.subplots(figsize=(8.6, 4.8))
    largeur = 0.8 / len(configurations)

    for rang, config in enumerate(configurations):
        valeurs = [d.get(config, 0.0) for _, d in donnees]
        positions = [i + rang * largeur - 0.4 + largeur / 2
                     for i in range(len(donnees))]
        barres = axes.bar(positions, valeurs, width=largeur * 0.9,
                          color=COULEURS[config], edgecolor="white",
                          label=LIBELLES[config])
        for barre, valeur in zip(barres, valeurs):
            axes.text(barre.get_x() + barre.get_width() / 2, valeur + 0.014,
                      f"{valeur:.3f}", ha="center", fontsize=9)

    axes.set_xticks(range(len(donnees)))
    axes.set_xticklabels([e for e, _ in donnees], fontsize=10)
    axes.set_ylim(0, 1.10)
    axes.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    axes.set_ylabel("Rappel@10", fontsize=11)
    axes.grid(alpha=0.3, axis="y")
    axes.set_axisbelow(True)
    axes.legend(fontsize=9.5, loc="lower center", ncol=3,
                bbox_to_anchor=(0.5, -0.26), frameon=False)

    figure.subplots_adjust(left=0.115, right=0.98, top=0.97, bottom=0.22)
    enregistrer(figure, "e1b_deux_corpus")


# ------------------------------------------------------------------ figure 2

def figure_e5():
    """Le meme jeu de questions, interroge a dix puis a cent resultats."""
    chemins = {10: "resultats/e5/e5_cout.json",
               100: "resultats/e5_profondeur/e5_cout.json"}
    mesures = {}
    for k, chemin in chemins.items():
        if not Path(chemin).exists():
            print(f"  absent, ignore : {chemin}")
            continue
        d = lire(chemin)
        cle = f"recall@{d['k']}"
        mesures[d["k"]] = {n: m[cle]["moyenne"]
                           for n, m in d["resultats"].items()}
    if len(mesures) < 2:
        raise SystemExit("il faut les deux mesures, k=10 et k=100")

    figure, axes = plt.subplots(figsize=(8.8, 4.8))
    largeur = 0.36
    couleurs = {10: "#a0aec0", 100: "#2b6cb0"}

    for rang, (k, valeurs) in enumerate(sorted(mesures.items())):
        hauteurs = [valeurs.get(nom, 0.0) for nom, _ in REGIMES]
        positions = [i + rang * largeur - largeur / 2
                     for i in range(len(REGIMES))]
        barres = axes.bar(positions, hauteurs, width=largeur * 0.9,
                          color=couleurs[k], edgecolor="white",
                          label=f"Rappel@{k}")
        for barre, valeur in zip(barres, hauteurs):
            axes.text(barre.get_x() + barre.get_width() / 2, valeur + 0.014,
                      f"{valeur:.3f}", ha="center", fontsize=9)

    axes.set_xticks(range(len(REGIMES)))
    axes.set_xticklabels([e for _, e in REGIMES], fontsize=9.5)
    axes.set_ylim(0, 1.0)
    axes.set_yticks([0, 0.2, 0.4, 0.6, 0.8])
    axes.set_ylabel("Rappel", fontsize=11)
    axes.grid(alpha=0.3, axis="y")
    axes.set_axisbelow(True)
    axes.legend(fontsize=9.5, loc="upper right", frameon=False)

    figure.subplots_adjust(left=0.115, right=0.98, top=0.97, bottom=0.14)
    enregistrer(figure, "e5_profondeur")


if __name__ == "__main__":
    figure_e1b()
    figure_e5()
