"""
E7 : comparaison des detecteurs d'entites nommees.

Le rapport choisit une chaine de masquage souveraine et dit que l'ecart avec
Presidio est mesure. Ce module fait cette mesure.

VERITE TERRAIN

Le champ `entities` du schema commun contient les entites trouvees par spaCy
a l'ingestion. Le prendre comme reference reviendrait a comparer spaCy a
lui-meme : il aurait 100 % d'office, et Presidio serait penalise a chaque
desaccord, meme quand il a raison.

Je construis donc la reference a partir des donnees structurees de Synthea.
`patients.csv` donne le nom, le prenom, la ville, le code postal et la date
de naissance de chaque patient, et l'adaptateur `synthea.py` ecrit la
rubrique `identite` a partir de ces memes champs. On connait donc exactement
les chaines sensibles de la rubrique et leur position.

C'est le meme principe que pour E2 : la mesure est exacte parce que toute la
population est connue.

Valeurs mesurees : rappel (la fuite), precision (le sur-masquage), F1 et
debit. Le rappel compte le plus, car une entite non detectee franchit la
Frontiere A en clair.
"""

import csv
import re
import time
from pathlib import Path

from ..confidentialite.verrou import CAMEMBERT, Masqueur, PRESIDIO, SPACY

# Colonnes de patients.csv qui forment la rubrique identite, avec la
# categorie attendue pour chacune. Voir src/ingestion/synthea.py.
CHAMPS_SENSIBLES = {
    "FIRST": "PERSONNE",
    "LAST": "PERSONNE",
    "CITY": "LIEU",
    "COUNTY": "LIEU",
    "ZIP": "LIEU",
    "BIRTHDATE": "DATE",
    "DEATHDATE": "DATE",
    "ADDRESS": "LIEU",
}

# Suffixes numeriques retires a l'ingestion (common.nettoyer_nom_synthea).
# La reference fait la meme chose, sinon elle chercherait « Wallace647 » dans
# un texte qui contient « Wallace ».
MOTIF_CHIFFRES = re.compile(r"\d+")


def _nettoyer(nom):
    return MOTIF_CHIFFRES.sub("", str(nom)).strip()


def construire_reference(chemin_patients="data/synthea/patients.csv",
                         limite=None):
    """Verite terrain par patient : les chaines sensibles.

    Renvoie [{"patient": id, "attendus": [(chaine, categorie), ...]}].
    """
    reference = []
    with open(chemin_patients, encoding="utf-8") as f:
        for ligne in csv.DictReader(f):
            attendus = []
            for colonne, categorie in CHAMPS_SENSIBLES.items():
                valeur = (ligne.get(colonne) or "").strip()
                if colonne in ("FIRST", "LAST"):
                    valeur = _nettoyer(valeur)
                # Les chaines tres courtes donneraient des correspondances
                # par hasard : « MA » se retrouve dans beaucoup de mots.
                if len(valeur) >= 4:
                    attendus.append((valeur, categorie))
            reference.append({"patient": ligne["Id"], "attendus": attendus})
            if limite and len(reference) >= limite:
                break
    return reference


def positions_attendues(texte, attendus):
    """Localise chaque chaine sensible dans le texte de la rubrique."""
    trouvees = []
    for chaine, categorie in attendus:
        debut = 0
        while True:
            position = texte.find(chaine, debut)
            if position < 0:
                break
            trouvees.append((position, position + len(chaine), categorie))
            debut = position + 1
    return trouvees


def _recouvre(span_a, span_b, seuil=0.5):
    """Indique si deux empans se chevauchent assez.

    Exiger une egalite exacte serait trop severe : un detecteur qui trouve
    « Boston, MA » quand la reference indique « Boston » a fait son travail.
    Je demande donc un chevauchement suffisant.
    """
    debut = max(span_a[0], span_b[0])
    fin = min(span_a[1], span_b[1])
    if fin <= debut:
        return False
    intersection = fin - debut
    longueur_reference = span_a[1] - span_a[0]
    return intersection / longueur_reference >= seuil


def evaluer_texte(texte, attendus, masqueur, seuil=0.5,
                  categorie_stricte=False):
    """Compte vrais positifs, faux negatifs et faux positifs sur un texte."""
    reference = positions_attendues(texte, attendus)
    detectees = masqueur.detecter(texte)

    apparies = set()
    vrais_positifs = 0
    for span_ref in reference:
        for i, span_det in enumerate(detectees):
            # Une detection peut couvrir plusieurs entites de la reference :
            # « Pieter Marchand » est un seul empan, alors que la reference a
            # le prenom et le nom separes. Avant, une detection ne pouvait
            # couvrir qu'une entite : le nom etait compte comme faux negatif,
            # et le rappel sur les personnes etait divise par deux.
            if _recouvre(span_ref, span_det, seuil):
                if categorie_stricte and span_ref[2] != span_det[2]:
                    continue
                apparies.add(i)
                vrais_positifs += 1
                break

    return {
        "vrais_positifs": vrais_positifs,
        "faux_negatifs": len(reference) - vrais_positifs,
        "faux_positifs": len(detectees) - len(apparies),
        "reference": len(reference),
        "detectees": len(detectees),
        # `vrais_positifs` compte des entites de reference. Depuis le
        # correctif du 31/08, une detection peut en couvrir plusieurs. Ce
        # compte ne peut donc pas servir a calculer la precision, qui porte
        # sur les detections : je compte ici les detections appariees.
        "detections_appariees": len(apparies),
    }


