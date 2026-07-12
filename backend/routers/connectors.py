"""
Router Connecteurs — /api/connectors
=====================================
Sources externes (cloud / NAS DSM) en LECTURE. Un **compte connecté = une `Source`**
(multi-comptes natif). P0 : créer / tester / parcourir. L'indexation réutilise le
pipeline durable existant (via le connecteur `walk_files`/`fetch_to_temp`).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.source import Source

log = get_logger(__name__)
router = APIRouter()


class ConnecteurCreate(BaseModel):
    type: str = Field(description="Type de connecteur (ex. synology)")
    libelle: str = Field(min_length=1)
    hote: str = Field(min_length=1, description="ID QuickConnect, IP/host(:port) ou URL")
    identifiant: str
    mot_de_passe: str
    chemin_base: str | None = None


def _src_dict(s: Source) -> dict:
    return {"id": str(s.id), "type": s.type, "libelle": s.libelle, "hote": s.hote,
            "identifiant": s.identifiant, "chemin_base": s.chemin_base, "actif": s.actif}


@router.get("/connectors", tags=["Connecteurs"])
async def types_disponibles() -> dict:
    """Types de connecteurs gérés + liste des comptes déjà connectés."""
    from services.connectors import types_supportes
    types = types_supportes()
    return {"types": types}


@router.get("/connectors/comptes", tags=["Connecteurs"])
async def lister_comptes(db: AsyncSession = Depends(get_db)) -> dict:
    """Comptes connectés (sources dont le type est géré par un connecteur)."""
    from services.connectors import types_supportes
    types = set(types_supportes())
    rows = (await db.execute(select(Source))).scalars().all()
    return {"comptes": [_src_dict(s) for s in rows if s.type in types]}


@router.post("/connectors", tags=["Connecteurs"])
async def creer_compte(body: ConnecteurCreate, db: AsyncSession = Depends(get_db)) -> dict:
    """Crée un compte connecté (secret chiffré). Ne l'indexe pas encore."""
    from services.connectors import get_connector
    if not get_connector(body.type):
        raise HTTPException(status_code=422, detail=f"Type de connecteur inconnu : {body.type}")
    from services.crypto import encrypt
    src = Source(type=body.type, libelle=body.libelle, hote=body.hote,
                 identifiant=body.identifiant, secret_chiffre=encrypt(body.mot_de_passe),
                 chemin_base=body.chemin_base)
    db.add(src)
    await db.commit()
    await db.refresh(src)
    log.info("Compte connecteur créé", type=body.type, libelle=body.libelle)
    return _src_dict(src)


async def _get_src_conn(source_id: str, db: AsyncSession):
    from services.connectors import get_connector
    try:
        src = await db.get(Source, uuid.UUID(source_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")
    if not src:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    conn = get_connector(src.type)
    if not conn:
        raise HTTPException(status_code=422, detail=f"Type '{src.type}' sans connecteur")
    return src, conn


@router.post("/connectors/{source_id}/test", tags=["Connecteurs"])
async def tester(source_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Teste la connexion (auth + joignabilité)."""
    src, conn = await _get_src_conn(source_id, db)
    try:
        ok = await conn.test(src)
        return {"ok": ok}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Connexion impossible : {exc}")


@router.get("/connectors/{source_id}/browse", tags=["Connecteurs"])
async def parcourir(source_id: str, chemin: str = Query(default="/"),
                    db: AsyncSession = Depends(get_db)) -> dict:
    """Liste un dossier distant (racine = partages)."""
    src, conn = await _get_src_conn(source_id, db)
    try:
        return {"chemin": chemin, "entrees": await conn.browse(src, chemin)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Navigation impossible : {exc}")
