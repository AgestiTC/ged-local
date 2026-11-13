"""
ReorgPlan — plan de réorganisation PERSISTÉ (Phase 2, vue logique/virtuelle)
============================================================================
Chaque document reçoit un `dossier_cible` (arborescence virtuelle). Éditable (drag & drop).
Aucun fichier n'est déplacé à ce stade — l'application physique (NAS) est la Phase 3.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, false, func
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
    # Facultatif depuis l'étape 10 du plan rangement : un fichier de la médiathèque n'a pas de fiche GED.
    # SET NULL : supprimer une fiche ne doit pas effacer la trace d'un déplacement (décision n° 3).
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    chemin_source: Mapped[str] = mapped_column(Text, comment="chemin avant déplacement")
    chemin_dest: Mapped[str] = mapped_column(Text, comment="chemin après déplacement")
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Journal commun à tout ce qui déplace un fichier (décision d'architecture n° 3 du plan
    # rangement + mails). Colonnes posées à l'étape 3 ; l'annulation qui s'en sert — par lot
    # désigné, sans supprimer de ligne — arrive à l'étape 10. ⚠️ Toute colonne ajoutée ici doit
    # l'être aussi dans les migrations à chaud de database.py (la table existe déjà en prod).
    origine: Mapped[str] = mapped_column(
        Text, nullable=False, default="ged_reorg", server_default="ged_reorg",
        comment="ged_reorg | scan | quarantaine | rangement")
    est_dossier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    annule_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="date d'annulation")
    annule_par: Mapped[str | None] = mapped_column(Text, comment="identifiant de qui a annulé")
