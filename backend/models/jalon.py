"""
Modèle Jalon — rétroplanning d'un dossier thématique
====================================================
Un **jalon** est une chose à faire (ou à savoir) située dans le temps par rapport à une
**date d'ancrage** propre au dossier — pour « Devenir parent », la **date du terme**.

Le temps est repéré par un entier signé, `mois`, et un seul :

    -9 … -1   mois de GROSSESSE   (-9 = 1ᵉʳ mois … -1 = 9ᵉ mois, celui qui précède le terme)
     0 … 36   mois d'ÂGE de l'enfant (0 = premier mois de vie)

Le même calcul vaut des deux côtés : la fenêtre du mois `m` va de `terme + m mois` à
`terme + (m+1) mois`. Un seul champ, pas de phase redondante à tenir cohérente — la
phase se déduit du signe (voir `routers/dossiers._fenetre_mois`).

`sa` (semaines d'aménorrhée) double l'information pour les échéances médicales, qui se
disent en SA et non en mois — c'est la référence des soignants, et celle des textes.

Le SUIVI (`fait`, `fait_le`, `note_perso`) vit sur la même ligne : Matothèque est une
application mono-utilisateur, une table de progression séparée n'apporterait qu'une
jointure. Ces trois colonnes sont les seules qu'un seed ne réécrit jamais.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class Jalon(Base):
    __tablename__ = "jalons"
    __table_args__ = (
        # Listing d'un planning : tout est lu d'un coup, trié par mois puis position.
        Index("ix_jalons_dossier_mois", "dossier_id", "mois", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dossier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dossiers_thematiques.id", ondelete="CASCADE"), nullable=False
    )

    # Position dans le temps — cf. docstring du module. Négatif = avant la naissance.
    mois: Mapped[int] = mapped_column(Integer, nullable=False)
    # Semaines d'aménorrhée, quand l'échéance se dit en SA (examens, dépistages). Facultatif.
    sa: Mapped[int | None] = mapped_column(Integer)

    titre: Mapped[str] = mapped_column(Text, nullable=False)
    # Le « pourquoi » et le « comment » : c'est ce qui distingue un rétroplanning d'une
    # liste de cases à cocher. Affiché dans la fiche, pas dans la carte.
    detail: Mapped[str | None] = mapped_column(Text)
    # 'medical' | 'administratif' | 'conges' | 'garde' | 'materiel' | 'preparation' | 'reperes'
    # Sans contrainte CHECK, comme `ressources.type` : ajouter une catégorie ne doit pas
    # demander de migration.
    categorie: Mapped[str] = mapped_column(Text, nullable=False, default="preparation")
    # Formulation exacte de l'échéance quand elle est réglementaire (« avant la fin de la
    # 14ᵉ semaine »). Le mois seul ne suffit pas à dire une date limite opposable.
    echeance: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    # `true` = obligatoire ou à échéance légale — se distingue visuellement du conseil.
    obligatoire: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                              server_default="false")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # 'manuel' | 'seed:<cle>' — même convention que les dossiers et les ressources.
    origine: Mapped[str] = mapped_column(Text, nullable=False, default="manuel")

    # ── Suivi personnel (jamais réécrit par un seed) ──────────────────────────
    fait: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    fait_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note_perso: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
