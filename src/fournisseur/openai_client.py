"""
Client OpenAI a injecter dans FournisseurAPI (palier `api-hors-ue`).

    from src.fournisseur import openai_client, base
    client = openai_client.ClientOpenAI(modele="gpt-5.6-luna")
    fournisseur = base.FournisseurAPI(
        palier=base.API_HORS_UE, modele=client.modele,
        tarif_entree=..., tarif_sortie=..., client=client)

PERIMETRE

Le module rend un appelable `(invite, systeme, max_jetons) -> (texte,
jetons_entree, jetons_sortie)`, conforme au contrat de
`FournisseurAPI._appeler`. Il ne decide ni du modele, ni des tarifs, ni du
plafond de depense : ces choix relevent de la campagne et restent a
l'appelant.

GESTION DE LA CLE

La cle est lue par la bibliotheque officielle depuis la variable
d'environnement OPENAI_API_KEY, que `charger_cle` se contente de renseigner
depuis le fichier .env. Aucune fonction de ce module ne prend la cle en
argument, ne la journalise ni ne la retourne, ce qui garantit son absence
des traces d'execution.

PALIER

OpenAI est un fournisseur situe hors de l'Union europeenne. Ce client
materialise donc le palier `api-hors-ue` au sens de la section 3.1.5 : la
Frontiere B est franchie, et le champ `palier` de chaque trace le consigne.
La mesure des deux autres paliers requiert une API europeenne et un modele
servi localement.

DETERMINISME

`config.generation.temperature` vaut 0, pour la raison exposee dans la
docstring de la configuration : sans cela, deux executions de la meme
campagne donnent des taux de succes d'attaque differents et E3 n'est plus
rejouable.

Certains modeles refusent cette valeur. Mesure du 14/09/2026 sur
gpt-5.6-luna : « Unsupported value: 'temperature' does not support 0.0 with
this model. Only the default (1) value is supported. » La temperature n'est
donc envoyee que si l'appelant en fixe une ; la valeur par defaut de ce
client est None, c'est-a-dire aucun envoi.

Le repli est la graine (`seed`), que l'API accepte et qui rend la generation
reproductible dans la mesure du possible, sans garantie contractuelle. Une
campagne menee sans temperature fixee doit donc etre declaree comme non
strictement rejouable ; `decrire()` expose les deux champs afin que la trace
l'indique explicitement.
"""

import os
from pathlib import Path


def charger_cle(chemin=".env"):
    """Peuple OPENAI_API_KEY depuis le fichier .env, s'il existe.

    Rend True si la variable est disponible apres l'appel. La valeur n'est ni
    retournee, ni journalisee, ni affichee.
    """
    if os.environ.get("OPENAI_API_KEY"):
        return True

    fichier = Path(chemin)
    if not fichier.exists():
        return False

    try:
        from dotenv import load_dotenv
    except ImportError:
        # Repli sans dependance : le format d'un .env est simple, et un
        # echec du a un paquet manquant serait injustifie.
        for ligne in fichier.read_text(encoding="utf-8-sig").splitlines():
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#") or "=" not in ligne:
                continue
            nom, _, valeur = ligne.partition("=")
            # Les guillemets provoquent un echec silencieux : la cle est
            # envoyee avec ses guillemets et l'API repond « clé invalide »,
            # message qui n'indique pas la cause.
            os.environ.setdefault(nom.strip(),
                                  valeur.strip().strip('"').strip("'"))
    else:
        load_dotenv(fichier, override=False)
        valeur = os.environ.get("OPENAI_API_KEY", "")
        if valeur[:1] in ('"', "'") and valeur[-1:] == valeur[:1]:
            os.environ["OPENAI_API_KEY"] = valeur[1:-1]

    return bool(os.environ.get("OPENAI_API_KEY"))


class ClefAbsente(RuntimeError):
    """La cle n'est ni dans l'environnement ni dans le .env."""


