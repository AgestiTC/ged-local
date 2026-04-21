"""
Router Extract — /api/extract
==============================
Gère les jobs d'extraction et permet de relancer l'extraction d'un document.

Endpoints :
  GET  /extract/status/{job_id}    → statut d'un job
  POST /extract/{document_id}      → relancer l'extraction d'un document existant
  GET  /extract/jobs               → liste des jobs récents
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.document import Document
from models.job import Job

log = get_logger(__name__)
router = APIRouter()


@router.get("/extract/status/{job_id}")
async def get_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retourne le statut et le résultat d'un job d'extraction."""
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de job invalide")

    result = await db.execute(select(Job).where(Job.id == job_uuid))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job non trouvé")

    return {
        "id": str(job.id),
        "type": job.type,
        "statut": job.statut,
        "document_id": str(job.document_id) if job.document_id else None,
        "parametres": job.parametres,
        "resultat": job.resultat,
        "erreur": job.erreur,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.post("/extract/{document_id}")
async def relancer_extraction(
    document_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Relance l'extraction complète d'un document existant.
    Utile pour ré-enrichir un document après une erreur ou une mise à jour du modèle.
    """
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de document invalide")

    result = await db.execute(select(Document).where(Document.id == doc_uuid))
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Document non trouvé")

    # Vérifier que le fichier source existe encore
    file_path = Path(doc.chemin)
    if not file_path.exists():
        raise HTTPException(
            status_code=422,
            detail=f"Fichier source introuvable : {doc.chemin}",
        )

    # Créer un nouveau job
    job = Job(
        type="extraction",
        statut="pending",
        document_id=doc.id,
        parametres={"fichier": doc.chemin, "source": doc.source, "relance": True},
    )
    db.add(job)

    # Remettre le document en pending pour forcer le retraitement
    # On supprime d'abord les métadonnées et embeddings existants
    # (la cascade FK s'en charge)
    doc.statut = "pending"
    doc.erreur = None
    await db.flush()
    job_id = str(job.id)

    # Lancer en arrière-plan (réimporte depuis upload pour ne pas dupliquer la logique)
    from routers.upload import _lancer_extraction_background
    background_tasks.add_task(
        _lancer_extraction_background,
        file_path,
        doc.source,
        job_id,
    )

    log.info("Relance extraction", doc_id=document_id, job_id=job_id)
    return {
        "document_id": document_id,
        "job_id": job_id,
        "statut": "en_attente",
        "message": f"Extraction de '{doc.nom}' relancée",
    }


@router.get("/extract/jobs")
async def list_jobs(
    statut: str | None = Query(default=None, description="pending|running|completed|failed"),
    type_job: str | None = Query(default=None, alias="type", description="extraction|enrichissement|rapport|embedding"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Liste les jobs récents (pour monitoring)."""
    stmt = select(Job)

    if statut:
        stmt = stmt.where(Job.statut == statut)
    if type_job:
        stmt = stmt.where(Job.type == type_job)

    stmt = stmt.order_by(Job.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    jobs = result.scalars().all()

    return {
        "total": len(jobs),
        "jobs": [
            {
                "id": str(j.id),
                "type": j.type,
                "statut": j.statut,
                "document_id": str(j.document_id) if j.document_id else None,
                "erreur": j.erreur,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            }
            for j in jobs
        ],
    }
