r"""
Interroge le systeme avec des questions dont la reponse attendue est connue.

    .venv\Scripts\python.exe scripts\run_recherche_questions.py

Ecrit un fichier par question sous `resultats/recherche_questions/`, nomme
`Resultats_recherche_question_<n>.txt`, avec la question, l'ancrage attendu,
puis les resultats du systeme : rang, score, ancrage exact et les trente
premiers caracteres du texte.

COMPARAISON PAR ANCRAGE

Verifier une recherche en lisant des extraits est lent et subjectif.
Comparer deux chemins est simple : `eurlex/MiFID2/FR/art_29/p66_7bf8c66d`
est le bon passage, ou pas. Les trente caracteres servent seulement a voir
de quoi parle le passage, pas a juger s'il est correct.

LIMITE DE LA MESURE

Le rappel se calcule ici avec un seul document attendu par question : il
vaut 1 si ce document est dans les k premiers, 0 sinon. Or, sur une question
reglementaire, plusieurs passages peuvent repondre (un article et son
considerant, la version FR et la version EN). Un rappel de 0 veut donc dire
que le passage de reference n'est pas dans les k premiers, pas forcement que
la reponse y manque. C'est une borne basse.

C'est aussi pour cela que chaque fichier liste les resultats : on voit tout
de suite si un passage proche du bon a ete trouve, ce qu'un chiffre seul ne
montre pas.
"""

import argparse
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

from src.commun import config as mod_config          # noqa: E402
from src.evaluation import montage_gpu as montage    # noqa: E402

# Les douze questions reglementaires, avec le passage d'ou elles viennent.
# Ecrites le 13/09/2026 en lisant le corpus.
QUESTIONS = [
    ("Quelles procédures doivent être faites par les déployeurs avant de mettre en service ou d'utiliser un système d'IA à haut risque ?",
     "eurlex/AI_Act/FR/art_49/p81_51e82120"),
    ("Qui doit démontrer le caractère infondé ou excessif de la demande 6 ?",
     "eurlex/RGPD/FR/art_12/p40_46255e14"),
    ("Quelles actions sont autorisés à effectuer des agents liés à qui une entreprise d'investissement fait appel ?",
     "eurlex/MiFID2/FR/art_29/p66_7bf8c66d"),
    ("Quelles conditions remplit un représentant d'un État membre du comité IA ?",
     "eurlex/AI_Act/FR/considerants/p38_ddf085be"),
    ("Que doit au moins indiquer l'alerte qualifiée ?",
     "eurlex/AI_Act/FR/art_90/p111_2277557c"),
    ("Dans quel cas l'obligation de fournir des informations sur les sanctions et mesures imposées ne s'applique pas ?",
     "eurlex/MiFID2/FR/art_71/p113_feb28565"),
    ("A qui les organisme d'évaluation de la conformité doivent-ils soumettre une demande de notification ?",
     "eurlex/AI_Act/FR/art_29/p70_5c2cef6e"),
    ("Quelle est la période maximale de conservation des données à caractère personnel du paragraphe 1?",
     "eurlex/DORA/FR/art_56/p73_c657fbe4"),
    ("Quelles sont les parties prenantes du forum consultatif ?",
     "eurlex/AI_Act/FR/art_67/p97_43a86f20"),
    ("À quelles exigences sont soumises les entreprises d'investissement qui exécutent des ordres de clients ?",
     "eurlex/MiFID2/FR/art_27/p65_dc0af581"),
    ("À quelles exigences est soumis un marché réglementé qui suspend la négociation dans tout État membre ?",
     "eurlex/MiFID2/FR/art_48/p84_17b080b3"),
    ("Que précise exactement un agrément ?",
     "eurlex/MiFID2/FR/art_60/p98_eecdff2b"),
]

RANGS = (5, 10, 25)
EXTRAIT = 30


def charger_textes(chemin="data/external/eurlex/eurlex_schema.json"):
    with open(chemin, encoding="utf-8") as f:
        return {d["doc_id"]: d.get("text", "") for d in json.load(f)}


