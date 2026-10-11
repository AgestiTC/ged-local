"""
Modèle ConsigneVersion — consignes de base modifiables, versionnées (11/10/2026)
================================================================================
Les consignes de base de Matothèque (analyse d'un document de référence, version corrigée…)
sont modifiables par l'utilisateur, AVEC GARDE-FOU : chaque modification est une NOUVELLE
version (jamais d'écrasement), restaurer une version en crée une autre, et la consigne
d'origine — écrite dans le code — reste toujours restaurable (`texte` NULL = l'origine).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class ConsigneVersion(Base):
    __tablename__ = "consignes_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cle: Mapped[str] = mapped_column(Text, comment="reference_analyse | reference_corrigee")
    version: Mapped[int] = mapped_column(Integer, comment="1, 2, 3… par clé ; la plus haute est active")
    texte: Mapped[str | None] = mapped_column(Text, comment="NULL = consigne d'origine (celle du code)")
    commentaire: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now())

    __table_args__ = (UniqueConstraint("cle", "version", name="uq_consigne_cle_version"),)
