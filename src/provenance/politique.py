"""
Provenance, attribution et politique de reponse (pilier 4, section 3.5).

La provenance n'est pas reconstruite a posteriori : elle est transportee.
Chaque fragment porte, dans ses metadonnees, sa source, son palier
d'origine, son etiquette de confiance et son score de fiabilite, de l'index
jusqu'a l'affichage. Cette continuite rend l'attribution effective plutot que
declarative, car apres l'indexation la provenance serait irrecuperable.

Ce meme substrat porte la piste d'audit attendue en contexte bancaire : la
journalisation exigee par le reglement europeen sur l'IA et la resilience
operationnelle visee par DORA reposent sur la capacite a retracer, pour
chaque reponse, les sources mobilisees, les frontieres franchies et le
palier employe.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..isolation import teinte

NON_VERIFIEE = "non verifiee"
ABSTENTION = "abstention"


@dataclass
class Assertion:
    """Une phrase de la reponse, et ce qui la soutient."""
    texte: str
    fragments: list = field(default_factory=list)
    a_enjeu: bool = False
    confiance: str = ""
    verifiee: bool = True

    def references(self):
        return [f.reference() for f in self.fragments]


@dataclass
class Reponse:
    """Reponse attribuee, telle qu'elle est restituee a l'utilisateur."""
    assertions: list = field(default_factory=list)
    abstention: bool = False
    motif: str = ""
    palier: str = ""
    frontieres: list = field(default_factory=list)

    def rendre(self):
        """Rendu texte, chaque assertion suivie de son attribution."""
        if self.abstention:
            return f"[{ABSTENTION}] {self.motif}"
        lignes = []
        for assertion in self.assertions:
            marque = "" if assertion.verifiee else f"  [{NON_VERIFIEE}]"
            sources = ", ".join(assertion.references()) or "aucune source"
            lignes.append(
                f"{assertion.texte}{marque}\n"
                f"    source : {sources} ({assertion.confiance})"
            )
        return "\n".join(lignes)


def appliquer(assertions, seuil_corroboration=2):
    """Applique la politique de reponse a une liste d'assertions.

    Une assertion a enjeu non corroboree n'est pas emise comme un fait mais
    signalee comme non verifiee. En l'absence de tout fragment soutenant la
    reponse, le systeme s'abstient plutot que d'inventer.
    """
    if not assertions or all(not a.fragments for a in assertions):
        return Reponse(
            abstention=True,
            motif="aucun fragment ne soutient la reponse",
        )

    retenues = []
    for assertion in assertions:
        soutenable, confiance = teinte.assertion_soutenable(
            assertion.fragments, assertion.a_enjeu, seuil_corroboration
        )
        assertion.confiance = confiance
        assertion.verifiee = soutenable
        retenues.append(assertion)

    return Reponse(assertions=retenues)


class PisteAudit:
    """Journal des reponses, pour l'auditabilite prudentielle.

    Une entree par reponse : sources mobilisees, frontieres franchies, palier
    employe, escalades. Un fragment empoisonne ou une erreur heritee peut
    ainsi etre remonte jusqu'a son origine.
    """

    def __init__(self, chemin="data/piste_audit.jsonl"):
        self.chemin = Path(chemin)

    def consigner(self, requete, reponse, session=None, entite=None,
                  budget_restant=None):
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        entree = {
            "horodatage": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "session": session,
            "entite": entite,
            "requete": requete,
            "palier": reponse.palier,
            "frontieres_franchies": reponse.frontieres,
            "abstention": reponse.abstention,
            "motif": reponse.motif,
            "budget_restant": budget_restant,
            "assertions": [
                {
                    "texte": a.texte,
                    "confiance": a.confiance,
                    "verifiee": a.verifiee,
                    "sources": a.references(),
                }
                for a in reponse.assertions
            ],
        }
        with open(self.chemin, "a", encoding="utf-8") as f:
            f.write(json.dumps(entree, ensure_ascii=False) + "\n")
        return entree
