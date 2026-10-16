r"""
E7 : comparaison des detecteurs d'entites nommees.

    python scripts\run_e7.py --patients 300 --langue en --moteurs spacy,presidio

spaCy et Presidio n'ont pas besoin de GPU. CamemBERT va plus vite avec un
GPU, mais tourne sans. Le script peut tourner sur le poste local comme sur
la machine de calcul : la qualite se mesure partout, seul le debit demande
un materiel representatif, et le journal le signale.

Prerequis :
    python -m spacy download fr_core_news_lg     (si absent)
    pip install presidio-analyzer transformers   (pour la comparaison)
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.commun import config as mod_config, journal as mod_journal  # noqa: E402
from src.confidentialite.verrou import CAMEMBERT, PRESIDIO, SPACY    # noqa: E402
from src.evaluation import e7_masquage as e7                          # noqa: E402


def lire_schema(chemin):
    chemin = Path(chemin)
    if not chemin.exists():
        chemin = chemin.with_suffix(".jsonl")
    if chemin.suffix == ".jsonl":
        with open(chemin, encoding="utf-8") as f:
            return [json.loads(ligne) for ligne in f if ligne.strip()]
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def main():
    parseur = argparse.ArgumentParser(description="E7 : detecteurs de PII")
    parseur.add_argument("--patients", type=int, default=300,
                         help="nombre de patients echantillonnes")
    # Pas de valeur par defaut : les rubriques Synthea sont en anglais et le
    # corpus bancaire en francais. Une mauvaise valeur ne leve aucune erreur :
    # le mauvais modele spaCy tourne, le rappel s'effondre, et le resultat
    # ressemble a une vraie mesure. Voir JOURNAL_DONNEES section 11.
    parseur.add_argument("--langue", required=True, choices=("fr", "en"),
                         help="langue du corpus : en pour Synthea, "
                              "fr pour le corpus bancaire")
    parseur.add_argument("--seuil", type=float, default=0.5)
    parseur.add_argument("--moteurs", default="spacy,presidio",
                         help="spacy,camembert,presidio")
    parseur.add_argument("--schema", default="data/synthea/synthea_schema.json")
    parseur.add_argument("--patients-csv", default="data/synthea/patients.csv")
    arguments = parseur.parse_args()

    config = mod_config.Config()
    reference = e7.construire_reference(arguments.patients_csv,
                                        limite=arguments.patients)
    identifiants = {r["patient"] for r in reference}

    documents = [
        d for d in lire_schema(arguments.schema)
        if d.get("doc_id", "").endswith("/identite")
        and d["doc_id"].split("/")[1] in identifiants
    ]

    print(f"patients de reference : {len(reference)}")
    print(f"rubriques identite    : {len(documents)}")
    # Deux comptes differents. Les confondre avait fait ecrire 2121 dans le
    # rapport, alors que le denominateur du rappel vaut 2712 : `attendus`
    # liste les chaines sensibles, `positions_attendues` trouve toutes leurs
    # occurrences dans le texte. Le rappel se calcule sur les occurrences.
    chaines = sum(len(r["attendus"]) for r in reference)
    occurrences = sum(
        len(e7.positions_attendues(d.get("text", ""),
                                   next((r["attendus"] for r in reference
                                         if r["patient"] == d["doc_id"].split("/")[1]),
                                        [])))
        for d in documents
    )
    print(f"chaines sensibles     : {chaines}")
    print(f"occurrences attendues : {occurrences}   (denominateur du rappel)\n")

    moteurs = tuple(m.strip() for m in arguments.moteurs.split(","))
    with mod_journal.Execution("e7-masquage", config,
                               manifeste=[arguments.patients_csv]) as ex:
        rapport = e7.campagne(documents, reference, moteurs,
                              arguments.langue, arguments.seuil)

        print(f"{'moteur':<12} {'rappel':>8} {'precis.':>8} {'F1':>8} "
              f"{'debit c/s':>10}")
        print("-" * 50)
        for nom in moteurs:
            m = rapport["resultats"].get(nom, {})
            if "erreur" in m:
                print(f"{nom:<12} INDISPONIBLE : {m['erreur'][:60]}")
                continue
            print(f"{nom:<12} {m['rappel']:>8.3f} {m['precision']:>8.3f} "
                  f"{m['f1']:>8.3f} {m['debit_car_s']:>10,}")
            ex.mesure(f"{nom}.rappel", m["rappel"])
            ex.mesure(f"{nom}.precision", m["precision"])
            ex.mesure(f"{nom}.debit_car_s", m["debit_car_s"],
                      grandeur="latence")

        if rapport["ecart_sur_presidio"]:
            print("\necart de rappel sur Presidio :")
            for nom, e in rapport["ecart_sur_presidio"].items():
                print(f"  {nom:<12} {e['rappel_absolu']:+.4f} "
                      f"({e['rappel_relatif']:+.1%})")

        with open(ex.dossier / "e7_masquage.json", "w", encoding="utf-8") as f:
            json.dump(rapport, f, ensure_ascii=False, indent=2)
        print(f"\necrit : {ex.dossier}")


if __name__ == "__main__":
    main()
