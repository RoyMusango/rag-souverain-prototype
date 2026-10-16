r"""
Construction de l'index sur processeur (profils PARITE et MODESTE).

    python scripts\build_index_cpu.py --profil parite  --corpus eurlex
    python scripts\build_index_cpu.py --profil modeste --corpus tous

Ce script fournit le point de comparaison avec l'index construit sur GPU.
Le profil PARITE verifie que les mesures de qualite faites sur GPU restent
valables pour un deploiement sur site. Le profil MODESTE mesure ce que l'on
perd en qualite avec un materiel modeste.

Trois precautions propres au processeur :

  ESTIMATION AVANT CALCUL  la duree est affichee et doit etre confirmee
                           avant de lancer. BGE-M3 sur processeur traite
                           environ 0,5 a 2 documents par seconde : le corpus
                           entier prendrait des dizaines d'heures.

  ECHANTILLONNAGE          stratifie par rubrique, avec une graine, donc
                           rejouable. Un tirage uniforme sur EnronQA pourrait
                           ne toucher que quelques boites, et on comparerait
                           des corpus de structures differentes.

  DETERMINISME             graines, fils et noyaux fixes. Sinon deux
                           executions sur la meme machine peuvent deja
                           differer, et on ne peut plus comparer deux
                           materiels.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.commun import config as mod_config, journal as mod_journal   # noqa: E402
from src.commun import profils as mod_profils                          # noqa: E402
from src.index import embeddings as mod_emb, lexical as mod_lex        # noqa: E402

SCHEMAS = {
    "synthea": "data/synthea/synthea_schema.json",
    "finqa": "data/finqa/finqa_schema.json",
    "tatqa": "data/tatqa/tatqa_schema.json",
    "eurlex": "data/external/eurlex/eurlex_schema.json",
    "pubmedqa": "data/pubmedqa/pubmedqa_schema.jsonl",
    "enronqa": "data/enronqa/enronqa_schema.jsonl",
}


def resoudre(chemin):
    p = Path(chemin)
    if p.exists():
        return p
    autre = p.with_suffix(".jsonl" if p.suffix == ".json" else ".json")
    return autre if autre.exists() else None


def lire(chemin):
    chemin = Path(chemin)
    if chemin.suffix == ".jsonl":
        with open(chemin, encoding="utf-8") as f:
            return [json.loads(ligne) for ligne in f if ligne.strip()]
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def main():
    parseur = argparse.ArgumentParser(
        description="Index sur processeur (profils de comparaison)")
    parseur.add_argument("--profil", choices=[mod_profils.PARITE,
                                              mod_profils.MODESTE],
                         default=mod_profils.PARITE)
    parseur.add_argument("--corpus", default="eurlex")
    parseur.add_argument("--taux", type=float, default=None,
                         help="remplace le taux d'echantillon du profil")
    parseur.add_argument("--tranche", type=int, default=500)
    parseur.add_argument("--fils", type=int, default=None)
    parseur.add_argument("--sans-confirmation", action="store_true")
    arguments = parseur.parse_args()

    profil = mod_profils.PROFILS[arguments.profil]
    if arguments.taux is not None:
        profil.taux_echantillon = arguments.taux
    if arguments.fils is not None:
        profil.fils_processeur = arguments.fils

    config = mod_config.Config()
    config.recherche.modele_embeddings = profil.modele_embeddings
    config.recherche.dimension = profil.dimension

    releve = mod_profils.appliquer_determinisme(
        config.graine, profil.fils_processeur)

    noms = (list(SCHEMAS) if arguments.corpus == "tous"
            else [c.strip() for c in arguments.corpus.split(",")])

    print(f"profil       : {profil.nom} : {profil.question}")
    print(f"modele       : {profil.modele_embeddings} ({profil.dimension} dim)")
    print(f"materiel     : {config.materiel.nom} (role : {config.materiel.role})")
    print(f"determinisme : {releve}")
    print(f"echantillon  : {profil.taux_echantillon:.0%} du corpus, "
          f"stratifie par rubrique, graine {config.graine}")
    if profil.comparable_a:
        print(f"comparable a : profil '{profil.comparable_a}'")
    print()

    # --- estimation de la duree, avant tout calcul -------------------------
    total_estime = 0
    plan = []
    for nom in noms:
        chemin = resoudre(SCHEMAS.get(nom, ""))
        if chemin is None:
            print(f"  [ABSENT]  {nom}")
            continue
        documents = lire(chemin)
        estimation = mod_profils.estimer_duree(profil, len(documents), "cpu",
                                               documents=documents,
                                               graine=config.graine)
        plan.append((nom, chemin, documents, estimation))
        total_estime += estimation["duree_estimee_min"]
        print(f"  {nom:10s} {len(documents):>7d} docs -> "
              f"{estimation['documents_retenus']:>6d} retenus, "
              f"~{estimation['duree_estimee_min']:>6.1f} min")

    print(f"\n  TOTAL ESTIME : {total_estime:.0f} min "
          f"({total_estime / 60:.1f} h)")
    print("  Estimation approximative, a remplacer par le debit observe.")

    if total_estime > 90 and not arguments.sans_confirmation:
        reponse = input("\n  Plus d'une heure et demie. Continuer ? [o/N] ")
        if reponse.strip().lower() not in ("o", "oui", "y"):
            print("  Interrompu. Reduisez --taux ou choisissez --profil modeste.")
            return

    # --- calcul -----------------------------------------------------------
    vectoriseur = mod_emb.Vectoriseur(
        modele=profil.modele_embeddings,
        peripherique=profil.peripherique,
        taille_lot=profil.taille_lot,
        longueur_max=profil.longueur_max,
    )

    manifeste = [str(c) for _, c, _, _ in plan]
    with mod_journal.Execution(f"index-{profil.nom}", config,
                               manifeste=manifeste) as execution:
        execution.evenement("profil", **{
            "nom": profil.nom, "modele": profil.modele_embeddings,
            "dimension": profil.dimension,
            "taux_echantillon": profil.taux_echantillon,
            "determinisme": releve,
        })

        for nom, chemin, documents, estimation in plan:
            retenus = profil.echantillonner(documents, config.graine)
            print(f"\n[{nom}] {len(retenus)} documents retenus "
                  f"sur {len(documents)}")

            debut = time.time()
            calcul = mod_emb.CalculPersistant(
                vectoriseur,
                dossier=f"data/embeddings/{profil.nom}/{nom}",
                taille_tranche=arguments.tranche,
            )
            calcul.executer(retenus, corpus=nom, journal=execution)
            duree = time.time() - debut

            debit = len(retenus) / duree if duree else 0
            execution.mesure(f"{nom}.documents", len(retenus))
            # La qualite se mesure sur n'importe quel materiel. Le debit est
            # une mesure de performance, et le journal le signale comme tel.
            execution.mesure(f"{nom}.debit_docs_s", round(debit, 2),
                             grandeur="latence")
            print(f"  debit observe : {debit:.1f} docs/s "
                  f"(indicatif prealable : "
                  f"{estimation['debit_indicatif_docs_s']:.1f})")

            lexique = mod_lex.IndexLexical(
                langue="fr" if nom in ("synthea", "eurlex") else "en")
            lexique.construire(retenus)
            lexique.enregistrer(
                f"data/index_lexical/{profil.nom}/{nom}.pkl")

        print(f"\nEcrit dans {execution.dossier}")
        print("Comparer par :")
        print(f"  python scripts\\comparer_materiel.py --nature parite "
              f"--reference resultats\\construction-index-... "
              f"--candidat {execution.dossier}")


if __name__ == "__main__":
    main()
