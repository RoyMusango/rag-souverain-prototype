"""
Enchainement de bout en bout (section 4.4 du rapport).

Ce module met en oeuvre la chaine du chapitre 3 sous forme de pipeline.
Chaque etape garantit un invariant et bloque une ou plusieurs menaces. Le
principe de base est la separation entre une zone interne de confiance,
etiquetee « confidentiel », et un exterieur non fiable, avec un controle des
flux d'information entre les deux.

Parcours d'une requete :

  1. ROUTAGE          l'interne suffit-il ? (si oui, I1 est respecte d'office)
  2. CONFIDENTIALITE  en cas de sortie : gabarit fige sur l'entite, budget,
                      masquage, verrou de sortie                      (I1)
  3. FRANCHISSEMENT   requete texte seule ; aucun embedding ne franchit A
  4. EMBARQUEMENT     le contenu externe est rapatrie en texte puis
                      vectorise et indexe localement
  5. ISOLATION        contenu externe balise, traite comme une donnee   (I2)
  6. FUSION TEINTEE   corroboration, detection de collusion             (I2)
  7. GENERATION       via l'abstraction de fournisseur (Frontiere B ou non)
  8. RESTITUTION      attribution, non-verifie, abstention              (I3)

Le budget d'exposition et le gabarit fige sont conserves d'une requete a
l'autre et d'une session a l'autre. Sans cela, l'enquete ne serait qu'une
suite de requetes independantes, faciles a recouper (section 3.3.5).
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
    """Le moteur de recherche hybride securise, avec tous ses composants.

    Tous les composants sont passes en argument, aucun n'est cree ici : le
    pipeline ne connait que des interfaces. C'est ce qui permet les ablations
    du chapitre 5 (retirer une couche et mesurer l'ecart).
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
        # A None, le moteur fait comme dans les versions precedentes : pas de
        # re-classement ni de reduction du nombre de fragments. On peut donc
        # rejouer les anciennes campagnes a l'identique.
        self.reclasseur = reclasseur
        self.top_k_generation = top_k_generation

    # ------------------------------------------------------------ pipeline

    def repondre(self, contexte, couches=None):
        """Traite une requete de bout en bout.

        `couches` permet de desactiver une protection, pour les ablations du
        chapitre 5 : {'verrou', 'isolation', 'corroboration', 'budget'}. Par
        defaut, toutes sont actives.
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
        # CORRIGER ne termine pas le routage : dans routeur.py, cela veut dire
        # refaire la recherche interne avant de conclure. Sans ce second
        # passage, la decision restait sur CORRIGER, `_franchir` n'etait
        # jamais appele et aucun contenu externe n'entrait dans le moteur.
        # Sur le jeu d'E6, 132 requetes sur 172 etaient concernees.
        #
        # La reprise est la meme que celle mesuree par E6 : rapporter plus de
        # resultats, puis juger a nouveau avec `deja_corrige`. Sans index
        # dense a cette etape, c'est la seule facon de refaire la recherche
        # interne. Je ne simule pas de gain qui n'existe pas.
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
            # Le systeme ne decide jamais seul d'une escalade : il la
            # propose, et un operateur habilite decide (section 3.2).
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
        # Copie de securite. `teinte.teinter` ecrit l'etiquette de confiance
        # dans le fragment. Sans copie, une execution modifierait les
        # fragments de la suivante. C'est le cas des ablations du chapitre 5,
        # qui rejouent les memes fragments dans plusieurs configurations.
        fragments = [_copier(f) for f in list(internes) + list(externes)]
        if "isolation" in couches:
            fragments = teinte.teinter(
                fragments,
                seuil_corroboration=self.config.isolation.seuil_corroboration,
            )

        # --- 6 bis. Re-classement, puis resserrement ---------------------
        #
        # `hybride.reclasser` existait mais n'etait jamais appele : le
        # cross-encodeur etait charge pour rien. Mesure du 15/09 sur les
        # invites envoyees : quarante fragments internes prenaient 72,2 % du
        # texte, la plupart hors sujet, alors que l'attribution n'en gardait
        # que trois.
        #
        # L'ordre des etapes est voulu. Le re-classement juge la pertinence,
        # la ponderation par confiance juge la fiabilite, et c'est la
        # ponderation qui passe en dernier. Sinon un document externe tres
        # pertinent mais empoisonne passerait devant un fragment interne
        # verifie, ce que le pilier 3 doit eviter.
        #
        # Le re-classement porte sur tous les candidats. `hybride.reclasser`
        # ne trie que ses `top_k` premiers elements et laisse le reste en
        # place. Or ici la liste vaut `internes + externes`, dans un ordre
        # sans lien avec la pertinence : re-classer les vingt premiers
        # reviendrait a ne regarder que des fragments internes. Mesure du
        # 15/09 : la charge adverse disparaissait alors de cinq invites sur
        # cinq, sans avoir jamais ete evaluee.
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
        # On enregistre le palier du fournisseur reellement utilise, qui peut
        # differer de celui de la configuration. Le detail par palier du
        # chapitre 5 en depend.
        reponse.palier = getattr(self.fournisseur, "palier",
                                 self.config.generation.palier)
        reponse.frontieres = resultat.frontieres
        resultat.reponse = reponse

        return self._clore(resultat, contexte, debut)

    # ------------------------------------------------------------ etapes

    def _recuperer_interne(self, requete, n=None):
        """Recherche interne. `n` augmente le nombre de resultats pour la correction."""
        if self.recuperateur_interne is None:
            return []
        return self.recuperateur_interne.rechercher(
            requete, n=n or self.config.recherche.n_final, avec_teinte=False
        )

    def _franchir(self, contexte, resultat, couches):
        """Passage controle de la Frontiere A.

        Trois controles a la suite, du plus souple au plus strict :
        generalisation selon le gabarit fige, masquage des entites nommees,
        puis verrou deterministe sur tous les secrets connus.
        """
        requete = contexte.requete

        # 2a. Generalisation selon le gabarit fige, si la requete porte sur une entite protegee.
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

        # 2b. Masquage des donnees personnelles.
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

        # 3 et 4. Seule une requete texte franchit A. Le contenu revient en
        # texte et sera vectorise en local par le recuperateur externe.
        t0 = time.perf_counter()
        externes = self.recuperateur_externe.rechercher(
            requete, n=self.config.recherche.n_final, avec_teinte=False
        )
        resultat.etapes["recuperation_externe_ms"] = self._ms(t0)
        return externes

    def _generer(self, contexte, fragments, couches):
        """Generation qui doit rattacher chaque assertion a ses sources."""
        if self.fournisseur is None:
            # Sans fournisseur, les fragments sont renvoyes tels quels. On
            # mesure ainsi la recherche seule (E1), sans l'effet du modele.
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
        pass  # la trace est dans Resultat.frontieres, voir _clore

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
