"""
Modèle Document — Table principale des fichiers indexés
========================================================
Chaque ligne représente un fichier unique (identifié par son hash SHA256).
Le texte extrait et les métadonnées Tika brutes sont stockés ici.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

if TYPE_CHECKING:
    from models.job import Job
    from models.embedding import Embedding
    from models.version import Version
    from models.metadata import MetadonneeIA


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    chemin: Mapped[str] = mapped_column(Text, nullable=False, comment="Chemin absolu du fichier source")
    nom: Mapped[str] = mapped_column(Text, nullable=False, comment="Nom du fichier")
    extension: Mapped[str] = mapped_column(String(20), nullable=False, comment="pdf, docx, pptx...")
    type_mime: Mapped[str | None] = mapped_column(Text, comment="Type MIME retourné par Tika")
    hash_sha256: Mapped[str] = mapped_column(String(64), nullable=False, comment="Hash SHA256 pour déduplication")
    taille_octets: Mapped[int | None] = mapped_column(BigInteger)
    date_import: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    date_modification_fichier: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    date_derniere_extraction: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    texte_extrait: Mapped[str | None] = mapped_column(Text, comment="Texte brut extrait par Tika")
    tika_metadata: Mapped[dict | None] = mapped_column(JSONB, comment="Métadonnées brutes Tika")
    statut: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        comment="pending | extracted | enriched | error",
    )
    erreur: Mapped[str | None] = mapped_column(Text, comment="Message d'erreur si échec")
    source: Mapped[str] = mapped_column(
        String(20),
        default="watch",
        comment="watch | upload | drag_drop",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relations
    metadonnees_ia: Mapped["MetadonneeIA"] = relationship(back_populates="document", uselist=False, cascade="all, delete-orphan")
    embeddings: Mapped[list["Embedding"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    versions: Mapped[list["Version"]] = relationship(back_populates="document", cascade="all, delete-orphan")
    jobs: Mapped[list["Job"]] = relationship(back_populates="document", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_documents_hash", "hash_sha256"),
        Index("idx_documents_chemin", "chemin"),
        Index("idx_documents_statut", "statut"),
    )
