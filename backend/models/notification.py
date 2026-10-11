"""
Modèle Notification — la cloche de l'en-tête (11/10/2026)
==========================================================
Messages que Matothèque adresse à l'utilisateur, lus dans la cloche entre « Tâches » et « Tika ».
Premier usage : le bilan périodique « idées d'évolution » tiré des instructions complémentaires
données pour analyser les documents de référence (services/idees_evolution.py).

En base et non en mémoire : l'API tourne sur plusieurs processus, le worker les écrit.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(Text, comment="idees_evolution | …")
    titre: Mapped[str] = mapped_column(Text)
    contenu: Mapped[str] = mapped_column(Text, comment="Markdown")
    periode_debut: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    periode_fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lu: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now())

    __table_args__ = (
        Index("idx_notifications_lu_date", "lu", "created_at"),
    )
