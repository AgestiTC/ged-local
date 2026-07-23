"""
Service Audit — journal d'activité métier (observabilité Phase 2)
=================================================================
`emit()` enregistre un événement dans `audit_events`. **Best effort absolu** : ne lève JAMAIS
(l'audit ne doit pas casser l'opération auditée) et n'impose aucune session à l'appelant.

Un `correlation_id` relie les événements d'une même opération à travers les couches
(UI → API → worker). Utilitaire `new_correlation_id()` pour en créer un.
"""

import uuid

from database import AsyncSessionLocal
from logger import get_logger
from models.audit import AuditEvent

log = get_logger(__name__)


def new_correlation_id() -> str:
    """Nouvel identifiant de corrélation (préfixé pour être reconnaissable dans les logs)."""
    return f"cor_{uuid.uuid4().hex[:16]}"


async def emit(action: str, statut: str, *, acteur: str = "api",
               correlation_id: str | None = None, cible: str | None = None,
               duree_ms: int | None = None, message: str | None = None,
               detail: dict | None = None) -> None:
    """
    Enregistre un événement d'audit. **Ne lève jamais** : un échec d'audit est logué en debug
    et ignoré, pour ne pas perturber l'opération métier.
    """
    try:
        async with AsyncSessionLocal() as db:
            db.add(AuditEvent(
                correlation_id=correlation_id, acteur=acteur, action=action, cible=cible,
                statut=statut, duree_ms=duree_ms,
                message=(message or "")[:2000] or None, detail=detail,
            ))
            await db.commit()
    except Exception as e:  # noqa: BLE001 — l'audit est secondaire, jamais bloquant
        log.debug("Audit non enregistré", action=action, statut=statut, erreur=str(e))
