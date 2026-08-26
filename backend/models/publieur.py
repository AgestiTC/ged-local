"""
Modèle ProjetPublieur — registre des projets autorisés à publier (passerelle wiki)
=================================================================================
Un projet AgestiTC autorisé à pousser sa documentation vers BookStack via la passerelle Matothèque.
Porte le jeton d'authentification (HACHÉ) et la **liste blanche** des livres où il peut publier.
Cf. `docs/plan-passerelle-wiki-multiprojets.md` (Lot 2 — auth entrante).
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class ProjetPublieur(Base):
    __tablename__ = "projets_publieurs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(Text, nullable=False, unique=True, comment="nom du projet, ex. « sapyn »")
    # SHA-256 (hex) du jeton ; le jeton en clair n'est montré qu'UNE fois à la génération.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, comment="SHA-256 hex du jeton d'API du projet")
    # Liste blanche des livres BookStack où ce projet peut publier (borne `ensure_book`).
    livres_autorises: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
