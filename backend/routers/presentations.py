"""
Router Présentations — /api/presentations
=========================================
Génère un diaporama (slides JSON) par IA à partir d'un groupe de documents, le
stocke, et l'expose pour la visionneuse (JSON) et l'export PPTX.

  POST /presentations              → génère + stocke ; retourne {id, titre, slides}
  GET  /presentations/{id}         → structure JSON (pour la visionneuse)
  GET  /presentations/{id}/pptx    → fichier PPTX téléchargeable
"""

import io
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.presentation import Presentation
from services import presentation_service

log = get_logger(__name__)
router = APIRouter()


class PresentationIn(BaseModel):
    document_ids: list[str] = Field(min_length=2, description="≥ 2 documents")
    consigne: str | None = None
    model: str | None = None


def _to_dict(p: Presentation) -> dict:
    return {
        "id": str(p.id),
        "titre": p.titre,
        "theme": p.theme,
        "slides": p.slides,
        "modele_utilise": p.modele_utilise,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.post("/presentations", tags=["Présentations"])
async def creer_presentation(body: PresentationIn, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Lance la génération d'un diaporama comme **tâche durable** (worker) : renvoie un
    `job_id` immédiatement. Le résultat (`presentation_id`) est dans `GET /api/jobs/{id}`.
    """
    if len(body.document_ids) < 2:
        raise HTTPException(status_code=422, detail="Sélectionnez au moins 2 documents")

    from services import job_worker
    job_id = await job_worker.enqueue(db, "presentation", {
        "document_ids": body.document_ids, "consigne": body.consigne, "model": body.model,
    })
    await db.commit()
    log.info("Présentation mise en file (job durable)", job_id=job_id, nb_docs=len(body.document_ids))
    return {"job_id": job_id, "statut": "pending"}


@router.get("/presentations/{presentation_id}", tags=["Présentations"])
async def get_presentation(presentation_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        p = await db.get(Presentation, uuid.UUID(presentation_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")
    if not p:
        raise HTTPException(status_code=404, detail="Présentation introuvable")
    return _to_dict(p)


@router.get("/presentations/{presentation_id}/pptx", tags=["Présentations"])
async def telecharger_pptx(presentation_id: str, db: AsyncSession = Depends(get_db)):
    try:
        p = await db.get(Presentation, uuid.UUID(presentation_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")
    if not p:
        raise HTTPException(status_code=404, detail="Présentation introuvable")

    data = presentation_service.slides_to_pptx(p.titre, p.slides)
    nom = (p.titre or "presentation").replace("/", "-").replace("\\", "-")[:80]
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="{nom}.pptx"'},
    )
