"""
Enchainement de bout en bout (section 4.4 du rapport).

L'architecture materialise la chaine concue au chapitre 3 sous la forme d'un
pipeline ordonne, dans lequel chaque etape garantit un invariant et neutralise
une ou plusieurs menaces. Le principe directeur reste la separation entre une
zone de confiance interne, etiquetee « confidentiel », et un exterieur non
fiable, sous controle de flux d'information.

Parcours d'une requete :

  1. ROUTAGE          l'interne suffit-il ? (I1 tenu sans effort si oui)
  2. CONFIDENTIALITE  en cas de sortie : gabarit fige sur l'entite, budget,
                      masquage, verrou de sortie                      (I1)
  3. FRANCHISSEMENT   requete texte seule ; aucun embedding ne franchit A
  4. EMBARQUEMENT     le contenu externe est rapatrie en texte puis
                      vectorise et indexe localement
  5. ISOLATION        contenu externe balise, cantonne en donnee        (I2)
  6. FUSION TEINTEE   corroboration, detection de collusion             (I2)
  7. GENERATION       via l'abstraction de fournisseur (Frontiere B ou non)
  8. RESTITUTION      attribution, non-verifie, abstention              (I3)

L'etat de session (budget d'exposition et gabarit fige) persiste d'une
requete a l'autre et au-dela des frontieres de session : c'est ce qui
distingue une enquete protegee d'une suite de requetes independantes,
vulnerables au recoupement (section 3.3.5).
"""

import time
from dataclasses import dataclass, field, replace

from .commun import config as mod_config
from .confidentialite import politique as mod_politique, verrou as mod_verrou
from .index import hybride
from .isolation import teinte
from .provenance import politique as mod_provenance
from .routage import routeur as mod_routeur


def _copier(fragment):
    """Copie superficielle d'un fragment, contenu inchange."""
    return replace(fragment)


@dataclass
class Contexte:
    """Contexte d'une requete : ce qui est protege, et sous quel budget."""
    requete: str
    session: str = "session-1"
    cle_entite: str = None
    entite: dict = None
    attributs: tuple = ()
    a_enjeu: bool = True
    source_structuree: bool = False


@dataclass
class Resultat:
    """Trace complete d'une requete, de bout en bout."""
    reponse: object = None
    issue_routage: str = ""
    issue_confidentialite: str = ""
    requete_emise: str = ""
    frontieres: list = field(default_factory=list)
    fragments: list = field(default_factory=list)
    budget_restant: float = None
    taille_ensemble: int = None
    latence_ms: float = 0.0
    etapes: dict = field(default_factory=dict)
    motif: str = ""
    passe_par_correction: bool = False


