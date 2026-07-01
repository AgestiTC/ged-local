"""
Router Jobs — /api/jobs
=======================
Suivi des tâches durables (file `jobs` consommée par le worker) : lister les jobs en
cours / récents, consulter un job (statut + progression + résultat), annuler.

  GET  /api/jobs?statut=&type=&limit=   → liste (plus récents d'abord)
  GET  /api/jobs/{id}                   → détail (statut, progression, résultat)
  POST /api/jobs/{id}/cancel            → demande d'annulation
  POST /api/jobs/demo                   → (dev) met un job de démo en file
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.job import Job
from services import job_worker

log = get_logger(__name__)
router = APIRouter()


def _job_dict(job: Job) -> dict:
    return {
        "id": str(job.id),
        "type": job.type,
        "statut": job.statut,
        "progress": job.progress or 0,
        "progress_message": job.progress_message,
        "document_id": str(job.document_id) if job.document_id else None,
        "parametres": job.parametres,
        "resultat": job.resultat,
        "erreur": job.erreur,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.get("/jobs")
async def list_jobs(
    statut: str | None = Query(default=None, description="pending|running|completed|failed|cancelled (CSV possible)"),
    type: str | None = Query(default=None, description="Filtrer par type de job"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Liste les jobs, plus récents d'abord. `statut` accepte plusieurs valeurs séparées par des virgules."""
    stmt = select(Job)
    if statut:
        statuts = [s.strip() for s in statut.split(",") if s.strip()]
        if statuts:
            stmt = stmt.where(Job.statut.in_(statuts))
    if type:
        stmt = stmt.where(Job.type == type)
    stmt = stmt.order_by(Job.created_at.desc()).limit(limit)
    jobs = (await db.execute(stmt)).scalars().all()
    return {"jobs": [_job_dict(j) for j in jobs]}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Détail d'un job (statut, progression, résultat)."""
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de job invalide")
    job = await db.get(Job, job_uuid)
    if not job:
        raise HTTPException(status_code=404, detail="Job non trouvé")
    return _job_dict(job)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Demande l'annulation d'un job (immédiate si `pending`, best effort si `running`)."""
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de job invalide")
    statut = await job_worker.request_cancel(db, job_id)
    if statut is None:
        raise HTTPException(status_code=404, detail="Job non trouvé")
    return {"job_id": job_id, "statut": statut}


_TERMINES = ("completed", "failed", "cancelled")


@router.get("/jobs/purge/count")
async def purge_count(days: int = Query(365, ge=1, le=3650), db: AsyncSession = Depends(get_db)) -> dict:
    """Compteurs pour la fenêtre de confirmation : historique total + entrées > N jours."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)
    total = (await db.execute(select(func.count()).select_from(Job).where(Job.statut.in_(_TERMINES)))).scalar() or 0
    anciens = (await db.execute(
        select(func.count()).select_from(Job).where(Job.statut.in_(_TERMINES), Job.completed_at < cutoff)
    )).scalar() or 0
    return {"total_termines": total, "anciens": anciens, "days": days}


@router.post("/jobs/purge")
async def purge_jobs(
    scope: str = Query("older_than", pattern="^(all|older_than)$"),
    days: int = Query(365, ge=1, le=3650),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Purge l'**historique** des tâches TERMINÉES (completed|failed|cancelled). Ne touche **jamais**
    aux tâches `pending`/`running`. `scope=all` (tout l'historique) | `older_than` (> N jours).
    """
    cond = Job.statut.in_(_TERMINES)
    if scope == "older_than":
        cond = cond & (Job.completed_at < datetime.now(tz=timezone.utc) - timedelta(days=days))
    n = (await db.execute(select(func.count()).select_from(Job).where(cond))).scalar() or 0
    await db.execute(delete(Job).where(cond))
    await db.commit()
    log.info("Purge historique tâches", scope=scope, days=days, supprimes=n)
    return {"supprimes": n, "scope": scope, "days": days if scope == "older_than" else None}


class DemoRequest(BaseModel):
    etapes: int = Field(default=5, ge=1, le=60, description="Nombre d'étapes (≈ secondes)")


@router.post("/jobs/demo")
async def enqueue_demo(body: DemoRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """(Dev) Met en file un job de démonstration pour valider le pipeline durable."""
    job_id = await job_worker.enqueue(db, "demo", {"etapes": body.etapes})
    await db.commit()
    return {"job_id": job_id, "statut": "pending"}
