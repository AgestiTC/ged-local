"""
Modèles Veille RSS — flux abonnés à un dossier thématique & items reçus
======================================================================
La **veille** prolonge un dossier thématique : au lieu de ne contenir que des
ressources choisies à la main, un dossier peut s'**abonner à des flux RSS/Atom**
(un blog, une chaîne YouTube, un podcast, une revue…). Les nouveautés arrivent
dans une **liste d'items** que l'utilisateur lit, puis **promeut** en ressource
permanente (`ressources`) si elles méritent d'être gardées, ou écarte.

⚠️ **100 % local / sortie réseau confirmée** : le téléchargement des flux n'est
JAMAIS automatique en tâche de fond. Il se déclenche sur action explicite de
l'utilisateur (bouton « Rafraîchir la veille » → `POST /dossiers/{ref}/veille/refresh`),
au même titre qu'un test de service ou un pull de modèle.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class FluxRss(Base):
    __tablename__ = "flux_rss"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dossier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dossiers_thematiques.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    # Titre du flux : renseigné par l'utilisateur ou, à défaut, déduit du flux au 1er fetch.
    titre: Mapped[str | None] = mapped_column(Text)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # Trace du dernier rafraîchissement (pour l'UI) : quand, et si ça s'est bien passé.
    dernier_fetch: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dernier_etat: Mapped[str | None] = mapped_column(Text, comment="'ok' | 'erreur: …'")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # Un même flux ne s'abonne qu'une fois par dossier.
        UniqueConstraint("dossier_id", "url", name="uq_flux_dossier_url"),
    )


class VeilleItem(Base):
    __tablename__ = "veille_items"
    __table_args__ = (
        # Dédup : un item d'un flux est identifié par son guid (sinon son lien).
        UniqueConstraint("flux_id", "guid", name="uq_veille_flux_guid"),
        # Listing d'un dossier : items récents d'abord, non-lus mis en avant.
        Index("ix_veille_dossier", "dossier_id", "lu", "date_pub"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flux_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flux_rss.id", ondelete="CASCADE"), nullable=False
    )
    # Dénormalisé (le dossier du flux) : évite une jointure pour lister/compter la veille d'un dossier.
    dossier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dossiers_thematiques.id", ondelete="CASCADE"), nullable=False
    )
    guid: Mapped[str] = mapped_column(Text, nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    auteur: Mapped[str | None] = mapped_column(Text)
    resume: Mapped[str | None] = mapped_column(Text)
    date_pub: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lu: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # `true` = déjà transformé en ressource permanente du dossier (n'encombre plus la veille).
    promu: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
