"""
Index vectoriel Qdrant, dont la charge utile porte la provenance.

L'interet de ce module ne reside pas dans la recherche vectorielle, qui est
standard, mais dans la charge utile. Chaque fragment y transporte sa source,
son palier, sa rubrique, sa page, son pave, son etiquette de confiance et son
score de fiabilite. La provenance n'est pas reconstruite a l'affichage : elle
accompagne le fragment depuis l'index, car elle serait irrecuperable apres
l'indexation (section 3.5.1).

C'est ce qui rend l'invariant I3 effectif plutot que declaratif, et qui
fournit le substrat de la piste d'audit exigee en contexte bancaire.

Qdrant est deploye localement. Le principe directeur interdit d'envoyer des
vecteurs au-dela de la Frontiere A ; un service vectoriel heberge est donc
exclu, quelles que soient ses garanties contractuelles.
"""

import uuid

CHAMPS_PROVENANCE = (
    "doc_id", "source", "rubrique", "page", "pave",
    "origine", "confiance", "fiabilite", "corpus", "palier_origine",
)


def charge_utile(document, corpus="", palier_origine="interne"):
    """Construit la charge utile d'un fragment, provenance comprise.

    Aligne sur le schema commun d'ingestion : `doc_id`, `text`, `source`,
    `entities`, `rubrique`, `page`, `pave`.
    """
    return {
        "doc_id": str(document.get("doc_id", "")),
        "text": str(document.get("text", "")),
        "source": document.get("source", "interne"),
        "rubrique": str(document.get("rubrique", "")),
        "page": int(document.get("page", 1)),
        "pave": int(document.get("pave", 1)),
        "origine": document.get("origine", ""),
        "corpus": corpus,
        "palier_origine": palier_origine,
        # Teinte et fiabilite sont calculees a la fusion, non a l'ingestion :
        # elles dependent du contexte de la requete (corroboration,
        # collusion). Les champs sont reserves pour garder une structure
        # stable.
        "confiance": "",
        "fiabilite": 0.0,
        "entities": document.get("entities", []) or [],
    }


def identifiant_point(document, corpus=""):
    """Identifiant stable et reproductible d'un point.

    Deterministe : reindexer le meme corpus produit les memes identifiants,
    ce qui rend l'index rejouable a l'identique (section 4.1.5).
    """
    graine = f"{corpus}|{document.get('doc_id')}|{document.get('pave', 1)}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, graine))


class IndexQdrant:
    """Enveloppe minimale autour du client Qdrant.

    Le client est injecte plutot qu'instancie : les tests et les ablations du
    chapitre 5 doivent pouvoir lui substituer une implementation en memoire.
    """

    def __init__(self, collection="rag_souverain", dimension=1024,
                 hote="http://localhost:6333", client=None,
                 chemin_local=None, delai=60):
        self.collection = collection
        self.dimension = dimension
        self.hote = hote
        self.chemin_local = chemin_local
        # Delai d'attente d'une reponse du serveur, en secondes. La valeur par
        # defaut de la bibliotheque (cinq secondes) suffit tant que la
        # collection est vide, mais plus des qu'elle indexe en tache de fond :
        # une ecriture de 256 points expirait alors au troisieme corpus, sur
        # un poste dont le disque est partage avec le moteur conteneurise. Ce
        # delai n'est qu'un plafond et ne ralentit rien lorsque le serveur
        # repond rapidement.
        self.delai = delai
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from qdrant_client import QdrantClient
            # `chemin_local` permet un index sur fichier, sans serveur, par
            # exemple pour transferer l'index d'une machine louee vers le
            # portable.
            self._client = (QdrantClient(path=self.chemin_local)
                            if self.chemin_local
                            else QdrantClient(url=self.hote,
                                              timeout=self.delai))
        return self._client

    def creer(self, recreer=False):
        from qdrant_client.models import Distance, VectorParams
        existe = self.client.collection_exists(self.collection)
        if existe and not recreer:
            return self
        if existe:
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(
                size=self.dimension, distance=Distance.COSINE
            ),
        )
        # Index de charge utile : le filtrage par source et par corpus est
        # central pour le routage interne/externe et doit donc etre indexe.
        for champ, genre in (("source", "keyword"), ("corpus", "keyword"),
                             ("rubrique", "keyword")):
            try:
                self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=champ, field_schema=genre,
                )
            except Exception:
                pass
        return self

    def verser(self, documents, vecteurs, corpus="", lot=256,
               palier_origine="interne"):
        """Verse documents et vecteurs, par lots."""
        from qdrant_client.models import PointStruct
        total = len(documents)
        for debut in range(0, total, lot):
            tranche = documents[debut:debut + lot]
            points = [
                PointStruct(
                    id=identifiant_point(d, corpus),
                    vector=vecteurs[debut + i].tolist(),
                    payload=charge_utile(d, corpus, palier_origine),
                )
                for i, d in enumerate(tranche)
            ]
            self.client.upsert(collection_name=self.collection, points=points)
        return self

    def rechercher(self, vecteur_requete, n=50, source=None, corpus=None):
        """Recherche par voisinage, avec filtrage optionnel par provenance.

        Le filtre `source` est ce qui materialise la separation interne /
        externe au niveau de l'index : le routeur peut interroger l'un ou
        l'autre sans que les deux se melangent avant la fusion teintee.
        """
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        conditions = []
        if source:
            conditions.append(FieldCondition(key="source",
                                             match=MatchValue(value=source)))
        if corpus:
            conditions.append(FieldCondition(key="corpus",
                                             match=MatchValue(value=corpus)))
        filtre = Filter(must=conditions) if conditions else None

        resultats = self.client.query_points(
            collection_name=self.collection,
            query=vecteur_requete.tolist() if hasattr(vecteur_requete, "tolist")
            else vecteur_requete,
            limit=n, query_filter=filtre, with_payload=True,
        ).points
        return [(r.payload, float(r.score)) for r in resultats]

    def volumetrie(self):
        """Grandeurs a reporter dans JOURNAL_DONNEES, section 9."""
        info = self.client.get_collection(self.collection)
        return {
            "collection": self.collection,
            "points": info.points_count,
            "dimension": self.dimension,
            "statut": str(info.status),
        }
