r"""
Figures E7b, detecteurs sur le corpus bancaire.

    python scripts\tracer_e7b.py

Sans argument, le script prend la derniere execution e7b-banque du dossier
resultats. Pour en choisir une :

    python scripts\tracer_e7b.py --json resultats\e7b-banque-<horodatage>\e7b_banque.json

TROIS FICHIERS

Une premiere version mettait les trois panneaux dans une seule image, peu
lisible en projection : trois messages se melangeaient et les valeurs
etaient trop petites. Chaque figure a maintenant un seul message.

    e7b_qualite.png      rappel, precision, F1 des trois detecteurs
    e7b_debit.png        cout du detecteur le plus precis
    e7b_categories.png   rappel par categorie d'entite

PAS DE TITRE DANS LES FIGURES

Le titre est donne par le document qui contient la figure ; le mettre aussi
dans l'image le ferait apparaitre deux fois. Les figures ne contiennent que
le nom des axes, la legende et la valeur de chaque barre. L'explication est
dans le texte qui les accompagne.

ECHELLE DES ORDONNEES

La qualite et le rappel vont de 0 a 1, sans couper l'axe. Un axe qui
commencerait a 0,80 grossirait l'ecart de precision. L'ecart reel, 0,987
contre 0,892, se voit bien sur l'echelle complete. Que les rappels soient
presque egaux est le resultat : c'est la precision qui separe
les detecteurs, pas le rappel.
"""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

SORTIE = Path("figures")

# Memes couleurs que tracer_e7.py : les figures se lisent ensemble dans le
# chapitre 5, et un moteur doit garder la meme couleur partout.
COULEURS = {"spacy": "#2b6cb0", "camembert": "#2f855a", "presidio": "#a0aec0"}
LIBELLES = {"spacy": "spaCy (souverain)", "camembert": "CamemBERT (souverain)",
            "presidio": "Presidio"}
COURTS = {"spacy": "spaCy", "camembert": "CamemBERT", "presidio": "Presidio"}

# Detecteurs statistiques d'abord, deterministes ensuite. L'ordre alphabetique
# melangerait les deux familles, que la figure doit separer.
STATISTIQUES = ("PERSONNE", "LIEU", "ORGANISATION")
DETERMINISTES = ("IBAN", "CARTE", "IDENTIFIANT")


def derniere_execution():
    racine = Path("resultats")
    if not racine.exists():
        raise SystemExit("dossier 'resultats' introuvable")
    candidats = sorted(racine.glob("e7b-banque-*/e7b_banque.json"))
    if not candidats:
        raise SystemExit(
            "aucun e7b_banque.json trouve.\n"
            "Lancez d'abord : python scripts\\run_e7_banque.py "
            "--moteurs spacy,camembert,presidio --langue fr")
    return candidats[-1]


def enregistrer(figure, nom):
    SORTIE.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "pdf"):
        chemin = SORTIE / f"{nom}.{extension}"
        figure.savefig(chemin, dpi=300, bbox_inches="tight")
        print(f"  ecrit : {chemin}")
    plt.close(figure)


def ordonner(categories):
    connues = [c for c in STATISTIQUES + DETERMINISTES if c in categories]
    return connues + [c for c in categories if c not in connues]


def espacer(nombre):
    """12345 devient '12 345', plus lisible en projection."""
    return f"{nombre:,}".replace(",", " ")


# ------------------------------------------------------------------ figure 1

def figure_qualite(globales, moteurs):
    """Rappel, precision et F1 des trois detecteurs."""
    metriques = ["rappel", "precision", "f1"]
    etiquettes = ["Rappel", "Précision", "F1"]

    figure, axes = plt.subplots(figsize=(8.4, 4.8))
    largeur = 0.8 / len(moteurs)

    for rang, nom in enumerate(moteurs):
        valeurs = [globales[nom].get(m) or 0.0 for m in metriques]
        positions = [i + rang * largeur - 0.4 + largeur / 2
                     for i in range(len(metriques))]
        barres = axes.bar(positions, valeurs, width=largeur * 0.9,
                          color=COULEURS.get(nom, "#718096"),
                          edgecolor="white", label=LIBELLES.get(nom, nom))
        for barre, valeur in zip(barres, valeurs):
            axes.text(barre.get_x() + barre.get_width() / 2, valeur + 0.014,
                      f"{valeur:.3f}", ha="center", fontsize=9)

    axes.set_xticks(range(len(metriques)))
    axes.set_xticklabels(etiquettes, fontsize=11)
    axes.set_ylim(0, 1.10)
    axes.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    axes.set_ylabel("valeur (0 à 1)", fontsize=10)
    axes.grid(alpha=0.3, axis="y")
    axes.set_axisbelow(True)
    axes.legend(fontsize=9.5, loc="lower center", ncol=3,
                bbox_to_anchor=(0.5, -0.24), frameon=False)

    figure.subplots_adjust(left=0.10, right=0.98, top=0.97, bottom=0.20)
    enregistrer(figure, "e7b_qualite")


