"""
ModelMeta — classification PERSISTÉE des modèles Ollama
========================================================
On mémorise en base la classe d'un modèle (« officiel » registre Ollama vs « uncensored » /
import perso hors registre), calculée lors de la vérif MAJ (registre) ou du catalogue HF.
Évite de redeviner par heuristique de nom à chaque affichage.
"""

from datetime import datetime

from sqlalchemy import DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from models.document import Base


class ModelMeta(Base):
    __tablename__ = "model_meta"

    name: Mapped[str] = mapped_column(Text, primary_key=True, comment="nom Ollama du modèle")
    classe: Mapped[str] = mapped_column(Text, comment="officiel | uncensored")
    # Évaluation du tableau comparatif, RECALCULÉE depuis les faits (« Mettre à jour le tableau »)
    # et persistée : sans elle, chaque affichage retombait sur une base écrite à la main, qui
    # vieillit (elle citait encore un modèle supprimé) et ignore les modèles importés.
    evaluation: Mapped[dict | None] = mapped_column(JSONB, nullable=True,
                                                    comment="role/resume/ecriture_fr/vitesse/vram/verdict/source")
    evaluee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
