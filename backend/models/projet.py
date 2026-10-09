"""
Modèle Projet — le travail de la page Créer, en brouillon, repris plus tard
========================================================================
Demande de Thomas (09/10/2026), plan : docs/plan-projets-creer.md. Un projet garde l'état complet
d'une tuile (documents cochés, instructions, groupes, paroles…) dans `etat`, sauvegardé
automatiquement, et la liste de ce qu'il a produit (`projet_resultats`, par référence : les
rapports, tableaux et morceaux restent dans leurs tables).

`proprietaire` PRÉVOIT les profils : aujourd'hui une valeur unique, demain le profil actif — toutes
les requêtes filtrent déjà dessus.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base

PROPRIETAIRE_PAR_DEFAUT = "thomas"
STATUTS = ("brouillon", "archive")


class Projet(Base):
    __tablename__ = "projets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False, comment="tuile de la page Créer")
    etat: Mapped[dict | None] = mapped_column(JSONB, comment="travail en cours, propre à la tuile")
    statut: Mapped[str] = mapped_column(Text, nullable=False, default="brouillon", server_default="brouillon")
    proprietaire: Mapped[str] = mapped_column(Text, nullable=False, default=PROPRIETAIRE_PAR_DEFAUT,
                                              server_default=PROPRIETAIRE_PAR_DEFAUT)
    supprime_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="corbeille")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 onupdate=func.now())

    __table_args__ = (Index("idx_projets_proprietaire_statut", "proprietaire", "statut"),)


class ProjetResultat(Base):
    __tablename__ = "projet_resultats"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    projet_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projets.id", ondelete="CASCADE"),
                                                 nullable=False, index=True)
    type: Mapped[str] = mapped_column(Text, nullable=False, comment="rapport | job | presentation | morceau")
    ref: Mapped[str] = mapped_column(Text, nullable=False, comment="identifiant de l'objet produit")
    libelle: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
