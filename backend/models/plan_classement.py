"""
Plan de classement (module Rangement, étape 9) — conception : docs/conception-plan-classement.md.

Trois tables, petites (des centaines de lignes, pas des millions comme l'inventaire) : elles passent
par l'ORM et sont créées par `create_all`, sous PostgreSQL comme sous SQLite (tests).

- `plan_noeuds`        : l'arborescence cible, partage par partage ;
- `plan_regles`        : où va quoi, explicitement, dans l'ordre de priorité ;
- `plan_propositions`  : pour chaque grand dossier (ou fichier isolé) de l'inventaire, où il irait.

Le plan ne déplace RIEN : ranger, c'est l'étape 10.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.document import Base


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


class PlanNoeud(Base):
    __tablename__ = "plan_noeuds"
    __table_args__ = (UniqueConstraint("partage", "chemin", name="uq_plan_noeud_chemin"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    partage: Mapped[str] = mapped_column(Text, nullable=False, comment="partage Synology (1er niveau, jamais créé par le plan)")
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("plan_noeuds.id", ondelete="CASCADE"))
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    chemin: Mapped[str] = mapped_column(Text, nullable=False, comment="chemin dans le partage, ex. 10-ADMINISTRATIF/Impôts")
    gabarit: Mapped[str | None] = mapped_column(Text, comment="sous-dossier calculé, ex. {annee}")
    verrouille: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="nom intouchable (ex. lu par Plex)")
    origine: Mapped[str] = mapped_column(Text, nullable=False, default="humain", comment="modele | humain | ia")
    description: Mapped[str | None] = mapped_column(Text, comment="ce qu'on y met — sert aussi d'indication à l'IA")
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_maintenant)


class PlanRegle(Base):
    __tablename__ = "plan_regles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    priorite: Mapped[int] = mapped_column(Integer, nullable=False, default=100, comment="la plus petite gagne")
    type: Mapped[str] = mapped_column(Text, nullable=False, comment="famille | extension | motif_nom | motif_chemin")
    valeur: Mapped[str] = mapped_column(Text, nullable=False)
    noeud_id: Mapped[int] = mapped_column(ForeignKey("plan_noeuds.id", ondelete="CASCADE"), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    origine: Mapped[str] = mapped_column(Text, nullable=False, default="humain")
    description: Mapped[str | None] = mapped_column(Text)
    valide_par: Mapped[str | None] = mapped_column(Text)
    valide_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_maintenant)


class PlanProposition(Base):
    __tablename__ = "plan_propositions"
    __table_args__ = (UniqueConstraint("emplacement_id", "chemin", name="uq_plan_proposition"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    emplacement_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="inv_emplacements.id")
    chemin: Mapped[str] = mapped_column(Text, nullable=False, comment="chemin de l'élément, relatif à l'emplacement")
    est_dossier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    taille: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="au calcul : une autre taille la périme")
    destination: Mapped[str | None] = mapped_column(Text, comment="chemin du nœud cible dans le partage")
    noeud_id: Mapped[int | None] = mapped_column(ForeignKey("plan_noeuds.id", ondelete="SET NULL"))
    regle_id: Mapped[int | None] = mapped_column(ForeignKey("plan_regles.id", ondelete="SET NULL"))
    par: Mapped[str | None] = mapped_column(Text, comment="regle | ia | humain")
    raison: Mapped[str | None] = mapped_column(Text)
    confiance: Mapped[float | None] = mapped_column(Float)
    statut: Mapped[str] = mapped_column(Text, nullable=False, default="proposee",
                                        comment="proposee | validee | refusee | en_place | sans_place")
    valide_par: Mapped[str | None] = mapped_column(Text)
    valide_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calcule_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_maintenant)
    signale_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),
                                                        comment="hors plan signalé dans la cloche (étape 11)")
    contenu: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false",
                                          comment="déplacer le CONTENU du dossier (pack de série vidé dans S01)")



class PlanLot(Base):
    """Un lot de rangement (étape 10) : des propositions validées, rangées ensemble et annulables
    ensemble. `id` est le `batch_id` de leurs lignes dans `reorg_moves` (origine `rangement`)."""
    __tablename__ = "plan_lots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    emplacement_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    statut: Mapped[str] = mapped_column(Text, nullable=False, default="pret",
                                        comment="pret | en_cours | range | partiel | refuse | annule | annule_partiel")
    operations: Mapped[list] = mapped_column(JSON, nullable=False, default=list, comment="l'aperçu validé")
    nb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    octets: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    message: Mapped[str | None] = mapped_column(Text)
    cree_par: Mapped[str | None] = mapped_column(Text)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_maintenant)
    range_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    annule_par: Mapped[str | None] = mapped_column(Text)
    annule_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
