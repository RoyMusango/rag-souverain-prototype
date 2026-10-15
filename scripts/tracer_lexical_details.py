r"""
Figures complementaires sur la recuperation lexicale.

    python scripts\tracer_lexical_details.py

Deux figures, toutes deux lues depuis le JSON produit par run_e1_lexical.py.
Aucune valeur n'est ecrite en dur.

  C  distribution des rangs : position du document cherche
  D  comparaison au resultat publie : validation externe

Le script est separe de tracer_graphiques.py afin de ne pas modifier un
fichier deja verifie.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

SORTIE = Path("figures")

# Resultats publies par les auteurs du corpus, pour validation externe.
# Ryan, Xu, Nivera, Campos, "EnronQA: Towards Personalized RAG over Private
# Documents", arXiv:2505.00263, 2025, table 4. Rappel@5.
PUBLIE = {"BM25 (publie)": 0.875, "ColBERT (publie)": 0.541}


def enregistrer(figure, nom):
    SORTIE.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "pdf"):
        chemin = SORTIE / f"{nom}.{extension}"
        figure.savefig(chemin, dpi=300, bbox_inches="tight")
        print(f"  ecrit : {chemin}")
    plt.close(figure)


def lire(chemin):
    chemin = Path(chemin)
    if not chemin.exists():
        raise SystemExit(
            f"introuvable : {chemin}\n"
            f"Lancez d'abord : python scripts\\run_e1_lexical.py")
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def figure_distribution(donnees):
    """Position du document cherche, lorsqu'il est trouve.

    Une courbe de rappel indique combien de questions sont satisfaites, sans
    distinguer un document classe premier d'un document classe trentieme.
    Cette figure montre cette position et rend visible le plancher des
    questions jamais satisfaites.
    """
    rangs = donnees["rangs_bruts"]
    total = len(rangs)
    jamais = sum(1 for r in rangs if r is None)

    # Regroupement : les rangs eleves sont rares, les detailler n'apporte rien.
    tranches = ["1", "2-3", "4-5", "6-10", "11-20", "21-50", "absent"]

    def classer(rang):
        if rang is None:
            return "absent"
        if rang == 1:
            return "1"
        if rang <= 3:
            return "2-3"
        if rang <= 5:
            return "4-5"
        if rang <= 10:
            return "6-10"
        if rang <= 20:
            return "11-20"
        return "21-50"

    comptes = Counter(classer(r) for r in rangs)
    valeurs = [comptes.get(t, 0) for t in tranches]
    parts = [100 * v / total for v in valeurs]

    figure, axes = plt.subplots(figsize=(7.5, 4.2))
    couleurs = ["#2b6cb0"] * (len(tranches) - 1) + ["#c53030"]
    barres = axes.bar(tranches, parts, color=couleurs, edgecolor="white")

    for barre, valeur, part in zip(barres, valeurs, parts):
        if valeur:
            axes.text(barre.get_x() + barre.get_width() / 2,
                      part + 1, f"{valeur}", ha="center", fontsize=9)

    axes.set_xlabel("rang auquel le document cherche apparait")
    axes.set_ylabel("part des questions (%)")
    axes.set_title(
        f"Distribution des rangs — BM25 seul, {total} questions\n"
        f"{jamais} question(s) jamais satisfaite(s) dans les 50 premiers",
        fontsize=11)
    axes.grid(alpha=0.3, axis="y")
    axes.set_axisbelow(True)

    enregistrer(figure, "e1_lexical_distribution_rangs")


def figure_comparaison(donnees):
    """Rappel@5 obtenu, compare aux valeurs publiees sur le meme corpus.

    Il s'agit d'une validation de la chaine et non d'une comparaison de
    methodes : BM25 est reimplemente de part et d'autre. Un ecart important
    signalerait un defaut d'ingestion ou d'alignement, et non une
    superiorite.
    """
    notre = donnees["mesures"]["rappel@5"]
    questions = donnees["corpus"]["questions_evaluees"]

    etiquettes = [f"Notre mesure\n({questions} questions)"] + list(PUBLIE)
    valeurs = [notre] + list(PUBLIE.values())
    couleurs = ["#2b6cb0", "#718096", "#a0aec0"]

    figure, axes = plt.subplots(figsize=(6.5, 4.2))
    barres = axes.bar(etiquettes, valeurs, color=couleurs, edgecolor="white",
                      width=0.55)

    for barre, valeur in zip(barres, valeurs):
        axes.text(barre.get_x() + barre.get_width() / 2, valeur + 0.02,
                  f"{valeur:.3f}", ha="center", fontsize=10)

    ecart = abs(notre - PUBLIE["BM25 (publie)"])
    axes.set_ylabel("Rappel@5")
    axes.set_ylim(0, 1.05)
    axes.set_title(
        f"Validation externe sur EnronQA — ecart de {ecart:.3f} au resultat "
        f"publie\n(Ryan et al., arXiv:2505.00263, table 4)",
        fontsize=10)
    axes.grid(alpha=0.3, axis="y")
    axes.set_axisbelow(True)

    enregistrer(figure, "e1_lexical_validation_externe")


def figure_latence(donnees):
    """Distribution des latences de recherche.

    Une mediane ne renseigne pas sur la queue de distribution, qui determine
    pourtant l'experience percue. Je trace donc l'histogramme, avec la
    mediane et le p90 comme reperes.
    """
    latences = donnees.get("latences_ms")
    if not latences:
        raise SystemExit(
            "champ 'latences_ms' absent : appliquez d'abord le patch de "
            "run_e1_lexical.py, puis relancez la mesure.")

    mesures = donnees["mesures"]
    mediane = mesures["latence_mediane_ms"]
    p90 = mesures["latence_p90_ms"]

    figure, axes = plt.subplots(figsize=(7.5, 4.2))
    axes.hist(latences, bins=30, color="#2b6cb0", edgecolor="white")
    axes.axvline(mediane, color="#c53030", linestyle="--", linewidth=1.5,
                 label=f"mediane {mediane:.0f} ms")
    axes.axvline(p90, color="#dd6b20", linestyle=":", linewidth=1.5,
                 label=f"p90 {p90:.0f} ms")

    axes.set_xlabel("latence d'une recherche (ms)")
    axes.set_ylabel("nombre de requetes")
    axes.set_title(
        f"Latence de recuperation lexicale — {len(latences)} requetes\n"
        f"rank_bm25 en Python pur, sans index inverse, "
        f"{donnees['corpus']['documents']} documents",
        fontsize=10)
    axes.grid(alpha=0.3, axis="y")
    axes.set_axisbelow(True)
    axes.legend()

    enregistrer(figure, "e1_lexical_latence")


def main():
    parseur = argparse.ArgumentParser(description="Figures lexicales")
    parseur.add_argument(
        "--json",
        default="resultats/e1_lexical/e1_lexical_enronqa.json")
    arguments = parseur.parse_args()

    donnees = lire(arguments.json)
    print("figure : distribution des rangs")
    figure_distribution(donnees)
    print("figure : validation externe")
    figure_comparaison(donnees)
    if donnees.get("latences_ms"):
        print("figure : latence")
        figure_latence(donnees)


if __name__ == "__main__":
    main()
