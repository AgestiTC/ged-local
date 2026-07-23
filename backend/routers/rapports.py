"""
Router Historique des rapports — /api/rapports
==============================================
Archive persistante des rapports générés (table `rapports`). Consultée et gérée depuis
l'onglet « Historique » de la page Créer.

  GET    /rapports                 → liste (métadonnées, sans le contenu — léger)
  GET    /rapports/{id}            → un rapport complet (contenu Markdown)
  DELETE /rapports/{id}            → supprime un rapport
  POST   /rapports/delete          → supprime un LOT (ids) ou TOUT (tout=true)
  POST   /rapports/purge           → purge les rapports plus vieux que N jours
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.rapport import Rapport

log = get_logger(__name__)
router = APIRouter()


def _resume(r: Rapport, avec_contenu: bool = False) -> dict:
    d = {
        "id": str(r.id),
        "titre": r.titre,
        "mode": r.mode,
        "prompt": r.prompt,
        "modele": r.modele,
        "nb_caracteres": r.nb_caracteres,
        "sources": r.sources or [],
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }
    if avec_contenu:
        d["contenu"] = r.contenu
    return d


@router.get("/rapports", tags=["Historique"])
async def list_rapports(limit: int = 100, db: AsyncSession = Depends(get_db)) -> dict:
    """Liste des rapports archivés (plus récents d'abord), SANS le contenu (charge légère)."""
    rows = (await db.execute(
        select(Rapport).order_by(Rapport.created_at.desc()).limit(max(1, min(limit, 500)))
    )).scalars().all()
    total = (await db.execute(select(func.count()).select_from(Rapport))).scalar_one()
    return {"total": total, "rapports": [_resume(r) for r in rows]}


@router.get("/rapports/{rapport_id}", tags=["Historique"])
async def get_rapport(rapport_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Un rapport complet (avec son contenu Markdown) — pour le rouvrir dans le panneau."""
    try:
        rid = uuid.UUID(rapport_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")
    r = await db.get(Rapport, rid)
    if not r:
        raise HTTPException(status_code=404, detail="Rapport introuvable")
    return _resume(r, avec_contenu=True)


@router.delete("/rapports/{rapport_id}", tags=["Historique"])
async def delete_rapport(rapport_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        rid = uuid.UUID(rapport_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")
    r = await db.get(Rapport, rid)
    if not r:
        raise HTTPException(status_code=404, detail="Rapport introuvable")
    await db.delete(r)
    await db.commit()
    return {"supprimes": 1, "id": rapport_id}


class DeleteLot(BaseModel):
    ids: list[str] = Field(default_factory=list)
    tout: bool = Field(default=False, description="true = vide TOUT l'historique")


@router.post("/rapports/delete", tags=["Historique"])
async def delete_rapports(body: DeleteLot, db: AsyncSession = Depends(get_db)) -> dict:
    """Suppression en LOT : soit une sélection d'`ids`, soit **tout** l'historique (`tout=true`)."""
    if body.tout:
        n = (await db.execute(select(func.count()).select_from(Rapport))).scalar_one()
        await db.execute(delete(Rapport))
        await db.commit()
        log.info("Historique des rapports vidé", supprimes=n)
        return {"supprimes": n}

    ids = []
    for i in body.ids:
        try:
            ids.append(uuid.UUID(i))
        except ValueError:
            continue
    if not ids:
        return {"supprimes": 0}
    res = await db.execute(delete(Rapport).where(Rapport.id.in_(ids)))
    await db.commit()
    return {"supprimes": res.rowcount or 0}


@router.post("/rapports/purge", tags=["Historique"])
async def purge_rapports(jours: int = 30, db: AsyncSession = Depends(get_db)) -> dict:
    """Supprime les rapports de plus de `jours` jours. `jours<=0` = désactivé (ne supprime rien)."""
    if jours <= 0:
        return {"supprimes": 0, "message": "Purge désactivée (jours ≤ 0)."}
    from datetime import datetime, timedelta, timezone
    limite = datetime.now(tz=timezone.utc) - timedelta(days=jours)
    res = await db.execute(delete(Rapport).where(Rapport.created_at < limite))
    await db.commit()
    return {"supprimes": res.rowcount or 0, "jours": jours}
