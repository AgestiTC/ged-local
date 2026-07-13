"""
Router Regroupements — /api/regroupements
==========================================
Groupes PERSISTANTS de documents + **analyse** (prompt/modèle → rendu formaté, exportable).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.document import Document
from models.regroupement import Regroupement

log = get_logger(__name__)
router = APIRouter()


class RegroupementIn(BaseModel):
    nom: str = Field(min_length=1)
    description: str | None = None
    document_ids: list[str] = Field(default_factory=list)
    prompt: str | None = None
    modele: str | None = None


class RegroupementPatch(BaseModel):
    nom: str | None = None
    description: str | None = None
    document_ids: list[str] | None = None
    prompt: str | None = None
    modele: str | None = None


class AnalyseIn(BaseModel):
    prompt: str | None = None   # override ponctuel
    model: str | None = None


def _resume(rg: Regroupement) -> dict:
    return {
        "id": str(rg.id), "nom": rg.nom, "description": rg.description,
        "nb_documents": len(rg.document_ids or []),
        "prompt": rg.prompt, "modele": rg.modele,
        "dernier_analyse_at": rg.dernier_analyse_at.isoformat() if rg.dernier_analyse_at else None,
        "dernier_modele": rg.dernier_modele,
    }


async def _get(db: AsyncSession, rid: str) -> Regroupement:
    try:
        rg = await db.get(Regroupement, uuid.UUID(rid))
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")
    if not rg:
        raise HTTPException(status_code=404, detail="Regroupement introuvable")
    return rg


@router.get("/regroupements", tags=["Regroupements"])
async def lister(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(Regroupement).order_by(Regroupement.created_at.desc()))).scalars().all()
    return {"regroupements": [_resume(r) for r in rows]}


@router.post("/regroupements", tags=["Regroupements"])
async def creer(body: RegroupementIn, db: AsyncSession = Depends(get_db)) -> dict:
    rg = Regroupement(nom=body.nom, description=body.description,
                      document_ids=body.document_ids, prompt=body.prompt, modele=body.modele)
    db.add(rg)
    await db.commit()
    await db.refresh(rg)
    log.info("Regroupement créé", nom=body.nom, nb=len(body.document_ids))
    return _resume(rg)


@router.get("/regroupements/{rid}", tags=["Regroupements"])
async def detail(rid: str, db: AsyncSession = Depends(get_db)) -> dict:
    rg = await _get(db, rid)
    ids = []
    for x in (rg.document_ids or []):
        try:
            ids.append(uuid.UUID(str(x)))
        except ValueError:
            pass
    docs = (await db.execute(select(Document).where(Document.id.in_(ids)))).scalars().all() if ids else []
    docmap = {str(d.id): d for d in docs}
    documents = [{"id": i, "nom": docmap[i].nom if i in docmap else "(supprimé)",
                  "extension": docmap[i].extension if i in docmap else None}
                 for i in (str(x) for x in (rg.document_ids or []))]
    return {**_resume(rg), "documents": documents, "dernier_rendu": rg.dernier_rendu}


@router.put("/regroupements/{rid}", tags=["Regroupements"])
async def modifier(rid: str, body: RegroupementPatch, db: AsyncSession = Depends(get_db)) -> dict:
    rg = await _get(db, rid)
    for champ in ("nom", "description", "document_ids", "prompt", "modele"):
        val = getattr(body, champ)
        if val is not None:
            setattr(rg, champ, val)
    await db.commit()
    await db.refresh(rg)
    return _resume(rg)


@router.delete("/regroupements/{rid}", tags=["Regroupements"])
async def supprimer(rid: str, db: AsyncSession = Depends(get_db)) -> dict:
    rg = await _get(db, rid)
    await db.delete(rg)
    await db.commit()
    return {"ok": True}


@router.post("/regroupements/{rid}/analyser", tags=["Regroupements"])
async def analyser(rid: str, body: AnalyseIn, db: AsyncSession = Depends(get_db)) -> dict:
    """Lance l'**analyse** (tâche durable) : prompt+modèle → rendu markdown stocké dans le groupe."""
    rg = await _get(db, rid)
    if not (rg.document_ids or []):
        raise HTTPException(status_code=422, detail="Regroupement vide")
    from services import job_worker
    params = {"regroupement_id": str(rg.id)}
    if body.prompt:
        params["prompt"] = body.prompt
    if body.model:
        params["model"] = body.model
    job_id = await job_worker.enqueue(db, "analyse_regroupement", params, document_id=None)
    await db.commit()
    log.info("Analyse regroupement mise en file", regroupement_id=str(rg.id), job_id=job_id)
    return {"job_id": job_id, "statut": "pending"}
