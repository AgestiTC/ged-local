"""
Modèle DossierSurveille — Dossiers à indexer automatiquement
=============================================================
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class DossierSurveille(Base):
    __tablename__ = "dossiers_surveilles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chemin: Mapped[str] = mapped_column(Text, nullable=False, unique=True, comment="Chemin absolu sur l'hôte")
    nom_affichage: Mapped[str | None] = mapped_column(Text)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    recursive: Mapped[bool] = mapped_column(Boolean, default=True, comment="Surveiller les sous-dossiers")
    extensions_filtrees: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), comment="Filtrer par extension (null = tout)"
    )
    intervalle_scan_secondes: Mapped[int] = mapped_column(Integer, default=300, comment="5 min par défaut")
    dernier_scan: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
