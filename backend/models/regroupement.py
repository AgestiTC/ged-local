"""
Modèle Regroupement — ensemble PERSISTANT de documents pour analyse.
====================================================================
Un « regroupement » = un groupe nommé de documents (réutilisable) sur lequel on lance
une **analyse** (prompt + modèle au choix) produisant un **rendu formaté** (markdown,
exportable PDF/DOCX). `prompt`/`modele` = consigne d'analyse propre au groupe ; le
dernier rendu est conservé (`dernier_rendu`).
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class Regroupement(Base):
    __tablename__ = "regroupements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    document_ids: Mapped[list] = mapped_column(JSONB, default=list)     # UUIDs (str) des documents
    prompt: Mapped[str | None] = mapped_column(Text, comment="Consigne d'analyse propre au groupe")
    modele: Mapped[str | None] = mapped_column(Text, comment="Modèle préféré (défaut = usage 'rapport')")

    # Dernier rendu d'analyse (markdown) — exportable via /export
    dernier_rendu: Mapped[str | None] = mapped_column(Text)
    dernier_modele: Mapped[str | None] = mapped_column(Text)
    dernier_analyse_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
