"""
Retours sur les réponses de l'IA (plan prompts + RAG, étape B3)
================================================================
Sur une question du journal (`rag_questions`, B2) : 👍 / 👎 sur la réponse, une réponse corrigée, et
« pertinent / pas pertinent » sur chaque document fourni à l'IA. Un clic, jamais obligatoire.

UN retour par question — celui de la personne qui l'a posée (c'est elle qui sait si la réponse
l'aide). La ligne disparaît avec sa question (conservation, effacement par l'utilisateur).
Ces retours alimenteront le classement (B4) et les fiches réponses (B5).
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base

AVIS = ("utile", "inutile")
JUGEMENTS = ("pertinent", "hors_sujet")


class RagRetour(Base):
    __tablename__ = "rag_retours"

    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rag_questions.id", ondelete="CASCADE"), primary_key=True)
    avis: Mapped[str | None] = mapped_column(Text, index=True, comment="utile | inutile — null = pas d'avis")
    correction: Mapped[str | None] = mapped_column(Text, comment="réponse corrigée par l'utilisateur")
    sources: Mapped[dict | None] = mapped_column(
        JSONB, comment="{id du document: pertinent | hors_sujet} — seulement les documents jugés")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
