"""
Modèle Template — Templates DOCX/PDF pour remplissage automatique
==================================================================
Les champs sont détectés automatiquement ({{ champ }} dans docxtpl).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(10), nullable=False, comment="docx | pdf")
    chemin_fichier: Mapped[str] = mapped_column(Text, nullable=False, comment="Chemin vers le fichier template sur l'hôte")
    champs: Mapped[dict | None] = mapped_column(
        JSONB, comment="Liste des champs [{nom, type, description}]"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
