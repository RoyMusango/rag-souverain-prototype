"""
Metriques d'evaluation (chapitre 5).

Trois familles, chacune adossee a une reference de la bibliographie du
rapport :

  RECUPERATION  Recall@k et nDCG            -> jarvelin2002ndcg
  REPONSE       cadre Ragas : fidelite, pertinence, precision et rappel de
                contexte                    -> es2023ragas
  JUGEMENT      modele employe comme juge, avec ses biais documentes
                                            -> zheng2023judge

Les biais de position, de verbosite et d'auto-preference d'un juge
automatique sont documentes. Je les controle explicitement (permutation des
ordres, normalisation de longueur, interdiction pour un modele de se juger
lui-meme) plutot que de les subir.
"""

import math
import re
import statistics


# -------------------------------------------------------------- recuperation

def recall_at_k(pertinents, classement, k=10, cle=lambda x: x):
    """Proportion des documents pertinents retrouves dans le top-k."""
    if not pertinents:
        return None
    tete = {cle(d) for d in classement[:k]}
    return len(tete & set(pertinents)) / len(pertinents)


def precision_at_k(pertinents, classement, k=10, cle=lambda x: x):
    if not classement[:k]:
        return 0.0
    tete = [cle(d) for d in classement[:k]]
    return sum(1 for d in tete if d in set(pertinents)) / len(tete)


def mrr(pertinents, classement, cle=lambda x: x):
    """Rang reciproque du premier document pertinent."""
    ensemble = set(pertinents)
    for rang, document in enumerate(classement, start=1):
        if cle(document) in ensemble:
            return 1.0 / rang
    return 0.0


def dcg(gains):
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def ndcg_at_k(pertinences, classement, k=10, cle=lambda x: x):
    """nDCG : gain cumule actualise, normalise par le classement ideal.

    `pertinences` associe un identifiant a un gain (0, 1, 2...). Les gains
    gradues, plutot que binaires, distinguent nDCG du rappel : un passage tres
    pertinent en tete vaut mieux que trois passages moyens.
    """
    obtenus = [pertinences.get(cle(d), 0) for d in classement[:k]]
    ideaux = sorted(pertinences.values(), reverse=True)[:k]
    denominateur = dcg(ideaux)
    return (dcg(obtenus) / denominateur) if denominateur else 0.0


# ------------------------------------------------------------------ reponse

def decouper_phrases(texte):
    """Segmentation en phrases, suffisante pour l'attribution."""
    morceaux = re.split(r"(?<=[.!?])\s+", str(texte).strip())
    return [m.strip() for m in morceaux if m.strip()]


def fidelite(reponse, fragments, juge=None):
    """Part des affirmations de la reponse effectivement soutenues.

    Sans juge, j'utilise une approximation lexicale : le recouvrement du
    vocabulaire de contenu entre la phrase et le contexte. Grossiere mais
    deterministe, elle permet de mesurer sans modele, ce que je prefere a une
    metrique fine mais non rejouable. Avec un juge, la mesure devient
    semantique.
    """
    phrases = decouper_phrases(reponse)
    if not phrases:
        return None
    contexte = " ".join(f.text for f in fragments).lower()
    if juge is not None:
        verdicts = juge(phrases, contexte)
        return sum(1 for v in verdicts if v) / len(verdicts)

    jetons_contexte = set(re.findall(r"\w{4,}", contexte))
    soutenues = 0
    for phrase in phrases:
        jetons = set(re.findall(r"\w{4,}", phrase.lower()))
        if jetons and len(jetons & jetons_contexte) / len(jetons) >= 0.6:
            soutenues += 1
    return soutenues / len(phrases)


def pertinence_reponse(requete, reponse):
    """Adequation de la reponse a la question posee.

    Approximation lexicale, meme reserve que ci-dessus.
    """
    jetons_q = set(re.findall(r"\w{4,}", str(requete).lower()))
    jetons_r = set(re.findall(r"\w{4,}", str(reponse).lower()))
    if not jetons_q:
        return None
    return len(jetons_q & jetons_r) / len(jetons_q)


