"""
Modèle PromptPresetVersion — historique des prompts pré-enregistrés (étape A6, 18/11/2026)
=========================================================================================
Chaque création ou modification d'un preset (`prompts_presets`) écrit une version complète
(nom, texte, description, catégorie, modèle préféré) : aucune donnée perdue, et « Restaurer »
recopie une ancienne version EN UNE NOUVELLE (jamais d'écrasement). Un preset créé avant A6 reçoit
sa version 1 au premier besoin (lecture de l'historique ou première modification). Supprimer un
preset supprime son historique (cascade).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class PromptPresetVersion(Base):
    __tablename__ = "prompts_presets_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    preset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompts_presets.id", ondelete="CASCADE"), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, comment="1, 2, 3… par preset ; la plus haute = contenu actuel")
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    categorie: Mapped[str | None] = mapped_column(Text)
    modele_prefere: Mapped[str | None] = mapped_column(Text)
    auteur: Mapped[str | None] = mapped_column(Text, comment="Identifiant de la personne connectée, si connu")
    commentaire: Mapped[str | None] = mapped_column(Text, comment="Ex. « Restauration de la version 2 »")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now())

    __table_args__ = (UniqueConstraint("preset_id", "version", name="uq_prompt_preset_version"),)
