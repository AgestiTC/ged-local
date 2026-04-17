"""
Router Folders — /api/folders
==============================
Gestion des dossiers surveillés et navigation dans le système de fichiers.

Endpoints :
  GET    /folders                  → liste des dossiers surveillés
  POST   /folders                  → ajouter un dossier
  PUT    /folders/{id}             → modifier un dossier
  DELETE /folders/{id}             → retirer un dossier
  POST   /folders/{id}/scan        → forcer un scan immédiat
  GET    /folders/browse?path=...  → naviguer dans le système de fichiers
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from logger import get_logger
from models.document import Document
from models.folder import DossierSurveille
from services.embedding_service import EmbeddingService
from services.extraction import ExtractionService
from services.ollama_service import OllamaService
from services.tika_service import TikaService

log = get_logger(__name__)
settings = get_settings()
router = APIRouter()

# Extensions supportées pour l'indexation
EXTENSIONS_INDEXEES = {"pdf", "docx", "pptx", "ppsx", "xlsx", "odt", "ods", "odp"}


class DossierCreate(BaseModel):
    chemin: str = Field(..., description="Chemin absolu du dossier sur l'hôte")
    nom_affichage: str | None = Field(default=None, description="Nom affiché dans l'interface")
    recursive: bool = Field(default=True, description="Indexer les sous-dossiers")
    extensions_filtrees: list[str] | None = Field(default=None, description="Extensions à indexer (null = toutes)")
    intervalle_scan_secondes: int = Field(default=300, ge=30, description="Intervalle de scan en secondes")


class DossierUpdate(BaseModel):
    nom_affichage: str | None = None
    actif: bool | None = None
    recursive: bool | None = None
    extensions_filtrees: list[str] | None = None
    intervalle_scan_secondes: int | None = Field(default=None, ge=30)


def _dossier_to_dict(d: DossierSurveille) -> dict:
    return {
        "id": str(d.id),
        "chemin": d.chemin,
        "nom_affichage": d.nom_affichage or Path(d.chemin).name,
        "actif": d.actif,
        "recursive": d.recursive,
        "extensions_filtrees": d.extensions_filtrees,
        "intervalle_scan_secondes": d.intervalle_scan_secondes,
        "dernier_scan": d.dernier_scan.isoformat() if d.dernier_scan else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


async def _scanner_dossier(dossier_id: str, chemin: str, recursive: bool, extensions: list[str] | None) -> None:
    """Scan un dossier en arrière-plan et indexe les fichiers non encore présents en DB."""
    from database import AsyncSessionLocal

    tika = TikaService()
    ollama = OllamaService()
    embedding = EmbeddingService(ollama)
    service = ExtractionService(tika, ollama, embedding)

    chemin_path = Path(chemin)
    exts = set(extensions) if extensions else EXTENSIONS_INDEXEES

    if recursive:
        fichiers = [f for f in chemin_path.rglob("*") if f.is_file() and f.suffix.lstrip(".").lower() in exts]
    else:
        fichiers = [f for f in chemin_path.iterdir() if f.is_file() and f.suffix.lstrip(".").lower() in exts]

    log.info("Scan dossier", chemin=chemin, nb_fichiers=len(fichiers))

    for fichier in fichiers:
        async with AsyncSessionLocal() as db:
            # Vérifier si déjà indexé (même chemin) avant de lancer l'extraction
            existing = (await db.execute(
                select(Document).where(Document.chemin == str(fichier.resolve()))
            )).scalar_one_or_none()
            if existing:
                log.debug("Fichier déjà indexé — ignoré", fichier=fichier.name)
                continue
        async with AsyncSessionLocal() as db:
            try:
                await service.process_file(fichier, source="watch", db=db)
                await db.commit()
            except Exception as e:
                log.error("Erreur indexation fichier", fichier=str(fichier), erreur=str(e))

    # Mettre à jour dernier_scan
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(DossierSurveille).where(DossierSurveille.id == uuid.UUID(dossier_id)))
        dossier = result.scalar_one_or_none()
        if dossier:
            dossier.dernier_scan = datetime.now(tz=timezone.utc)
            await db.commit()

    log.info("Scan terminé", chemin=chemin, nb_fichiers_traites=len(fichiers))


@router.get("/folders")
async def list_folders(db: AsyncSession = Depends(get_db)):
    """Liste tous les dossiers surveillés."""
    result = await db.execute(select(DossierSurveille).order_by(DossierSurveille.created_at))
    dossiers = result.scalars().all()
    return {"dossiers": [_dossier_to_dict(d) for d in dossiers]}


@router.post("/folders")
async def add_folder(
    data: DossierCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Ajoute un dossier à surveiller et lance un premier scan."""
    chemin = Path(data.chemin)
    if not chemin.exists() or not chemin.is_dir():
        raise HTTPException(status_code=422, detail=f"Dossier introuvable : {data.chemin}")

    # Vérifier doublon
    result = await db.execute(
        select(DossierSurveille).where(DossierSurveille.chemin == str(chemin.resolve()))
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Ce dossier est déjà surveillé")

    dossier = DossierSurveille(
        chemin=str(chemin.resolve()),
        nom_affichage=data.nom_affichage or chemin.name,
        recursive=data.recursive,
        extensions_filtrees=data.extensions_filtrees,
        intervalle_scan_secondes=data.intervalle_scan_secondes,
    )
    db.add(dossier)
    await db.flush()
    dossier_id = str(dossier.id)

    # Lancer le premier scan en arrière-plan
    background_tasks.add_task(
        _scanner_dossier,
        dossier_id,
        str(chemin.resolve()),
        data.recursive,
        data.extensions_filtrees,
    )

    log.info("Dossier ajouté", chemin=str(chemin.resolve()), id=dossier_id)
    return {**_dossier_to_dict(dossier), "scan": "lancé en arrière-plan"}


@router.put("/folders/{dossier_id}")
async def update_folder(
    dossier_id: str,
    data: DossierUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Modifie la configuration d'un dossier surveillé."""
    try:
        uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")

    result = await db.execute(select(DossierSurveille).where(DossierSurveille.id == uuid.UUID(dossier_id)))
    dossier = result.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=404, detail="Dossier non trouvé")

    if data.nom_affichage is not None:
        dossier.nom_affichage = data.nom_affichage
    if data.actif is not None:
        dossier.actif = data.actif
    if data.recursive is not None:
        dossier.recursive = data.recursive
    if data.extensions_filtrees is not None:
        dossier.extensions_filtrees = data.extensions_filtrees
    if data.intervalle_scan_secondes is not None:
        dossier.intervalle_scan_secondes = data.intervalle_scan_secondes

    await db.flush()
    return _dossier_to_dict(dossier)


@router.delete("/folders/{dossier_id}")
async def remove_folder(
    dossier_id: str,
    supprimer_documents: bool = Query(default=False, description="Supprimer aussi les documents indexés depuis ce dossier"),
    db: AsyncSession = Depends(get_db),
):
    """Retire un dossier de la surveillance (ne supprime pas les fichiers sources)."""
    try:
        uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")

    result = await db.execute(select(DossierSurveille).where(DossierSurveille.id == uuid.UUID(dossier_id)))
    dossier = result.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=404, detail="Dossier non trouvé")

    chemin = dossier.chemin
    nb_supprimes = 0

    if supprimer_documents:
        # Supprimer les documents indexés depuis ce dossier
        result_docs = await db.execute(select(Document).where(Document.chemin.like(f"{chemin}%")))
        docs = result_docs.scalars().all()
        for doc in docs:
            await db.delete(doc)
        nb_supprimes = len(docs)

    await db.delete(dossier)
    await db.flush()

    log.info("Dossier retiré", chemin=chemin, docs_supprimes=nb_supprimes)
    return {
        "message": f"Dossier '{chemin}' retiré de la surveillance",
        "documents_supprimes": nb_supprimes,
    }


