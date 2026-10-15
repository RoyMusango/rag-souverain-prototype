r"""
Orchestration des campagnes E1, E3, E4 et E5 sur un index construit.

    py -3.11 scripts\run_campagne.py --experiences e1,e5 --corpus enronqa
    py -3.11 scripts\run_campagne.py --experiences e3,e4 --sans-index

Ce script assemble ce que les modules d'evaluation ne peuvent assembler
seuls : il monte la cascade a partir des index persistes, construit les
configurations d'ablation et estampille l'execution.

E2 dispose de son propre lanceur (run_e2.py), car il ne depend d'aucun
index : |S| est un decompte sur une population enumeree. Il en va de meme
pour E7. Ce script couvre les experiences qui exigent la chaine de
recherche.

E6 n'y figure pas ; il dispose de son propre lanceur (run_e6.py).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.commun import config as mod_config, journal as mod_journal  # noqa: E402
from src.evaluation import (e1_hybridation, e3_injection,            # noqa: E402
                            e4_provenance, e5_cout)
from src.index import lexical as mod_lexical, recuperateurs          # noqa: E402
from src.index.hybride import RecuperateurHybride                    # noqa: E402

PAIRES = {
    "enronqa": "data/enronqa/enronqa_qa.jsonl",
    "finqa": "data/finqa/finqa_programmes.json",
}
SCHEMAS = {
    "enronqa": "data/enronqa/enronqa_schema.jsonl",
    "finqa": "data/finqa/finqa_schema.json",
    "tatqa": "data/tatqa/tatqa_schema.json",
    "eurlex": "data/external/eurlex/eurlex_schema.json",
    "synthea": "data/synthea/synthea_schema.json",
    "pubmedqa": "data/pubmedqa/pubmedqa_schema.jsonl",
}


def lire_schema(chemin):
    chemin = Path(chemin)
    if not chemin.exists():
        chemin = chemin.with_suffix(".jsonl" if chemin.suffix == ".json"
                                    else ".json")
    if not chemin.exists():
        return []
    if chemin.suffix == ".jsonl":
        with open(chemin, encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def monter_index(corpus, config, avec_dense=True):
    """Charge les index persistes et construit les recuperateurs.

    Retourne (dense, lexical, reclasseur). Chacun peut valoir None : les
    ablations d'E1 en dependent, et une voie absente doit degrader la
    cascade sans la faire echouer.
    """
    dense = reclasseur = None
    chemin_lex = Path(f"data/index_lexical/{corpus}.pkl")
    lexique = (recuperateurs.RecuperateurLexical(
        mod_lexical.IndexLexical.charger(chemin_lex))
        if chemin_lex.exists() else None)

    if avec_dense:
        try:
            from src.index import embeddings as mod_emb
            from src.index import qdrant_index as mod_qdrant
            vectoriseur = mod_emb.Vectoriseur(
                modele=config.recherche.modele_embeddings)
            index = mod_qdrant.IndexQdrant(
                collection=config.recherche.collection,
                dimension=config.recherche.dimension,
                hote=config.recherche.hote_qdrant)
            index.client.get_collection(config.recherche.collection)
            dense = recuperateurs.RecuperateurDense(
                index, vectoriseur, corpus=corpus)
            reclasseur = mod_lexical.Reclasseur(
                config.recherche.modele_reclasseur)
        except Exception as erreur:
            print(f"  voie dense indisponible : {type(erreur).__name__} "
                  f"— {str(erreur)[:70]}")

    return dense, lexique, reclasseur


def fabrique_e1(dense, lexique, reclasseur, config):
    """Construit une cascade par configuration d'ablation."""
    def fabriquer(configuration):
        if configuration == "dense":
            return (RecuperateurHybride(dense=dense) if dense else None)
        if configuration == "lexical":
            return (RecuperateurHybride(lexical=lexique) if lexique else None)
        if configuration == "fusion":
            if not (dense and lexique):
                return None
            return RecuperateurHybride(dense=dense, lexical=lexique)
        if configuration == "complet":
            if not (dense and lexique):
                return None
            return RecuperateurHybride(
                dense=dense, lexical=lexique, reclasseur=reclasseur,
                top_k_reclassement=config.recherche.top_k_reclassement)
        return None
    return fabriquer


