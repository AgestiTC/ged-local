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

import asyncio
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
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

# Progression d'indexation en mémoire (par source) → barre de progression UI.
_progression: dict[str, dict] = {}


def _prog_demarrer(sid: str) -> None:
    _progression[sid] = {"en_cours": True, "phase": "enumeration", "total": 0, "fait": 0}


def _prog_total(sid: str, total: int) -> None:
    if sid in _progression:
        _progression[sid].update({"phase": "indexation", "total": total})


def _prog_tick(sid: str) -> None:
    if sid in _progression:
        _progression[sid]["fait"] += 1


def _prog_fin(sid: str) -> None:
    if sid in _progression:
        _progression[sid].update({"en_cours": False, "phase": "termine"})


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


async def _index_local(chemin_base, chemin, recursive, source_id=None):
    from services.folder_watcher import _est_cache, MEDIA_EXTENSIONS
    from services import runtime_config
    exts = runtime_config.effective_extensions()
    service = _extraction_service()
    base = Path(chemin_base or "/")
    cible = (base / chemin.lstrip("/")) if chemin not in ("", "/") else base

    # Parcours du système de fichiers (stat sur chaque entrée) déporté en thread :
    # sur un gros arbre, le rglob synchrone bloquerait l'event loop au démarrage.
    def _lister_fichiers() -> list[Path]:
        it = cible.rglob("*") if recursive else cible.iterdir()
        return [f for f in it if f.is_file() and not _est_cache(f)
                and f.suffix.lstrip(".").lower() in exts]

    fichiers = await asyncio.to_thread(_lister_fichiers)
    nb_media = sum(1 for f in fichiers if f.suffix.lstrip(".").lower() in MEDIA_EXTENSIONS)
    log.info("Indexation source locale", chemin=str(cible), nb=len(fichiers), nb_media_catalogue=nb_media)
    if source_id:
        _prog_total(source_id, len(fichiers))
    try:
        for f in fichiers:
            async with AsyncSessionLocal() as db:
                try:
                    if f.suffix.lstrip(".").lower() in MEDIA_EXTENSIONS:
                        # Média : catalogue léger (pas de Tika/IA/embeddings)
                        await service.catalogue_media(chemin=str(f), nom=f.name, taille=f.stat().st_size, source="watch", db=db)
                    else:
                        await service.process_file(f, source="watch", db=db)
                    await db.commit()
                except Exception as e:
                    log.error("Erreur indexation", fichier=str(f), erreur=str(e))
            if source_id:
                _prog_tick(source_id)
            await asyncio.sleep(0)  # rendre la main à l'event loop entre deux fichiers
    finally:
        if source_id:
            _prog_fin(source_id)


async def _index_smb(hote, partage, chemin, identifiant, secret, domaine, source_id=None):
    from services import runtime_config
    from services.folder_watcher import MEDIA_EXTENSIONS
    service = _extraction_service()
    fichiers = await smb_service.walk_files(hote, partage, chemin, identifiant, secret, domaine, runtime_config.effective_extensions())
    nb_media = sum(1 for e in fichiers if Path(e["rel"]).suffix.lstrip(".").lower() in MEDIA_EXTENSIONS)
    log.info("Indexation source SMB", hote=hote, partage=partage, nb=len(fichiers), nb_media_catalogue=nb_media)
    if source_id:
        _prog_total(source_id, len(fichiers))
    try:
        for entry in fichiers:
            rel, taille = entry["rel"], entry["taille"]
            chemin_doc = f"smb://{hote}/{partage}{rel}"
            ext = Path(rel).suffix.lstrip(".").lower()
            try:
                if ext in MEDIA_EXTENSIONS:
                    # Médias : catalogue léger (nom/taille) SANS fetch ni Tika/IA/embeddings
                    async with AsyncSessionLocal() as db:
                        await service.catalogue_media(chemin=chemin_doc, nom=Path(rel).name, taille=taille, source="watch", db=db)
                        await db.commit()
                else:
                    # Documents : pipeline complet (fetch temp → extraction → IA → embeddings)
                    tmp = None
                    try:
                        tmp = await smb_service.fetch_to_temp(hote, partage, rel, identifiant, secret, domaine)
                        async with AsyncSessionLocal() as db:
                            doc_id = await service.process_file(Path(tmp), source="watch", db=db)
                            doc = await db.get(Document, uuid.UUID(doc_id))
                            if doc:
                                doc.chemin = chemin_doc
                                doc.nom = Path(rel).name
                            await db.commit()
                    finally:
                        if tmp and os.path.exists(tmp):
                            os.unlink(tmp)
            except Exception as e:
                log.error("Erreur indexation SMB", fichier=rel, erreur=str(e))
            finally:
                if source_id:
                    _prog_tick(source_id)
                await asyncio.sleep(0)  # rendre la main à l'event loop entre deux fichiers
    finally:
        if source_id:
            _prog_fin(source_id)


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
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Indexe un dossier d'une source (local ou SMB) comme **tâche durable** (worker) : renvoie
    un `job_id` immédiatement. La progression fine reste consultable via
    `GET /sources/{id}/progression` (barre UI) et le job via `GET /api/jobs/{id}`.
    """
    src = await _get(db, source_id)
    if src.type not in ("local", "smb"):
        raise HTTPException(status_code=422, detail="type de source inconnu")
    if src.type == "smb" and not body.partage:
        raise HTTPException(status_code=422, detail="partage requis pour une source SMB")

    _prog_demarrer(str(src.id))  # la barre s'affiche tout de suite (même en file d'attente)
    from services import job_worker
    job_id = await job_worker.enqueue(db, "indexation", {
        "source_id": str(src.id), "chemin": body.chemin, "partage": body.partage, "recursive": body.recursive,
    })
    await db.commit()
    log.info("Indexation mise en file (job durable)", source=src.libelle, job_id=job_id)
    return {"job_id": job_id, "statut": "pending", "message": "Indexation lancée (tâche durable)",
            "source": src.libelle, "chemin": body.chemin}


@router.get("/sources/{source_id}/progression", tags=["Sources"])
async def progression_source(source_id: str) -> dict:
    """État d'avancement de l'indexation d'une source (pour la barre de progression)."""
    p = _progression.get(source_id)
    if not p:
        return {"en_cours": False, "phase": "aucune", "total": 0, "fait": 0}
    return p