@router.post("/folders/{dossier_id}/scan")
async def force_scan(
    dossier_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Force un scan immédiat du dossier."""
    try:
        uuid.UUID(dossier_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")

    result = await db.execute(select(DossierSurveille).where(DossierSurveille.id == uuid.UUID(dossier_id)))
    dossier = result.scalar_one_or_none()
    if not dossier:
        raise HTTPException(status_code=404, detail="Dossier non trouvé")

    if not dossier.actif:
        raise HTTPException(status_code=422, detail="Ce dossier est désactivé")

    background_tasks.add_task(
        _scanner_dossier,
        dossier_id,
        dossier.chemin,
        dossier.recursive,
        dossier.extensions_filtrees,
    )

    return {"message": f"Scan lancé pour '{dossier.chemin}'", "dossier_id": dossier_id}


@router.get("/folders/browse")
async def browse_filesystem(
    path: str = Query(default="/", description="Chemin à explorer"),
):
    """
    Navigue dans le système de fichiers de l'hôte.
    Retourne la liste des sous-dossiers et fichiers à la racine donnée.
    Utilisé par l'interface pour choisir un dossier à surveiller.
    """
    # Dans le conteneur Docker, les documents sont montés dans /app/documents
    # En dev local, on navigue depuis le chemin demandé
    chemin = Path(path)

    if not chemin.exists():
        raise HTTPException(status_code=404, detail=f"Chemin introuvable : {path}")
    if not chemin.is_dir():
        raise HTTPException(status_code=422, detail=f"Ce chemin n'est pas un dossier : {path}")

    try:
        entrees = list(chemin.iterdir())
    except PermissionError:
        raise HTTPException(status_code=403, detail="Accès refusé à ce dossier")

    dossiers = sorted(
        [{"nom": e.name, "chemin": str(e), "type": "dossier"} for e in entrees if e.is_dir()],
        key=lambda x: x["nom"].lower(),
    )
    fichiers = sorted(
        [
            {
                "nom": e.name,
                "chemin": str(e),
                "type": "fichier",
                "extension": e.suffix.lstrip(".").lower(),
                "taille_octets": e.stat().st_size,
            }
            for e in entrees
            if e.is_file() and e.suffix.lstrip(".").lower() in EXTENSIONS_INDEXEES
        ],
        key=lambda x: x["nom"].lower(),
    )

    return {
        "chemin_actuel": str(chemin),
        "chemin_parent": str(chemin.parent) if chemin.parent != chemin else None,
        "dossiers": dossiers,
        "fichiers": fichiers,
    }
