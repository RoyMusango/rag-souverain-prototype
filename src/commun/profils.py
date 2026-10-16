"""
Profils d'execution, du petit portable a la machine avec GPU.

Ces profils permettent de faire tourner le projet sur une petite machine, et
aussi de mesurer ce que coute le materiel. La section 3.1.5 du rapport
demande de mesurer l'interet d'un deploiement entierement souverain : une
banque qui deploie sur site n'a pas forcement un GPU de laboratoire.

Il y a trois profils, chacun pour une question :

  COMPLET      GPU, modele de reference, corpus entier.
               Question : quelles sont les performances du moteur ?

  PARITE       meme modele et meme corpus que COMPLET, sur processeur, en
               precision simple, sur un echantillon.
               Question : les resultats obtenus sur GPU restent-ils valables
               pour un deploiement sur site ? C'est un controle : on attend
               une derive nulle.

  MODESTE      modele plus leger, corpus echantillonne, processeur.
               Question : combien de qualite perd-on avec un materiel
               modeste ?

PARITE change le materiel et garde le modele. MODESTE change le modele. Il
ne faut pas melanger les deux.
"""

from dataclasses import dataclass, field

COMPLET = "complet"
PARITE = "parite"
MODESTE = "modeste"


@dataclass
class ProfilExecution:
    """Parametres d'execution et ce qu'ils permettent de conclure."""
    nom: str
    modele_embeddings: str
    dimension: int
    modele_reclasseur: str = ""
    peripherique: str = None          # None = detecte
    precision: str = "float32"
    taille_lot: int = 8
    longueur_max: int = 2048
    taux_echantillon: float = 1.0     # 1.0 = corpus entier
    fils_processeur: int = None       # None = laisser torch decider
    question: str = ""
    comparable_a: str = None          # profil de reference pour la comparaison

    def echantillonner(self, documents, graine=42):
        """Echantillon reproductible, stratifie par rubrique.

        Un tirage uniforme sur EnronQA peut ne toucher que quelques boites aux
        lettres. On comparerait alors des corpus de structures differentes.
        D'ou la stratification.
        """
        if self.taux_echantillon >= 1.0:
            return list(documents)

        import random
        alea = random.Random(f"{graine}|{self.nom}")

        strates = {}
        for document in documents:
            strates.setdefault(document.get("rubrique", ""), []).append(document)

        retenus = []
        for rubrique in sorted(strates):
            membres = strates[rubrique]
            nombre = max(1, round(len(membres) * self.taux_echantillon))
            retenus.extend(alea.sample(membres, min(nombre, len(membres))))
        retenus.sort(key=lambda d: str(d.get("doc_id", "")))
        return retenus


PROFILS = {
    COMPLET: ProfilExecution(
        nom=COMPLET,
        modele_embeddings="BAAI/bge-m3", dimension=1024,
        modele_reclasseur="BAAI/bge-reranker-v2-m3",
        peripherique=None, precision="float16",
        taille_lot=32, longueur_max=8192, taux_echantillon=1.0,
        question="performances du moteur, corpus entier",
    ),
    PARITE: ProfilExecution(
        nom=PARITE,
        # Meme modele que le profil complet, sinon le controle ne vaut rien.
        modele_embeddings="BAAI/bge-m3", dimension=1024,
        modele_reclasseur="BAAI/bge-reranker-v2-m3",
        peripherique="cpu", precision="float32",
        taille_lot=4, longueur_max=2048, taux_echantillon=0.02,
        fils_processeur=4,
        question=("les resultats releves sur accelerateur valent-ils pour un "
                  "deploiement sur site ?"),
        comparable_a=COMPLET,
    ),
    MODESTE: ProfilExecution(
        nom=MODESTE,
        # Modele allege : 384 dimensions contre 1024, environ dix fois plus
        # rapide sur processeur, multilingue (francais et anglais couverts).
        modele_embeddings="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        dimension=384,
        modele_reclasseur="cross-encoder/ms-marco-MiniLM-L-6-v2",
        peripherique="cpu", precision="float32",
        taille_lot=16, longueur_max=512, taux_echantillon=0.10,
        fils_processeur=4,
        question="que coute la souverainete materielle en qualite ?",
        comparable_a=COMPLET,
    ),
}


# Debits approximatifs, en documents par seconde. Ils servent seulement a
# estimer la duree avant de lancer un calcul, pour ne pas demarrer sans le
# savoir un calcul de neuf heures. A remplacer par les debits observes des
# la premiere tranche.
DEBITS_INDICATIFS = {
    ("BAAI/bge-m3", "cuda"): 220.0,
    # Observe le 24/08/2026 sur ultraportable Core U, 4 fils, float32 :
    # 769 documents EUR-Lex en 25,9 min. Voir JOURNAL_DONNEES section 9.
    ("BAAI/bge-m3", "cpu"): 0.5,
    ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "cpu"): 45.0,
    ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "cuda"): 900.0,
}


def estimer_duree(profil, nombre_documents, peripherique=None,
                  documents=None, graine=42):
    """Duree estimee du calcul, en minutes, a consulter avant de lancer.

    Sur une machine louee a l'heure comme sur un portable, il faut savoir a
    l'avance si le calcul durera dix minutes ou neuf heures. Le rapport
    mentionne neuf heures d'extraction NER sur processeur.
    """
    peripherique = peripherique or profil.peripherique or "cpu"
    debit = DEBITS_INDICATIFS.get(
        (profil.modele_embeddings, peripherique),
        2.0 if peripherique == "cpu" else 150.0,
    )
    # `echantillonner` garde au moins un document par rubrique. Sur un corpus
    # avec beaucoup de rubriques, ce minimum pese lourd : je compte donc les
    # documents retenus au lieu d'extrapoler.
    if documents is not None:
        retenus = len(profil.echantillonner(documents, graine))
    else:
        retenus = round(nombre_documents * profil.taux_echantillon)
    minutes = retenus / debit / 60
    return {
        "documents_corpus": nombre_documents,
        "documents_retenus": retenus,
        "debit_indicatif_docs_s": debit,
        "duree_estimee_min": round(minutes, 1),
        "avertissement": (
            "estimation prealable, a remplacer par le debit observe"
            if minutes < 60 else
            f"ATTENTION : environ {minutes / 60:.1f} h. Reduisez "
            f"--taux ou changez de profil."
        ),
    }


def appliquer_determinisme(graine=42, fils=None):
    """Fixe toutes les graines possibles avant un calcul.

    Sinon, deux executions sur le meme materiel peuvent deja donner des
    resultats differents, et on ne peut plus comparer deux materiels.
    """
    import os
    import random

    random.seed(graine)
    os.environ["PYTHONHASHSEED"] = str(graine)

    releve = {"graine": graine, "torch": "absent"}
    try:
        import torch
        torch.manual_seed(graine)
        if fils:
            torch.set_num_threads(fils)
            releve["fils"] = fils
        # Certains noyaux CUDA ne sont pas deterministes par defaut (atomiques,
        # autotuning cuDNN). Je les desactive : sinon un ecart de rang du a
        # l'ordre des calculs ressemblerait a un ecart de materiel.
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(graine)
            torch.backends.cudnn.deterministic = True
            torch.backends.cudnn.benchmark = False
            releve["cudnn_deterministe"] = True
        releve["torch"] = torch.__version__
        releve["fils_effectifs"] = torch.get_num_threads()
    except ImportError:
        pass

    try:
        import numpy as np
        np.random.seed(graine)
        releve["numpy"] = np.__version__
    except ImportError:
        pass

    return releve
