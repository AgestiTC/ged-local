"""
Service GED — Logique de la Gestion Électronique de Documents
=============================================================
Gère les opérations CRUD sur les documents, les tags, les versions.
"""

from logger import get_logger

log = get_logger(__name__)


class GEDService:
    """Service principal de la GED."""

    async def get_documents(
        self,
        page: int = 1,
        per_page: int = 20,
        filters: dict | None = None,
    ) -> dict:
        """
        Retourne une liste paginée de documents avec leurs métadonnées.

        Returns:
            {items: [...], total: int, page: int, per_page: int}
        """
        # TODO Phase 3
        raise NotImplementedError("TODO Phase 3")

    async def get_document(self, document_id: str) -> dict:
        """Retourne un document avec toutes ses métadonnées."""
        # TODO Phase 3
        raise NotImplementedError("TODO Phase 3")

    async def update_tags(self, document_id: str, tags: list[str]) -> None:
        """Met à jour les tags d'un document (édition manuelle)."""
        # TODO Phase 3
        raise NotImplementedError("TODO Phase 3")

    async def delete_document(self, document_id: str) -> None:
        """Supprime un document de l'index (pas le fichier source)."""
        # TODO Phase 3
        raise NotImplementedError("TODO Phase 3")

    async def detect_duplicate(self, hash_sha256: str) -> str | None:
        """
        Vérifie si un document avec ce hash existe déjà.

        Returns:
            document_id si doublon, None sinon
        """
        # TODO Phase 1 (utilisé dans ExtractionService)
        raise NotImplementedError("TODO Phase 1")
