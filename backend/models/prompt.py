"""
Modèle PromptPreset — Prompts pré-enregistrés
==============================================
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class PromptPreset(Base):
    __tablename__ = "prompts_presets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    categorie: Mapped[str | None] = mapped_column(Text, comment="rapport | classement | extraction | analyse")
    modele_prefere: Mapped[str | None] = mapped_column(Text, comment="Modèle Ollama recommandé")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
