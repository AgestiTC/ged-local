"""
Modèle AuditEvent — journal d'activité métier (observabilité Phase 2)
====================================================================
Trace les opérations importantes de bout en bout (UI → API → worker) reliées par un
**`correlation_id`** commun : on peut suivre une indexation, une synchro ou une génération
depuis le clic jusqu'à la fin du job. Complète les logs techniques bruts (page Logs → Debug)
par une vue **métier lisible** (page Logs → Activité).

Distinct de la table `jobs` (état courant d'une tâche) : ici c'est un **historique d'événements**
horodatés (démarré / terminé / échec) avec durées et détails.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Relie les événements d'une même opération à travers les couches (UI/API/worker).
    correlation_id: Mapped[str | None] = mapped_column(Text)
    acteur: Mapped[str] = mapped_column(Text, comment="ui | api | worker | system")
    action: Mapped[str] = mapped_column(Text, comment="indexation | sync_source | generate_report | analyze | …")
    cible: Mapped[str | None] = mapped_column(Text, comment="objet concerné (source, document, …)")
    statut: Mapped[str] = mapped_column(Text, comment="start | success | error | cancelled | info")
    duree_ms: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("idx_audit_correlation", "correlation_id"),
        Index("idx_audit_created", "created_at"),
        Index("idx_audit_action", "action"),
    )
