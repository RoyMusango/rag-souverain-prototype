"""
Adaptateur EUR-Lex -> schema commun, version 4.

Correctif v3 : trois des quatre textes (RGPD, DORA, AI Act) contiennent des
espaces parasites a l'interieur des mots (« Ar ticle 6 », « trait ement »),
artefact d'extraction lie au positionnement des glyphes. Le motif d'en-tete
d'article ne pouvait donc pas s'appliquer ; MiFID II, exempt de ce defaut,
etait le seul texte correctement segmente en v2.

La v3 normalise chaque ligne avant la detection, sans modifier le texte
stocke : la fonction compacter() ne sert qu'au motif, et l'indexation
conserve le texte d'origine.

Correctif v4 : l'extraction passe de pypdf a pymupdf. La v3 contournait les
espaces parasites pour la detection des en-tetes, mais les conservait dans
le texte stocke, ou ils perturbaient silencieusement la tokenisation de BM25.
Mesure du 01/09 : 26 881 occurrences de lettre isolee sous pypdf, 2 514 sous
pymupdf, et 214 coupures intra-mot certaines ramenees a zero. La v4 corrige
aussi les doc_id, qui reposaient sur hash() et n'etaient donc pas
reproductibles d'une execution a l'autre.

Sortie : data/external/eurlex/eurlex_schema.json
"""

import re
import sys
from collections import Counter
from pathlib import Path
import hashlib
import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from common import (charger_ner, extraire_entites_lot, numeroter_paves,
                    dedupliquer, ecrire, rapport)

DOSSIER = Path("data/external/eurlex")
SORTIE = DOSSIER / "eurlex_schema.json"

ARTICLES_ATTENDUS = {"DORA": 64, "RGPD": 99, "AI_Act": 113, "MiFID2": 97}

MOTIF_ARTICLE = re.compile(
    r"^\s*(?:Article|Artikel)\s*(premier|first|\d+)\b", re.IGNORECASE)

LONGUEUR_MIN_PARAGRAPHE = 60


def compacter(ligne):
    """
    Recolle les fragments de mots separes par un espace unique.
    Usage strictement limite a la detection : appliquee au texte stocke,
    cette fonction le rendrait illisible en supprimant les espaces legitimes
    entre mots courts.
    """
    return re.sub(r"(?<=\w) (?=\w)", "", ligne)


def paragraphes_de_page(texte):
    """
    Retourne [(numero_article_ou_None, paragraphe)].
    La detection se fait ligne par ligne, avant toute agregation : c'est la
    correction apportee en v3, ou le motif etait teste sur des blocs deja
    constitues et manquait les en-tetes non isoles.
    """
    blocs, courant, article_du_bloc = [], [], None
    for ligne in texte.split("\n"):
        nue = ligne.strip()
        if not nue:
            if courant:
                blocs.append((article_du_bloc, " ".join(courant)))
                courant, article_du_bloc = [], None
            continue
        m = MOTIF_ARTICLE.match(compacter(nue))
        if m:
            if courant:
                blocs.append((article_du_bloc, " ".join(courant)))
                courant = []
            brut = m.group(1).lower()
            article_du_bloc = "1" if brut in ("premier", "first") else brut
        courant.append(nue)
        if nue.endswith(".") and len(nue) < 70:
            blocs.append((article_du_bloc, " ".join(courant)))
            courant, article_du_bloc = [], None
    if courant:
        blocs.append((article_du_bloc, " ".join(courant)))
    return blocs


records = []

