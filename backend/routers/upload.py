"""
Router Upload — POST /api/upload
=================================
Gère l'upload de fichiers via multipart/form-data.
Supporte : fichiers individuels, dossiers (webkitdirectory), ZIP.
"""

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

from logger import get_logger

log = get_logger(__name__)
router = APIRouter()


@router.post("/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    """
    Upload un ou plusieurs fichiers.
    TODO Phase 1 : sauvegarder dans storage/uploads/, déclencher extraction.
    """
    log.info("Upload reçu", nb_fichiers=len(files))
    # TODO Phase 1
    return JSONResponse({"message": "TODO Phase 1", "nb_fichiers": len(files)})


@router.post("/upload/zip")
async def upload_zip(file: UploadFile = File(...)):
    """
    Upload un ZIP → extraction automatique de chaque fichier.
    TODO Phase 1
    """
    log.info("Upload ZIP reçu", nom=file.filename)
    # TODO Phase 1
    return JSONResponse({"message": "TODO Phase 1"})
