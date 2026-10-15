r"""
Figures E6, justesse du routage reflexif.

    python scripts\tracer_e6.py

DEUX FICHIERS DISTINCTS

Une premiere version reunissait les deux panneaux dans une meme image. Ils
portent deux affirmations distinctes, et le premier comporte six classes aux
etiquettes longues : reunis, ils devenaient illisibles en projection.

    e6_par_classe.png   justesse selon l'emplacement de la reponse
    e6_erreurs.png      les deux erreurs, globales puis sur les cas difficiles

La seconde figure porte le resultat, la premiere l'explique.

AUCUN TITRE, AUCUNE NOTE DE BAS DE FIGURE

Le titre est porte par le document qui integre la figure. Les figures ne
contiennent que le nom des axes, la legende et la valeur des barres ;
l'interpretation figure dans le texte qui les accompagne.

PRECAUTION DE LECTURE

Le taux global de decisions correctes est de 96,5 %, et ce chiffre est
trompeur. Il agrege des classes de difficulte tres inegale : une requete qui
nomme la cle de son dossier est retrouvee mot pour mot par BM25, et le
routage y est trivial. Le seul taux global laisserait croire que le routeur
fonctionne sans reserve ; les deux figures montrent ou il echoue.

Les deux erreurs ne sont jamais additionnees : manquer une source externe
degrade la reponse, sortir inutilement expose la requete. La seconde est
determinante pour ce travail.
"""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

SORTIE = Path("figures")

# Ordre de lecture : facile puis difficile, interne puis externe. L'ordre
# alphabetique melangerait les deux et effacerait la progression.
ORDRE = [
    ("interne", "interne\nnomme\nle dossier", False),
    ("externe", "externe\nnomme\nle règlement", False),
    ("absente", "absente\nréponse\nnulle part", False),
    ("enrichissement-interdit", "sortie\nfermée\nabstention", False),
    ("interne-decrit", "interne\nDÉCRIT\nsans nommer", True),
    ("externe-implicite", "externe\nIMPLICITE\ntexte non nommé", True),
]

VERT = "#2f855a"
ROUGE = "#c53030"
GRIS = "#a0aec0"


def enregistrer(figure, nom):
    SORTIE.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "pdf"):
        chemin = SORTIE / f"{nom}.{extension}"
        figure.savefig(chemin, dpi=300, bbox_inches="tight")
        print(f"  ecrit : {chemin}")
    plt.close(figure)


# ------------------------------------------------------------------ figure 1

def figure_par_classe(par_classe):
    """Justesse selon l'emplacement reel de la reponse."""
    presentes = [(c, e, d) for c, e, d in ORDRE if c in par_classe]
    etiquettes = [f"{e}\n{par_classe[c]['cas']} cas" for c, e, d in presentes]
    valeurs = [par_classe[c]["taux_correct"] for c, _, _ in presentes]

    figure, axes = plt.subplots(figsize=(9.6, 4.8))
    barres = axes.bar(
        range(len(presentes)), valeurs, width=0.6,
        color=[VERT if v >= 0.999 else ROUGE for v in valeurs],
        edgecolor="white",
        hatch=["//" if d else "" for _, _, d in presentes])

    for barre, valeur in zip(barres, valeurs):
        axes.text(barre.get_x() + barre.get_width() / 2, valeur + 0.025,
                  f"{valeur:.0%}", ha="center", fontsize=10.5,
                  fontweight="bold")

    # Le trait separe les requetes qui nomment leur cible de celles qui la
    # decrivent : c'est la lecture principale de la figure.
    frontiere = sum(1 for _, _, d in presentes if not d)
    if 0 < frontiere < len(presentes):
        axes.axvline(frontiere - 0.5, color="#4a5568", linestyle="--",
                     linewidth=1.2)
        axes.text(frontiere / 2 - 0.5, 1.16, "la requête NOMME sa cible",
                  ha="center", fontsize=9.5, color="#4a5568")
        axes.text((frontiere + len(presentes)) / 2 - 0.5, 1.16,
                  "elle la DÉCRIT seulement", ha="center", fontsize=9.5,
                  color="#4a5568", fontweight="bold")

    axes.set_xticks(range(len(presentes)))
    axes.set_xticklabels(etiquettes, fontsize=8.5)
    axes.set_ylim(0, 1.24)
    axes.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    axes.set_ylabel("taux de décision correcte", fontsize=10)
    axes.grid(alpha=0.3, axis="y")
    axes.set_axisbelow(True)

    figure.subplots_adjust(left=0.085, right=0.985, top=0.97, bottom=0.19)
    enregistrer(figure, "e6_par_classe")


