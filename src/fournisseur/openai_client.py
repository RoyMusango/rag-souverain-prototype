"""
Client OpenAI a injecter dans FournisseurAPI (palier `api-hors-ue`).

    from src.fournisseur import openai_client, base
    client = openai_client.ClientOpenAI(modele="gpt-5.6-luna")
    fournisseur = base.FournisseurAPI(
        palier=base.API_HORS_UE, modele=client.modele,
        tarif_entree=..., tarif_sortie=..., client=client)

CE QUE FAIT LE MODULE

Le module fournit un appelable `(invite, systeme, max_jetons) -> (texte,
jetons_entree, jetons_sortie)`, comme l'attend `FournisseurAPI._appeler`. Il
ne choisit ni le modele, ni les tarifs, ni le plafond de depense : c'est a
la campagne de les fixer.

GESTION DE LA CLE

La bibliotheque officielle lit la cle dans la variable d'environnement
OPENAI_API_KEY. `charger_cle` remplit seulement cette variable a partir du
fichier .env. Aucune fonction du module ne prend la cle en argument, ne
l'enregistre ni ne la renvoie : elle n'apparait donc dans aucune trace.

PALIER

OpenAI est un fournisseur situe hors de l'Union europeenne. Ce client
correspond donc au palier `api-hors-ue` (section 3.1.5) : la Frontiere B est
franchie, et le champ `palier` de chaque trace l'indique. Pour mesurer les
deux autres paliers, il faut une API europeenne et un modele servi en local.

DETERMINISME

`config.generation.temperature` vaut 0. Sinon, deux executions de la meme
campagne donnent des taux de succes d'attaque differents et E3 ne peut plus
etre rejoue.

Certains modeles refusent cette valeur. Constat du 14/09/2026 sur
gpt-5.6-luna : « Unsupported value: 'temperature' does not support 0.0 with
this model. Only the default (1) value is supported. » La temperature n'est
donc envoyee que si l'appelant en fixe une. Par defaut elle vaut None, et
rien n'est envoye.

A defaut, on utilise la graine (`seed`). L'API l'accepte et la generation
devient reproductible autant que possible, sans garantie. Une campagne sans
temperature fixee doit donc etre declaree comme non strictement rejouable.
`decrire()` renvoie les deux champs pour que la trace l'indique.
"""

import os
from pathlib import Path


def charger_cle(chemin=".env"):
    """Remplit OPENAI_API_KEY a partir du fichier .env, s'il existe.

    Renvoie True si la variable existe apres l'appel. La valeur n'est jamais
    renvoyee, enregistree ou affichee.
    """
    if os.environ.get("OPENAI_API_KEY"):
        return True

    fichier = Path(chemin)
    if not fichier.exists():
        return False

    try:
        from dotenv import load_dotenv
    except ImportError:
        # Sans python-dotenv, je lis le fichier moi-meme : le format d'un .env
        # est simple, inutile d'echouer pour un paquet manquant.
        for ligne in fichier.read_text(encoding="utf-8-sig").splitlines():
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#") or "=" not in ligne:
                continue
            nom, _, valeur = ligne.partition("=")
            # Je retire les guillemets. Sinon la cle est envoyee avec, et
            # l'API repond « clé invalide » sans dire pourquoi.
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
    """Appelable utilisable par FournisseurAPI.

    Le client OpenAI n'est cree qu'au premier appel. Creer l'objet ne lance
    donc aucune connexion, et on peut calculer un devis sans reseau.
    """

    def __init__(self, modele="gpt-5.6-luna", temperature=None,
                 graine=None, chemin_env=".env", delai=60,
                 base_url=None, palier="api-hors-ue"):
        self.modele = modele
        # `base_url` pointe vers un serveur local compatible avec l'API OpenAI
        # (Ollama, vLLM). On mesure ainsi le palier local avec le meme client :
        # seule l'adresse change. L'appel et le comptage des jetons sont les
        # memes, donc les deux paliers sont comparables.
        self.base_url = base_url
        # Le palier est declare, pas deduit de l'adresse. Sinon une API
        # hebergee en UE pourrait etre enregistree comme locale.
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
                # Un serveur local ne demande pas de cle, mais la bibliotheque
                # officielle en exige une : je donne une valeur factice. La
                # vraie cle ne doit jamais partir vers une adresse locale.
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
        """Un appel. Renvoie (texte, jetons_entree, jetons_sortie)."""
        messages = []
        if systeme:
            messages.append({"role": "system", "content": systeme})
        messages.append({"role": "user", "content": invite})

        # OpenAI utilise maintenant `max_completion_tokens`. Les serveurs
        # locaux compatibles ne connaissent souvent que `max_tokens`. Avec le
        # mauvais nom, le modele genere sans limite et une campagne locale
        # n'en finit plus.
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
        # Les nombres de jetons viennent de l'API, jamais d'une estimation
        # locale : le plafond de depense se calcule a partir d'eux.
        entree = getattr(usage, "prompt_tokens", 0) or 0
        sortie = getattr(usage, "completion_tokens", 0) or 0
        return texte, int(entree), int(sortie)

    def decrire(self):
        """Etat du client, a enregistrer dans le journal (sans la cle)."""
        return {
            "fournisseur": "openai",
            "modele": self.modele,
            "temperature": self.temperature,
            "graine": self.graine,
            # Une campagne sans temperature fixee n'est pas strictement
            # rejouable : la trace doit le dire.
            "strictement_rejouable": self.temperature == 0,
            "palier": self.palier,
            "base_url": self.base_url,
            # Au palier local, aucune cle n'est utilisee, meme si la variable
            # existe dans l'environnement.
            "cle_presente": (False if self.base_url
                             else bool(os.environ.get("OPENAI_API_KEY"))),
        }
