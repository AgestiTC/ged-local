"""
Modèle Source — origine de fichiers à indexer
==============================================
Une « source » décrit OÙ Matothèque va chercher des documents :
- type `local` : un chemin filesystem (volume monté, ex. NAS en prod).
- type `smb`   : un partage réseau distant (hôte + partage) lu via SMB.

Les identifiants SMB (mot de passe / token) sont stockés **chiffrés** (Fernet) —
jamais en clair (cf. services/crypto.py).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False, comment="local | smb")

    # Commun
    chemin_base: Mapped[str | None] = mapped_column(Text, comment="local: chemin FS ; smb: partage ou partage/sous-dossier")

    # Spécifique SMB
    hote: Mapped[str | None] = mapped_column(Text, comment="IP/nom du serveur SMB")
    domaine: Mapped[str | None] = mapped_column(Text)
    identifiant: Mapped[str | None] = mapped_column(Text, comment="utilisateur SMB")
    secret_chiffre: Mapped[str | None] = mapped_column(Text, comment="mot de passe/token chiffré (Fernet)")

    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
