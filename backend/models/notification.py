"""
Modèle Notification — la cloche de l'en-tête (11/10/2026)
==========================================================
Messages que Matothèque adresse à l'utilisateur, lus dans la cloche entre « Tâches » et « Tika ».
Premier usage : le bilan périodique « idées d'évolution » tiré des instructions complémentaires
données pour analyser les documents de référence (services/idees_evolution.py).

Rangement, étape 11 (14/11/2026 — décision d'architecture n° 4) : une notification peut viser une
personne (`utilisateur_id`) ou un rôle (`pour_role`, ex. « admin ») ; NULL partout = pour tous. Une
`cle` dédoublonne : tant qu'une notification de même clé n'est pas lue, la suivante la REMPLACE au
lieu de s'empiler (index unique partiel, PostgreSQL). `visible_le` diffère l'affichage pendant les
heures de silence de son destinataire. Tout passe par `services/notifier.py`.

En base et non en mémoire : l'API tourne sur plusieurs processus, le worker les écrit.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func, text

from models.document import Base

#: Destinataire des préférences quand l'authentification est éteinte (personne n'est connecté) :
#: le « poste local ». Pas une fiche d'utilisateur — d'où l'absence de clé étrangère sur les préférences.
POSTE_LOCAL = uuid.UUID(int=0)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(Text, comment="idees_evolution | rangement_* …")
    titre: Mapped[str] = mapped_column(Text)
    contenu: Mapped[str] = mapped_column(Text, comment="Markdown")
    periode_debut: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    periode_fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lu: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now())
    utilisateur_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("utilisateurs.id", ondelete="CASCADE"),
        comment="destinataire ; NULL = selon pour_role")
    pour_role: Mapped[str | None] = mapped_column(Text, comment="admin = réservée aux administrateurs ; NULL = tous")
    cle: Mapped[str | None] = mapped_column(Text, comment="dédoublonnage : une seule non lue par (destinataire, clé)")
    lien: Mapped[str | None] = mapped_column(Text, comment="page de l'application à ouvrir (ex. /rangement?onglet=plan)")
    visible_le: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="masquée jusque-là (heures de silence du destinataire)")

    __table_args__ = (
        Index("idx_notifications_lu_date", "lu", "created_at"),
        Index("idx_notifications_utilisateur", "utilisateur_id"),
    )


class NotificationPreference(Base):
    """Préférences d'alerte d'UNE personne (ou du poste local, auth éteinte). Les préférences d'un
    utilisateur ne touchent jamais celles d'un autre : une ligne par personne."""
    __tablename__ = "notification_preferences"

    utilisateur_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True,
                                                      comment="utilisateurs.id, ou POSTE_LOCAL")
    alertes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'"),
                                          comment="{type: bool} ; absent = valeur par défaut du type")
    seuil_disque_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=80, server_default="80")
    seuil_croissance_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=50, server_default="50")
    seuil_croissance_gio: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    silence_debut: Mapped[str | None] = mapped_column(Text, comment="HH:MM, heure du foyer")
    silence_fin: Mapped[str | None] = mapped_column(Text, comment="HH:MM, heure du foyer")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc))
