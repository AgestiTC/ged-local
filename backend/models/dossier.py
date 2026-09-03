"""
Modèles Dossier thématique & Ressource — veille documentaire par sujet
=====================================================================
Un **dossier thématique** est un sujet de veille (« Devenir parent », « RGPD »…)
regroupant des **ressources externes** : podcasts, chaînes, documentaires, livres,
articles, études, associations. Contrairement à la GED (qui indexe des *fichiers*)
et aux Liens (qui relient des *documents entre eux*), un dossier référence des
ressources **hors du système de fichiers** — d'où l'URL plutôt qu'un chemin.

Le `slug` sert d'URL lisible (`/dossiers/devenir-parent`) et de clé d'idempotence
pour les dossiers pré-remplis livrés avec l'application (voir `services/dossier_seed`).

`type` et `langue` sont volontairement **sans contrainte CHECK** (évolutif) : la
liste de référence vit côté applicatif, dans `routers/dossiers.TYPES_RESSOURCE`.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class DossierThematique(Base):
    __tablename__ = "dossiers_thematiques"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    # Identifiant lisible et stable : sert d'URL et de clé d'idempotence des seeds.
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    # 'manuel' (créé par l'utilisateur) | 'seed:<cle>' (livré avec l'application).
    origine: Mapped[str] = mapped_column(Text, nullable=False, default="manuel")

    # Hiérarchie : un dossier peut être le SOUS-DOSSIER d'un autre (ex. « MON BÉBÉ » →
    # « 0-1 an », « 1-2 ans »…). `null` = dossier RACINE. `ON DELETE CASCADE` → supprimer un
    # parent supprime ses enfants (et, par la FK des ressources, leurs ressources).
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dossiers_thematiques.id", ondelete="CASCADE"), nullable=True
    )
    # Ordre d'affichage des sous-dossiers dans leur parent (progression voulue, pas alphabétique).
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Ressource(Base):
    __tablename__ = "ressources"
    __table_args__ = (
        # Listing d'un dossier : tri par position seule. Le `groupe` n'entre PAS dans
        # l'ordre — sinon les groupes sortiraient par ordre alphabétique, alors que leur
        # succession porte une progression voulue (voir routers/dossiers.detail).
        Index("ix_ressources_dossier_ordre", "dossier_id", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dossier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dossiers_thematiques.id", ondelete="CASCADE"), nullable=False
    )
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    auteur: Mapped[str | None] = mapped_column(Text, comment="Auteur, producteur, réalisateur, éditeur")
    # 'podcast' | 'chaine' | 'video' | 'documentaire' | 'emission' | 'film' | 'serie' |
    # 'livre' | 'bd' | 'article' | 'etude' | 'rapport' | 'association' | 'prompt'
    type: Mapped[str] = mapped_column(Text, nullable=False, default="article")
    url: Mapped[str | None] = mapped_column(Text)
    langue: Mapped[str] = mapped_column(Text, nullable=False, default="fr")
    # Sous-section libre à l'intérieur du dossier (« Paternité », « Essais »…).
    groupe: Mapped[str | None] = mapped_column(Text)
    # Ce que la ressource apporte de spécifique — c'est elle qui fait la valeur du dossier.
    note: Mapped[str | None] = mapped_column(Text)
    # Texte long INTÉGRAL quand la ressource EST le contenu et non un pointeur vers lui :
    # texte complet d'un prompt, extrait, citation, mode d'emploi. `note` reste la phrase
    # de présentation affichée en liste ; `contenu` se déplie et se copie.
    contenu: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    favori: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # `false` = ressource périmée (replay expiré, podcast arrêté) conservée pour mémoire.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