def ecrire(dossier, numero, question, attendu, resultats, textes,
           configuration):
    chemin = dossier / ("Resultats_recherche_question_%d.txt" % numero)
    lignes = []
    lignes.append("=" * 78)
    lignes.append("QUESTION %d" % numero)
    lignes.append("=" * 78)
    lignes.append("")
    lignes.append("Enonce :")
    lignes.append("  %s" % question)
    lignes.append("")
    lignes.append("Ancrage attendu :")
    lignes.append("  %s" % attendu)
    texte_attendu = " ".join(textes.get(attendu, "").split())
    lignes.append("  extrait : %s..." % texte_attendu[:120])
    lignes.append("")
    lignes.append("Configuration de recherche : %s" % configuration)
    lignes.append("")

    rangs_trouves = [r for r, (d, _) in enumerate(resultats, start=1)
                     if d == attendu]
    rang = rangs_trouves[0] if rangs_trouves else None

    lignes.append("-" * 78)
    lignes.append("RAPPEL")
    lignes.append("-" * 78)
    for k in RANGS:
        atteint = rang is not None and rang <= k
        lignes.append("  rappel@%-3d : %-4s%s"
                      % (k, "OUI" if atteint else "non",
                         "   (rang %d)" % rang if atteint else ""))
    if rang is None:
        lignes.append("")
        lignes.append("  Le passage attendu n'apparait dans aucun des %d "
                      "premiers resultats." % len(resultats))
    lignes.append("")

    lignes.append("-" * 78)
    lignes.append("RESULTATS RENDUS PAR LE SYSTEME")
    lignes.append("-" * 78)
    lignes.append("%-5s %-9s %-46s %s"
                  % ("rang", "score", "ancrage", "debut du texte"))
    lignes.append("-" * 78)
    for position, (doc_id, score) in enumerate(resultats, start=1):
        marque = "  <== ATTENDU" if doc_id == attendu else ""
        extrait = " ".join(textes.get(doc_id, "").split())[:EXTRAIT]
        lignes.append("%-5d %-9.4f %-46s %s%s"
                      % (position, score, doc_id, extrait, marque))
    lignes.append("")

    chemin.write_text("\n".join(lignes), encoding="utf-8")
    return chemin, rang


def main():
    parseur = argparse.ArgumentParser(
        description="Recherche sur des questions a reponse connue")
    parseur.add_argument("--configuration", default="lexical",
                         choices=("lexical", "dense", "fusion", "complet"))
    parseur.add_argument("--k", type=int, default=25,
                         help="profondeur affichee, au moins max(RANGS)")
    parseur.add_argument("--sortie", default="resultats/recherche_questions")
    arguments = parseur.parse_args()

    config = mod_config.Config()
    textes = charger_textes()

    index_lexical = montage.charger_index_lexical(
        "data/index_lexical/eurlex.pkl")
    vectoriseur = index_dense = None
    if arguments.configuration != "lexical":
        vectoriseur = montage.charger_vectoriseur(config)
        index_dense = montage.charger_index_dense(config)

    fabrique = montage.fabrique(config, index_dense, index_lexical,
                                vectoriseur, corpus="eurlex")
    recuperateur = fabrique(arguments.configuration)
    if recuperateur is None:
        raise SystemExit("configuration '%s' indisponible : il manque un "
                         "index." % arguments.configuration)

    dossier = Path(arguments.sortie)
    dossier.mkdir(parents=True, exist_ok=True)

    compte = {k: 0 for k in RANGS}
    print("configuration : %s" % arguments.configuration)
    print("questions     : %d\n" % len(QUESTIONS))

    for numero, (question, attendu) in enumerate(QUESTIONS, start=1):
        fragments = recuperateur.rechercher(question, n=arguments.k,
                                            avec_teinte=False)
        resultats = [(f.doc_id, f.score) for f in fragments]
        chemin, rang = ecrire(dossier, numero, question, attendu, resultats,
                              textes, arguments.configuration)
        for k in RANGS:
            if rang is not None and rang <= k:
                compte[k] += 1
        etat = ("rang %d" % rang) if rang else "absent"
        print("  question %-3d %-10s -> %s" % (numero, etat, chemin.name))

    n = len(QUESTIONS)
    print("\n%-12s %s" % ("", "  ".join("rappel@%d" % k for k in RANGS)))
    print("%-12s %s" % ("global",
                        "  ".join("%9.4f" % (compte[k] / n) for k in RANGS)))

    resume = dossier / "000_synthese.txt"
    with open(resume, "w", encoding="utf-8") as f:
        f.write("Recherche sur %d questions a reponse connue\n" % n)
        f.write("Configuration : %s\n\n" % arguments.configuration)
        for k in RANGS:
            f.write("rappel@%-3d : %.4f   (%d sur %d)\n"
                    % (k, compte[k] / n, compte[k], n))
    print("\nsynthese : %s" % resume)


if __name__ == "__main__":
    main()
