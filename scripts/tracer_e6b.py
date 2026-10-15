r"""
Figure E6b : l'arbitrage de l'abstention par ignorance.

    python scripts\tracer_e6b.py

Deux courbes de sens oppose : plus le systeme exige de soutien externe avant
de repondre, plus il s'abstient lorsque rien ne porte la reponse, mais aussi
lorsque la reponse se trouvait a l'exterieur.

Aucun titre dans l'image. Le seuil effectivement retenu est marque, sans etre
presente comme un optimum : il n'a pas ete cale sur cette courbe.
"""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

SORTIE = Path("figures")
VERT = "#2f855a"
ROUGE = "#c53030"
GRIS = "#4a5568"


def main():
    p = argparse.ArgumentParser(description="Figure E6b")
    p.add_argument("--dossiers", nargs="+",
                   default=sorted(str(d) for d in Path("resultats").glob(
                       "e6b_seuil_*")))
    p.add_argument("--retenu", type=float, default=0.55,
                   help="seuil effectivement applique, marque sur la figure")
    p.add_argument("--nom", default="e6b_abstention")
    a = p.parse_args()

    points = []
    for dossier in a.dossiers:
        fichier = Path(dossier) / "e6b_abstention.json"
        if not fichier.exists():
            continue
        o = json.load(open(fichier, encoding="utf-8"))
        m, par = o["mesures"], o["parametres"]
        points.append((par.get("seuil_externe_effectif"),
                       m["abstention_par_ignorance"], m["silence_indu"]))
    points.sort()
    if not points:
        raise SystemExit("aucun resultat : lancez d'abord le balayage.")

    seuils = [x for x, _, _ in points]
    bons = [y for _, y, _ in points]
    mauvais = [z for _, _, z in points]

    figure, axes = plt.subplots(figsize=(8.0, 4.6))
    axes.plot(seuils, bons, "-o", color=VERT, linewidth=2.2, markersize=6,
              label="se tait quand la réponse n'existe nulle part")
    axes.plot(seuils, mauvais, "--s", color=ROUGE, linewidth=2.2,
              markersize=6, label="se tait alors que la réponse était dehors")

    for x, y, z in points:
        axes.annotate(f"{y:.0%}", (x, y), textcoords="offset points",
                      xytext=(0, 9), ha="center", fontsize=9,
                      color=VERT, fontweight="bold")
        axes.annotate(f"{z:.0%}", (x, z), textcoords="offset points",
                      xytext=(0, -16), ha="center", fontsize=9,
                      color=ROUGE, fontweight="bold")

    if a.retenu in seuils:
        axes.axvline(a.retenu, color=GRIS, linestyle=":", linewidth=1.4)
        axes.text(a.retenu, 1.09, "seuil appliqué", ha="center",
                  fontsize=9.5, color=GRIS)

    axes.set_xlabel("exigence de soutien externe avant de répondre")
    axes.set_ylabel("part des cas")
    axes.set_ylim(-0.08, 1.16)
    axes.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    axes.set_yticklabels(["0 %", "25 %", "50 %", "75 %", "100 %"])
    axes.grid(alpha=0.3, axis="y")
    axes.set_axisbelow(True)
    # Le coin superieur gauche est le seul emplacement libre : la courbe
    # verte y est basse et la rouge au plancher.
    axes.legend(fontsize=9.5, loc="upper left", frameon=False)

    SORTIE.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        chemin = SORTIE / f"{a.nom}.{ext}"
        figure.savefig(chemin, dpi=300, bbox_inches="tight")
        print(f"  ecrit : {chemin}")
    plt.close(figure)


if __name__ == "__main__":
    main()
