"""
ReorgPlan — plan de réorganisation PERSISTÉ (Phase 2, vue logique/virtuelle)
============================================================================
Chaque document reçoit un `dossier_cible` (arborescence virtuelle). Éditable (drag & drop).
Aucun fichier n'est déplacé à ce stade — l'application physique (NAS) est la Phase 3.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.document import Base


class ReorgPlan(Base):
    __tablename__ = "reorg_plan"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    dossier_cible: Mapped[str] = mapped_column(Text, nullable=False, comment="arborescence virtuelle (ex. Factures/2025)")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReorgMove(Base):
    """Journal des déplacements PHYSIQUES appliqués (Phase 3) — base de l'undo."""

    __tablename__ = "reorg_moves"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, comment="regroupe une application")
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE")
    )
    chemin_source: Mapped[str] = mapped_column(Text, comment="chemin avant déplacement")
    chemin_dest: Mapped[str] = mapped_column(Text, comment="chemin après déplacement")
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
