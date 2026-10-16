"""Teste les hypotheses sur le faible rappel ORGANISATION de Presidio.

A lancer depuis la racine du depot :

    python scripts\\diag_presidio_org.py

Le script ne modifie rien. Il affiche, dans l'ordre : ce que produit spaCy
seul, ce que Presidio dit gerer, la configuration NER reellement utilisee,
ce que Presidio produit avec un seuil nul, le verdict, puis la table de
normalisation du projet.

Aucun releve ne suffit seul : Presidio peut annoncer ORGANIZATION et
l'ecarter ensuite, ou le produire alors que la normalisation du projet le
perd. Il faut les lire ensemble.

Resultat (01/09/2026) : c'etait la table de normalisation, qui ne
connaissait pas ORGANIZATION. Voir verrou.py et JOURNAL_DONNEES, section 11.
"""

import argparse
import sys

# Une note dans le style du corpus bancaire synthetique : une organisation,
# une personne, un lieu, un identifiant.
NOTE = (
    "Le dossier KYC-200147 concerne Pieter Marchand, domicilie a Namur, "
    "titulaire d un compte chez Banque Delvaux SA et administrateur de la "
    "societe Immobiliere du Sablon SPRL."
)


def separateur(titre):
    print("\n" + "=" * 68)
    print(titre)
    print("=" * 68)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modele", default="fr_core_news_lg")
    ap.add_argument("--langue", default="fr")
    ap.add_argument("--seuil", type=float, default=0.5,
                    help="le seuil applique par verrou.py")
    ap.add_argument("--texte", default=NOTE)
    args = ap.parse_args()

    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider
    import presidio_analyzer
    import spacy

    print(f"presidio-analyzer {getattr(presidio_analyzer, '__version__', '?')}"
          f"   spaCy {spacy.__version__}   modele {args.modele}")

    # -- D3 (temoin) : ce que le modele spaCy produit, hors Presidio ---------
    separateur("D3  TEMOIN : spaCy seul, sans Presidio")
    nlp = spacy.load(args.modele)
    ents_spacy = [(e.text, e.label_) for e in nlp(args.texte).ents]
    for texte, etiquette in ents_spacy:
        print(f"   {etiquette:<14} {texte}")
    org_spacy = [t for t, l in ents_spacy if l == "ORG"]
    if not org_spacy:
        print("   AUCUN ORG. Le probleme est en amont de Presidio : le modele "
              "lui-meme n'etiquette pas cette organisation.")

    # -- Construction du moteur, comme dans _charger_presidio ---------------
    configuration = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": args.langue, "model_name": args.modele}],
    }
    moteur = NlpEngineProvider(nlp_configuration=configuration).create_engine()
    analyseur = AnalyzerEngine(nlp_engine=moteur,
                               supported_languages=[args.langue])

    # -- D1 : ce que Presidio DECLARE supporter -----------------------------
    separateur("D1  Types d'entites que Presidio expose pour cette langue")
    exposees = sorted(analyseur.get_supported_entities(language=args.langue))
    print("   " + ", ".join(exposees))
    org_declare = "ORGANIZATION" in exposees
    print(f"\n   ORGANIZATION declare : {org_declare}")

    # -- D2 : la configuration NER reellement utilisee ----------------------
    separateur("D2  Configuration NER utilisee (NerModelConfiguration)")
    c = moteur.ner_model_configuration
    print(f"   labels_to_ignore            : {list(c.labels_to_ignore)}")
    print(f"   low_score_entity_names      : {list(c.low_score_entity_names)}")
    print(f"   low_confidence_score_multiplier : {c.low_confidence_score_multiplier}")
    print(f"   default_score               : {c.default_score}")
    print(f"   correspondance ORG          -> {c.model_to_presidio_entity_mapping.get('ORG')}")

    # -- D4 : ce que Presidio produit vraiment, a seuil nul -----------------
    separateur("D4  Detections Presidio, seuil 0,0 puis seuil applique")
    r0 = analyseur.analyze(text=args.texte, language=args.langue,
                           score_threshold=0.0)
    for x in sorted(r0, key=lambda r: r.start):
        print(f"   {x.entity_type:<14} {x.score:.3f}   "
              f"{args.texte[x.start:x.end]}")
    orgs_seuil_nul = [x for x in r0 if x.entity_type == "ORGANIZATION"]

    rs = analyseur.analyze(text=args.texte, language=args.langue,
                           score_threshold=args.seuil)
    orgs_seuil = [x for x in rs if x.entity_type == "ORGANIZATION"]
    print(f"\n   ORGANIZATION a seuil 0,0        : {len(orgs_seuil_nul)}"
          f"  (scores : {[round(x.score, 3) for x in orgs_seuil_nul]})")
    print(f"   ORGANIZATION a seuil {args.seuil}        : {len(orgs_seuil)}")

    # -- Verdict ------------------------------------------------------------
    separateur("VERDICT")
    if not org_spacy:
        print("   EN AMONT : spaCy n'a trouve aucune ORG dans ce texte.")
        print("   Relancez avec un --texte tire d'une vraie note du corpus")
        print("   avant de conclure : ce diagnostic n'a de sens que si le")
        print("   temoin D3 contient au moins une organisation.")
    elif not orgs_seuil_nul:
        print("   HYPOTHESE 2 : reconnaisseur ORG non expose.")
        print("   spaCy produit ORG, mais Presidio ne le recoit pas : il est")
        print("   filtre par labels_to_ignore (voir D2). Le seuil n'y est pour")
        print("   rien : l'entite est retiree avant tout calcul de score.")
        print("   => probleme de CONFIGURATION, cote Presidio.")
    elif not orgs_seuil:
        print(f"   HYPOTHESE 1 : effet de seuil.")
        print(f"   ORGANIZATION est produit mais avec un score de "
              f"{[round(x.score, 3) for x in orgs_seuil_nul]}, sous le seuil de")
        print(f"   {args.seuil}. Voir low_score_entity_names en D2 : Presidio")
        print("   baisse le score des entites jugees peu fiables.")
        print("   => probleme de SEUIL, cote Presidio.")
    else:
        print("   NI 1 NI 2 : Presidio produit bien ORGANIZATION au-dessus du")
        print("   seuil. L'entite se perd donc ensuite, dans notre code.")
        print("   => voir le releve D5 (table NORMALISATION) ci-dessous.")
        print("   Cause la plus probable : Presidio produit 'ORGANIZATION'")
        print("   (orthographe americaine) alors que notre table ne connait")
        print("   que 'ORG' ou 'ORGANISATION'.")

    # -- D5 : table de normalisation du projet ------------------------------
    separateur("D5  Notre table NORMALISATION")
    try:
        from src.confidentialite import verrou
        table = getattr(verrou, "NORMALISATION", None)
        if table is None:
            print("   verrou.NORMALISATION introuvable : le nom de la table a")
            print("   change. Cherchez-la dans src/confidentialite/verrou.py.")
        else:
            for cle in sorted(table):
                print(f"   {cle:<16} -> {table[cle]}")
            for cle in ("ORG", "ORGANIZATION", "ORGANISATION"):
                print(f"   cle '{cle}' presente : {cle in table}")
    except Exception as e:  # noqa: BLE001
        print(f"   import de src.confidentialite.verrou impossible : {e}")
        print("   Lancez depuis la racine du depot, venv actif.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
