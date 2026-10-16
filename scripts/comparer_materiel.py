r"""
Compare deux executions : parite materielle ou degradation mesuree.

    python scripts\comparer_materiel.py `
        --reference resultats\index-complet-20260813-... `
        --candidat  resultats\index-parite-20260813-... `
        --nature parite

Deux types de comparaison :

  --nature parite    meme modele, autre materiel. On attend une derive
                     nulle. Si c'est le cas, les mesures faites sur GPU
                     valent aussi pour un deploiement souverain. La section
                     4.1.1 le suppose sans le verifier.

  --nature degrade   modele plus leger. On attend une derive, et c'est elle
                     qu'on mesure : ce que coute en qualite un materiel
                     modeste (section 3.1.5).

Le script affiche un tableau que l'on peut reprendre tel quel au chapitre 5.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.evaluation import parite as mod_parite   # noqa: E402


def charger(dossier):
    chemin = Path(dossier) / "execution.json"
    if not chemin.exists():
        raise SystemExit(f"introuvable : {chemin}")
    with open(chemin, encoding="utf-8") as f:
        return json.load(f)


def charger_vecteurs(dossier_embeddings):
    """Relit les vecteurs sauvegardes d'un profil, si numpy est disponible."""
    try:
        import numpy as np
    except ImportError:
        return None, []
    dossier = Path(dossier_embeddings)
    if not dossier.exists():
        return None, []
    vecteurs, identifiants = [], []
    for fichier in sorted(dossier.glob("vecteurs-*.npy")):
        vecteurs.append(np.load(fichier))
        compagnon = fichier.parent / fichier.name.replace(
            "vecteurs-", "identifiants-").replace(".npy", ".json")
        if compagnon.exists():
            with open(compagnon, encoding="utf-8") as f:
                identifiants.extend(json.load(f))
    if not vecteurs:
        return None, []
    return np.concatenate(vecteurs, axis=0), identifiants


def main():
    parseur = argparse.ArgumentParser(description="Comparaison de materiels")
    parseur.add_argument("--reference", required=True)
    parseur.add_argument("--candidat", required=True)
    parseur.add_argument("--nature", choices=["parite", "degrade"],
                         default="parite")
    parseur.add_argument("--vecteurs-reference", default=None)
    parseur.add_argument("--vecteurs-candidat", default=None)
    parseur.add_argument("--sortie", default=None)
    arguments = parseur.parse_args()

    reference = charger(arguments.reference)
    candidat = charger(arguments.candidat)

    print("=" * 72)
    print(f"REFERENCE  {reference['identifiant']}")
    print(f"           materiel : {reference['materiel']['nom']} "
          f"({reference['materiel']['role']})")
    print(f"CANDIDAT   {candidat['identifiant']}")
    print(f"           materiel : {candidat['materiel']['nom']} "
          f"({candidat['materiel']['role']})")
    print("=" * 72)

    # Verification prealable : si les deux executions n'ont pas lu les memes
    # donnees, l'ecart viendrait aussi du corpus, pas seulement du materiel.
    if reference["manifeste_hash"] != candidat["manifeste_hash"]:
        print("\n  ATTENTION : les manifestes de donnees sont differents.")
        print("  Les deux executions n'ont pas lu les memes corpus : l'ecart")
        print("  observe melange l'effet du materiel et celui des donnees.")

    if reference["commit"] != candidat["commit"]:
        print(f"\n  ATTENTION : commits differents "
              f"({reference['commit']} contre {candidat['commit']}).")

    rapport = {"reference": reference["identifiant"],
               "candidat": candidat["identifiant"],
               "nature": arguments.nature}

    # --- representation ---------------------------------------------------
    if arguments.vecteurs_reference and arguments.vecteurs_candidat:
        va, ia = charger_vecteurs(arguments.vecteurs_reference)
        vb, ib = charger_vecteurs(arguments.vecteurs_candidat)
        if va is not None and vb is not None:
            derive = mod_parite.derive_representation(va, vb, ia, ib)
            rapport["representation"] = derive
            print("\nDERIVE DE REPRESENTATION")
            if derive.get("comparable"):
                print(f"  documents apparies : {derive['documents']}")
                print(f"  cosinus median     : {derive['cosinus_median']}")
                print(f"  derive maximale    : {derive['derive_max']:.2e}")
                print(f"  -> {derive['verdict']}")
            else:
                print(f"  non comparable : {derive['motif']}")

    # --- mesures ----------------------------------------------------------
    comparaison = mod_parite.comparer_executions(
        reference.get("mesures", {}), candidat.get("mesures", {}),
        arguments.nature,
    )
    rapport["mesures"] = comparaison

    if not comparaison.get("comparable"):
        print(f"\n  {comparaison['motif']}")
    else:
        print("\nECARTS DE MESURE")
        print(f"  {'grandeur':<28} {'reference':>12} {'candidat':>12} "
              f"{'ecart':>10}")
        print("  " + "-" * 64)
        for nom, ecart in sorted(comparaison["ecarts"].items()):
            relatif = ecart["ecart_relatif"]
            affiche = f"{relatif:+.1%}" if relatif is not None else "n/a"
            print(f"  {nom:<28} {ecart['reference']:>12.4g} "
                  f"{ecart['candidat']:>12.4g} {affiche:>10}")
        print(f"\n  ecart de qualite maximal : "
              f"{comparaison['ecart_qualite_max_relatif']:.2%}")
        print(f"\n  VERDICT")
        for ligne in _paragraphe(comparaison["verdict"], 68):
            print(f"    {ligne}")

    if arguments.sortie:
        chemin = Path(arguments.sortie)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(rapport, f, ensure_ascii=False, indent=2)
        print(f"\n  ecrit : {chemin}")


def _paragraphe(texte, largeur):
    mots, ligne, lignes = texte.split(), "", []
    for mot in mots:
        if len(ligne) + len(mot) + 1 > largeur:
            lignes.append(ligne)
            ligne = mot
        else:
            ligne = f"{ligne} {mot}".strip()
    if ligne:
        lignes.append(ligne)
    return lignes


if __name__ == "__main__":
    main()
