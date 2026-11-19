"""
/api/journal-questions — consulter et effacer le journal des questions à l'IA (plan RAG, étape B2)
==================================================================================================
Chacun voit et efface SES questions ; l'administrateur voit et efface celles de tous (`tous=true`).
Authentification éteinte : tout appelant est administrateur (`acces.role_appelant`).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.rag_question import ORIGINES, RagQuestion
from services import journal_questions
from services.acces import ADMIN, role_appelant

router = APIRouter()

APERCU = 200   # caractères de la question dans la liste


def _portee(request: Request, tous: bool):
    """Filtre SQL de ce que l'appelant peut voir : ses questions, ou toutes s'il est admin et le demande."""
    role, qui = role_appelant(request)
    if tous and role == ADMIN:
        return None
    return RagQuestion.auteur == qui


def _resume(q: RagQuestion) -> dict:
    return {
        "id": str(q.id), "created_at": q.created_at.isoformat() if q.created_at else None,
        "origine": q.origine, "auteur": q.auteur, "question": (q.question or "")[:APERCU],
        "statut": q.statut, "modele": q.modele, "nb_sources": len(q.sources or []), "duree_ms": q.duree_ms,
    }


async def _une(qid: str, request: Request, db: AsyncSession) -> RagQuestion:
    try:
        ident = uuid.UUID(qid)
    except ValueError:
        raise HTTPException(status_code=404, detail="Question introuvable")
    q = await db.get(RagQuestion, ident)
    role, qui = role_appelant(request)
    # Celle d'un autre = « introuvable » : on ne confirme pas son existence.
    if q is None or (role != ADMIN and q.auteur != qui):
        raise HTTPException(status_code=404, detail="Question introuvable")
    return q


@router.get("/journal-questions")
async def lister(request: Request, origine: str | None = None, tous: bool = False,
                 limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                 db: AsyncSession = Depends(get_db)) -> dict:
    """Questions de l'appelant (ou de tous pour l'admin), les plus récentes d'abord."""
    filtres = [f for f in (_portee(request, tous),) if f is not None]
    if origine:
        if origine not in ORIGINES:
            raise HTTPException(status_code=422, detail=f"Origine inconnue : {origine}")
        filtres.append(RagQuestion.origine == origine)
    total = (await db.execute(select(func.count()).select_from(RagQuestion).where(*filtres))).scalar_one()
    lignes = (await db.execute(select(RagQuestion).where(*filtres)
                               .order_by(RagQuestion.created_at.desc()).limit(limit).offset(offset))).scalars()
    return {"total": total, "retention_jours": journal_questions.retention_jours(),
            "questions": [_resume(q) for q in lignes]}


@router.get("/journal-questions/{qid}")
async def detail(qid: str, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Une question complète : réglages, sources et passages, prompts et versions, réponse."""
    q = await _une(qid, request, db)
    return {**_resume(q), "question": q.question, "reglages": q.reglages or {}, "sources": q.sources or [],
            "prompts": q.prompts or [], "reponse": q.reponse}


@router.delete("/journal-questions/{qid}")
async def effacer(qid: str, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    q = await _une(qid, request, db)
    await db.delete(q)
    await db.commit()
    return {"supprimees": 1}


@router.delete("/journal-questions")
async def effacer_tout(request: Request, tous: bool = False, db: AsyncSession = Depends(get_db)) -> dict:
    """Efface toutes SES questions (l'admin, avec `tous=true` : celles de tout le monde)."""
    portee = _portee(request, tous)
    req = delete(RagQuestion) if portee is None else delete(RagQuestion).where(portee)
    res = await db.execute(req)
    await db.commit()
    return {"supprimees": res.rowcount or 0}
