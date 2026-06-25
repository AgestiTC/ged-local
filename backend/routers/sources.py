"""
Router Sources — /api/sources
=============================
Gère les sources de fichiers (local monté ou SMB distant) et leur exploration.

  GET    /sources               → liste (sans secret)
  POST   /sources               → créer (secret chiffré)
  PUT    /sources/{id}          → modifier
  DELETE /sources/{id}          → supprimer
  POST   /sources/test          → tester une connexion (avant sauvegarde)
  GET    /sources/{id}/shares   → lister les partages (SMB)
  GET    /sources/{id}/browse   → parcourir (local: FS, SMB: réseau)
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.source import Source
from services import crypto, smb_service

log = get_logger(__name__)
router = APIRouter()


class SourceIn(BaseModel):
    libelle: str
    type: str = Field(description="local | smb")
    chemin_base: str | None = None
    hote: str | None = None
    domaine: str | None = None
    identifiant: str | None = None
    secret: str | None = Field(default=None, description="mot de passe/token en clair (sera chiffré)")


def _to_dict(s: Source) -> dict:
    """Sérialise une source SANS jamais exposer le secret."""
    return {
        "id": str(s.id),
        "libelle": s.libelle,
        "type": s.type,
        "chemin_base": s.chemin_base,
        "hote": s.hote,
        "domaine": s.domaine,
        "identifiant": s.identifiant,
        "secret_defini": bool(s.secret_chiffre),  # ne révèle que la présence
        "actif": s.actif,
    }


async def _get(db: AsyncSession, source_id: str) -> Source:
    try:
        sid = uuid.UUID(source_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")
    src = await db.get(Source, sid)
    if not src:
        raise HTTPException(status_code=404, detail="Source introuvable")
    return src


@router.get("/sources", tags=["Sources"])
async def list_sources(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(Source).order_by(Source.created_at))).scalars().all()
    return {"sources": [_to_dict(s) for s in rows]}


@router.post("/sources", tags=["Sources"])
async def create_source(body: SourceIn, db: AsyncSession = Depends(get_db)) -> dict:
    if body.type not in ("local", "smb"):
        raise HTTPException(status_code=422, detail="type doit être 'local' ou 'smb'")
    src = Source(
        libelle=body.libelle, type=body.type, chemin_base=body.chemin_base,
        hote=body.hote, domaine=body.domaine, identifiant=body.identifiant,
        secret_chiffre=crypto.encrypt(body.secret) if body.secret else None,
    )
    db.add(src)
    await db.flush()
    return _to_dict(src)


@router.put("/sources/{source_id}", tags=["Sources"])
async def update_source(source_id: str, body: SourceIn, db: AsyncSession = Depends(get_db)) -> dict:
    src = await _get(db, source_id)
    src.libelle = body.libelle
    src.type = body.type
    src.chemin_base = body.chemin_base
    src.hote = body.hote
    src.domaine = body.domaine
    src.identifiant = body.identifiant
    if body.secret:  # ne ré-écrit le secret que s'il est fourni
        src.secret_chiffre = crypto.encrypt(body.secret)
    await db.flush()
    return _to_dict(src)


@router.delete("/sources/{source_id}", tags=["Sources"])
async def delete_source(source_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    src = await _get(db, source_id)
    await db.delete(src)
    return {"message": "Source supprimée", "id": source_id}


@router.post("/sources/test", tags=["Sources"])
async def test_source(body: SourceIn) -> dict:
    """Teste une source AVANT sauvegarde (secret en clair fourni dans le body)."""
    if body.type == "local":
        p = Path(body.chemin_base or "")
        return {"ok": p.exists() and p.is_dir(), "chemin": str(p)}
    if body.type == "smb":
        if not body.hote:
            raise HTTPException(status_code=422, detail="hôte requis pour une source SMB")
        return await smb_service.test_connexion(body.hote, body.identifiant, body.secret, body.domaine)
    raise HTTPException(status_code=422, detail="type inconnu")


@router.get("/sources/{source_id}/shares", tags=["Sources"])
async def list_shares(source_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    src = await _get(db, source_id)
    if src.type != "smb":
        raise HTTPException(status_code=400, detail="Source non-SMB")
    secret = crypto.decrypt(src.secret_chiffre) if src.secret_chiffre else None
    try:
        partages = await smb_service.list_shares(src.hote, src.identifiant, secret, src.domaine)
        return {"partages": partages}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SMB : {exc}")


@router.get("/sources/{source_id}/browse", tags=["Sources"])
async def browse_source(
    source_id: str,
    chemin: str = Query(default="/"),
    partage: str | None = Query(default=None, description="partage SMB (requis pour SMB)"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    src = await _get(db, source_id)
    if src.type == "local":
        base = Path(src.chemin_base or "/")
        cible = (base / chemin.lstrip("/")) if chemin not in ("", "/") else base
        if not cible.exists() or not cible.is_dir():
            raise HTTPException(status_code=404, detail="Dossier introuvable")
        entries = []
        for e in sorted(cible.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            entries.append({"nom": e.name, "dossier": e.is_dir(), "taille": e.stat().st_size if e.is_file() else 0})
        return {"chemin": str(cible), "entries": entries}
    # SMB
    if not partage:
        raise HTTPException(status_code=422, detail="partage requis pour une source SMB")
    secret = crypto.decrypt(src.secret_chiffre) if src.secret_chiffre else None
    try:
        entries = await smb_service.browse(src.hote, partage, chemin, src.identifiant, secret, src.domaine)
        return {"partage": partage, "chemin": chemin, "entries": entries}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SMB : {exc}")
