"""
Modèles d'authentification — SSO OpenID Connect (plan docs/plan-authentification.md, étape 1)
==============================================================================================
Tout est EN BASE : la prod tourne en `uvicorn --workers 2`, un état en mémoire ne serait vu que
d'un process sur deux. Matothèque ne stocke aucun mot de passe : les comptes vivent sur le NAS
(SSO), la fiche locale est créée à la première connexion (just-in-time).

- `utilisateurs`     : fiche locale d'une personne (clé = `sub` du SSO) ;
- `sessions_auth`    : sessions ouvertes. L'`id` est le SHA-256 du jeton du cookie — la base ne
                       contient jamais le jeton lui-même (une fuite de base ne donne aucune session) ;
- `oidc_tentatives`  : état d'une connexion en cours (state, nonce, PKCE) — usage unique, 10 min.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.document import Base


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


class Utilisateur(Base):
    __tablename__ = "utilisateurs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    emetteur: Mapped[str] = mapped_column(Text, nullable=False, default="", comment="émetteur (issuer) du SSO")
    sub: Mapped[str] = mapped_column(Text, nullable=False, comment="identifiant stable du SSO, propre à l'émetteur")
    identifiant: Mapped[str | None] = mapped_column(Text, comment="preferred_username (compte DSM)")
    nom: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    groupes: Mapped[list | None] = mapped_column(JSONB, comment="groupes du SSO à la dernière connexion")
    role: Mapped[str] = mapped_column(Text, nullable=False, comment="admin | utilisateur (lu du groupe)")
    bloque: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                         comment="frein d'urgence : refus même si le SSO accepte")
    premiere_connexion: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_maintenant)
    derniere_connexion: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_maintenant)

    __table_args__ = (UniqueConstraint("emetteur", "sub", name="uq_utilisateurs_emetteur_sub"),)


class SessionAuth(Base):
    __tablename__ = "sessions_auth"

    id: Mapped[str] = mapped_column(Text, primary_key=True, comment="SHA-256 (hex) du jeton du cookie")
    utilisateur_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("utilisateurs.id", ondelete="CASCADE"), nullable=False)
    creee: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_maintenant)
    derniere_activite: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_maintenant)
    expire_max: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("idx_sessions_auth_utilisateur", "utilisateur_id"),
                      Index("idx_sessions_auth_expire_max", "expire_max"))


class OidcTentative(Base):
    __tablename__ = "oidc_tentatives"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    state: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    nonce: Mapped[str] = mapped_column(Text, nullable=False)
    code_verifier: Mapped[str] = mapped_column(Text, nullable=False, comment="PKCE")
    retour: Mapped[str] = mapped_column(Text, nullable=False, default="/", comment="chemin relatif après connexion")
    navigateur: Mapped[str] = mapped_column(
        Text, nullable=False, default="", comment="SHA-256 du cookie `matotheque_oidc` (lie le state au navigateur)")
    creee: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_maintenant)

    __table_args__ = (Index("idx_oidc_tentatives_creee", "creee"),)
