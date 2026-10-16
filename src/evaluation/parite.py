"""
Parite materielle : comparaison de deux executions du meme moteur.

La section 4.1.1 du rapport affirme que « la qualite du modele local se
mesure sur tout materiel, au besoin sur un echantillon ». C'est une
hypothese, et ce module sert a la verifier.

Deux comparaisons differentes :

  PARITE    meme modele, autre materiel. On attend une derive nulle. Si
            c'est le cas, les mesures de qualite faites sur GPU valent aussi
            pour un deploiement souverain.

  DEGRADE   autre modele, materiel modeste. On attend une vraie derive, et
            c'est elle qu'on mesure : c'est ce que coute en qualite un
            materiel modeste (section 3.1.5).

Trois familles de mesures :
  representation   derive des vecteurs (distance cosinus)
  classement       accord des ordres (Spearman, Kendall, Jaccard@k)
  bout en bout     ecart des metriques de recuperation et de reponse
"""

import math
import statistics


# ------------------------------------------------------------ representation

def cosinus(u, v):
    """Similarite cosinus, sans dependance externe."""
    produit = sum(a * b for a, b in zip(u, v))
    norme_u = math.sqrt(sum(a * a for a in u))
    norme_v = math.sqrt(sum(b * b for b in v))
    if not norme_u or not norme_v:
        return 0.0
    return produit / (norme_u * norme_v)


def derive_representation(vecteurs_a, vecteurs_b, identifiants_a=None,
                          identifiants_b=None):
    """Derive entre deux jeux de vecteurs pour les memes documents.

    Deux causes possibles :
      - precision : fp16 sur GPU contre fp32 sur processeur. Derive attendue
        de l'ordre de 1e-3, sans effet reel sur les rangs.
      - modele : dimensions differentes, comparaison impossible. La fonction
        le signale au lieu de renvoyer un nombre sans signification.
    """
    if identifiants_a and identifiants_b:
        index_b = {i: n for n, i in enumerate(identifiants_b)}
        paires = [
            (vecteurs_a[n], vecteurs_b[index_b[i]])
            for n, i in enumerate(identifiants_a) if i in index_b
        ]
    else:
        paires = list(zip(vecteurs_a, vecteurs_b))

    if not paires:
        return {"comparable": False, "motif": "aucun document en commun"}
    if len(paires[0][0]) != len(paires[0][1]):
        return {
            "comparable": False,
            "motif": (f"dimensions differentes ({len(paires[0][0])} contre "
                      f"{len(paires[0][1])}) : modeles distincts, la derive "
                      f"de representation n'a pas de sens"),
        }

    similarites = [cosinus(list(u), list(v)) for u, v in paires]
    ecarts = [1 - s for s in similarites]
    return {
        "comparable": True,
        "documents": len(paires),
        "cosinus_median": round(statistics.median(similarites), 6),
        "cosinus_min": round(min(similarites), 6),
        "derive_moyenne": round(statistics.mean(ecarts), 8),
        "derive_max": round(max(ecarts), 8),
        "verdict": _verdict_derive(max(ecarts)),
    }


def _verdict_derive(derive_max):
    if derive_max < 1e-4:
        return "identique : parite materielle etablie"
    if derive_max < 1e-2:
        return ("derive numerique negligeable : compatible avec un ecart de "
                "precision fp16/fp32, sans effet attendu sur les rangs")
    return ("DERIVE SIGNIFICATIVE : verifier le modele, la longueur maximale "
            "et la graine avant de conclure a un effet du materiel")


# ------------------------------------------------------------- classement

def _rangs(sequence):
    """Rangs moyens, ex aequo compris."""
    ordonne = sorted(range(len(sequence)), key=lambda i: sequence[i])
    rangs = [0.0] * len(sequence)
    i = 0
    while i < len(ordonne):
        j = i
        while j + 1 < len(ordonne) and sequence[ordonne[j + 1]] == sequence[ordonne[i]]:
            j += 1
        moyen = (i + j) / 2 + 1
        for k in range(i, j + 1):
            rangs[ordonne[k]] = moyen
        i = j + 1
    return rangs


def spearman(x, y):
    """Correlation de rang de Spearman, implementee sans scipy."""
    if len(x) < 2:
        return None
    rx, ry = _rangs(x), _rangs(y)
    n = len(x)
    mx, my = sum(rx) / n, sum(ry) / n
    numerateur = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    denominateur = math.sqrt(
        sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)
    )
    return numerateur / denominateur if denominateur else None


def kendall_tau(x, y):
    """Tau de Kendall, plus sensible que Spearman aux inversions locales."""
    n = len(x)
    if n < 2:
        return None
    concordantes = discordantes = 0
    for i in range(n):
        for j in range(i + 1, n):
            signe = (x[i] - x[j]) * (y[i] - y[j])
            if signe > 0:
                concordantes += 1
            elif signe < 0:
                discordantes += 1
    total = concordantes + discordantes
    return (concordantes - discordantes) / total if total else None


