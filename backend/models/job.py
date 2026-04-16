"""
Modèle Job — File d'attente des tâches asynchrones
====================================================
Gère l'ordre et le statut des tâches : extraction, enrichissement,
génération de rapports, calcul d'embeddings.

Évite le parallélisme LLM (Mixtral 26 GB = 1 tâche à la fois).
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from models.document import Base

if TYPE_CHECKING:
    from models.document import Document


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(
        String(30), nullable=False,
        comment="extraction | enrichissement | rapport | embedding"
    )
    statut: Mapped[str] = mapped_column(
        String(20), default="pending",
        comment="pending | running | completed | failed"
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )
    parametres: Mapped[dict | None] = mapped_column(JSONB, comment="Paramètres du job")
    resultat: Mapped[dict | None] = mapped_column(JSONB, comment="Résultat du job")
    erreur: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relations
    document: Mapped["Document"] = relationship(back_populates="jobs")

    __table_args__ = (
        Index("idx_jobs_statut", "statut"),
        Index("idx_jobs_type", "type"),
    )
