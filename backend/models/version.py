"""
Modèle Version — Historique des modifications de fichiers
==========================================================
Détecte et enregistre quand un fichier source change (nouveau hash SHA256).
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from models.document import Base


class Version(Base):
    __tablename__ = "versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    numero_version: Mapped[int] = mapped_column(Integer, nullable=False)
    hash_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    taille_octets: Mapped[int | None] = mapped_column(BigInteger)
    date_detection: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    diff_resume: Mapped[str | None] = mapped_column(Text, comment="Résumé des changements par le LLM")
    chemin_archive: Mapped[str | None] = mapped_column(Text, comment="Chemin vers la version archivée")

    # Relations
    document: Mapped["Document"] = relationship(back_populates="versions")

    __table_args__ = (Index("idx_versions_document", "document_id"),)