# ------------------------------------------------------------------ figure 2

def figure_debit(globales, moteurs):
    """Cout du detecteur le plus precis."""
    debits = [globales[nom].get("debit_car_s") or 0 for nom in moteurs]

    figure, axes = plt.subplots(figsize=(6.6, 4.4))
    barres = axes.bar([COURTS.get(n, n) for n in moteurs], debits,
                      color=[COULEURS.get(n, "#718096") for n in moteurs],
                      edgecolor="white", width=0.55)
    for barre, valeur in zip(barres, debits):
        axes.text(barre.get_x() + barre.get_width() / 2, valeur * 1.02,
                  espacer(valeur), ha="center", fontsize=10)

    axes.set_ylabel("débit (caractères/s)", fontsize=10)
    axes.set_ylim(0, max(debits) * 1.14 if debits else 1)
    axes.grid(alpha=0.3, axis="y")
    axes.set_axisbelow(True)
    axes.tick_params(axis="x", labelsize=10.5)

    figure.subplots_adjust(left=0.16, right=0.98, top=0.97, bottom=0.10)
    enregistrer(figure, "e7b_debit")


# ------------------------------------------------------------------ figure 3

def figure_categories(par_categorie, moteurs):
    """Rappel par categorie d'entite, avec l'etiquette exigee."""
    categories = ordonner(list(par_categorie))

    figure, axes = plt.subplots(figsize=(10.2, 4.8))
    largeur = 0.8 / len(moteurs)

    for rang, nom in enumerate(moteurs):
        valeurs = [par_categorie[c]["rappel"].get(nom) or 0.0
                   for c in categories]
        positions = [i + rang * largeur - 0.4 + largeur / 2
                     for i in range(len(categories))]
        barres = axes.bar(positions, valeurs, width=largeur * 0.9,
                          color=COULEURS.get(nom, "#718096"),
                          edgecolor="white", label=LIBELLES.get(nom, nom))
        for barre, valeur in zip(barres, valeurs):
            axes.text(barre.get_x() + barre.get_width() / 2, valeur + 0.014,
                      f"{valeur:.3f}", ha="center", fontsize=8)

    # Trait de separation entre les deux familles de detection : c'est le
    # message principal de la figure.
    frontiere = sum(1 for c in categories if c in STATISTIQUES)
    if 0 < frontiere < len(categories):
        axes.axvline(frontiere - 0.5, color="#4a5568", linestyle="--",
                     linewidth=1.1)
        axes.text(frontiere / 2 - 0.5, 1.075, "détecté par le modèle",
                  ha="center", fontsize=9, color="#4a5568")
        axes.text((frontiere + len(categories)) / 2 - 0.5, 1.075,
                  "détecté par expression régulière", ha="center", fontsize=9,
                  color="#4a5568")

    etiquettes = [f"{c}\n{espacer(par_categorie[c]['attendus'])} occ."
                  for c in categories]
    axes.set_xticks(range(len(categories)))
    axes.set_xticklabels(etiquettes, fontsize=9)
    axes.set_ylim(0, 1.16)
    axes.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    axes.set_ylabel("Rappel (étiquette exigée)", fontsize=10)
    axes.grid(alpha=0.3, axis="y")
    axes.set_axisbelow(True)
    axes.legend(fontsize=9.5, loc="lower center", ncol=3,
                bbox_to_anchor=(0.5, -0.30), frameon=False)

    figure.subplots_adjust(left=0.095, right=0.985, top=0.97, bottom=0.25)
    enregistrer(figure, "e7b_categories")


def main():
    parseur = argparse.ArgumentParser(description="Figures E7b")
    parseur.add_argument("--json", default=None)
    arguments = parseur.parse_args()

    chemin = Path(arguments.json) if arguments.json else derniere_execution()
    print(f"lecture : {chemin}")
    with open(chemin, encoding="utf-8") as f:
        rapport = json.load(f)

    globales = rapport.get("global", {})
    moteurs = [nom for nom, m in globales.items()
               if isinstance(m, dict) and "erreur" not in m
               and m.get("rappel") is not None]
    if not moteurs:
        raise SystemExit(
            "aucun moteur utilisable dans ce fichier : tous ont echoue, "
            "ou le format n'est pas celui attendu.")
    print(f"moteurs : {', '.join(moteurs)}")

    figure_qualite(globales, moteurs)
    figure_debit(globales, moteurs)
    figure_categories(rapport.get("par_categorie", {}), moteurs)


if __name__ == "__main__":
    main()