# ------------------------------------------------------------------ figure 2

def figure_erreurs(mesures):
    """Les deux erreurs asymetriques, globales puis sur les cas difficiles."""
    couples = [
        ("Franchissement\ninjustifié",
         mesures["taux_franchissement_injustifie"],
         mesures["franchissement_injustifie_sur_decrit"]),
        ("Franchissement\nmanqué",
         mesures["taux_franchissement_manque"],
         mesures["franchissement_manque_sur_implicite"]),
    ]

    figure, axes = plt.subplots(figsize=(7.6, 4.8))
    largeur = 0.32
    marge = max(0.25, max(v or 0.0 for _, g, d in couples
                          for v in (g, d)) * 1.45) * 0.022
    for rang, (_, global_, difficile) in enumerate(couples):
        axes.bar(rang - largeur / 2, global_ or 0.0, width=largeur,
                 color=GRIS, edgecolor="white",
                 label="tout le jeu" if rang == 0 else None)
        axes.bar(rang + largeur / 2, difficile or 0.0, width=largeur,
                 color=ROUGE, edgecolor="white", hatch="//",
                 label="requêtes descriptives" if rang == 0 else None)
        for decalage, valeur in ((-largeur / 2, global_),
                                 (largeur / 2, difficile)):
            axes.text(rang + decalage, (valeur or 0.0) + marge,
                      f"{(valeur or 0.0):.1%}".replace(".", ","),
                      ha="center", fontsize=11, fontweight="bold")

    axes.set_xticks(range(len(couples)))
    axes.set_xticklabels([t for t, _, _ in couples], fontsize=9.5)
    # L'echelle suit la barre la plus haute. Fixee a 1,0, elle ecrasait les
    # quatre barres du jeu etendu contre l'axe : sur le corpus corrige, la
    # pire valeur est de 24 % et non plus de 100 %.
    haut = max(v or 0.0 for _, g, d in couples for v in (g, d))
    plafond = max(0.25, haut * 1.45)
    pas = 0.05 if plafond <= 0.45 else 0.2
    axes.set_ylim(0, plafond)
    graduations, valeur = [], 0.0
    while valeur <= plafond + 1e-9:
        graduations.append(round(valeur, 2))
        valeur += pas
    axes.set_yticks(graduations)
    axes.set_ylabel("taux d'erreur", fontsize=10)
    axes.grid(alpha=0.3, axis="y")
    axes.set_axisbelow(True)
    # Coin superieur droit : les barres de droite sont nulles et laissent cet
    # emplacement libre. En haut a gauche, la legende recouvrait le 100 %.
    axes.legend(fontsize=9, loc="upper right", frameon=False)

    figure.subplots_adjust(left=0.105, right=0.985, top=0.97, bottom=0.185)
    enregistrer(figure, "e6_erreurs")


def main():
    parseur = argparse.ArgumentParser(description="Figures E6")
    # Jeu etendu v2, sur le corpus bancaire corrige : 195 cas, dont 17
    # requetes descriptives au lieu de 6. Le dossier resultats/e6 correspond
    # a une campagne de septembre, trop petite sur la classe determinante.
    parseur.add_argument("--json",
                         default="resultats/e6_etendu_v2/e6_routage.json")
    arguments = parseur.parse_args()

    chemin = Path(arguments.json)
    if not chemin.exists():
        raise SystemExit(
            f"introuvable : {chemin}\n"
            f"Lancez d'abord : python scripts\\run_e6.py")
    with open(chemin, encoding="utf-8") as f:
        rapport = json.load(f)

    print(f"lecture : {chemin}  ({rapport['cas']} cas)")
    mesures = rapport["mesures"]

    figure_par_classe(mesures["par_classe"])
    figure_erreurs(mesures)


if __name__ == "__main__":
    main()
