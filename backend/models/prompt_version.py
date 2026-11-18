"""
Modèle PromptVersion — prompts système modifiés depuis Paramètres › Prompts (étapes A4-A5)
=========================================================================================
Le texte d'ORIGINE d'un prompt système reste dans le code (`services/prompts.py`, revu et testé
par git). Cette table ne porte que les versions enregistrées depuis l'interface, sur le modèle de
`consignes_versions` : chaque enregistrement est une NOUVELLE version (jamais d'écrasement),
restaurer une version en crée une autre, et `texte` NULL = revenir à l'origine du code. La plus
haute version d'une clé est l'active.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class PromptVersion(Base):
    __tablename__ = "prompts_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cle: Mapped[str] = mapped_column(Text, index=True, comment="Clé du registre services/prompts.py")
    version: Mapped[int] = mapped_column(Integer, comment="1, 2, 3… par clé ; la plus haute est active")
    texte: Mapped[str | None] = mapped_column(Text, comment="NULL = texte d'origine (celui du code)")
    commentaire: Mapped[str | None] = mapped_column(Text)
    auteur: Mapped[str | None] = mapped_column(Text, comment="Identifiant de la personne connectée, si connu")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now())

    __table_args__ = (UniqueConstraint("cle", "version", name="uq_prompt_version_cle_version"),)
