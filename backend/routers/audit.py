"""
Router Audit — /api/audit (observabilité Phase 2)
=================================================
Consultation du journal d'activité métier (`audit_events`) : vue **Activité** de la page Logs.
Complète les logs techniques bruts (`/api/logs/tail`, vue Debug).

  GET /audit           → événements récents (filtres : action, statut, acteur, correlation_id)
  GET /audit/actions   → liste des actions distinctes (pour le filtre)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.audit import AuditEvent

router = APIRouter()


def _to_dict(e: AuditEvent) -> dict:
    return {
        "id": str(e.id),
        "correlation_id": e.correlation_id,
        "acteur": e.acteur,
        "action": e.action,
        "cible": e.cible,
        "statut": e.statut,
        "duree_ms": e.duree_ms,
        "message": e.message,
        "detail": e.detail,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


@router.get("/audit", tags=["Audit"])
async def list_audit(
    action: str | None = Query(default=None),
    statut: str | None = Query(default=None),
    acteur: str | None = Query(default=None),
    correlation_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Événements d'audit récents (plus récents d'abord), filtrables."""
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if statut:
        stmt = stmt.where(AuditEvent.statut == statut)
    if acteur:
        stmt = stmt.where(AuditEvent.acteur == acteur)
    if correlation_id:
        # Pour une corrélation, ordre CHRONOLOGIQUE (suivre l'enchaînement des couches).
        stmt = select(AuditEvent).where(AuditEvent.correlation_id == correlation_id).order_by(AuditEvent.created_at)
    rows = (await db.execute(stmt)).scalars().all()
    return {"events": [_to_dict(e) for e in rows]}


@router.get("/audit/actions", tags=["Audit"])
async def list_actions(db: AsyncSession = Depends(get_db)) -> dict:
    """Liste des `action` distinctes présentes (alimente le filtre de l'UI)."""
    rows = (await db.execute(select(distinct(AuditEvent.action)).order_by(AuditEvent.action))).scalars().all()
    return {"actions": [a for a in rows if a]}
