"""
Modèle MetadonneeIA — Enrichissement IA des documents
======================================================
Stocke les résultats de l'analyse LLM : catégorie, tags, résumé,
entités nommées, mots-clés, langue.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from models.document import Base

if TYPE_CHECKING:
    from models.document import Document


class MetadonneeIA(Base):
    __tablename__ = "metadonnees_ia"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    categorie: Mapped[str | None] = mapped_column(Text, comment="Catégorie déterminée par le LLM")
    sous_categorie: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text), comment="Tags extraits par le LLM")
    resume: Mapped[str | None] = mapped_column(Text, comment="Résumé auto-généré")
    langue: Mapped[str | None] = mapped_column(String(10), comment="Code langue (fr, en...)")
    entites: Mapped[dict | None] = mapped_column(
        JSONB, comment="Entités : {personnes:[], dates:[], lieux:[], organisations:[]}"
    )
    mots_cles: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    niveau_confidentialite: Mapped[str] = mapped_column(
        Text, default="normal", comment="normal | confidentiel | restreint"
    )
    modele_utilise: Mapped[str | None] = mapped_column(Text, comment="Nom du modèle Ollama utilisé")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relations
    document: Mapped["Document"] = relationship(back_populates="metadonnees_ia")

    __table_args__ = (
        Index("idx_meta_categorie", "categorie"),
    )
