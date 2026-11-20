"""
/api/journal-questions — consulter et effacer le journal des questions à l'IA (plan RAG, étape B2)
==================================================================================================
Chacun voit et efface SES questions ; l'administrateur voit et efface celles de tous (`tous=true`).
Authentification éteinte : tout appelant est administrateur (`acces.role_appelant`).

B3 : `PUT /journal-questions/{qid}/retour` — 👍/👎, réponse corrigée, pertinence de chaque source.
Seule la personne qui a posé la question juge sa réponse (l'admin LIT les retours des autres).
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.rag_question import ORIGINES, RagQuestion
from models.rag_retour import RagRetour
from services import journal_questions
from services.acces import ADMIN, role_appelant

router = APIRouter()

APERCU = 200   # caractères de la question dans la liste
CORRECTION_MAX = 20_000
FILTRES_AVIS = ("utile", "inutile", "corrigee", "avec", "sans")


def _portee(request: Request, tous: bool):
    """Filtre SQL de ce que l'appelant peut voir : ses questions, ou toutes s'il est admin et le demande."""
    role, qui = role_appelant(request)
    if tous and role == ADMIN:
        return None
    return RagQuestion.auteur == qui


def _resume(q: RagQuestion, r: RagRetour | None = None) -> dict:
    return {
        "id": str(q.id), "created_at": q.created_at.isoformat() if q.created_at else None,
        "origine": q.origine, "auteur": q.auteur, "question": (q.question or "")[:APERCU],
        "statut": q.statut, "modele": q.modele, "nb_sources": len(q.sources or []), "duree_ms": q.duree_ms,
        "avis": r.avis if r else None, "corrigee": bool(r and r.correction),
    }


def _retour(r: RagRetour | None) -> dict | None:
    if r is None:
        return None
    return {"avis": r.avis, "correction": r.correction, "sources": r.sources or {},
            "updated_at": r.updated_at.isoformat() if r.updated_at else None}


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


def _filtre_avis(avis: str):
    if avis in ("utile", "inutile"):
        return RagRetour.avis == avis
    if avis == "corrigee":
        return RagRetour.correction.is_not(None)
    if avis == "avec":
        return RagRetour.question_id.is_not(None)
    return RagRetour.question_id.is_(None)   # « sans » retour


@router.get("/journal-questions")
async def lister(request: Request, origine: str | None = None, tous: bool = False, avis: str | None = None,
                 limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                 db: AsyncSession = Depends(get_db)) -> dict:
    """Questions de l'appelant (ou de tous pour l'admin), les plus récentes d'abord, avec leur retour."""
    filtres = [f for f in (_portee(request, tous),) if f is not None]
    if origine:
        if origine not in ORIGINES:
            raise HTTPException(status_code=422, detail=f"Origine inconnue : {origine}")
        filtres.append(RagQuestion.origine == origine)
    jointure = RagRetour.question_id == RagQuestion.id

    # Bilan des retours sur le périmètre (avant le filtre par avis : il sert justement à choisir ce filtre).
    bilan = (await db.execute(
        select(func.count(case((RagRetour.avis == "utile", 1))),
               func.count(case((RagRetour.avis == "inutile", 1))),
               func.count(RagRetour.correction))
        .select_from(RagQuestion).outerjoin(RagRetour, jointure).where(*filtres))).one()

    if avis:
        if avis not in FILTRES_AVIS:
            raise HTTPException(status_code=422, detail=f"Filtre inconnu : {avis}")
        filtres.append(_filtre_avis(avis))
    total = (await db.execute(select(func.count()).select_from(RagQuestion)
                              .outerjoin(RagRetour, jointure).where(*filtres))).scalar_one()
    lignes = (await db.execute(select(RagQuestion, RagRetour).outerjoin(RagRetour, jointure).where(*filtres)
                               .order_by(RagQuestion.created_at.desc()).limit(limit).offset(offset))).all()
    return {"total": total, "retention_jours": journal_questions.retention_jours(),
            "retours": {"utile": bilan[0], "inutile": bilan[1], "corrigees": bilan[2]},
            "questions": [_resume(q, r) for q, r in lignes]}


