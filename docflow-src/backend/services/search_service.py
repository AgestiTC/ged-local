"""
Service Recherche — Hybride full-text + vectorielle
=====================================================
Combine deux méthodes de recherche :
  1. Full-text PostgreSQL (pg_trgm + to_tsvector) → pertinence lexicale
  2. Sémantique pgvector (cosine similarity) → pertinence sémantique

Le score final est une pondération : 40% full-text + 60% sémantique.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger

log = get_logger(__name__)

# Pondération des scores (doit sommer à 1.0)
POIDS_FULLTEXT = 0.40
POIDS_SEMANTIQUE = 0.60


class SearchService:
    """Service de recherche hybride."""

    def __init__(self, ollama_service):
        self.ollama = ollama_service

    async def search(
        self,
        query: str,
        db: AsyncSession,
        search_type: str = "hybrid",
        limit: int = 20,
        categorie: str | None = None,
        extension: str | None = None,
    ) -> list[dict]:
        """
        Recherche des documents.

        Args:
            query: Texte de la requête
            db: Session DB async
            search_type: "hybrid" | "text" | "semantic"
            limit: Nombre max de résultats
            categorie: Filtre catégorie
            extension: Filtre extension

        Returns:
            Liste de {document_id, score, ...} triée par score décroissant
        """
        if not query.strip():
            return []

        resultats_texte: dict[str, float] = {}
        resultats_semantiques: dict[str, float] = {}

        # --- Full-text ---
        if search_type in ("hybrid", "text"):
            resultats_texte = await self._recherche_fulltext(query, db, limit=limit * 2)

        # --- Sémantique ---
        if search_type in ("hybrid", "semantic"):
            try:
                embedding = await self.ollama.embed(query)
                resultats_semantiques = await self._recherche_semantique(
                    embedding, db, limit=limit * 2
                )
            except Exception as e:
                log.warning("Embeddings non disponibles, fallback full-text", erreur=str(e))
                if not resultats_texte:
                    resultats_texte = await self._recherche_fulltext(query, db, limit=limit * 2)

        # --- Fusion ---
        if search_type == "text":
            scores = resultats_texte
        elif search_type == "semantic":
            scores = resultats_semantiques
        else:
            scores = self._fusionner(resultats_texte, resultats_semantiques)

        if not scores:
            return []

        # Trier par score décroissant et limiter
        doc_ids_tries = sorted(scores, key=lambda k: scores[k], reverse=True)[:limit]

        # Récupérer les documents avec leurs métadonnées
        return await self._charger_resultats(doc_ids_tries, scores, db, categorie, extension)

    async def _recherche_fulltext(
        self, query: str, db: AsyncSession, limit: int = 50
    ) -> dict[str, float]:
        """Recherche full-text avec PostgreSQL ts_rank."""
        sql = text("""
            SELECT
                d.id::text AS document_id,
                ts_rank(
                    to_tsvector('french', COALESCE(d.texte_extrait, '') || ' ' || COALESCE(d.nom, '')),
                    plainto_tsquery('french', :query)
                ) AS score
            FROM documents d
            WHERE
                to_tsvector('french', COALESCE(d.texte_extrait, '') || ' ' || COALESCE(d.nom, ''))
                @@ plainto_tsquery('french', :query)
            ORDER BY score DESC
            LIMIT :limit
        """)
        result = await db.execute(sql, {"query": query, "limit": limit})
        rows = result.fetchall()

        if not rows:
            return {}

        # Normaliser entre 0 et 1
        max_score = max(r.score for r in rows) or 1.0
        return {r.document_id: r.score / max_score for r in rows}

    async def _recherche_semantique(
        self, embedding: list[float], db: AsyncSession, limit: int = 50
    ) -> dict[str, float]:
        """Recherche sémantique par cosine similarity avec pgvector."""
        if not embedding:
            return {}

        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

        sql = text("""
            SELECT
                e.document_id::text,
                MAX(1 - (e.embedding <=> :embedding::vector)) AS score
            FROM embeddings e
            WHERE e.embedding IS NOT NULL
            GROUP BY e.document_id
            ORDER BY score DESC
            LIMIT :limit
        """)

        try:
            result = await db.execute(sql, {"embedding": embedding_str, "limit": limit})
            rows = result.fetchall()
        except Exception as e:
            log.warning("Erreur recherche sémantique", erreur=str(e))
            return {}

        if not rows:
            return {}

        # Normaliser entre 0 et 1 (cosine similarity est déjà dans [-1, 1])
        max_score = max(r.score for r in rows) or 1.0
        return {r.document_id: max(0, r.score / max_score) for r in rows}

    def _fusionner(
        self,
        scores_texte: dict[str, float],
        scores_semantiques: dict[str, float],
    ) -> dict[str, float]:
        """
        Fusionne les scores full-text et sémantiques par pondération.
        Documents présents dans un seul index : score = 0 pour l'autre.
        """
        tous_ids = set(scores_texte) | set(scores_semantiques)
        return {
            doc_id: (
                POIDS_FULLTEXT * scores_texte.get(doc_id, 0.0)
                + POIDS_SEMANTIQUE * scores_semantiques.get(doc_id, 0.0)
            )
            for doc_id in tous_ids
        }

    async def _charger_resultats(
        self,
        doc_ids: list[str],
        scores: dict[str, float],
        db: AsyncSession,
        categorie: str | None,
        extension: str | None,
    ) -> list[dict]:
        """Charge les documents et leurs métadonnées depuis la DB."""
        if not doc_ids:
            return []

        sql = text("""
            SELECT
                d.id::text,
                d.nom,
                d.extension,
                d.taille_octets,
                d.statut,
                d.date_import,
                m.categorie,
                m.sous_categorie,
                m.tags,
                m.resume,
                m.langue
            FROM documents d
            LEFT JOIN metadonnees_ia m ON m.document_id = d.id
            WHERE d.id::text = ANY(:ids)
        """)

        result = await db.execute(sql, {"ids": doc_ids})
        rows = result.fetchall()

        resultats = []
        for row in rows:
            doc_id = row[0]

            # Filtres post-requête
            if categorie and row[6] != categorie:
                continue
            if extension and row[2] != extension:
                continue

            resultats.append({
                "id": doc_id,
                "nom": row[1],
                "extension": row[2],
                "taille_octets": row[3],
                "statut": row[4],
                "date_import": row[5].isoformat() if row[5] else None,
                "score": round(scores.get(doc_id, 0.0), 4),
                "metadonnees_ia": {
                    "categorie": row[6],
                    "sous_categorie": row[7],
                    "tags": row[8] or [],
                    "resume": row[9],
                    "langue": row[10],
                },
            })

        # Trier par score (ordre initial peut être perdu après le JOIN)
        resultats.sort(key=lambda r: r["score"], reverse=True)
        return resultats

    async def search_by_tags(self, tags: list[str], db: AsyncSession, limit: int = 20) -> list[dict]:
        """Recherche par tags exacts (intersection)."""
        if not tags:
            return []

        sql = text("""
            SELECT
                d.id::text, d.nom, d.extension, d.taille_octets, d.statut, d.date_import,
                m.categorie, m.tags, m.resume
            FROM documents d
            JOIN metadonnees_ia m ON m.document_id = d.id
            WHERE m.tags @> :tags
            ORDER BY d.date_import DESC
            LIMIT :limit
        """)

        result = await db.execute(sql, {"tags": tags, "limit": limit})
        rows = result.fetchall()

        return [
            {
                "id": row[0],
                "nom": row[1],
                "extension": row[2],
                "taille_octets": row[3],
                "statut": row[4],
                "date_import": row[5].isoformat() if row[5] else None,
                "score": 1.0,
                "metadonnees_ia": {
                    "categorie": row[6],
                    "tags": row[7] or [],
                    "resume": row[8],
                },
            }
            for row in rows
        ]
