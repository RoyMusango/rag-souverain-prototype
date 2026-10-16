r"""
Figures du chapitre 5, et leurs variantes pour la presentation.

    python scripts\tracer_graphiques.py --figure lexical
    python scripts\tracer_graphiques.py --figure anonymat
    python scripts\tracer_graphiques.py --figure tout

Aucune valeur n'est ecrite en dur : chaque figure est construite a partir
du JSON de l'experience. Si le JSON manque, le script le dit et s'arrete,
sans tracer de courbe inventee.

Sortie en PNG (300 dpi, pour la projection) et en PDF (vectoriel, pour le
rapport LaTeX).
"""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")            # pas besoin d'affichage interactif
import matplotlib.pyplot as plt  # noqa: E402

SORTIE = Path("figures")


def enregistrer(figure, nom):
    SORTIE.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "pdf"):
        chemin = SORTIE / f"{nom}.{extension}"
        figure.savefig(chemin, dpi=300, bbox_inches="tight")
        print(f"  ecrit : {chemin}")
    plt.close(figure)


def figure_lexical(chemin_json):
    """Rappel@k et nDCG@k de la recherche lexicale seule."""
    chemin = Path(chemin_json)
    if not chemin.exists():
        raise SystemExit(
            f"introuvable : {chemin}\n"
            f"Lancez d'abord : python scripts\\run_e1_lexical.py")

    with open(chemin, encoding="utf-8") as f:
        donnees = json.load(f)

    mesures = donnees["mesures"]
    rangs = sorted(int(c.split("@")[1]) for c in mesures if c.startswith("rappel@"))
    rappels = [mesures[f"rappel@{k}"] for k in rangs]
    ndcgs = [mesures[f"ndcg@{k}"] for k in rangs]

    figure, axes = plt.subplots(figsize=(7, 4.5))
    axes.plot(rangs, rappels, marker="o", linewidth=2, label="Rappel@k")
    axes.plot(rangs, ndcgs, marker="s", linewidth=2, linestyle="--",
              label="nDCG@k")

    axes.set_xlabel("k (nombre de documents restitues)")
    axes.set_ylabel("valeur")
    axes.set_title(
        f"Recuperation lexicale seule (BM25) : {donnees['corpus']['nom']}\n"
        f"{donnees['corpus']['questions_evaluees']} questions, "
        f"{donnees['corpus']['documents']} documents",
        fontsize=11)
    axes.set_xscale("log")
    axes.set_xticks(rangs)
    axes.set_xticklabels([str(k) for k in rangs])
    axes.set_ylim(0, 1.0)
    axes.grid(alpha=0.3)
    axes.legend()

    # Lecture : l'ecart entre les deux courbes est ce qu'un re-classement
    # pourrait gagner. Le rappel dit si le passage est present, le nDCG s'il
    # est bien classe.
    enregistrer(figure, "e1_lexical_rappel_ndcg")


# Les libelles du JSON decrivent le mecanisme et parlent peu a un public non
# specialiste. La variante pour la presentation les remplace.
LIBELLES_SIMPLES = {
    "c1_session_session": "Compteur remis à zéro chaque matin",
    "c2_session_entite": "Compromis",
    "c3_entite_entite": "Compteur attaché à la personne",
}


def figure_anonymat(chemin_json, nom="e2_effondrement_anonymat",
                    titre=True, simples=False):
    """Effondrement de l'ensemble d'anonymat selon la configuration.

    `nom` evite que la campagne a trente questions ecrase la figure du
    memoire, dont le texte cite les valeurs a dix questions.
    """
    chemin = Path(chemin_json)
    if not chemin.exists():
        raise SystemExit(f"introuvable : {chemin}")

    with open(chemin, encoding="utf-8") as f:
        donnees = json.load(f)

    resume = donnees["resume"]
    parametres = donnees.get("parametres", {})
    k = parametres.get("k")

    figure, axes = plt.subplots(figsize=(7.5, 4.5))
    styles = ["-", "--", ":"]
    marqueurs = ["o", "s", "^"]

    # Le resume contient deux modes par configuration. Je ne trace que le
    # mode a effort constant : c'est le seul ou les trois traces ont la meme
    # longueur, donc le seul ou on peut comparer les courbes.
    entrees = [(c, e) for c, e in sorted(resume.items())
               if e.get("mode", "reel") == "effort-constant"] \
        or sorted(resume.items())

    for numero, (cle, entree) in enumerate(entrees):
        courbe = entree["courbe_mediane"]
        libelle = entree["libelle"]
        if simples:
            libelle = LIBELLES_SIMPLES.get(cle.split("|")[0], libelle)
        axes.plot(range(len(courbe)), courbe,
                  linestyle=styles[numero % 3],
                  marker=marqueurs[numero % 3],
                  linewidth=2, markersize=5,
                  label=libelle)

    if k:
        axes.axhline(k, color="crimson", linewidth=1.2, linestyle="-.")
        # A gauche, la legende simplifiee chevauchait les courbes au rang 10 ;
        # la zone libre se trouve a droite, entre le seuil et le plateau vert.
        gauche, droite = axes.get_xlim()
        axes.text(droite - (droite - gauche) * 0.02 if simples
                  else gauche + (droite - gauche) * 0.02,
                  k * (1.12 if simples else 1.25),
                  f"il doit rester au moins {k} personnes possibles"
                  if simples else f"seuil k = {k}",
                  color="crimson", fontsize=10 if simples else 9,
                  ha="right" if simples else "left")

    axes.set_xlabel("nombre de questions posées sur la même personne")
    axes.set_ylabel("|S| : personnes encore possibles (médiane)")
    # Dans la variante pour la presentation, la diapositive porte deja le
    # titre : le repeter dans l'image prendrait de la place pour rien.
    if titre:
        axes.set_title("Effondrement de l'ensemble d'anonymat", fontsize=12)
    axes.set_yscale("log")
    axes.grid(alpha=0.3, which="both")
    axes.legend(fontsize=9, loc="upper right")

    # Deux des trois courbes se superposent. C'est le resultat, pas un bug du
    # trace : attacher le budget a l'entite ne sert a rien si le gabarit est
    # toujours tire a chaque session.
    enregistrer(figure, nom)


def main():
    parseur = argparse.ArgumentParser(description="Traces des figures")
    parseur.add_argument("--figure",
                         choices=["lexical", "anonymat", "tout"],
                         default="tout")
    parseur.add_argument("--json-lexical",
                         default="resultats/e1_lexical/e1_lexical_enronqa.json")
    parseur.add_argument("--json-anonymat",
                         default="resultats/e2/resume.json")
    parseur.add_argument("--nom-anonymat",
                         default="e2_effondrement_anonymat")
    parseur.add_argument("--sans-titre", action="store_true",
                         help="pour une slide, qui porte deja son titre")
    parseur.add_argument("--libelles-simples", action="store_true",
                         help="legende en francais courant, pour une slide")
    arguments = parseur.parse_args()

    if arguments.figure in ("anonymat", "tout"):
        print("figure : effondrement de l'anonymat")
        figure_anonymat(arguments.json_anonymat, arguments.nom_anonymat,
                        titre=not arguments.sans_titre,
                        simples=arguments.libelles_simples)

    if arguments.figure in ("lexical", "tout"):
        print("figure : recuperation lexicale")
        figure_lexical(arguments.json_lexical)


if __name__ == "__main__":
    main()