@router.get("/journal-questions/{qid}")
async def detail(qid: str, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Une question complète : réglages, sources et passages, prompts et versions, réponse, retour."""
    q = await _une(qid, request, db)
    r = await db.get(RagRetour, q.id)
    _, qui = role_appelant(request)
    return {**_resume(q, r), "question": q.question, "reglages": q.reglages or {}, "sources": q.sources or [],
            "prompts": q.prompts or [], "reponse": q.reponse,
            "retour": _retour(r), "peut_juger": q.auteur == qui}


class RetourIn(BaseModel):
    """Champs ABSENTS = inchangés ; `null` = retiré. `sources` se fusionne (une source à `null` est retirée)."""
    avis: Literal["utile", "inutile"] | None = None
    correction: str | None = Field(None, max_length=CORRECTION_MAX)
    sources: dict[str, Literal["pertinent", "hors_sujet"] | None] | None = None


@router.put("/journal-questions/{qid}/retour")
async def juger(qid: str, body: RetourIn, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Enregistre le retour (un clic suffit : chaque champ s'envoie seul). Rend le retour tel qu'il est gardé."""
    q = await _une(qid, request, db)
    _, qui = role_appelant(request)
    if q.auteur != qui:
        # L'admin voit les questions des autres, mais leur réponse n'est pas la sienne à juger.
        raise HTTPException(status_code=403, detail="Seule la personne qui a posé la question peut la juger")

    r = await db.get(RagRetour, q.id)
    if r is None:
        r = RagRetour(question_id=q.id, sources={})
        db.add(r)
    champs = body.model_fields_set
    if "avis" in champs:
        r.avis = body.avis
    if "correction" in champs:
        r.correction = (body.correction or "").strip() or None
    if "sources" in champs and body.sources is not None:
        connues = {str(s.get("id")) for s in (q.sources or []) if s.get("id")}
        if set(body.sources) - connues:
            raise HTTPException(status_code=422, detail="Document absent des sources de cette réponse")
        jugees = dict(r.sources or {})
        for doc_id, jugement in body.sources.items():
            if jugement is None:
                jugees.pop(doc_id, None)
            else:
                jugees[doc_id] = jugement
        r.sources = jugees   # nouvel objet : SQLAlchemy ne suit pas les mutations d'un JSONB en place

    if not (r.avis or r.correction or r.sources):
        # Tout retiré : pas de ligne vide qui compterait comme « jugée ».
        if r in db.new:
            db.expunge(r)
        else:
            await db.delete(r)
        await db.commit()
        return {"retour": None}
    await db.commit()
    await db.refresh(r)
    return {"retour": _retour(r)}


@router.delete("/journal-questions/{qid}")
async def effacer(qid: str, request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    q = await _une(qid, request, db)
    # Explicite : la cascade de la clé étrangère n'existe pas sous SQLite (tests).
    await db.execute(delete(RagRetour).where(RagRetour.question_id == q.id))
    await db.delete(q)
    await db.commit()
    return {"supprimees": 1}


@router.delete("/journal-questions")
async def effacer_tout(request: Request, tous: bool = False, db: AsyncSession = Depends(get_db)) -> dict:
    """Efface toutes SES questions (l'admin, avec `tous=true` : celles de tout le monde)."""
    portee = _portee(request, tous)
    if portee is None:
        await db.execute(delete(RagRetour))
        res = await db.execute(delete(RagQuestion))
    else:
        await db.execute(delete(RagRetour).where(
            RagRetour.question_id.in_(select(RagQuestion.id).where(portee))))
        res = await db.execute(delete(RagQuestion).where(portee))
    await db.commit()
    return {"supprimees": res.rowcount or 0}
