"""
API de l'agent de poste — `/api/agent/*`, authentifiée par jeton de POSTE (étape 5 du plan rangement).

Pas de session ici : l'agent n'a pas de navigateur. Il présente `Authorization: Bearer mato_…`, un
jeton de portée `agent` (`jetons_api`), exigé par `jetons_api.poste_authentifie` QUE
L'AUTHENTIFICATION SOIT ACTIVE OU NON ; le middleware (`services/acces.py`) cantonne de son côté ce
jeton à ce préfixe. Le jeton désigne UN poste, qui ne voit et ne touche que SES emplacements.

| Méthode | Chemin | Rôle |
|---|---|---|
| GET  | `/api/agent/config` | racines à inventorier (et si elles sont dues), réglages |
| POST | `/api/agent/envois` | ouvre un envoi pour un emplacement → `envoi_id` |
| POST | `/api/agent/envois/{id}/lots` | un lot de listes de dossiers (JSON, gzip accepté) |
| POST | `/api/agent/envois/{id}/fin` | fin de l'envoi : le worker le traite (tâche `inventaire_envoi`) |
| GET  | `/api/agent/empreintes` | empreintes à calculer, dans la limite du jour |
| POST | `/api/agent/empreintes` | empreintes calculées |
"""

from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.auth import JetonApi
from services import jetons_api, job_worker
from services.rangement import agent, service
from services.rangement.depot import Depot, Poste

log = get_logger(__name__)
router = APIRouter(prefix="/agent")
T = TypeVar("T")


@dataclass
class Contexte:
    depot: Depot
    poste: Poste


async def _appliquer(attente: Awaitable[T]) -> T:
    try:
        return await attente
    except agent.AgentRefuse as exc:
        raise HTTPException(exc.statut, exc.message) from None


def _sync(fonction, *args):
    try:
        return fonction(*args)
    except agent.AgentRefuse as exc:
        raise HTTPException(exc.statut, exc.message) from None


async def contexte(request: Request, jeton: JetonApi = Depends(jetons_api.poste_authentifie)) -> Contexte:
    depot = service.fabrique()
    if depot is None:
        raise HTTPException(503, "Base de l'inventaire indisponible.")
    poste = await _appliquer(agent.poste_du_jeton(depot, jeton.id, request.headers.get("x-agent-version", "")))
    return Contexte(depot, poste)


async def _corps_borne(request: Request) -> bytes:
    """Corps lu en flux, plafonné : un lot géant est refusé avant d'être chargé en entier."""
    morceaux: list[bytes] = []
    total = 0
    async for morceau in request.stream():
        total += len(morceau)
        if total > agent.TAILLE_LOT_RECU_MAX:
            raise HTTPException(413, "Lot trop gros.")
        morceaux.append(morceau)
    return b"".join(morceaux)


@router.get("/config")
async def config(ctx: Contexte = Depends(contexte)) -> dict[str, Any]:
    return await agent.configuration(ctx.depot, ctx.poste, datetime.now(timezone.utc))


@router.post("/envois", status_code=201)
async def ouvrir(request: Request, ctx: Contexte = Depends(contexte)) -> dict[str, Any]:
    corps = _sync(agent.corps_json, await _corps_borne(request))
    emplacement_id = corps.get("emplacement_id") if isinstance(corps, dict) else None
    return {"envoi_id": await _appliquer(agent.ouvrir_envoi(ctx.depot, ctx.poste, emplacement_id))}


@router.post("/envois/{envoi_id}/lots")
async def lot(envoi_id: int, request: Request, ctx: Contexte = Depends(contexte)) -> dict[str, Any]:
    corps = await _corps_borne(request)
    encodage = request.headers.get("content-encoding", "")
    return {"recus": await _appliquer(agent.recevoir_lot(ctx.depot, ctx.poste, envoi_id, corps, encodage))}


@router.post("/envois/{envoi_id}/fin", status_code=202)
async def fin(envoi_id: int, ctx: Contexte = Depends(contexte), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    emp, scan_id = await _appliquer(agent.terminer_envoi(ctx.depot, ctx.poste, envoi_id))
    try:
        await job_worker.enqueue(db, service.JOB_ENVOI, {"emplacement_id": emp.id, "envoi_id": envoi_id,
                                                         "scan_id": scan_id, "cible": f"poste:{ctx.poste.nom}"})
        await db.commit()
    except Exception:
        await ctx.depot.clore_envoi(envoi_id, "abandonne")
        await service.clore_en_echec(ctx.depot, scan_id, "lancement du traitement impossible")
        raise
    return {"scan_id": scan_id}


@router.get("/empreintes")
async def a_calculer(ctx: Contexte = Depends(contexte)) -> dict[str, Any]:
    return await agent.demandes(ctx.depot, ctx.poste, service.maintenant_local().date())


@router.post("/empreintes")
async def calculees(request: Request, ctx: Contexte = Depends(contexte)) -> dict[str, Any]:
    corps = _sync(agent.corps_json, await _corps_borne(request))
    retenus = await _appliquer(agent.recevoir_empreintes(ctx.depot, ctx.poste, corps,
                                                         service.maintenant_local().date()))
    return {"retenus": retenus}
