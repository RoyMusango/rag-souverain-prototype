r"""
Figure E2b, les deux bornes de l'effondrement de l'anonymat.

    python scripts\tracer_e2b.py

UNE FIGURE, DEUX PANNEAUX

Les figures E7b sont separees en trois parce qu'elles portent trois
affirmations independantes. Ici, au contraire, la figure demontre la
comparaison entre les deux bornes : les separer obligerait le lecteur a
memoriser la premiere pour lire la seconde, et l'echelle commune, qui porte
l'argument, ne serait plus visible d'un seul regard.

Les deux panneaux sont de meme nature (memes axes, meme seuil) et restent
lisibles cote a cote.

    gauche   borne optimiste : vingt entites prelevees a pas regulier sur
             toute la population. C'est le cas moyen, celui d'E2.
    droite   borne pessimiste : vingt entites prelevees parmi les seules
             entites uniques sur les quasi-identifiants bruts, soit les
             46,2 % que la population ne protege pas.

AUCUN TITRE GENERAL, AUCUNE NOTE DE BAS DE FIGURE

Le titre est porte par le document qui integre la figure. Les etiquettes de
panneau sont conservees, car elles indiquent quelle borne est representee.
L'interpretation figure dans le texte qui accompagne la figure.

LECTURE

La population est la meme dans les deux panneaux (11 538 individus), donc N
et le calcul de fuite log2(N/|S|) sont identiques. Seules les entites
enquetees changent, et cette invariance rend les deux bornes comparables.

A droite, les deux configurations par session descendent jusqu'au seuil ;
la configuration par entite plafonne au-dessus.
"""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt   # noqa: E402

SORTIE = Path("figures")

STYLES = ["-", "--", ":"]
MARQUEURS = ["o", "s", "^"]
COULEURS = ["#a0aec0", "#dd6b20", "#2b6cb0"]

# Les libelles stockes dans resume.json sont sans accent, comme le reste du
# code. Les afficher tels quels a cote d'axes accentues serait incoherent ; je
# les remplace donc a l'affichage. Corriger e2_anonymat.py obligerait a
# rejouer les deux campagnes (quarante-cinq minutes chacune) pour un accent.
LIBELLES = {
    "c1_session_session": "Gabarit et budget par session",
    "c2_session_entite": "Gabarit par session, budget par entité",
    "c3_entite_entite": "Gabarit et budget par entité",
}


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
            f"Lancez d'abord les deux bornes :\n"
            f"  python scripts\\run_e2.py --k 50 --budget 6.0 --entites 20 "
            f"--sortie resultats\\e2_controle\n"
            f"  python scripts\\run_e2.py --k 50 --budget 6.0 --entites 20 "
            f"--cibles uniques --sortie resultats\\e2b")
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def tracer(axes, donnees, etiquette, k, montrer_legende):
    """Un panneau : les trois configurations, a effort constant."""
    resume = donnees["resume"]
    # Mode a effort constant uniquement : c'est le seul ou les trois
    # trajectoires ont la meme longueur, et donc ou elles sont comparables.
    entrees = [(c, e) for c, e in sorted(resume.items())
               if e.get("mode", "reel") == "effort-constant"]

    for numero, (cle, entree) in enumerate(entrees):
        courbe = entree["courbe_mediane"]
        libelle = LIBELLES.get(cle.split("|")[0], entree["libelle"])
        # La legende n'indique pas le taux de violation. Les courbes sont
        # celles du mode a effort constant, ou C1 viole dans 85 % des cas,
        # alors que le rapport cite les 80 % du mode reel. Les deux valeurs
        # sont exactes mais paraitraient contradictoires une fois juxtaposees.
        axes.plot(range(len(courbe)), courbe,
                  linestyle=STYLES[numero % 3], marker=MARQUEURS[numero % 3],
                  color=COULEURS[numero % 3], linewidth=2, markersize=5,
                  label=libelle)

    if k:
        axes.axhline(k, color="crimson", linewidth=1.3, linestyle="-.")
        axes.text(0.2, k * 1.16, f"k = {k}", color="crimson", fontsize=9)

    axes.set_xlabel("requêtes émises sur l'entité", fontsize=9.5)
    axes.set_yscale("log")
    axes.set_title(etiquette, fontsize=10.5)
    axes.grid(alpha=0.3, which="both")
    axes.set_axisbelow(True)
    if montrer_legende:
        axes.legend(fontsize=8.5, loc="upper right")


def main():
    parseur = argparse.ArgumentParser(description="Figure E2b, deux bornes")
    parseur.add_argument("--optimiste",
                         default="resultats/e2_controle/resume.json")
    parseur.add_argument("--pessimiste", default="resultats/e2b/resume.json")
    arguments = parseur.parse_args()

    opt = lire(arguments.optimiste)
    pes = lire(arguments.pessimiste)
    k = opt.get("parametres", {}).get("k")
    print(f"optimiste  : {arguments.optimiste}")
    print(f"pessimiste : {arguments.pessimiste}")

    figure, (gauche, droite) = plt.subplots(
        1, 2, figsize=(12, 4.8), sharey=True)

    tracer(gauche, opt,
           "Cas moyen : entités tirées dans toute la population",
           k, montrer_legende=True)
    tracer(droite, pes,
           "Pire cas : entités uniques sur les quasi-identifiants",
           k, montrer_legende=False)

    gauche.set_ylabel("|S|, ensemble d'anonymat (médiane)",
                      fontsize=9.5)

    figure.subplots_adjust(left=0.085, right=0.985, top=0.93, bottom=0.135,
                           wspace=0.06)
    enregistrer(figure, "e2b_deux_bornes")


if __name__ == "__main__":
    main()
