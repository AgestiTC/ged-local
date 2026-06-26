"""
Router Corbeille — /api/corbeille
=================================
Déplace un fichier vers un dossier « A-SUPPRIMER-MATOTEQUE/ » (corbeille), au lieu
de le supprimer définitivement, et permet de **restaurer** (annuler) le déplacement.
Gère les fichiers SMB (NAS) et locaux. Opérations DESTRUCTIVES → confirmation côté UI.

  POST /corbeille/envoyer/{document_id}   → déplace le fichier vers la corbeille + retire de l'index
  GET  /corbeille                         → liste des éléments en corbeille
  POST /corbeille/{id}/restaurer          → remet le fichier à sa place + ré-indexe
"""

import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, get_db
from logger import get_logger
from models.corbeille import Corbeille
from models.document import Document
from models.source import Source
from services import crypto, smb_service
from services.file_access import _parse_smb

log = get_logger(__name__)
router = APIRouter()

CORBEILLE_DIR = "A-SUPPRIMER-MATOTEQUE"


def _extraction_service():
    from services.embedding_service import EmbeddingService
    from services.extraction import ExtractionService
    from services.ollama_service import OllamaService
    from services.tika_service import TikaService
    ollama = OllamaService()
    return ExtractionService(TikaService(), ollama, EmbeddingService(ollama))


async def _source_smb(db: AsyncSession, hote: str) -> Source | None:
    rows = (await db.execute(select(Source).where(Source.type == "smb", Source.hote == hote))).scalars().all()
    return next((s for s in rows if s.secret_chiffre), rows[0] if rows else None)


def _creds(src: Source | None):
    if not src:
        return None, None, None
    secret = crypto.decrypt(src.secret_chiffre) if src.secret_chiffre else None
    return src.identifiant, secret, src.domaine


@router.post("/corbeille/envoyer/{document_id}", tags=["Corbeille"])
async def envoyer_corbeille(document_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Déplace le fichier d'un document vers la corbeille + retire le document de l'index."""
    try:
        doc = await db.get(Document, uuid.UUID(document_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")

    chemin = doc.chemin or ""
    source_id = None

    if chemin.startswith("smb://"):
        hote, partage, rel = _parse_smb(chemin)
        src = await _source_smb(db, hote)
        source_id = src.id if src else None
        ident, secret, dom = _creds(src)
        base = f"/{CORBEILLE_DIR}"
        nom = Path(rel).name
        try:
            await smb_service.ensure_dir(hote, partage, base, ident, secret, dom)
            dest_rel = f"{base}/{nom}"
            if await smb_service.exists(hote, partage, dest_rel, ident, secret, dom):
                dest_rel = f"{base}/{Path(nom).stem}__{uuid.uuid4().hex[:6]}{Path(nom).suffix}"
            await smb_service.move_file(hote, partage, rel, dest_rel, ident, secret, dom)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Déplacement SMB impossible : {exc}")
        chemin_corbeille = f"smb://{hote}/{partage}{dest_rel}"
    else:
        p = Path(chemin)
        if not p.exists():
            raise HTTPException(status_code=404, detail=f"Fichier introuvable : {chemin}")
        trash = p.parent / CORBEILLE_DIR
        trash.mkdir(parents=True, exist_ok=True)
        dest = trash / p.name
        if dest.exists():
            dest = trash / f"{p.stem}__{uuid.uuid4().hex[:6]}{p.suffix}"
        shutil.move(str(p), str(dest))
        chemin_corbeille = str(dest)

    entry = Corbeille(nom=doc.nom, chemin_origine=chemin, chemin_corbeille=chemin_corbeille, source_id=source_id)
    db.add(entry)
    await db.delete(doc)            # retire de l'index (le fichier est en corbeille, pas supprimé)
    await db.flush()
    log.info("Fichier envoyé en corbeille", nom=doc.nom, vers=chemin_corbeille)
    return {"corbeille_id": str(entry.id), "nom": doc.nom, "chemin_corbeille": chemin_corbeille}


@router.get("/corbeille", tags=["Corbeille"])
async def lister_corbeille(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(Corbeille).order_by(Corbeille.created_at.desc()))).scalars().all()
    return {"elements": [
        {"id": str(c.id), "nom": c.nom, "chemin_origine": c.chemin_origine,
         "chemin_corbeille": c.chemin_corbeille,
         "date": c.created_at.isoformat() if c.created_at else None}
        for c in rows
    ]}


async def _reindexer(chemin_origine: str, source_id, db: AsyncSession) -> None:
    """Ré-indexe un fichier restauré (média = catalogue léger, sinon pipeline complet)."""
    from services.folder_watcher import MEDIA_EXTENSIONS
    service = _extraction_service()
    ext = Path(chemin_origine).suffix.lstrip(".").lower()

    if chemin_origine.startswith("smb://"):
        hote, partage, rel = _parse_smb(chemin_origine)
        src = await db.get(Source, source_id) if source_id else await _source_smb(db, hote)
        ident, secret, dom = _creds(src)
        if ext in MEDIA_EXTENSIONS:
            # taille via attributs SMB (sinon 0)
            await service.catalogue_media(chemin=chemin_origine, nom=Path(rel).name, taille=0, source="watch", db=db)
            return
        tmp = await smb_service.fetch_to_temp(hote, partage, rel, ident, secret, dom)
        try:
            doc_id = await service.process_file(Path(tmp), source="watch", db=db)
            d = await db.get(Document, uuid.UUID(doc_id))
            if d:
                d.chemin = chemin_origine
                d.nom = Path(rel).name
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
    else:
        p = Path(chemin_origine)
        if ext in MEDIA_EXTENSIONS:
            await service.catalogue_media(chemin=str(p), nom=p.name, taille=p.stat().st_size if p.exists() else 0, source="watch", db=db)
        else:
            await service.process_file(p, source="watch", db=db)


@router.post("/corbeille/{corbeille_id}/restaurer", tags=["Corbeille"])
async def restaurer(corbeille_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Remet le fichier à son emplacement d'origine et le ré-indexe (annulation)."""
    try:
        entry = await db.get(Corbeille, uuid.UUID(corbeille_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")
    if not entry:
        raise HTTPException(status_code=404, detail="Élément de corbeille introuvable")

    if entry.chemin_corbeille.startswith("smb://"):
        hote, partage, rel_cb = _parse_smb(entry.chemin_corbeille)
        _, _, rel_orig = _parse_smb(entry.chemin_origine)
        src = await db.get(Source, entry.source_id) if entry.source_id else await _source_smb(db, hote)
        ident, secret, dom = _creds(src)
        try:
            await smb_service.move_file(hote, partage, rel_cb, rel_orig, ident, secret, dom)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Restauration SMB impossible : {exc}")
    else:
        src_p, dst_p = Path(entry.chemin_corbeille), Path(entry.chemin_origine)
        if not src_p.exists():
            raise HTTPException(status_code=404, detail="Fichier absent de la corbeille")
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_p), str(dst_p))

    # Ré-indexer le fichier restauré (best-effort) + retirer le journal
    try:
        await _reindexer(entry.chemin_origine, entry.source_id, db)
    except Exception as exc:
        log.warning("Ré-indexation après restauration échouée", erreur=str(exc))
    await db.delete(entry)
    await db.flush()
    log.info("Fichier restauré depuis la corbeille", nom=entry.nom, vers=entry.chemin_origine)
    return {"nom": entry.nom, "chemin_origine": entry.chemin_origine}
