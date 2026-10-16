r"""
Figure E5, le rappel en fonction de la profondeur de recherche.

    .venv\Scripts\python.exe scripts\tracer_e5_profondeur.py

POURQUOI

La version precedente n'avait que deux points, k=10 et k=100, avec un
message simple : la cible descend dans le classement mais ne disparait pas.
Avec six points, on voit la vraie forme de la courbe.

ABSCISSES EN ECHELLE LOGARITHMIQUE

k va de 10 a 500. En echelle lineaire, les quatre premiers points seraient
serres contre l'axe et la partie interessante de la courbe serait
illisible. L'echelle logarithmique convient a des valeurs de k qui sont
multipliees a chaque pas.

ZONE k > 200 EN GRIS

Le corpus bancaire a 1500 notes. A k=500, on ramene un tiers du corpus, et
les quatre regimes se rejoignent entre 0,95 et 0,99. L'ecart entre eux
tient alors a quelques questions sur 200 et ne veut plus rien dire : la
mesure sature. Je mets cette zone en gris au lieu de la retirer, pour qu'on
voie pourquoi elle n'est pas interpretee.

Le script lit les dossiers resultats/e5_profondeur_k<k>/ (balayage v1, avant
la correction du gabarit `aml`). Pour la v2, voir JOURNAL_DONNEES, E5b v2.
"""

import glob
import io
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

SORTIE = "figures"
SATURATION = 200          # au-dela, k depasse 13 % du corpus

# Memes couleurs que les autres figures du chapitre, pour reconnaitre les
# regimes d'une figure a l'autre.
REGIMES = [
    ("brut", "requête brute", "#2b6cb0", "o", "-"),
    ("generalise-1", "généralisée, cran 1", "#2f855a", "s", "-"),
    ("masque", "masquée", "#a0aec0", "^", "--"),
    ("generalise-2", "généralisée, cran 2", "#c05621", "D", "--"),
]


def charger():
    """Lit tous les resultats du balayage, ranges par k."""
    mesures = {}
    for chemin in glob.glob("resultats/e5_profondeur_k*/e5_cout.json"):
        with open(chemin, encoding="utf-8") as f:
            rapport = json.load(f)
        k = rapport["k"]
        mesures[k] = {
            regime: bloc["recall@%d" % k]["moyenne"]
            for regime, bloc in rapport["resultats"].items()
        }
    if not mesures:
        raise SystemExit(
            "aucun resultat de balayage trouve.\n"
            "Lancez d'abord run_e5.py pour plusieurs valeurs de --k, "
            "avec --sortie resultats\\e5_profondeur_k<k>")
    return dict(sorted(mesures.items()))


def tracer(mesures):
    ks = list(mesures)
    figure, axes = plt.subplots(figsize=(8.2, 5.0))

    if max(ks) > SATURATION:
        axes.axvspan(SATURATION, max(ks) * 1.08, color="#edf2f7", zorder=0)
        # Texte place en bas de la bande grise : entre k=200 et k=500, les
        # courbes protegees montent de 0,54 a 0,97, donc le bas est libre.
        axes.text(SATURATION * 1.55, 0.22,
                  "mesure saturée\nk > 13 % du corpus",
                  ha="center", fontsize=8.5, color="#4a5568")

    for cle, libelle, couleur, marque, trait in REGIMES:
        valeurs = [mesures[k].get(cle) for k in ks]
        axes.plot(ks, valeurs, marker=marque, linestyle=trait, color=couleur,
                  label=libelle, linewidth=1.8, markersize=5.5, zorder=3)

    axes.set_xscale("log")
    axes.set_xticks(ks)
    axes.set_xticklabels([str(k) for k in ks], fontsize=10)
    axes.minorticks_off()
    axes.set_xlabel("k, profondeur de recherche (échelle logarithmique)",
                    fontsize=10.5)
    axes.set_ylabel("Rappel@k", fontsize=10.5)
    axes.set_ylim(0, 1.04)
    axes.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    axes.grid(alpha=0.3, zorder=1)
    axes.set_axisbelow(True)
    # A gauche, a mi-hauteur : la seule zone qu'aucune courbe ne traverse.
    axes.legend(fontsize=9.5, loc="center left", frameon=False)

    figure.subplots_adjust(left=0.09, right=0.98, top=0.97, bottom=0.12)

    os.makedirs(SORTIE, exist_ok=True)
    for extension in ("png", "pdf"):
        chemin = os.path.join(SORTIE, "e5_courbe_profondeur.%s" % extension)
        figure.savefig(chemin, dpi=300, bbox_inches="tight")
        print("  ecrit :", chemin)
    plt.close(figure)


def main():
    mesures = charger()
    print("valeurs de k :", ", ".join(str(k) for k in mesures))
    tracer(mesures)

    # Regle de dimensionnement : a partir de quelle profondeur chaque regime
    # protege depasse la moitie du rappel de la requete brute.
    print("\nprofondeur necessaire pour atteindre la moitie du rappel brut :")
    for cle, libelle, _, _, _ in REGIMES[1:]:
        cible = mesures[min(mesures)]["brut"] / 2
        atteint = [k for k in mesures
                   if mesures[k].get(cle) is not None
                   and mesures[k][cle] >= cible and k <= SATURATION]
        rendu = ("k = %d" % min(atteint)) if atteint else "jamais sous k = 200"
        print("  %-22s %s" % (libelle, rendu))


if __name__ == "__main__":
    main()
