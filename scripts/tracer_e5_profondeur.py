r"""
Figure E5, le rappel en fonction de la profondeur de recherche.

    .venv\Scripts\python.exe scripts\tracer_e5_profondeur.py

MOTIVATION

La version precedente ne comportait que deux points, k=10 et k=100, et
suggerait une lecture simple : la cible est releguee, non perdue. Six points
montrent la forme reelle de la courbe, qui apporte deux informations
supplementaires.

AXE DES ABSCISSES LOGARITHMIQUE

Les valeurs de k vont de 10 a 500. Sur une echelle lineaire, les quatre
premiers points seraient tasses contre l'axe et la partie informative de la
courbe deviendrait illisible. L'echelle logarithmique est la representation
adaptee a un balayage a pas multiplicatif.

ZONE k > 200 GRISEE

Le corpus bancaire compte 1500 notes. A k=500, le tiers du corpus est
rapporte et les quatre regimes convergent entre 0,95 et 0,99 : l'ecart entre
eux se reduit a quelques questions sur 200 et n'est plus interpretable. Il
s'agit d'une saturation de la mesure et non d'un resultat. Je grise cette
zone plutot que de la retirer, afin de rendre explicite la raison pour
laquelle elle n'est pas interpretee.
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

# Memes couleurs que les autres figures du chapitre : les regimes doivent se
# reconnaitre d'une figure a l'autre.
REGIMES = [
    ("brut", "requête brute", "#2b6cb0", "o", "-"),
    ("generalise-1", "généralisée, cran 1", "#2f855a", "s", "-"),
    ("masque", "masquée", "#a0aec0", "^", "--"),
    ("generalise-2", "généralisée, cran 2", "#c05621", "D", "--"),
]


def charger():
    """Lit toutes les executions du balayage, indexees par k."""
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
        # Placee dans le creux de la bande : entre k=200 et k=500, les courbes
        # protegees passent de 0,54 a 0,97, et la zone basse est donc libre.
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
    # A gauche et a mi-hauteur : seule zone que ne traverse aucune courbe.
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

    # Le point de dimensionnement : la profondeur a partir de laquelle chaque
    # regime protege depasse la moitie du rappel de la requete brute.
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
