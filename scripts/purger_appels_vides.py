"""
Retire d'un journal de reprise E3 les appels dont la reponse est vide.

POURQUOI

Avec un budget de jetons serre, un modele peut utiliser tout `--max-jetons`
sans ecrire un seul caractere visible. La campagne `assertion` du 16
septembre en compte douze sur cent quatre-vingt-quinze, factures 2 500
jetons chacun pour une reponse vide.

Ces appels faussent aussi la mesure. Pour les familles `assertion` et
`instruction`, le verdict lit la reponse. Une reponse vide ne contient ni
valeur inventee ni marqueur d'execution : l'attaque est comptee comme
echouee alors qu'on ne sait pas ce qu'elle aurait donne. L'ASR publie est
donc trop bas, d'une valeur inconnue.

Une fois ces lignes retirees du journal de reprise, on peut rejouer ces
appels : la commande d'origine, relancee avec un `--max-jetons` plus grand,
ne refacture qu'eux.

Pour la famille `duplication`, c'est inutile : son verdict ne lit pas la
reponse, donc une reponse vide ne fausse rien. Le script le signale.

PRECAUTION

Retirer ces appels oblige a les payer de nouveau. Le script ne modifie donc
rien sans `--confirmer`, et ecrit toujours une sauvegarde horodatee a cote
du journal avant de le modifier.

    .venv\\Scripts\\python.exe scripts\\purger_appels_vides.py `
        resultats\\e3_complet\\journal_assertion.jsonl

    .venv\\Scripts\\python.exe scripts\\purger_appels_vides.py `
        resultats\\e3_complet\\journal_assertion.jsonl --confirmer
"""

import argparse
import json
import shutil
import time
from pathlib import Path


def lire(chemin):
    """Renvoie la liste des entrees, dans l'ordre du fichier."""
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
                "Le journal a peut-etre ete coupe en pleine ecriture. "
                "Supprimez la derniere ligne a la main et relancez."
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
                         help="modifie vraiment le journal. Sans cette "
                              "option, le script affiche seulement ce qu'il "
                              "ferait.")
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
        print("reponse du modele, donc une reponse vide ne fausse AUCUN")
        print("resultat. Retirer ces appels ferait payer pour rien.")

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
        print("Ajoutez --confirmer pour retirer ces appels, puis relancez la")
        print("commande de campagne d'origine avec un --max-jetons plus grand.")
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
    print("Relancez maintenant la commande de campagne d'origine, avec")
    print("--max-jetons 4000. Seuls les %d appels retires seront refactures."
          % len(vides))


if __name__ == "__main__":
    main()
