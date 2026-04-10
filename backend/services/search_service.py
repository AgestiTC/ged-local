"""
Service Recherche — Hybride full-text + vectorielle
=====================================================
Combine deux méthodes de recherche :
  1. Full-text PostgreSQL (pg_trgm + to_tsvector) → pertinence lexicale
  2. Sémantique pgvector (cosine similarity) → pertinence sémantique

Le score final est une pondération des deux scores.
"""

from logger import get_logger

log = get_logger(__name__)


class SearchService:
    """Service de recherche hybride."""

    def __init__(self, ollama_service):
        self.ollama = ollama_service

    async def search(
        self,
        query: str,
        search_type: str = "hybrid",
        limit: int = 20,
        filters: dict | None = None,
    ) -> list[dict]:
        """
        Recherche des documents.

        Args:
            query: Texte de la requête
            search_type: "hybrid" | "text" | "semantic"
            limit: Nombre max de résultats
            filters: Filtres optionnels (categorie, tags, extension, date...)

        Returns:
            Liste de documents avec score de pertinence
        """
        # TODO Phase 3 :
        # Si search_type in ["hybrid", "semantic"] :
        #   query_embedding = await self.ollama.embed(query)
        #   → Recherche cosine similarity dans embeddings
        # Si search_type in ["hybrid", "text"] :
        #   → SELECT ... WHERE to_tsvector('french', texte_extrait) @@ plainto_tsquery('french', query)
        # Fusionner les scores (Reciprocal Rank Fusion ou pondération simple)
        raise NotImplementedError("TODO Phase 3")

    async def search_by_tags(self, tags: list[str], limit: int = 20) -> list[dict]:
        """Recherche par tags exacts."""
        # TODO Phase 3
        raise NotImplementedError("TODO Phase 3")
