"""
Service Embedding — Génération et stockage des vecteurs
========================================================
Découpe le texte en chunks et calcule un embedding par chunk via Ollama.
Les embeddings sont stockés dans la table `embeddings` (pgvector).
"""

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from logger import get_logger
from models.embedding import Embedding
from utils.chunker import chunk_text
from utils.vectors import matryoshka_prefix

log = get_logger(__name__)
settings = get_settings()


class EmbeddingService:
    """Gère la génération et le stockage des embeddings."""

    def __init__(self, ollama_service):
        self.ollama = ollama_service

    async def embed_document(self, document_id: str, texte: str, db: AsyncSession) -> int:
        """
        Découpe le texte en chunks, calcule les vecteurs et les stocke en DB.

        Args:
            document_id: UUID du document (str)
            texte: Texte extrait à encoder
            db: Session DB async

        Returns:
            Nombre de chunks générés
        """
        # Découpage déporté en thread (CPU : peut être lourd sur de gros textes → ne pas bloquer l'event loop).
        chunks = await asyncio.to_thread(chunk_text, texte)
        if not chunks:
            log.warning("Aucun chunk généré", document_id=document_id)
            return 0

        log.info("Début embedding", document_id=document_id, nb_chunks=len(chunks))
        doc_uuid = uuid.UUID(document_id)

        # Usage « embeddings » (config Paramètres) > modèle d'embedding par défaut.
        from services import runtime_config
        modele = runtime_config.usage_model("embeddings") or settings.ollama_model_embedding
        for i, chunk in enumerate(chunks):
            try:
                vecteur = await self.ollama.embed(chunk, model=modele)
                # Une réponse VIDE est un échec, pas un résultat : stockée en NULL, le chunk
                # devenait invisible à la recherche sémantique alors que le document passait
                # « enrichi » (audit du 28/09/2026, M12 — même famille que les 1 220 « enrichis
                # à vide »). On la traite comme une erreur : repli, puis échec explicite.
                if not vecteur:
                    raise ValueError(f"embedding vide renvoyé par {modele}")
            except Exception as e:
                # Fallback vers le modèle léger si le modèle principal échoue
                log.warning(
                    "Fallback embedding",
                    erreur=str(e),
                    modele_principal=modele,
                    fallback=settings.ollama_model_embedding_fallback,
                )
                modele = settings.ollama_model_embedding_fallback
                vecteur = await self.ollama.embed(chunk, model=modele)
                if not vecteur:
                    raise RuntimeError(
                        f"Embedding vide, y compris avec le modèle de repli {modele} — "
                        "modèle d'embedding absent ou inadapté ?") from e

            embedding = Embedding(
                document_id=doc_uuid,
                chunk_index=i,
                chunk_text=chunk,
                embedding=vecteur if vecteur else None,
                # Préfixe Matryoshka 1024-d (indexable ANN) dérivé du 4096 — 1ᵉ passe de recherche.
                embedding_small=matryoshka_prefix(vecteur) if vecteur else None,
                modele_embedding=modele,
            )
            db.add(embedding)

        await db.flush()
        log.info("Embedding terminé", document_id=document_id, nb_chunks=len(chunks))
        return len(chunks)