def evaluer_moteur(documents, reference, moteur=SPACY, langue="fr",
                   seuil=0.5, categorie_stricte=False):
    """Mesure un detecteur sur les rubriques identite de Synthea.

    `documents` : rubriques `identite` du schema commun, dont le `doc_id` est
    de la forme `synthea/<patient_id>/identite`.
    """
    par_patient = {r["patient"]: r["attendus"] for r in reference}
    masqueur = Masqueur(moteur=moteur, langue=langue)

    totaux = {"vrais_positifs": 0, "faux_negatifs": 0, "faux_positifs": 0,
              "reference": 0, "detectees": 0, "detections_appariees": 0}
    caracteres = 0
    debut = time.perf_counter()

    for document in documents:
        morceaux = str(document.get("doc_id", "")).split("/")
        if len(morceaux) < 2:
            continue
        attendus = par_patient.get(morceaux[1])
        if not attendus:
            continue
        texte = document.get("text", "")
        caracteres += len(texte)
        compte = evaluer_texte(texte, attendus, masqueur, seuil,
                               categorie_stricte)
        for cle in totaux:
            totaux[cle] += compte[cle]

    duree = time.perf_counter() - debut
    vp, fn, fp = (totaux["vrais_positifs"], totaux["faux_negatifs"],
                  totaux["faux_positifs"])
    rappel = vp / (vp + fn) if (vp + fn) else None
    # `vp / (vp + fp)` melangeait deux unites : le numerateur compte des
    # entites de reference, le denominateur des references et des
    # detections. Sur E7, cette formule donnait 0,877, alors que la precision
    # calculee sur les detections donne 0,835, la meme valeur qu'avant le
    # correctif d'appariement. Je garde l'ancienne formule a cote, sous le
    # nom `precision_par_reference`, pour la tracabilite.
    precision = (totaux["detections_appariees"] / totaux["detectees"]
                 if totaux["detectees"] else None)
    precision_par_reference = vp / (vp + fp) if (vp + fp) else None
    f1 = (2 * rappel * precision / (rappel + precision)
          if rappel and precision else None)

    return {
        "moteur": moteur,
        "detecteur": masqueur.decrire(),
        "documents": len(documents),
        **totaux,
        "rappel": round(rappel, 4) if rappel is not None else None,
        "precision": round(precision, 4) if precision is not None else None,
        "precision_par_reference": (round(precision_par_reference, 4)
                                    if precision_par_reference is not None
                                    else None),
        "f1": round(f1, 4) if f1 is not None else None,
        "duree_s": round(duree, 2),
        "debit_car_s": round(caracteres / duree) if duree else None,
    }


def campagne(documents, reference, moteurs=(SPACY, CAMEMBERT, PRESIDIO),
             langue="fr", seuil=0.5):
    """Compare les detecteurs et calcule leur ecart avec Presidio."""
    resultats = {}
    for moteur in moteurs:
        try:
            resultats[moteur] = evaluer_moteur(
                documents, reference, moteur, langue, seuil)
        except Exception as erreur:
            # Si un moteur manque, la campagne continue : je note l'erreur et
            # je garde les mesures des autres moteurs.
            resultats[moteur] = {"moteur": moteur, "erreur": str(erreur)}

    disponibles = {n: r for n, r in resultats.items()
                   if r.get("rappel") is not None}
    ecarts = {}
    if PRESIDIO in disponibles:
        base = disponibles[PRESIDIO]["rappel"]
        for nom, mesure in disponibles.items():
            if nom != PRESIDIO:
                ecarts[nom] = {
                    "rappel_absolu": round(mesure["rappel"] - base, 4),
                    "rappel_relatif": round(
                        (mesure["rappel"] - base) / base, 4) if base else None,
                }

    return {
        "resultats": resultats,
        "ecart_sur_presidio": ecarts,
        "lecture": (
            "Le rappel compte le plus : une entite non detectee franchit la "
            "Frontiere A en clair. La precision mesure le sur-masquage, qui "
            "rend la recherche moins bonne sans rien proteger (son cout se "
            "voit dans E5). Si le moteur souverain a un rappel plus bas, "
            "l'ecart est rapporte tel quel : c'est le prix de la "
            "souverainete. Le verrou de sortie deterministe bloque de toute "
            "facon les secrets connus, quel que soit le detecteur."
        ),
    }
