"""
Modèle Rapport — historique persistant des rapports générés
============================================================
Chaque rapport terminé est archivé ici (survit au rechargement, à la fermeture du
navigateur et au redémarrage — contrairement à l'ancien tampon de session en mémoire).
Consultable et supprimable depuis l'onglet « Historique » de la page Créer.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class Rapport(Base):
    __tablename__ = "rapports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str | None] = mapped_column(Text, comment="rapport_libre | classement | comparatif | wiki…")
    prompt: Mapped[str | None] = mapped_column(Text)
    modele: Mapped[str | None] = mapped_column(Text, comment="modèle Ollama réellement utilisé")
    contenu: Mapped[str] = mapped_column(Text, nullable=False, comment="rapport Markdown complet")
    nb_caracteres: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Documents sources : liste de {id, nom} — figée à la génération (traçabilité même si un
    # document est ensuite supprimé de la GED).
    sources: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
