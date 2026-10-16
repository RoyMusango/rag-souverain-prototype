"""
Adaptateur EUR-Lex -> schema commun, version 4.

Correctif v3 : trois des quatre textes (RGPD, DORA, AI Act) contiennent des
espaces en trop a l'interieur des mots (« Ar ticle 6 », « trait ement »).
Ils viennent de l'extraction, qui se base sur la position des caracteres.
Le motif d'en-tete d'article ne les reconnaissait donc pas. En v2, seul
MiFID II, qui n'a pas ce defaut, etait bien decoupe.

La v3 nettoie chaque ligne avant la detection, sans toucher au texte
enregistre : compacter() sert seulement au motif, et l'index garde le texte
d'origine.

Correctif v4 : l'extraction passe de pypdf a pymupdf. La v3 detectait bien
les en-tetes, mais les espaces en trop restaient dans le texte enregistre,
ou ils genaient le decoupage en jetons de BM25 sans que rien ne le signale.
Mesure du 01/09 : 26 881 lettres isolees avec pypdf, 2 514 avec pymupdf, et
les 214 coupures certaines a l'interieur d'un mot disparaissent. La v4
corrige aussi les doc_id, qui utilisaient hash() et changeaient donc d'une
execution a l'autre.

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
    Recolle les morceaux de mots separes par un seul espace.
    A utiliser seulement pour la detection : sur le texte enregistre, cette
    fonction le rendrait illisible, car elle supprime aussi les vrais espaces
    entre mots courts.
    """
    return re.sub(r"(?<=\w) (?=\w)", "", ligne)


def paragraphes_de_page(texte):
    """
    Renvoie [(numero_article_ou_None, paragraphe)].
    La detection se fait ligne par ligne, avant de regrouper les lignes en
    blocs. Avant la v3, le motif etait teste sur des blocs deja formes et
    ratait les en-tetes qui n'etaient pas seuls sur leur ligne.
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
    # Le nom peut contenir un identifiant en plusieurs morceaux (AI_Act) : on
    # repere la langue par sa valeur, pas par sa position.
    parts = nom.split("_")
    langue = next((p for p in parts if p in ("FR", "EN", "DE", "NL")), "XX")
    texte_id = "_".join(parts[:parts.index(langue)]) if langue in parts else parts[0]

    # pymupdf plutot que pypdf : pypdf reconstruit le texte a partir de la
    # position des caracteres et ajoute des espaces dans les mots
    # (« har monised », « REGUL A TION »). Mesure du 01/09 : 26 881 lettres
    # isolees avec pypdf, contre 2 514 avec pymupdf (les cas normaux), et les
    # 214 coupures certaines dans un mot disparaissent. Grace a compacter(),
    # le decoupage par article fonctionnait, mais la recherche lexicale
    # souffrait.
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
                # `hash()` sur une chaine depend de PYTHONHASHSEED, qu'on ne
                # peut plus fixer une fois l'interpreteur lance :
                # `profils.appliquer_determinisme` le fixe trop tard, et ce
                # script ne l'appelle pas. Deux ingestions donnaient donc des
                # doc_id differents pour le meme paragraphe. Cela cassait tout
                # ce qui utilise l'identifiant : la comparaison de
                # `derive_representation`, la sauvegarde des embeddings et
                # l'attribution d'E4. Le § 4.1.5 promet des executions
                # rejouables, ce qui n'etait pas le cas sur ce corpus. SHA-1
                # donne toujours le meme resultat.
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

print("Verification de la chaine I3 (seul corpus a quatre niveaux) :")
print(f"  pages distinctes      : {len(Counter(r['page'] for r in records))}")
print(f"  rubriques (articles)  : {len({r['rubrique'] for r in records})}")
print(f"  pave maximal          : {max((r['pave'] for r in records), default=0)}")


