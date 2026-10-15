"""
E5 : cout en precision de la protection de l'intention.

Une protection dont le cout n'est pas mesure ne peut pas etre evaluee. E2
etablit ce que la protection apporte, E5 chiffre ce qu'elle coute ; seules
les deux mesures reunies constituent un resultat.

Le mecanisme du cout est direct : pour masquer l'entite, la requete est
generalisee, donc elargie. Le moteur renvoie alors des resultats plus larges,
en partie hors sujet, qui doivent etre filtres localement a posteriori, ce
qui coute a son tour du rappel. C'est la ligne « Precision » de la table des
techniques d'obfuscation du chapitre 3.

Trois regimes compares sur les memes questions :

    brut          la requete part telle quelle (reference)
    masque        entites nommees masquees (protection des donnees)
    generalise    gabarit fige sur l'entite (protection de l'intention)

L'ecart entre `brut` et `generalise` est le cout rapporte.
"""

import time

from .metriques import ndcg_at_k, recall_at_k, resumer

BRUT = "brut"
MASQUE = "masque"
GENERALISE = "generalise"


def evaluer(recuperateur, paires, transformer=None, k=10, regime=BRUT):
    """Mesure la recherche apres transformation eventuelle de la requete."""
    rappels, ndcgs, latences, longueurs = [], [], [], []

    for paire in paires:
        requete = paire["question"]
        if transformer is not None:
            requete = transformer(requete, paire)
        longueurs.append(len(requete.split()))

        debut = time.perf_counter()
        resultats = recuperateur.rechercher(requete, n=max(k, 20),
                                            avec_teinte=False)
        latences.append((time.perf_counter() - debut) * 1000)

        cle = lambda f: f.doc_id  # noqa: E731
        rappels.append(recall_at_k([paire["doc_id"]], resultats, k, cle))
        ndcgs.append(ndcg_at_k({paire["doc_id"]: 1}, resultats, k, cle))

    latences.sort()
    return {
        "regime": regime,
        "questions": len(paires),
        f"recall@{k}": resumer(rappels),
        f"ndcg@{k}": resumer(ndcgs),
        "longueur_requete_mots": resumer(longueurs),
        "latence_mediane_ms": round(latences[len(latences) // 2], 2)
        if latences else None,
    }


def campagne(recuperateur, paires, masqueur=None, generaliseur=None, k=10):
    """Compare les trois regimes et chiffre le cout de chaque protection."""
    resultats = {BRUT: evaluer(recuperateur, paires, None, k, BRUT)}

    if masqueur is not None:
        resultats[MASQUE] = evaluer(
            recuperateur, paires,
            lambda q, _: masqueur.masquer(q), k, MASQUE,
        )
    if generaliseur is not None:
        resultats[GENERALISE] = evaluer(
            recuperateur, paires, generaliseur, k, GENERALISE
        )

    cle = f"recall@{k}"
    reference = resultats[BRUT][cle]["moyenne"]
    couts = {}
    for regime, mesure in resultats.items():
        if regime == BRUT:
            continue
        valeur = mesure[cle]["moyenne"]
        couts[regime] = {
            "recall_absolu": round(valeur - reference, 4),
            "recall_relatif": round((valeur - reference) / reference, 4)
            if reference else None,
        }

    return {
        "k": k,
        "resultats": resultats,
        "cout_par_regime": couts,
        "lecture": ("le cout de `generalise` est le prix de la protection de "
                    "l'intention ; celui de `masque` le prix de la protection "
                    "des donnees. Les deux se cumulent en deploiement."),
    }


def generaliseur_depuis_politique(politique, cle_entite, entite, attributs):
    """Construit un transformateur de requete a partir du pilier 2.

    La requete emise n'est pas la question de l'utilisateur mais sa forme
    generalisee sous le gabarit fige. C'est ce que je cherche a mesurer : la
    degradation subie par la recherche, et non par la question.
    """
    def transformer(requete, paire):
        decision = politique.evaluer(cle_entite, entite, attributs)
        if not decision.emise:
            return requete
        termes = politique.formuler(entite, decision)
        return f"{requete} {termes}".strip() if termes else requete

    return transformer