def _prefixe_source(src: Source) -> str:
    """Préfixe de chemin des documents indexés d'une source."""
    if src.type == "smb":
        return f"smb://{src.hote}/"
    return (src.chemin_base or "/").rstrip("/") + "/"


@router.get("/sources/{source_id}/indexed", tags=["Sources"])
async def indexed_tree(source_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Arbre des dossiers réellement indexés pour cette source (dérivé des documents)."""
    from collections import defaultdict
    src = await _get(db, source_id)
    prefix = _prefixe_source(src)
    base = prefix.rstrip("/")
    chemins = (await db.execute(
        select(Document.chemin).where(Document.chemin.like(prefix.replace("%", "") + "%"))
    )).scalars().all()

    direct: dict[str, int] = defaultdict(int)
    for ch in chemins:
        folder = ch.rsplit("/", 1)[0] if "/" in ch[len(base):] else base
        direct[folder] += 1

    total: dict[str, int] = defaultdict(int)
    allpaths: set[str] = set()
    for folder, n in direct.items():
        p = folder
        while True:
            total[p] += n
            allpaths.add(p)
            if p == base or len(p) <= len(base):
                break
            p = p.rsplit("/", 1)[0]

    children: dict[str, list[str]] = defaultdict(list)
    for p in allpaths:
        if p == base:
            continue
        parent = p.rsplit("/", 1)[0]
        if len(parent) >= len(base):
            children[parent].append(p)

    def build(p: str) -> dict:
        return {
            "chemin": p,
            "nom": p[len(base):].strip("/") .split("/")[-1] or p.split("/")[-1] or p,
            "nb": total.get(p, 0),
            "enfants": [build(c) for c in sorted(set(children.get(p, [])))],
        }

    arbre = [build(c) for c in sorted(set(children.get(base, [])))]
    return {"racine": base, "nb_documents": len(chemins), "arbre": arbre}


class DeindexRequest(BaseModel):
    chemins: list[str] = Field(default_factory=list, min_length=1)


@router.post("/sources/{source_id}/deindex", tags=["Sources"])
async def deindex(source_id: str, body: DeindexRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Retire de l'index (GED) les documents des dossiers donnés. Ne touche PAS aux fichiers."""
    from sqlalchemy import or_
    await _get(db, source_id)  # valide l'existence
    retires = 0
    for folder in body.chemins:
        f = folder.rstrip("/")
        docs = (await db.execute(
            select(Document).where(or_(Document.chemin == f, Document.chemin.like(f + "/%")))
        )).scalars().all()
        for d in docs:
            await db.delete(d)
            retires += 1
    await db.flush()
    log.info("Désindexation", source=source_id, dossiers=len(body.chemins), docs_retires=retires)
    return {"retires": retires}


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
