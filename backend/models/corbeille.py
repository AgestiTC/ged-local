"""
Modèle Corbeille — journal des fichiers déplacés vers « À supprimer »
=====================================================================
Quand l'utilisateur envoie un fichier à la corbeille, on **déplace** le fichier
vers un dossier `A-SUPPRIMER-MATOTEQUE/` (jamais de suppression définitive) et on
journalise l'opération ici → permet de **restaurer** (annuler) le déplacement.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class Corbeille(Base):
    __tablename__ = "corbeille"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    chemin_origine: Mapped[str] = mapped_column(Text, nullable=False, comment="chemin complet d'origine (smb://… ou local)")
    chemin_corbeille: Mapped[str] = mapped_column(Text, nullable=False, comment="chemin complet dans la corbeille")
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), comment="source SMB (pour les identifiants au restore)")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