class Moteur:
    """Le moteur de recherche hybride securise, assemble.

    Toutes les dependances sont injectees et aucune n'est instanciee ici : le
    pipeline ne connait que des interfaces, condition necessaire pour ecrire
    les ablations du chapitre 5 (retirer une couche et mesurer l'ecart).
    """

    def __init__(self, config=None, recuperateur_interne=None,
                 recuperateur_externe=None, routeur=None, politique=None,
                 fournisseur=None, verrou_sortie=None, masqueur=None,
                 piste_audit=None, reclasseur=None, top_k_generation=None):
        self.config = config or mod_config.Config()
        self.recuperateur_interne = recuperateur_interne
        self.recuperateur_externe = recuperateur_externe
        self.routeur = routeur
        self.politique = politique
        self.fournisseur = fournisseur
        self.verrou = verrou_sortie
        self.masqueur = masqueur
        self.piste = piste_audit or mod_provenance.PisteAudit()
        # A None, le moteur se comporte comme dans les versions precedentes :
        # ni re-classement ni resserrement. Les campagnes anterieures restent
        # ainsi rejouables a l'identique.
        self.reclasseur = reclasseur
        self.top_k_generation = top_k_generation

    # ------------------------------------------------------------ pipeline

    def repondre(self, contexte, couches=None):
        """Traite une requete de bout en bout.

        `couches` permet de desactiver selectivement une protection, pour les
        ablations du chapitre 5 : {'verrou', 'isolation', 'corroboration',
        'budget'}. Par defaut, toutes sont actives.
        """
        couches = couches if couches is not None else {
            "verrou", "isolation", "corroboration", "budget"
        }
        debut = time.perf_counter()
        resultat = Resultat()

        # --- 1. Recuperation interne, puis routage reflexif ---------------
        t0 = time.perf_counter()
        internes = self._recuperer_interne(contexte.requete)
        resultat.etapes["recuperation_interne_ms"] = self._ms(t0)

        decision = self.routeur.decider(
            contexte.requete, internes,
            politique=self.politique if "budget" in couches else None,
            cle_entite=contexte.cle_entite, entite=contexte.entite,
            attributs=contexte.attributs,
            enrichissement_possible=self.recuperateur_externe is not None,
        )
        resultat.issue_routage = decision.issue
        resultat.motif = decision.motif

        # --- 1 bis. Correction, puis second routage ----------------------
        #
        # CORRIGER n'est pas une issue terminale : routeur.py la definit comme
        # une instruction de reprendre la recuperation interne avant de
        # conclure. En l'absence de ce second passage, la decision restait
        # bloquee sur CORRIGER, `_franchir` n'etait jamais appele et aucun
        # contenu externe n'entrait dans le moteur ; sur le jeu d'E6, 132
        # requetes sur 172 etaient concernees.
        #
        # La reprise reproduit celle que mesure E6 : elargir la tete
        # rapportee, puis rejuger sous `deja_corrige`. Faute d'index dense a
        # ce stade de la chaine, l'elargissement est la seule action possible
        # pour une reprise de recuperation interne ; je ne simule pas de gain
        # inexistant.
        if (decision.issue == mod_routeur.CORRIGER
                and hasattr(self.routeur, "apres_correction")):
            resultat.passe_par_correction = True
            t0 = time.perf_counter()
            internes = self._recuperer_interne(
                contexte.requete, n=self.config.recherche.n_final * 4)
            resultat.etapes["recuperation_corrigee_ms"] = self._ms(t0)

            decision = self.routeur.apres_correction().decider(
                contexte.requete, internes,
                politique=self.politique if "budget" in couches else None,
                cle_entite=contexte.cle_entite, entite=contexte.entite,
                attributs=contexte.attributs,
                enrichissement_possible=self.recuperateur_externe is not None,
            )
            resultat.issue_routage = decision.issue
            resultat.motif = decision.motif

        if decision.issue == mod_routeur.ABSTENIR:
            resultat.reponse = mod_provenance.Reponse(
                abstention=True, motif=decision.motif,
                palier=getattr(self.fournisseur, "palier",
                               self.config.generation.palier),
            )
            return self._clore(resultat, contexte, debut)

        if decision.issue == mod_routeur.ESCALADER:
            # Le systeme ne decide jamais lui-meme de l'escalade : il la
            # propose, et la decision revient a un operateur habilite
            # (section 3.2).
            resultat.reponse = mod_provenance.Reponse(
                abstention=True,
                motif="escalade humaine requise : " + decision.motif,
                palier=getattr(self.fournisseur, "palier",
                               self.config.generation.palier),
            )
            return self._clore(resultat, contexte, debut)

        externes = []
        if decision.issue == mod_routeur.ENRICHIR:
            externes = self._franchir(contexte, resultat, couches)

        # --- 5 et 6. Isolation, teinte, corroboration --------------------
        #
        # Copie defensive. `teinte.teinter` ecrit l'etiquette de confiance
        # dans le fragment ; sans copie, deux executions successives sur les
        # memes objets se contamineraient. C'est precisement le cas des
        # ablations du chapitre 5, qui rejouent les memes fragments sous
        # plusieurs configurations.
        fragments = [_copier(f) for f in list(internes) + list(externes)]
        if "isolation" in couches:
            fragments = teinte.teinter(
                fragments,
                seuil_corroboration=self.config.isolation.seuil_corroboration,
            )

        # --- 6 bis. Re-classement, puis resserrement ---------------------
        #
        # L'etage de re-classement existait dans `hybride.reclasser` sans
        # etre appele : la chaine embarquait un cross-encodeur inutilise.
        # Mesure du 15/09 sur les invites reellement envoyees : quarante
        # fragments internes occupaient 72,2 % du texte, pour l'essentiel hors
        # sujet, alors que l'attribution n'en retenait que trois.
        #
        # L'ordre des etapes est un choix de conception. Le re-classement juge
        # la pertinence, la ponderation par confiance juge la fiabilite, et la
        # seconde doit avoir le dernier mot : sinon, un document externe tres
        # pertinent mais empoisonne passerait devant un fragment interne
        # verifie, soit precisement l'asymetrie que le pilier 3 doit retablir.
        # Le re-classement porte sur tous les candidats, et non sur une tete.
        #
        # `hybride.reclasser` n'ordonne que ses `top_k` premiers elements et
        # laisse le reste en place. Or a ce stade la liste vaut
        # `internes + externes`, un ordre sans rapport avec la pertinence :
        # re-classer les vingt premiers reviendrait a n'examiner que des
        # fragments internes, sans jamais considerer les documents externes.
        # Mesure du 15/09 : la charge adverse disparaissait alors de cinq
        # invites sur cinq, non parce qu'elle avait ete jugee non pertinente,
        # mais parce qu'elle n'avait jamais ete jugee.
        t0 = time.perf_counter()
        if self.reclasseur is not None:
            fragments = hybride.reclasser(
                contexte.requete, fragments, self.reclasseur,
                top_k=len(fragments),
            )
            resultat.etapes["reclassement_ms"] = self._ms(t0)

        if "isolation" in couches:
            fragments = hybride.ponderer_par_confiance(fragments)

        if self.top_k_generation:
            fragments = fragments[:self.top_k_generation]
        resultat.fragments = fragments

        # --- 7 et 8. Generation attribuable, politique de reponse --------
        t0 = time.perf_counter()
        assertions = self._generer(contexte, fragments, couches)
        resultat.etapes["generation_ms"] = self._ms(t0)

        seuil = (self.config.isolation.seuil_corroboration
                 if "corroboration" in couches else 1)
        reponse = mod_provenance.appliquer(assertions, seuil_corroboration=seuil)
        # Le palier effectivement employe est celui du fournisseur, et non
        # celui de la configuration. Les deux peuvent diverger, et c'est ce
        # que mesure la ventilation par palier du chapitre 5.
        reponse.palier = getattr(self.fournisseur, "palier",
                                 self.config.generation.palier)
        reponse.frontieres = resultat.frontieres
        resultat.reponse = reponse

        return self._clore(resultat, contexte, debut)

    # ------------------------------------------------------------ etapes

    def _recuperer_interne(self, requete, n=None):
        """Recuperation interne. `n` elargit la tete pour la correction."""
        if self.recuperateur_interne is None:
            return []
        return self.recuperateur_interne.rechercher(
            requete, n=n or self.config.recherche.n_final, avec_teinte=False
        )

    def _franchir(self, contexte, resultat, couches):
        """Franchissement controle de la Frontiere A.

        Trois verrous successifs, du plus permissif au plus strict :
        generalisation sous gabarit fige, masquage des entites nommees,
        puis verrou deterministe sur l'ensemble des secrets connus.
        """
        requete = contexte.requete

        # 2a. Generalisation sous gabarit fige, si la requete est le secret.
        if self.politique and contexte.cle_entite and "budget" in couches:
            verdict = self.politique.evaluer(
                contexte.cle_entite, contexte.entite,
                contexte.attributs, contexte.session,
            )
            resultat.issue_confidentialite = verdict.issue
            resultat.budget_restant = verdict.budget_restant
            resultat.taille_ensemble = verdict.taille_ensemble
            if not verdict.emise:
                resultat.motif = verdict.motif
                return []
            generalisee = self.politique.formuler(contexte.entite, verdict)
            if generalisee:
                requete = generalisee

        # 2b. Masquage des entites a caractere personnel.
        if self.masqueur is not None:
            requete = self.masqueur.masquer(requete)

        # 2c. Verrou de sortie deterministe, dernier controle.
        if self.verrou is not None and "verrou" in couches:
            trouves = self.verrou.inspecter(requete)
            if trouves:
                resultat.motif = (
                    f"verrou de sortie : {len(trouves)} secret(s) detecte(s)"
                )
                resultat.issue_confidentialite = "bloquee-par-verrou"
                return []

        resultat.requete_emise = requete
        resultat.frontieres.append("A")

        # 3 et 4. Seule une requete texte franchit A ; le contenu revient en
        # texte et sera vectorise localement par le recuperateur externe.
        t0 = time.perf_counter()
        externes = self.recuperateur_externe.rechercher(
            requete, n=self.config.recherche.n_final, avec_teinte=False
        )
        resultat.etapes["recuperation_externe_ms"] = self._ms(t0)
        return externes

    def _generer(self, contexte, fragments, couches):
        """Generation contrainte a rattacher chaque assertion a ses sources."""
        if self.fournisseur is None:
            # Sans fournisseur, les fragments sont restitues tels quels, ce
            # qui permet de mesurer la recuperation seule (E1) sans le bruit
            # du modele.
            return [
                mod_provenance.Assertion(
                    texte=f.text[:200], fragments=[f], a_enjeu=contexte.a_enjeu
                )
                for f in fragments[:3]
            ]

        bloc = (teinte.baliser(fragments) if "isolation" in couches
                else "\n\n".join(f.text for f in fragments
                                 if f.source == "externe"))
        interne = "\n\n".join(
            f"[{f.reference()}]\n{f.text}"
            for f in fragments if f.source == "interne"
        )
        invite = (
            f"Question : {contexte.requete}\n\n"
            f"Sources internes verifiees :\n{interne}\n\n{bloc}\n\n"
            "Reponds en rattachant chaque affirmation a sa source. "
            "Si aucune source ne la soutient, indique que tu ne sais pas."
        )
        texte, trace = self.fournisseur.generer(
            invite, max_jetons=self.config.generation.max_jetons
        )
        if trace.frontiere_b_franchie:
            self._ajouter_frontiere_b(fragments)

        return [mod_provenance.Assertion(
            texte=texte, fragments=fragments[:3], a_enjeu=contexte.a_enjeu
        )]

    def _ajouter_frontiere_b(self, fragments):
        pass  # la trace est portee par Resultat.frontieres, voir _clore

    # -------------------------------------------------------------- sortie

    def _clore(self, resultat, contexte, debut):
        resultat.latence_ms = round((time.perf_counter() - debut) * 1000, 2)
        if (self.fournisseur is not None
                and getattr(self.fournisseur, "traces", None)
                and self.fournisseur.traces[-1].frontiere_b_franchie
                and "B" not in resultat.frontieres):
            resultat.frontieres.append("B")
            if resultat.reponse is not None:
                resultat.reponse.frontieres = resultat.frontieres
        self.piste.consigner(
            contexte.requete, resultat.reponse, contexte.session,
            contexte.cle_entite, resultat.budget_restant,
        )
        return resultat

    @staticmethod
    def _ms(t0):
        return round((time.perf_counter() - t0) * 1000, 2)
