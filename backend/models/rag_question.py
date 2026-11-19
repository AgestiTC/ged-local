"""
Journal des questions posées à l'IA sur les documents (plan prompts + RAG, étape B2)
=====================================================================================
Chaque question du chat appuyé sur la GED (mode Auto ou Toujours) et du mode Question de la GED
est gardée CÔTÉ SERVEUR, avec ce qu'il faut pour la rejouer et la juger : réglages, documents et
passages fournis au modèle, modèle, clés et versions des prompts servis, réponse, durée. Avant,
les conversations ne vivaient que dans le `localStorage` du navigateur.

Tout reste local. Conservation : `rag_questions_retention_jours` (180 par défaut, 0 = tout garder),
purgée par le worker ; chacun peut effacer ses questions (décision Q3 du 13/11/2026).
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base

ORIGINES = ("chat", "question")
STATUTS = ("en_cours", "ok", "erreur", "interrompue")


class RagQuestion(Base):
    __tablename__ = "rag_questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    origine: Mapped[str] = mapped_column(Text, nullable=False, comment="chat | question")
    auteur: Mapped[str | None] = mapped_column(Text, index=True,
                                               comment="identifiant de la session (SSO), jeton:<nom>, ou « api » sans authentification")
    question: Mapped[str] = mapped_column(Text, nullable=False)
    reglages: Mapped[dict | None] = mapped_column(JSONB, comment="mode GED, modèle demandé, intention comprise…")
    sources: Mapped[list | None] = mapped_column(
        JSONB, comment="[{id, nom, passages: [chunk_index…]}] — figées à la question (un document supprimé reste lisible)")
    modele: Mapped[str | None] = mapped_column(Text, comment="modèle réellement utilisé")
    prompts: Mapped[list | None] = mapped_column(JSONB, comment="[{cle, version}] — version 0 = texte d'origine du code")
    reponse: Mapped[str | None] = mapped_column(Text)
    statut: Mapped[str] = mapped_column(Text, nullable=False, default="en_cours")
    duree_ms: Mapped[int | None] = mapped_column(Integer)
