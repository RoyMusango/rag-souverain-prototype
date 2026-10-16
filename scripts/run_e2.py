r"""
Lance E2 et E2b et ecrit les resultats. Ce script n'a besoin ni du modele de
langue ni de l'index : |S| se compte sur une population connue en entier.

    python scripts\run_e2.py --k 50 --budget 6.0 --entites 20
    python scripts\run_e2.py --k 50 --budget 6.0 --entites 20 --cibles uniques

Utiliser `python` et non `py -3.11` : quand on donne une version, le lanceur
Windows ignore l'environnement virtuel et utilise le Python du systeme, ou
les dependances du projet ne sont pas installees.

Deux bornes, une seule population. `--cibles aleatoire` prend des entites a
intervalle regulier dans toute la population : c'est le cas moyen.
`--cibles uniques` les prend parmi les entites deja uniques sur les
quasi-identifiants bruts (les 46,2 % que la population ne protege pas) :
c'est le pire cas. La population reste entiere dans les deux modes. Sinon N
changerait, et on ne pourrait plus comparer les deux bornes.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.confidentialite import anonymat            # noqa: E402
from src.evaluation import e2_anonymat as e2        # noqa: E402


def moyenner(campagnes):
    """Regroupe les resultats de plusieurs entites (une seule courbe ne dit pas grand chose).

    Le regroupement se fait par couple (configuration, mode). Melanger le
    mode reel et le mode a effort constant donnerait une moyenne de deux
    valeurs qui ne se comparent pas.
    """
    agrege = {}
    for campagne in campagnes:
        for resultat in campagne["resultats"]:
            cle = f"{resultat['configuration']}|{resultat.get('mode', 'reel')}"
            entree = agrege.setdefault(cle, {
                "libelle": resultat["libelle"],
                "mode": resultat.get("mode", "reel"),
                "courbes": [], "S_T": [], "t_etoile": [], "aire": [],
                "aire_emises": [], "emises": [], "deficit": [],
                "violations": 0,
            })
            entree["courbes"].append(
                [p["taille_ensemble"] for p in resultat["points"]]
            )
            s = resultat["scalaires"]
            entree["S_T"].append(s["S_T"])
            entree["aire"].append(s["aire_normalisee"])
            entree["aire_emises"].append(s.get("aire_emises", 0.0))
            entree["emises"].append(s["requetes_emises"])
            entree["deficit"].append(s.get("deficit_max_bits", 0.0))
            if s.get("violation"):
                entree["violations"] += 1
            if s["t_etoile"] is not None:
                entree["t_etoile"].append(s["t_etoile"])

    sortie = {}
    for cle, e in agrege.items():
        longueur = min(len(c) for c in e["courbes"])
        nombre = len(e["courbes"])
        sortie[cle] = {
            "libelle": e["libelle"],
            "mode": e["mode"],
            "courbe_mediane": [
                statistics.median(c[i] for c in e["courbes"])
                for i in range(longueur)
            ],
            "S_T_median": statistics.median(e["S_T"]),
            "t_etoile_median": (statistics.median(e["t_etoile"])
                                if e["t_etoile"] else None),
            # Part des entites reidentifiees. Une mediane a None cache le
            # nombre d'entites passees sous le seuil.
            "part_franchissement": round(len(e["t_etoile"]) / nombre, 4),
            "aire_moyenne": round(statistics.mean(e["aire"]), 4),
            "aire_emises_moyenne": round(statistics.mean(e["aire_emises"]), 4),
            "emises_moyenne": round(statistics.mean(e["emises"]), 2),
            "deficit_max_moyen": round(statistics.mean(e["deficit"]), 4),
            "taux_violation": round(e["violations"] / nombre, 4),
            "entites": nombre,
        }
    return sortie


def main():
    parseur = argparse.ArgumentParser(description="E2 et E2b")
    parseur.add_argument("--population",
                         default="data/synthea/entities.json")
    parseur.add_argument("--k", type=int, default=50)
    parseur.add_argument("--budget", type=float, default=6.0)
    parseur.add_argument("--entites", type=int, default=20,
                         help="nombre d'entites echantillonnees")
    parseur.add_argument("--sessions", type=int, default=5)
    parseur.add_argument("--requetes", type=int, default=2)
    parseur.add_argument("--trace", choices=["progression", "reprise"],
                         default="progression")
    parseur.add_argument("--cibles", choices=("aleatoire", "uniques"),
                         default="aleatoire",
                         help="choix des entites enquetees : a intervalle "
                              "regulier dans toute la population, ou "
                              "seulement parmi les entites uniques sur les "
                              "quasi-identifiants bruts (pire cas)")
    parseur.add_argument("--sortie", default="resultats/e2")
    arguments = parseur.parse_args()

    population = anonymat.Population(
        e2.charger_population(arguments.population)
    )
    print(f"population : {len(population)} entites")
    print(f"taux d'uniques sur quasi-identifiants bruts : "
          f"{population.taux_uniques():.3f}")
    print(f"k = {arguments.k} | budget = {arguments.budget} bits\n")

    # Le mode `uniques` limite seulement les cibles, jamais la population :
    # `e2.campagne` recoit toute la population dans les deux cas. Ainsi les
    # deux bornes ont le meme N, donc le meme calcul de fuite log2(N/|S|).
    # Avec une population reduite, la borne pessimiste mesurerait autre
    # chose sous le meme nom.
    if arguments.cibles == "uniques":
        cibles = population.entites_uniques()
    else:
        cibles = population.entites
    print(f"cibles enquetees  : {arguments.cibles}, {len(cibles)} entites "
          f"disponibles, {arguments.entites} prises a intervalle regulier")
    print(f"population passee a la campagne : {len(population)} entites "
          f"(inchangee)\n")

    pas = max(1, len(cibles) // arguments.entites)
    echantillon = cibles[::pas][:arguments.entites]

    campagnes = []
    for rang, entite in enumerate(echantillon, start=1):
        cle = str(entite.get("id", f"e{rang}"))
        if arguments.trace == "reprise":
            trace = e2.trace_reprise(cle, sessions=arguments.sessions)
        else:
            trace = e2.trace_enquete_aml(
                cle, arguments.requetes, arguments.sessions
            )
        campagnes.append(e2.campagne(
            population, entite, trace, arguments.k, arguments.budget
        ))
        print(f"  entite {rang}/{len(echantillon)}", end="\r")

    print("\n")
    resume = moyenner(campagnes)

    print("=== PROTECTION : effort constant, budget desactive ===")
    print("Toutes les requetes sont envoyees : les traces ont la meme")
    print("longueur, donc |S_T| et l'aire se comparent.\n")
    for cfg in (e2.C1, e2.C2, e2.C3):
        r = resume[f"{cfg}|effort-constant"]
        print(f"{r['libelle']}")
        # Une decimale : la mediane de vingt entites peut tomber sur un
        # demi-entier. `:.0f` affichait 100 pour 100,5 et 122 pour 121,5,
        # deux valeurs absentes des tableaux du memoire. On risquait de citer
        # un chiffre faux en le recopiant depuis la console.
        print(f"   |S_T| median      : {r['S_T_median']:.1f}")
        print(f"   t* median         : {r['t_etoile_median']}")
        print(f"   entites sous k    : {r['part_franchissement']:.0%}")
        print(f"   aire moyenne      : {r['aire_moyenne']:.3f}")
        print("   courbe            : "
              + " ".join(f"{v:.0f}" for v in r["courbe_mediane"]))
        print()

    print("=== POLITIQUE : mode reel, avec blocage ===")
    print("Le deficit mesure l'ecart entre ce que l'adversaire apprend et ce")
    print("que le systeme croit avoir revele. Il vaut toujours 0 en C3.\n")
    for cfg in (e2.C1, e2.C2, e2.C3):
        r = resume[f"{cfg}|reel"]
        print(f"{r['libelle']}")
        print(f"   emises (moy.)     : {r['emises_moyenne']}")
        print(f"   deficit max (bits): {r['deficit_max_moyen']:.3f}")
        print(f"   taux de violation : {r['taux_violation']:.0%}")
        print(f"   aire sur emises   : {r['aire_emises_moyenne']:.3f}")
        print()

    chemin = Path(arguments.sortie)
    chemin.mkdir(parents=True, exist_ok=True)
    with open(chemin / "resume.json", "w", encoding="utf-8") as f:
        json.dump({"parametres": vars(arguments), "resume": resume},
                  f, ensure_ascii=False, indent=2)
    with open(chemin / "campagnes.json", "w", encoding="utf-8") as f:
        json.dump(campagnes, f, ensure_ascii=False, indent=2)
    print(f"ecrit dans {chemin}/")


if __name__ == "__main__":
    main()
