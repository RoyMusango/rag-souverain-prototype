r"""
Figure E7 : comparaison des detecteurs d'entites nommees.

    python scripts\tracer_e7.py

Sans argument, le script prend la derniere execution e7-masquage du dossier
resultats. Pour en choisir une :

    python scripts\tracer_e7.py --json resultats\e7-masquage-<horodatage>\e7_masquage.json

Deux panneaux :
  gauche  qualite : rappel, precision, F1 par moteur
  droite  debit   : caracteres par seconde

Le debit est dans un panneau a part, et son titre le precise : il a ete
mesure sur un materiel de developpement. Il est donc seulement indicatif, et
ne vaut pas pour le palier local (section 4.1.1 du rapport).
"""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

SORTIE = Path("figures")
COULEURS = {"spacy": "#2b6cb0", "camembert": "#2f855a", "presidio": "#a0aec0"}
LIBELLES = {"spacy": "spaCy (souverain)", "camembert": "CamemBERT (souverain)",
            "presidio": "Presidio"}


def derniere_execution():
    """Trouve le JSON de la campagne E7 la plus recente."""
    racine = Path("resultats")
    if not racine.exists():
        raise SystemExit("dossier 'resultats' introuvable")
    candidats = sorted(racine.glob("e7-masquage-*/e7_masquage.json"))
    if not candidats:
        raise SystemExit(
            "aucun e7_masquage.json trouve.\n"
            "Lancez d'abord : python scripts\\run_e7.py --patients 300 "
            "--langue en --moteurs spacy,presidio")
    return candidats[-1]


def enregistrer(figure, nom):
    SORTIE.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "pdf"):
        chemin = SORTIE / f"{nom}.{extension}"
        figure.savefig(chemin, dpi=300, bbox_inches="tight")
        print(f"  ecrit : {chemin}")
    plt.close(figure)


def main():
    parseur = argparse.ArgumentParser(description="Figure E7")
    parseur.add_argument("--json", default=None)
    arguments = parseur.parse_args()

    chemin = Path(arguments.json) if arguments.json else derniere_execution()
    print(f"lecture : {chemin}")
    with open(chemin, encoding="utf-8") as f:
        rapport = json.load(f)

    resultats = rapport.get("resultats", {})
    moteurs = [nom for nom, mesures in resultats.items()
               if isinstance(mesures, dict) and "erreur" not in mesures
               and "rappel" in mesures]
    if not moteurs:
        raise SystemExit(
            "aucun moteur utilisable dans ce fichier : tous ont echoue, "
            "ou le format n'est pas celui attendu.")

    print(f"moteurs : {', '.join(moteurs)}")

    figure, (gauche, droite) = plt.subplots(
        1, 2, figsize=(11, 4.4), gridspec_kw={"width_ratios": [2, 1]})

    # --- panneau qualite ---------------------------------------------------
    metriques = ["rappel", "precision", "f1"]
    etiquettes = ["Rappel", "Précision", "F1"]
    largeur = 0.8 / len(moteurs)

    for rang, nom in enumerate(moteurs):
        valeurs = [resultats[nom].get(m, 0.0) for m in metriques]
        positions = [i + rang * largeur - 0.4 + largeur / 2
                     for i in range(len(metriques))]
        barres = gauche.bar(positions, valeurs, width=largeur * 0.9,
                            color=COULEURS.get(nom, "#718096"),
                            edgecolor="white",
                            label=LIBELLES.get(nom, nom))
        for barre, valeur in zip(barres, valeurs):
            gauche.text(barre.get_x() + barre.get_width() / 2, valeur + 0.015,
                        f"{valeur:.3f}", ha="center", fontsize=8)

    gauche.set_xticks(range(len(metriques)))
    gauche.set_xticklabels(etiquettes)
    gauche.set_ylim(0, 1.0)
    gauche.set_ylabel("valeur")
    gauche.set_title("Qualité de détection", fontsize=11)
    gauche.grid(alpha=0.3, axis="y")
    gauche.set_axisbelow(True)
    gauche.legend(fontsize=9)

    # --- panneau debit -----------------------------------------------------
    debits = [resultats[nom].get("debit_car_s", 0) for nom in moteurs]
    barres = droite.bar([LIBELLES.get(n, n).split(" ")[0] for n in moteurs],
                        debits,
                        color=[COULEURS.get(n, "#718096") for n in moteurs],
                        edgecolor="white", width=0.55)
    for barre, valeur in zip(barres, debits):
        droite.text(barre.get_x() + barre.get_width() / 2, valeur * 1.02,
                    f"{valeur:,}".replace(",", " "), ha="center", fontsize=9)

    droite.set_ylabel("caractères par seconde")
    droite.set_title("Débit (indicatif,\nmatériel de développement)",
                     fontsize=10)
    droite.grid(alpha=0.3, axis="y")
    droite.set_axisbelow(True)

    ecart = rapport.get("ecart_sur_presidio") or {}
    sous_titre = ""
    for nom, e in ecart.items():
        sous_titre = (f"écart de rappel de {LIBELLES.get(nom, nom)} sur "
                      f"Presidio : {e['rappel_absolu']:+.4f} "
                      f"({e['rappel_relatif']:+.1%})")
        break

    figure.suptitle(
        "E7 : détecteurs d'entités personnelles" +
        (f"\n{sous_titre}" if sous_titre else ""),
        fontsize=12)
    figure.tight_layout(rect=[0, 0, 1, 0.93])

    enregistrer(figure, "e7_detecteurs")


if __name__ == "__main__":
    main()
