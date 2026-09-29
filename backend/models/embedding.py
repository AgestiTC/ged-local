"""
Modèle Embedding — Chunks vectoriels pour la recherche sémantique
==================================================================
Chaque document est découpé en chunks. Chaque chunk a son vecteur
d'embedding généré par qwen3-embedding:8b via Ollama.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from models.document import Base

if TYPE_CHECKING:
    from models.document import Document


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
    #
    # DEMI-PRÉCISION (`halfvec`, 2 octets par dimension au lieu de 4) depuis le 29/09/2026 : la
    # moitié de l'espace (~1 Go sur 2,5 en prod) pour AUCUNE perte mesurée — top-10 identique
    # 10/10 sur 25 requêtes exactes, 1024d et 4096d. Les requêtes qui passent encore un
    # `CAST(… AS vector)` restent valides : pgvector convertit, et l'index est bien utilisé.
    embedding: Mapped[list[float] | None] = mapped_column(
        HALFVEC(4096), comment="Vecteur d'embedding (demi-précision)"
    )
    # Vecteur Matryoshka tronqué à 1024 dims (préfixe L2-normalisé du 4096). pgvector plafonne
    # l'indexation ANN à 2000 dims → seule cette colonne est indexable (HNSW). Sert de 1ᵉ passe
    # rapide de la recherche sémantique (candidats), le 4096 servant au reclassement fin.
    embedding_small: Mapped[list[float] | None] = mapped_column(
        HALFVEC(1024), nullable=True, comment="Préfixe Matryoshka 1024-d (indexable HNSW)"
    )
    modele_embedding: Mapped[str] = mapped_column(Text, default="qwen3-embedding:8b")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relations
    document: Mapped["Document"] = relationship(back_populates="embeddings")

    __table_args__ = (
        Index("idx_embeddings_document", "document_id"),
        # Index IVFFlat créé via SQL dans init-db.sql (SQLAlchemy ne le supporte pas nativement)
    )
