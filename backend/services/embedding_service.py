"""
Service Embedding — Génération et stockage des vecteurs
========================================================
Découpe le texte en chunks et calcule un embedding par chunk via Ollama.
Les embeddings sont stockés dans la table `embeddings` (pgvector).
"""

from logger import get_logger
from utils.chunker import chunk_text

log = get_logger(__name__)


class EmbeddingService:
    """Gère la génération et le stockage des embeddings."""

    def __init__(self, ollama_service):
        self.ollama = ollama_service

    async def embed_document(self, document_id: str, texte: str) -> int:
        """
        Découpe le texte en chunks et stocke les embeddings en DB.

        Args:
            document_id: UUID du document
            texte: Texte extrait à encoder

        Returns:
            Nombre de chunks générés
        """
        chunks = chunk_text(texte)
        log.info("Début embedding", document_id=document_id, nb_chunks=len(chunks))

        # TODO Phase 1 :
        # Pour chaque chunk :
        #   vecteur = await self.ollama.embed(chunk)
        #   Insérer Embedding(document_id, chunk_index, chunk_text, embedding=vecteur) en DB
        # Gérer le fallback si qwen3-embedding:8b échoue → nomic-embed-text

        raise NotImplementedError("TODO Phase 1")
        return len(chunks)