for pdf in sorted(DOSSIER.glob("*.pdf")):
    nom = pdf.stem
    # Le nom peut contenir un identifiant en plusieurs segments (AI_Act) :
    # la langue est reperee par sa valeur, non par sa position.
    parts = nom.split("_")
    langue = next((p for p in parts if p in ("FR", "EN", "DE", "NL")), "XX")
    texte_id = "_".join(parts[:parts.index(langue)]) if langue in parts else parts[0]

    # pymupdf plutot que pypdf : ce dernier reconstruit le texte a partir du
    # positionnement des glyphes et insere des espaces a l'interieur des mots
    # (« har monised », « REGUL A TION »). Mesure du 01/09 : 26 881
    # occurrences de lettre isolee avec pypdf contre un plancher legitime de
    # 2 514 avec pymupdf, et 214 coupures intra-mot certaines ramenees a zero.
    # La segmentation par article resistait grace a compacter(), mais pas la
    # recuperation lexicale.
    document = pymupdf.open(str(pdf))
    article = "considerants"
    page_article = 1
    articles_vus = set()
    n_avant = len(records)

    for num_page, page in enumerate(document, start=1):
        texte = page.get_text() or ""
        if not texte.strip():
            continue

        for numero, bloc in paragraphes_de_page(texte):
            if numero:
                article = f"art_{numero}"
                page_article = num_page
                articles_vus.add(numero)

            if len(bloc) < LONGUEUR_MIN_PARAGRAPHE:
                continue

            rubrique = f"eurlex/{texte_id}/{langue}/{article}"
            records.append({
                # `hash()` sur une chaine est randomise par PYTHONHASHSEED,
                # qui ne peut pas etre fixe apres le demarrage de
                # l'interpreteur : `profils.appliquer_determinisme` le fixe
                # trop tard, et ce script ne l'appelle pas. Deux ingestions
                # successives produisaient donc des doc_id differents pour le
                # meme paragraphe, ce qui affectait tout ce qui repose sur
                # l'identifiant : l'intersection de parite de
                # `derive_representation`, la persistance des embeddings et
                # l'attribution d'E4. Le § 4.1.5 annonce des executions
                # rejouables ; sur ce corpus, elles ne l'etaient pas.
                "doc_id":   f"{rubrique}/p{num_page}_"
                            f"{hashlib.sha1(bloc.encode('utf-8')).hexdigest()[:8]}",
                "text":     bloc,
                "source":   "externe",
                "entities": [],
                "rubrique": rubrique,
                "page":     page_article if article != "considerants" else num_page,
                "pave":     0,
            })

    attendu = ARTICLES_ATTENDUS.get(texte_id)
    marqueur = ""
    if attendu and len(articles_vus) / attendu < 0.7:
        marqueur = "  <-- SOUS-DETECTION"
    print(f"  {nom:28s} : {document.page_count:3d} pages | "
          f"{len(articles_vus):3d} articles"
          f"{f' (attendu ~{attendu})' if attendu else ''} | "
          f"{len(records) - n_avant} paragraphes{marqueur}")

records, doublons = dedupliquer(records)
records = numeroter_paves(records)

print("\nExtraction NER (fr pour FR, en pour EN)...")
fr = [r for r in records if "/FR/" in r["doc_id"]]
en = [r for r in records if "/FR/" not in r["doc_id"]]

troncatures = 0
if fr:
    nlp_fr = charger_ner("fr_core_news_lg")
    ents, t = extraire_entites_lot([r["text"] for r in fr], nlp_fr, batch_size=64)
    troncatures += t
    for r, e in zip(fr, ents):
        r["entities"] = e
if en:
    nlp_en = charger_ner("en_core_web_lg")
    ents, t = extraire_entites_lot([r["text"] for r in en], nlp_en, batch_size=64)
    troncatures += t
    for r, e in zip(en, ents):
        r["entities"] = e

chemin = ecrire(records, SORTIE)
rapport("eurlex", records, chemin, doublons, troncatures)

print("Verification de la chaine I3 (le seul corpus a quatre niveaux) :")
print(f"  pages distinctes      : {len(Counter(r['page'] for r in records))}")
print(f"  rubriques (articles)  : {len({r['rubrique'] for r in records})}")
print(f"  pave maximal          : {max((r['pave'] for r in records), default=0)}")


