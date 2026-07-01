"""
ModelMeta — classification PERSISTÉE des modèles Ollama
========================================================
On mémorise en base la classe d'un modèle (« officiel » registre Ollama vs « uncensored » /
import perso hors registre), calculée lors de la vérif MAJ (registre) ou du catalogue HF.
Évite de redeviner par heuristique de nom à chaque affichage.
"""

from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from models.document import Base


class ModelMeta(Base):
    __tablename__ = "model_meta"

    name: Mapped[str] = mapped_column(Text, primary_key=True, comment="nom Ollama du modèle")
    classe: Mapped[str] = mapped_column(Text, comment="officiel | uncensored")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