class ClientOpenAI:
    """Appelable conforme au contrat de FournisseurAPI.

    Le client n'est construit qu'au premier appel : l'instanciation ne doit
    declencher aucune connexion, afin qu'un devis puisse etre etabli sans
    acceder au reseau.
    """

    def __init__(self, modele="gpt-5.6-luna", temperature=None,
                 graine=None, chemin_env=".env", delai=60,
                 base_url=None, palier="api-hors-ue"):
        self.modele = modele
        # `base_url` designe un serveur local compatible avec l'API OpenAI
        # (Ollama, vLLM). Cela permet de mesurer le palier local sans second
        # client : seule l'adresse change, la chaine d'appel et le comptage
        # des jetons restent identiques, et les deux paliers sont donc
        # comparables.
        self.base_url = base_url
        # Le palier n'est pas deduit de l'adresse : sa declaration explicite
        # evite qu'une API hebergee en UE soit journalisee comme locale.
        self.palier = palier
        # None signifie que le parametre n'est pas envoye : plusieurs modeles
        # rejettent toute valeur autre que leur valeur par defaut.
        self.temperature = temperature
        self.graine = graine
        self.chemin_env = chemin_env
        self.delai = delai
        self._client = None

    def _obtenir(self):
        if self._client is None:
            from openai import OpenAI
            if self.base_url:
                # Un serveur local n'authentifie pas, mais la bibliotheque
                # officielle exige une cle : je fournis une valeur factice.
                # Aucune cle reelle ne doit transiter vers une adresse locale.
                self._client = OpenAI(
                    timeout=self.delai, base_url=self.base_url,
                    api_key="local")
            else:
                if not charger_cle(self.chemin_env):
                    raise ClefAbsente(
                        "OPENAI_API_KEY introuvable.\n"
                        "Attendue dans l'environnement ou dans un fichier "
                        ".env a la racine, sous la forme :\n"
                        "    OPENAI_API_KEY=sk-...\n"
                        "sans guillemets autour de la valeur.")
                self._client = OpenAI(timeout=self.delai)
        return self._client

    def __call__(self, invite, systeme=None, max_jetons=1024):
        """Un appel. Rend (texte, jetons_entree, jetons_sortie)."""
        messages = []
        if systeme:
            messages.append({"role": "system", "content": systeme})
        messages.append({"role": "user", "content": invite})

        # `max_completion_tokens` est le nom recent cote OpenAI ; les serveurs
        # locaux compatibles ne connaissent souvent que `max_tokens`. Un nom
        # incorrect laisse le modele generer sans borne, ce qui allongerait
        # indefiniment une campagne locale.
        borne = "max_tokens" if self.base_url else "max_completion_tokens"
        options = {
            "model": self.modele,
            "messages": messages,
            borne: max_jetons,
        }
        if self.temperature is not None:
            options["temperature"] = self.temperature
        if self.graine is not None:
            options["seed"] = self.graine

        reponse = self._obtenir().chat.completions.create(**options)

        texte = (reponse.choices[0].message.content or "") if reponse.choices \
            else ""
        usage = getattr(reponse, "usage", None)
        # Les comptes de jetons proviennent de l'API, jamais d'une estimation
        # locale : le plafond de depense s'appuie sur eux, et une estimation
        # rendrait ce garde-fou approximatif.
        entree = getattr(usage, "prompt_tokens", 0) or 0
        sortie = getattr(usage, "completion_tokens", 0) or 0
        return texte, int(entree), int(sortie)

    def decrire(self):
        """Etat du client, a consigner au journal, sans la cle."""
        return {
            "fournisseur": "openai",
            "modele": self.modele,
            "temperature": self.temperature,
            "graine": self.graine,
            # Une campagne sans temperature fixee n'est pas strictement
            # rejouable : la trace doit l'indiquer explicitement.
            "strictement_rejouable": self.temperature == 0,
            "palier": self.palier,
            "base_url": self.base_url,
            # Au palier local, aucune cle n'est utilisee : une simple lecture
            # de l'environnement indiquerait le contraire.
            "cle_presente": (False if self.base_url
                             else bool(os.environ.get("OPENAI_API_KEY"))),
        }
