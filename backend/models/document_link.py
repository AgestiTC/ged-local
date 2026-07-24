"""
Modèle DocumentLink — liens entre documents (BC ↔ facture, devis ↔ commande…)
============================================================================
Un lien relie deux documents partageant une **référence** (n° de commande, de
facture, de devis…) détectée dans leur texte, OU créé **manuellement** par
l'utilisateur. Les liens détectés automatiquement naissent au statut `suggere`
et doivent être **validés** (ou **rejetés**) — un lien rejeté n'est jamais
re-proposé (mémorisation de la décision).

Le couple (source, cible) est stocké **normalisé** (plus petit UUID en premier)
via un index unique, pour éviter les doublons A→B / B→A.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class DocumentLink(Base):
    __tablename__ = "document_links"
    __table_args__ = (
        # Un seul lien par paire de documents (paire normalisée à l'insertion).
        UniqueConstraint("source_document_id", "cible_document_id", name="uq_document_links_paire"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    cible_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    # Nature du lien : 'bc_facture' (types documentaires distincts), 'reference' (même n°,
    # types indéterminés), 'manuel' (créé à la main). Évolutif — pas de contrainte CHECK.
    type_lien: Mapped[str] = mapped_column(Text, nullable=False, default="reference")
    # Référence partagée ayant justifié le lien (n° normalisé), null si manuel.
    reference: Mapped[str | None] = mapped_column(Text)
    # Confiance de la suggestion (1.0 = certain / manuel).
    score: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0")
    # Cycle de vie : 'suggere' (auto, à valider) | 'valide' | 'rejete'.
    statut: Mapped[str] = mapped_column(Text, nullable=False, default="suggere")
    # 'auto' (détecté) | 'manuel' (créé par l'utilisateur).
    origine: Mapped[str] = mapped_column(Text, nullable=False, default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
