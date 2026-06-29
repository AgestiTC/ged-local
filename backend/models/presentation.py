"""
Modèle Presentation — diaporama généré par IA
=============================================
Stocke la structure « slides » (JSON) produite par l'IA à partir d'un groupe de
documents. Sert à la fois la **visionneuse** (rendu HTML/reveal.js) et l'**export
PPTX** (python-pptx). Les `document_ids` sont conservés pour traçabilité.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class Presentation(Base):
    __tablename__ = "presentations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    theme: Mapped[str | None] = mapped_column(Text)
    slides: Mapped[list] = mapped_column(JSONB, nullable=False)        # [{titre, points[], notes?}]
    document_ids: Mapped[list] = mapped_column(JSONB, default=list)    # provenance
    modele_utilise: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