def main():
    p = argparse.ArgumentParser(description="Campagne E1, E3, E4, E5")
    p.add_argument("--experiences", default="e1,e4,e5")
    p.add_argument("--corpus", default="enronqa")
    p.add_argument("--questions", type=int, default=200)
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--sans-index", action="store_true",
                   help="n'exige pas Qdrant : E3 et E4 restent possibles")
    args = p.parse_args()

    config = mod_config.Config()
    experiences = [e.strip().lower() for e in args.experiences.split(",")]
    corpus = args.corpus

    print(f"materiel   : {config.materiel.nom} ({config.materiel.role})")
    print(f"corpus     : {corpus}")
    print(f"experiences: {', '.join(experiences)}\n")

    dense, lexique, reclasseur = monter_index(
        corpus, config, avec_dense=not args.sans_index)
    print(f"  voie dense   : {'disponible' if dense else 'ABSENTE'}")
    print(f"  voie lexicale: {'disponible' if lexique else 'ABSENTE'}\n")

    rapport = {}
    manifeste = [SCHEMAS.get(corpus, "")]

    with mod_journal.Execution(f"campagne-{corpus}", config,
                               manifeste=[m for m in manifeste if m]) as ex:

        # ---- E1 : apport de l'hybridation -----------------------------
        if "e1" in experiences:
            chemin = PAIRES.get(corpus)
            if not chemin or not Path(chemin).exists():
                print(f"E1 : paires absentes ({chemin}) — ignore\n")
            else:
                paires = e1_hybridation.echantillonner(
                    e1_hybridation.charger_paires(chemin, limite=20000),
                    nombre=args.questions, graine=config.graine)
                print(f"E1 : {len(paires)} questions")
                rapport["e1"] = e1_hybridation.campagne(
                    fabrique_e1(dense, lexique, reclasseur, config),
                    paires, k=args.k)
                for nom, m in rapport["e1"]["resultats"].items():
                    r = m[f"recall@{args.k}"]["moyenne"]
                    n = m[f"ndcg@{args.k}"]["moyenne"]
                    print(f"   {nom:<10} recall@{args.k}={r:.3f} "
                          f"ndcg@{args.k}={n:.3f} "
                          f"({m['latence_mediane_ms']:.0f} ms)")
                    ex.mesure(f"e1.{nom}.recall@{args.k}", r)
                    ex.mesure(f"e1.{nom}.ndcg@{args.k}", n)
                    ex.mesure(f"e1.{nom}.latence_ms",
                              m["latence_mediane_ms"], grandeur="latence")
                print(f"   apport sur dense seul : "
                      f"{rapport['e1']['apport_sur_dense_seul']}\n")

        # ---- E5 : cout de la protection --------------------------------
        if "e5" in experiences:
            chemin = PAIRES.get(corpus)
            recup = (RecuperateurHybride(dense=dense, lexical=lexique)
                     if (dense or lexique) else None)
            if not chemin or not Path(chemin).exists() or recup is None:
                print("E5 : paires ou index absents — ignore\n")
            else:
                from src.confidentialite.verrou import Masqueur
                paires = e1_hybridation.echantillonner(
                    e1_hybridation.charger_paires(chemin, limite=20000),
                    nombre=args.questions, graine=config.graine)
                masqueur = Masqueur(
                    moteur=config.confidentialite.moteur_ner,
                    langue=config.confidentialite.langue_ner)
                print(f"E5 : {len(paires)} questions")
                rapport["e5"] = e5_cout.campagne(recup, paires,
                                                 masqueur=masqueur, k=args.k)
                for regime, m in rapport["e5"]["resultats"].items():
                    print(f"   {regime:<12} recall@{args.k}="
                          f"{m[f'recall@{args.k}']['moyenne']:.3f}")
                print(f"   cout : {rapport['e5']['cout_par_regime']}\n")

        # ---- E4 : attribuabilite ---------------------------------------
        if "e4" in experiences:
            documents = lire_schema(SCHEMAS.get("eurlex", ""))
            if not documents:
                print("E4 : eurlex absent — ignore\n")
            else:
                from src.isolation.teinte import Fragment
                fragments = [
                    Fragment(doc_id=d["doc_id"], text=d["text"],
                             source=d["source"], rubrique=d["rubrique"],
                             page=d["page"], pave=d["pave"], origine="eurlex")
                    for d in documents[:2000]
                ]
                rapport["e4"] = e4_provenance.verifier_chaine(fragments)
                print(f"E4 : {rapport['e4']['fragments']} fragments, "
                      f"integrite {rapport['e4']['taux_integrite']:.4f}")
                ex.mesure("e4.taux_integrite",
                          rapport["e4"]["taux_integrite"])
                quatre = e4_provenance.corpus_a_quatre_niveaux(fragments)
                print(f"   corpus a pagination reelle : "
                      f"{sorted(quatre) or 'aucun'}\n")

        # ---- E3 : injection sous attaque adaptative ---------------------
        if "e3" in experiences:
            print("E3 : necessite un fournisseur de generation branche.")
            print("   Sans modele, seules les familles 'instruction' et")
            print("   'assertion' sont mesurables ; voir "
                  "LISEZ_MOI_POC_complement.md.\n")

        chemin = ex.dossier / "campagne.json"
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(rapport, f, ensure_ascii=False, indent=2, default=str)
        print(f"ecrit : {chemin}")


if __name__ == "__main__":
    main()