def jaccard_at_k(classement_a, classement_b, k=10, cle=lambda x: x):
    """Recouvrement des k premiers resultats, la mesure qui compte en pratique.

    Deux classements peuvent etre tres differents apres le rang k sans que
    cela change quoi que ce soit : seuls les k premiers vont dans le
    contexte du generateur.
    """
    tete_a = {cle(d) for d in classement_a[:k]}
    tete_b = {cle(d) for d in classement_b[:k]}
    union = tete_a | tete_b
    return len(tete_a & tete_b) / len(union) if union else None


def deplacement_moyen(classement_a, classement_b, cle=lambda x: x):
    """Deplacement moyen d'un document entre les deux classements."""
    positions_b = {cle(d): n for n, d in enumerate(classement_b)}
    ecarts = [
        abs(n - positions_b[cle(d)])
        for n, d in enumerate(classement_a) if cle(d) in positions_b
    ]
    return round(statistics.mean(ecarts), 3) if ecarts else None


def accord_classement(classement_a, classement_b, k=10, cle=lambda x: x):
    """Bilan de l'accord entre deux classements pour une meme requete."""
    communs = [cle(d) for d in classement_a if cle(d) in
               {cle(e) for e in classement_b}]
    if len(communs) < 2:
        return {"comparable": False, "motif": "moins de deux documents communs"}

    positions_a = {cle(d): n for n, d in enumerate(classement_a)}
    positions_b = {cle(d): n for n, d in enumerate(classement_b)}
    x = [positions_a[i] for i in communs]
    y = [positions_b[i] for i in communs]

    return {
        "comparable": True,
        "documents_communs": len(communs),
        "spearman": round(spearman(x, y) or 0, 4),
        "kendall": round(kendall_tau(x, y) or 0, 4),
        f"jaccard@{k}": round(jaccard_at_k(classement_a, classement_b, k, cle) or 0, 4),
        "deplacement_moyen": deplacement_moyen(classement_a, classement_b, cle),
    }


# ------------------------------------------------------------ bout en bout

def comparer_executions(reference, candidat, nature="parite"):
    """Compare deux rapports d'execution et renvoie un verdict lisible.

    `reference` et `candidat` sont les dictionnaires `mesures` produits par
    `commun.journal.Execution`. Seules les mesures presentes des deux cotes
    sont comparees.
    """
    communes = sorted(set(reference) & set(candidat))
    if not communes:
        return {"comparable": False, "motif": "aucune mesure commune"}

    ecarts = {}
    for nom in communes:
        a = reference[nom]["valeur"] if isinstance(reference[nom], dict) else reference[nom]
        b = candidat[nom]["valeur"] if isinstance(candidat[nom], dict) else candidat[nom]
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            continue
        absolu = b - a
        relatif = (absolu / a) if a else None
        ecarts[nom] = {
            "reference": a, "candidat": b,
            "ecart_absolu": round(absolu, 6),
            "ecart_relatif": round(relatif, 4) if relatif is not None else None,
        }

    qualite = {
        nom: e for nom, e in ecarts.items()
        if not any(m in nom for m in ("latence", "duree", "cout", "debit"))
    }
    ecart_max = max(
        (abs(e["ecart_relatif"]) for e in qualite.values()
         if e["ecart_relatif"] is not None), default=0.0
    )

    return {
        "comparable": True,
        "nature": nature,
        "ecarts": ecarts,
        "ecart_qualite_max_relatif": round(ecart_max, 4),
        "verdict": _verdict_execution(nature, ecart_max),
    }


def _verdict_execution(nature, ecart_max):
    if nature == "parite":
        if ecart_max < 0.01:
            return ("PARITE ETABLIE : les mesures de qualite faites sur le "
                    "materiel de reference valent pour le materiel modeste. "
                    "L'hypothese de la section 4.1.1 est verifiee.")
        if ecart_max < 0.05:
            return ("parite approximative : ecart inferieur a 5 %, a "
                    "mentionner comme incertitude.")
        return ("PARITE NON ETABLIE : un tel ecart avec le meme modele "
                "indique plutot un probleme de protocole (graine, "
                "echantillon, longueur maximale) qu'un effet du materiel. "
                "A diagnostiquer avant publication.")
    if ecart_max < 0.02:
        return ("degradation negligeable : le modele leger tient la "
                "comparaison, ce qui plaide pour un deploiement souverain "
                "sur materiel modeste.")
    if ecart_max < 0.15:
        return (f"degradation mesuree de {ecart_max:.1%} : c'est ce que coute "
                f"en qualite un materiel modeste, a rapporter tel quel.")
    return (f"degradation importante de {ecart_max:.1%} : un materiel modeste "
            f"coute cher en qualite, a rapporter tel quel au chapitre 5.")
