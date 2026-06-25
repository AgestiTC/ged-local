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

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, get_db
from logger import get_logger
from models.document import Document
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


class IndexRequest(BaseModel):
    chemin: str = "/"                       # sous-dossier à indexer
    partage: str | None = None              # requis pour SMB
    recursive: bool = True


def _extraction_service():
    """Construit le pipeline d'extraction (mêmes services que le scan de dossiers)."""
    from services.embedding_service import EmbeddingService
    from services.extraction import ExtractionService
    from services.ollama_service import OllamaService
    from services.tika_service import TikaService
    ollama = OllamaService()
    return ExtractionService(TikaService(), ollama, EmbeddingService(ollama))


async def _index_local(chemin_base, chemin, recursive):
    from services.folder_watcher import EXTENSIONS_ACCEPTEES, _est_cache
    service = _extraction_service()
    base = Path(chemin_base or "/")
    cible = (base / chemin.lstrip("/")) if chemin not in ("", "/") else base
    it = cible.rglob("*") if recursive else cible.iterdir()
    fichiers = [f for f in it if f.is_file() and not _est_cache(f)
                and f.suffix.lstrip(".").lower() in EXTENSIONS_ACCEPTEES]
    log.info("Indexation source locale", chemin=str(cible), nb=len(fichiers))
    for f in fichiers:
        async with AsyncSessionLocal() as db:
            try:
                await service.process_file(f, source="watch", db=db)
                await db.commit()
            except Exception as e:
                log.error("Erreur indexation", fichier=str(f), erreur=str(e))


async def _index_smb(hote, partage, chemin, identifiant, secret, domaine):
    from services.folder_watcher import EXTENSIONS_ACCEPTEES
    service = _extraction_service()
    rels = await smb_service.walk_files(hote, partage, chemin, identifiant, secret, domaine, EXTENSIONS_ACCEPTEES)
    log.info("Indexation source SMB", hote=hote, partage=partage, nb=len(rels))
    for rel in rels:
        tmp = None
        try:
            tmp = await smb_service.fetch_to_temp(hote, partage, rel, identifiant, secret, domaine)
            async with AsyncSessionLocal() as db:
                doc_id = await service.process_file(Path(tmp), source="watch", db=db)
                # Référence stable vers l'emplacement réseau (pas le fichier temp)
                doc = await db.get(Document, uuid.UUID(doc_id))
                if doc:
                    doc.chemin = f"smb://{hote}/{partage}{rel}"
                    doc.nom = Path(rel).name
                await db.commit()
        except Exception as e:
            log.error("Erreur indexation SMB", fichier=rel, erreur=str(e))
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)


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


@router.post("/sources/{source_id}/index", tags=["Sources"])
async def index_source(
    source_id: str,
    body: IndexRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Indexe (en arrière-plan) un dossier d'une source — local (FS) ou SMB (fetch)."""
    src = await _get(db, source_id)
    if src.type == "local":
        background_tasks.add_task(_index_local, src.chemin_base, body.chemin, body.recursive)
    elif src.type == "smb":
        if not body.partage:
            raise HTTPException(status_code=422, detail="partage requis pour une source SMB")
        secret = crypto.decrypt(src.secret_chiffre) if src.secret_chiffre else None
        background_tasks.add_task(_index_smb, src.hote, body.partage, body.chemin, src.identifiant, secret, src.domaine)
    return {"message": "Indexation lancée en arrière-plan", "source": src.libelle, "chemin": body.chemin}


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
