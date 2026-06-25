"""
Router Doublons — /api/duplicates
==================================
Détection des fichiers en double sur le volume documents + mise en quarantaine
(déplacement vers DOUBLON-MATOTEQUE), avec validation côté UI avant action.

Endpoints :
  GET  /duplicates              → groupes de fichiers en double (scan disque)
  POST /duplicates/quarantine   → déplace les fichiers choisis vers la quarantaine
"""

from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from logger import get_logger
from models.document import Document
from services import duplicate_service

log = get_logger(__name__)
settings = get_settings()
router = APIRouter()


class QuarantineRequest(BaseModel):
    """Liste des chemins absolus à mettre en quarantaine."""
    chemins: list[str] = Field(default_factory=list, min_length=1)


@router.get("/duplicates", tags=["Doublons"])
async def list_duplicates() -> dict:
    """
    Scanne le volume des documents et retourne les groupes de fichiers en double
    (même contenu). Ne modifie rien. Peut prendre quelques secondes selon le volume.
    """
    root = Path(settings.documents_root)
    groups = duplicate_service.find_duplicates(root, settings.duplicates_dirname)
    nb_fichiers = sum(len(g["fichiers"]) for g in groups)
    octets_recuperables = sum(
        g["taille_octets"] * (len(g["fichiers"]) - 1) for g in groups
    )
    return {
        "groupes": groups,
        "nb_groupes": len(groups),
        "nb_fichiers": nb_fichiers,
        "octets_recuperables": octets_recuperables,
        "dossier_quarantaine": settings.duplicates_dirname,
    }


@router.post("/duplicates/quarantine", tags=["Doublons"])
async def quarantine_duplicates(
    body: QuarantineRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Déplace les fichiers sélectionnés vers DOUBLON-MATOTEQUE (jamais de suppression
    définitive) et retire les entrées correspondantes de l'index Matothèque.
    """
    root = Path(settings.documents_root)
    result = duplicate_service.quarantine(body.chemins, root, settings.duplicates_dirname)

    # Nettoie l'index : retire les documents dont le fichier vient d'être déplacé
    index_retires = 0
    for moved in result["deplaces"]:
        chemin = moved["chemin"]
        docs = (
            await db.execute(select(Document).where(Document.chemin == chemin))
        ).scalars().all()
        for doc in docs:
            await db.delete(doc)
            index_retires += 1
    if index_retires:
        await db.flush()

    log.info(
        "Quarantaine doublons terminée",
        deplaces=len(result["deplaces"]),
        erreurs=len(result["erreurs"]),
        index_retires=index_retires,
    )
    return {
        "deplaces": result["deplaces"],
        "erreurs": result["erreurs"],
        "nb_deplaces": len(result["deplaces"]),
        "nb_erreurs": len(result["erreurs"]),
        "index_retires": index_retires,
        "dossier_quarantaine": settings.duplicates_dirname,
    }