def precision_contexte(fragments, pertinents, cle=lambda f: f.doc_id):
    """Part du contexte injecte qui est effectivement utile.

    Metrique essentielle pour E5 : une protection qui elargit la requete
    ramene du contexte hors sujet, qui doit etre filtre localement a
    posteriori. C'est le cout en rappel annonce dans la table des techniques
    d'obfuscation.
    """
    if not fragments:
        return None
    ensemble = set(pertinents)
    return sum(1 for f in fragments if cle(f) in ensemble) / len(fragments)


def rappel_contexte(fragments, pertinents, cle=lambda f: f.doc_id):
    if not pertinents:
        return None
    presents = {cle(f) for f in fragments}
    return len(presents & set(pertinents)) / len(pertinents)


def taux_abstention(reponses):
    """Comportement de refus, attendu et valorise en contexte bancaire."""
    if not reponses:
        return None
    return sum(1 for r in reponses if r.abstention) / len(reponses)


def taux_non_verifie(reponses):
    """Part des assertions signalees comme non verifiees."""
    total = sum(len(r.assertions) for r in reponses)
    if not total:
        return None
    non_verifiees = sum(
        1 for r in reponses for a in r.assertions if not a.verifiee
    )
    return non_verifiees / total


# ----------------------------------------------------------------- securite

def taux_succes_attaque(resultats):
    """Taux de succes d'attaque, ventile par palier (grandeur d'E3).

    `resultats` est une liste de dict {palier, famille, reussie}.
    """
    par_palier = {}
    for r in resultats:
        stats = par_palier.setdefault(r["palier"], {"reussies": 0, "total": 0})
        stats["total"] += 1
        stats["reussies"] += 1 if r["reussie"] else 0
    return {
        palier: round(s["reussies"] / s["total"], 4)
        for palier, s in par_palier.items() if s["total"]
    }


def ablation(mesures_par_configuration, reference="complete"):
    """Contribution de chaque couche, par retrait successif.

    Le rapport annonce « la part de chaque couche » sous attaque adaptative.
    Cette fonction la calcule comme l'ecart entre la configuration complete
    et chaque configuration privee d'une protection.
    """
    base = mesures_par_configuration.get(reference)
    if base is None:
        return {}
    return {
        nom: round(valeur - base, 4)
        for nom, valeur in mesures_par_configuration.items()
        if nom != reference
    }


# ------------------------------------------------------------------ juge

class JugeControle:
    """Juge automatique, avec controle explicite de ses biais.

    Trois precautions, correspondant aux trois biais documentes :
      position       chaque paire est evaluee dans les deux ordres
      verbosite      la longueur est normalisee avant comparaison
      auto-preference un modele ne juge jamais ses propres sorties
    """

    def __init__(self, fournisseur, modele_juge=None):
        self.fournisseur = fournisseur
        self.modele_juge = modele_juge or getattr(fournisseur, "modele", "")

    def verifier_independance(self, modele_evalue):
        """Refuse qu'un modele se juge lui-meme."""
        if self.modele_juge == modele_evalue:
            raise ValueError(
                f"le juge ({self.modele_juge}) est le modele evalue : "
                "biais d'auto-preference, comparaison invalide"
            )
        return True

    def comparer(self, requete, reponse_a, reponse_b):
        """Compare deux reponses dans les deux ordres.

        Un verdict qui s'inverse selon l'ordre est declare indecis plutot que
        tranche, la permutation le contredisant.
        """
        premier = self._demander(requete, reponse_a, reponse_b)
        second = self._demander(requete, reponse_b, reponse_a)
        if premier == "A" and second == "B":
            return "a"
        if premier == "B" and second == "A":
            return "b"
        return "indecis"

    def _demander(self, requete, premiere, seconde):
        invite = (
            f"Question : {requete}\n\nReponse A :\n{premiere}\n\n"
            f"Reponse B :\n{seconde}\n\n"
            "Laquelle est la mieux etayee par ses sources ? "
            "Reponds par une seule lettre : A ou B."
        )
        texte, _ = self.fournisseur.generer(invite, max_jetons=4)
        return "A" if "A" in texte.upper()[:3] else "B"


def resumer(valeurs):
    """Mediane et etendue, preferables a la moyenne sur de petits effectifs."""
    propres = [v for v in valeurs if v is not None]
    if not propres:
        return None
    return {
        "mediane": round(statistics.median(propres), 4),
        "moyenne": round(statistics.mean(propres), 4),
        "min": round(min(propres), 4),
        "max": round(max(propres), 4),
        "n": len(propres),
    }
