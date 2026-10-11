"""
Router Notifications — /api/notifications (la cloche de l'en-tête, 11/10/2026)
==============================================================================
  GET    /notifications                 → les plus récentes + nombre de non lues
  POST   /notifications/{id}/lu         → marquer lue
  POST   /notifications/lu-tout         → tout marquer lu
  DELETE /notifications/{id}            → supprimer
  POST   /notifications/idees/generer   → bilan « idées d'évolution » maintenant (tâche durable)

La fréquence du bilan automatique est un réglage (`notif_idees_frequence`, /api/system/config).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.notification import Notification

log = get_logger(__name__)
router = APIRouter()


def _uuid(valeur: str) -> uuid.UUID:
    try:
        return uuid.UUID(valeur)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")


def _to_dict(n: Notification) -> dict:
    return {
        "id": str(n.id), "type": n.type, "titre": n.titre, "contenu": n.contenu, "lu": n.lu,
        "periode_debut": n.periode_debut.isoformat() if n.periode_debut else None,
        "periode_fin": n.periode_fin.isoformat() if n.periode_fin else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


@router.get("/notifications")
async def lister(limite: int = Query(default=30, ge=1, le=200), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(
        select(Notification).order_by(Notification.created_at.desc()).limit(limite))).scalars().all()
    non_lues = (await db.execute(
        select(func.count()).select_from(Notification).where(Notification.lu.is_(False)))).scalar() or 0
    return {"notifications": [_to_dict(n) for n in rows], "non_lues": non_lues}


@router.post("/notifications/lu-tout")
async def tout_lire(db: AsyncSession = Depends(get_db)):
    await db.execute(update(Notification).where(Notification.lu.is_(False)).values(lu=True))
    await db.commit()
    return {"ok": True}


@router.post("/notifications/{notification_id}/lu")
async def marquer_lu(notification_id: str, db: AsyncSession = Depends(get_db)):
    n = await db.get(Notification, _uuid(notification_id))
    if not n:
        raise HTTPException(status_code=404, detail="Notification introuvable")
    n.lu = True
    await db.commit()
    return _to_dict(n)


@router.delete("/notifications/{notification_id}")
async def supprimer(notification_id: str, db: AsyncSession = Depends(get_db)):
    resultat = await db.execute(delete(Notification).where(Notification.id == _uuid(notification_id)))
    await db.commit()
    if not resultat.rowcount:
        raise HTTPException(status_code=404, detail="Notification introuvable")
    return {"ok": True}


@router.post("/notifications/idees/generer", status_code=202)
async def generer_idees(db: AsyncSession = Depends(get_db)):
    """Bilan « idées d'évolution » à la demande : tâche durable (file GPU), suivie par son job_id."""
    from services import job_worker
    from services.idees_evolution import TYPE

    job_id = await job_worker.enqueue(db, TYPE, {"force": True})
    await db.commit()
    log.info("Bilan idées d'évolution demandé", job_id=job_id)
    return {"job_id": job_id}
