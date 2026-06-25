"""
Router Upload — POST /api/upload
=================================
Gère l'upload de fichiers via multipart/form-data.
Supporte : fichiers individuels, dossiers (webkitdirectory), ZIP.

Flux :
  1. Sauvegarde le fichier dans storage/uploads/
  2. Crée un job en DB
  3. Lance l'extraction en tâche de fond (BackgroundTasks)
"""

import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from logger import get_logger
from models.job import Job
from services.embedding_service import EmbeddingService
from services.extraction import ExtractionService
from services.ollama_service import OllamaService
from services.tika_service import TikaService

log = get_logger(__name__)
settings = get_settings()
router = APIRouter()

# Extensions acceptées
EXTENSIONS_ACCEPTEES = {"pdf", "docx", "pptx", "ppsx", "xlsx", "zip", "odt", "ods", "odp"}


def _get_extraction_service() -> ExtractionService:
    """Instancie le pipeline d'extraction avec ses dépendances."""
    tika = TikaService()
    ollama = OllamaService()
    embedding = EmbeddingService(ollama)
    return ExtractionService(tika, ollama, embedding)


async def _sauvegarder_fichier(upload: UploadFile, dest_dir: Path) -> Path:
    """Sauvegarde un UploadFile sur le disque. Retourne le chemin final."""
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Éviter les collisions de noms
    nom_safe = Path(upload.filename).name  # Ignorer les chemins relatifs
    dest = dest_dir / nom_safe
    if dest.exists():
        stem = Path(nom_safe).stem
        suffix = Path(nom_safe).suffix
        dest = dest_dir / f"{stem}_{uuid.uuid4().hex[:8]}{suffix}"

    async with aiofiles.open(dest, "wb") as f:
        while chunk := await upload.read(65536):
            await f.write(chunk)

    return dest


async def _lancer_extraction_background(file_path: Path, source: str, job_id: str, folder_tag: str | None = None) -> None:
    """
    Tâche de fond : extraction complète d'un fichier.
    Utilise une nouvelle session DB (les sessions FastAPI ne survivent pas aux background tasks).
    """
    from database import AsyncSessionLocal

    service = _get_extraction_service()
    async with AsyncSessionLocal() as db:
        try:
            # Mettre le job en running
            from sqlalchemy import select
            result = await db.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
            job = result.scalar_one_or_none()
            if job:
                from datetime import datetime, timezone
                job.statut = "running"
                job.started_at = datetime.now(tz=timezone.utc)
                await db.flush()

            # Traitement selon le type de fichier
            if file_path.suffix.lower() == ".zip":
                doc_ids = await service.process_zip(file_path, source=source, db=db, folder_tag=folder_tag)
                resultat = {"doc_ids": doc_ids, "nb_documents": len(doc_ids)}
            else:
                doc_id = await service.process_file(file_path, source=source, db=db, folder_tag=folder_tag)
                resultat = {"doc_id": doc_id}

            if job:
                from datetime import datetime, timezone
                job.statut = "completed"
                job.completed_at = datetime.now(tz=timezone.utc)
                job.resultat = resultat

            await db.commit()
            log.info("Extraction background terminée", job_id=job_id, resultat=resultat)

        except Exception as e:
            await db.rollback()
            log.error("Erreur extraction background", job_id=job_id, erreur=str(e), exc_info=True)
            # Tenter de marquer le job comme failed
            try:
                async with AsyncSessionLocal() as db2:
                    from sqlalchemy import select
                    from datetime import datetime, timezone
                    result = await db2.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
                    job = result.scalar_one_or_none()
                    if job:
                        job.statut = "failed"
                        job.erreur = str(e)
                        job.completed_at = datetime.now(tz=timezone.utc)
                        await db2.commit()
            except Exception:
                pass


@router.post("/upload")
async def upload_files(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    folder_tag: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload un ou plusieurs fichiers (PDF, DOCX, PPTX, PPSX, XLSX, ZIP).
    Déclenche l'extraction en arrière-plan.
    Retourne immédiatement les IDs de jobs pour suivi.
    """
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier fourni")

    uploads_dir = Path(settings.storage_uploads)
    jobs_crees = []

    for upload in files:
        # Vérifier l'extension
        ext = Path(upload.filename or "").suffix.lstrip(".").lower()
        if ext not in EXTENSIONS_ACCEPTEES:
            log.warning("Extension refusée", fichier=upload.filename, extension=ext)
            jobs_crees.append({
                "fichier": upload.filename,
                "statut": "rejeté",
                "raison": f"Extension .{ext} non supportée",
            })
            continue

        # Sauvegarder sur le disque
        try:
            file_path = await _sauvegarder_fichier(upload, uploads_dir)
        except Exception as e:
            log.error("Erreur sauvegarde fichier", fichier=upload.filename, erreur=str(e))
            jobs_crees.append({"fichier": upload.filename, "statut": "erreur", "raison": str(e)})
            continue

        # Créer le job en DB
        job = Job(
            type="extraction",
            statut="pending",
            parametres={"fichier": str(file_path), "source": "upload"},
        )
        db.add(job)
        await db.flush()
        job_id = str(job.id)

        # Lancer l'extraction en arrière-plan
        background_tasks.add_task(
            _lancer_extraction_background,
            file_path,
            "upload",
            job_id,
            folder_tag,
        )

        log.info("Upload accepté", fichier=file_path.name, job_id=job_id)
        jobs_crees.append({
            "fichier": upload.filename,
            "job_id": job_id,
            "statut": "en_attente",
        })

    return {"jobs": jobs_crees}


@router.post("/upload/zip")
async def upload_zip(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload un ZIP → extraction automatique de chaque fichier contenu.
    Alias de /upload pour les ZIP, comportement identique.
    """
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Le fichier doit être un ZIP")

    uploads_dir = Path(settings.storage_uploads)

    try:
        file_path = await _sauvegarder_fichier(file, uploads_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur sauvegarde : {e}")

    job = Job(
        type="extraction",
        statut="pending",
        parametres={"fichier": str(file_path), "source": "upload", "type": "zip"},
    )
    db.add(job)
    await db.flush()
    job_id = str(job.id)

    background_tasks.add_task(
        _lancer_extraction_background,
        file_path,
        "upload",
        job_id,
    )

    log.info("Upload ZIP accepté", fichier=file_path.name, job_id=job_id)
    return {"fichier": file.filename, "job_id": job_id, "statut": "en_attente"}
