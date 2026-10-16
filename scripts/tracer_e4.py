r"""
Figure E4 : pourquoi un seul corpus permet la mesure a quatre niveaux.

    python scripts\tracer_e4.py

CE QUE MONTRE LA FIGURE

E4 donne les memes valeurs sur les deux corpus mesures : une integrite de
chaine de 1,0000 et 100 % de fragments a quatre niveaux d'adresse. Les
tracer donnerait quatre barres egales, qui n'apprennent rien.

La difference est ailleurs. Sur EnronQA, les quatre niveaux sont remplis,
mais le niveau page ne distingue rien : chaque courriel tient sur une page.
Sur EUR-Lex, il y a de vraies pages et le niveau page prend 141 valeurs.

La figure montre donc ce qui explique le resultat : le nombre de valeurs
distinctes du niveau page dans chaque corpus. On voit pourquoi la
profondeur d'attribution ne se mesure que sur EUR-Lex. C'est une propriete
des corpus, pas un defaut.

ECHELLE LINEAIRE

Six corpus a 1 et un a 141 : avec une echelle logarithmique, les six
premiers auraient une hauteur nulle et disparaitraient. En lineaire, ils
restent visibles sous forme de traits, et l'ecart saute aux yeux. La valeur
est ecrite au bout de chaque barre.
"""

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

SORTIE = Path("figures")
STRUCTURE = Path("resultats/e4_structure_corpus.json")

# Les deux corpus sur lesquels E4 a tourne, mis en couleur.
MESURES = ("EnronQA", "EUR-Lex")


def main():
    if not STRUCTURE.exists():
        raise SystemExit(
            f"introuvable : {STRUCTURE}\n"
            f"Ce fichier vient du releve de structure des corpus.")

    with open(STRUCTURE, encoding="utf-8") as f:
        donnees = json.load(f)

    # Ordre croissant : les corpus a une seule page d'abord, EUR-Lex au bout.
    lignes = sorted(donnees.items(), key=lambda t: t[1][1])
    noms = [n for n, _ in lignes]
    pages = [v[1] for _, v in lignes]
    passages = [v[0] for _, v in lignes]

    figure, axes = plt.subplots(figsize=(8.8, 4.4))
    couleurs = ["#2b6cb0" if n in MESURES else "#a0aec0" for n in noms]
    barres = axes.barh(range(len(noms)), pages, color=couleurs,
                       edgecolor="white", height=0.62)

    for barre, valeur in zip(barres, pages):
        axes.text(valeur + 2, barre.get_y() + barre.get_height() / 2,
                  str(valeur), va="center", fontsize=10, fontweight="bold")

    etiquettes = [f"{n}\n{p:,} passages".replace(",", " ")
                  for n, p in zip(noms, passages)]
    axes.set_yticks(range(len(noms)))
    axes.set_yticklabels(etiquettes, fontsize=9)
    axes.set_xlim(0, max(pages) * 1.18)
    axes.set_xlabel("valeurs distinctes du niveau « page »", fontsize=10)
    axes.grid(alpha=0.3, axis="x")
    axes.set_axisbelow(True)

    # Les deux corpus mesures sont en bleu, les autres en gris. Sinon on
    # lirait la figure comme une simple description des corpus, alors
    # qu'elle explique un resultat.
    axes.text(max(pages) * 0.42, 0.2,
              "en bleu, les deux corpus sur lesquels E4 a tourné",
              fontsize=9, color="#4a5568", style="italic")

    figure.subplots_adjust(left=0.185, right=0.98, top=0.97, bottom=0.155)
    SORTIE.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "pdf"):
        chemin = SORTIE / f"e4_pagination.{extension}"
        figure.savefig(chemin, dpi=300, bbox_inches="tight")
        print(f"  ecrit : {chemin}")
    plt.close(figure)


if __name__ == "__main__":
    main()
