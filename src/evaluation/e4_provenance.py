"""
E4 : attribuabilite. Chaque assertion est-elle rattachable a un pave ?

Grandeur rapportee : la part des assertions rattachees a une reference
complete document -> rubrique -> page -> pave.

Limite : cinq corpus sur six ont page = 1, un courriel ou un resume n'ayant
pas de pagination native (JOURNAL_DONNEES section 5.1). Seul EUR-Lex
instancie effectivement les quatre niveaux ; la mesure a quatre niveaux
repose donc sur lui, et la mesure a trois niveaux sur les autres. Ce module
distingue les deux plutot que de melanger des chiffres non comparables.
"""

from ..isolation import teinte

NIVEAUX = ("doc_id", "rubrique", "page", "pave")


def profondeur(fragment):
    """Nombre de niveaux effectivement renseignes pour ce fragment."""
    atteinte = 0
    if str(fragment.doc_id).strip():
        atteinte += 1
    if str(fragment.rubrique).strip():
        atteinte += 1
    if int(fragment.page or 0) >= 1:
        atteinte += 1
    if int(fragment.pave or 0) >= 1:
        atteinte += 1
    return atteinte


def corpus_a_quatre_niveaux(fragments):
    """Corpus dont la pagination est reelle, donc eligibles a la mesure 4/4."""
    pages = {}
    for fragment in fragments:
        pages.setdefault(fragment.origine or "inconnu", set()).add(
            int(fragment.page or 1)
        )
    return {corpus for corpus, valeurs in pages.items() if len(valeurs) > 1}


def evaluer(reponses, fragments_par_reponse=None):
    """Taux d'attribuabilite, ventile par profondeur atteinte."""
    total = 0
    par_profondeur = {1: 0, 2: 0, 3: 0, 4: 0}
    sans_source = 0
    non_verifiees = 0

    for reponse in reponses:
        if reponse.abstention:
            continue
        for assertion in reponse.assertions:
            total += 1
            if not assertion.fragments:
                sans_source += 1
                continue
            if not assertion.verifiee:
                non_verifiees += 1
            # La profondeur retenue est celle du fragment le plus precis :
            # une assertion soutenue par un pave EUR-Lex et un courriel est
            # attribuable au pave.
            meilleure = max(profondeur(f) for f in assertion.fragments)
            par_profondeur[meilleure] = par_profondeur.get(meilleure, 0) + 1

    if not total:
        return {"comparable": False, "motif": "aucune assertion emise"}

    attribuees = total - sans_source
    return {
        "comparable": True,
        "assertions": total,
        "attribuees": attribuees,
        "taux_attribuabilite": round(attribuees / total, 4),
        "taux_quatre_niveaux": round(par_profondeur.get(4, 0) / total, 4),
        "repartition_profondeur": par_profondeur,
        "sans_source": sans_source,
        "taux_non_verifiees": round(non_verifiees / attribuees, 4)
        if attribuees else None,
        "note": ("le taux a quatre niveaux n'est interpretable que sur les "
                 "corpus a pagination reelle ; voir JOURNAL_DONNEES 5.1"),
    }


def verifier_chaine(fragments):
    """Controle que la chaine de provenance n'a pas ete rompue.

    Couvre la menace « rupture de chaine » du modele de menace : une perte du
    lien fragment -> source, sans adversaire actif, qui viole I3 sans signal.
    """
    ruptures = []
    for fragment in fragments:
        manquants = [
            niveau for niveau in NIVEAUX
            if not str(getattr(fragment, niveau, "")).strip()
        ]
        if manquants:
            ruptures.append({
                "doc_id": fragment.doc_id, "manquants": manquants,
                "reference": fragment.reference(),
            })
    return {
        "fragments": len(fragments),
        "ruptures": len(ruptures),
        "taux_integrite": round(1 - len(ruptures) / len(fragments), 4)
        if fragments else None,
        "exemples": ruptures[:5],
    }
