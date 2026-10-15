"""
Purge d'un journal de reprise E3 les appels dont la reponse est vide.

MOTIVATION

Un modele soumis a un budget de jetons serre peut consommer la totalite de
`--max-jetons` sans rendre un seul caractere visible. La campagne `assertion`
du 16 septembre en compte douze sur cent quatre-vingt-quinze, factures 2 500
jetons chacun pour une reponse vide.

Ces appels faussent aussi la mesure. Pour les familles `assertion` et
`instruction`, le verdict lit la reponse : une reponse vide ne contient ni
valeur inventee ni marqueur d'execution, et l'attaque est donc comptee comme
echouee alors que son issue est inconnue. L'ASR publie est alors sous-estime
d'un montant inconnu.

Purger ces lignes du journal de reprise les rend rejouables : la commande
d'origine, relancee avec un `--max-jetons` plus large, ne refacture que ces
appels.

Pour la famille `duplication`, la purge est inutile : son verdict ne lit pas
la reponse, et une reponse vide ne fausse rien. Le script le signale.

PRECAUTION

Purger implique de repayer ces appels. Le script ne modifie donc rien sans
`--confirmer`, et ecrit toujours une sauvegarde horodatee a cote du journal
avant toute modification.

    .venv\\Scripts\\python.exe scripts\\purger_appels_vides.py ^
        resultats\\e3_complet\\journal_assertion.jsonl

    .venv\\Scripts\\python.exe scripts\\purger_appels_vides.py ^
        resultats\\e3_complet\\journal_assertion.jsonl --confirmer
"""

import argparse
import json
import shutil
import time
from pathlib import Path


def lire(chemin):
    """Rend la liste des entrees, en conservant l'ordre du fichier."""
    entrees = []
    for numero, ligne in enumerate(
            chemin.read_text(encoding="utf-8").splitlines(), start=1):
        if not ligne.strip():
            continue
        try:
            entrees.append((numero, json.loads(ligne), ligne))
        except json.JSONDecodeError as erreur:
            raise SystemExit(
                "ligne %d illisible dans %s : %s\n"
                "Le journal est peut-etre tronque par une coupure en pleine "
                "ecriture. Retire la derniere ligne a la main et relance."
                % (numero, chemin, erreur))
    return entrees


def est_vide(entree):
    return not (entree.get("trace", {}).get("reponse") or "").strip()


def main():
    parseur = argparse.ArgumentParser(
        description="Purge les appels a reponse vide d'un journal E3.")
    parseur.add_argument("journal",
                         help="chemin du journal_<famille>.jsonl")
    parseur.add_argument("--confirmer", action="store_true",
                         help="ecrit reellement. Sans ce drapeau, le script "
                              "se contente de rapporter ce qu'il ferait.")
    arguments = parseur.parse_args()

    chemin = Path(arguments.journal)
    if not chemin.exists():
        raise SystemExit("introuvable : %s" % chemin)

    entrees = lire(chemin)
    vides = [(n, e) for n, e, _ in entrees if est_vide(e)]

    print("journal            : %s" % chemin)
    print("appels journalises : %d" % len(entrees))
    print("reponses vides     : %d" % len(vides))

    if "duplication" in chemin.name:
        print()
        print("ATTENTION : famille duplication. Son verdict ne lit pas la")
        print("reponse du modele, une reponse vide ne fausse donc AUCUN")
        print("resultat. Purger ne ferait que repayer des appels pour rien.")

    if not vides:
        print("\nRien a purger.")
        return

    par_configuration = {}
    for _, entree in vides:
        configuration = entree["configuration"]
        par_configuration[configuration] = \
            par_configuration.get(configuration, 0) + 1
    print()
    for configuration, compte in sorted(par_configuration.items()):
        print("  %-22s %d appel(s) a rejouer" % (configuration, compte))

    if not arguments.confirmer:
        print()
        print("SIMULATION. Rien n'a ete modifie.")
        print("Ajoute --confirmer pour purger, puis relance la commande de")
        print("campagne d'origine avec un --max-jetons plus large.")
        return

    sauvegarde = chemin.with_suffix(
        ".%s.sauvegarde.jsonl" % time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(chemin, sauvegarde)

    gardees = [ligne for _, entree, ligne in entrees if not est_vide(entree)]
    chemin.write_text("\n".join(gardees) + "\n", encoding="utf-8")

    print()
    print("sauvegarde         : %s" % sauvegarde)
    print("lignes conservees  : %d" % len(gardees))
    print("lignes purgees     : %d" % len(vides))
    print()
    print("Relance maintenant la commande de campagne d'origine, en portant")
    print("--max-jetons a 4000. Seuls les %d appels purges seront refactures."
          % len(vides))


if __name__ == "__main__":
    main()
