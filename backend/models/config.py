"""
Modèle Config — configuration applicative en base (clé/valeur)
==============================================================
Principe « tout en base » : les paramètres éditables à chaud (URLs des services,
modèle par défaut…) sont stockés ici et surchargent les valeurs d'environnement.
"""

from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class Config(Base):
    __tablename__ = "config"

    cle: Mapped[str] = mapped_column(Text, primary_key=True, comment="ex: tika_url, ollama_url, n8n_url, default_model")
    valeur: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
