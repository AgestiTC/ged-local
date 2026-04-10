"""
Modèle Embedding — Chunks vectoriels pour la recherche sémantique
==================================================================
Chaque document est découpé en chunks. Chaque chunk a son vecteur
d'embedding généré par qwen3-embedding:8b via Ollama.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from models.document import Base


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, comment="Index du chunk dans le document")
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False, comment="Texte du chunk")
    # Dimension par défaut : 4096 (qwen3-embedding:8b)
    # À ajuster si un autre modèle est utilisé
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(4096), comment="Vecteur d'embedding"
    )
    modele_embedding: Mapped[str] = mapped_column(Text, default="qwen3-embedding:8b")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relations
    document: Mapped["Document"] = relationship(back_populates="embeddings")

    __table_args__ = (
        Index("idx_embeddings_document", "document_id"),
        # Index IVFFlat créé via SQL dans init-db.sql (SQLAlchemy ne le supporte pas nativement)
    )
