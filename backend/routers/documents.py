"""
Router Documents — GET/DELETE/PATCH /api/documents
====================================================
CRUD sur les documents indexés.

Endpoints :
  GET    /documents                    → liste paginée avec filtres
  GET    /documents/stats              → statistiques globales (totaux, statuts, catégories)
  GET    /documents/{id}               → détail complet
  GET    /documents/{id}/text          → texte extrait brut
  GET    /documents/{id}/metadata      → métadonnées IA
  PATCH  /documents/{id}/metadata      → mettre à jour tags/catégorie
  GET    /documents/{id}/versions      → historique des versions
  GET    /documents/{id}/jobs          → jobs associés
  DELETE /documents/{id}               → supprimer de l'index
  POST   /documents/purge-duplicates   → supprimer les doublons (même hash ou même chemin)
"""

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.background import BackgroundTask

from database import get_db
from logger import get_logger
from models.document import Document
from models.job import Job
from models.metadata import MetadonneeIA
from models.version import Version

log = get_logger(__name__)


class MetadataUpdate(BaseModel):
    """Champs éditables des métadonnées IA."""
    tags: list[str] | None = None
    categorie: str | None = None
    sous_categorie: str | None = None
    resume: str | None = None
    niveau_confidentialite: str | None = None
    mots_cles: list[str] | None = None
router = APIRouter()


def _doc_to_dict(doc: Document) -> dict:
    """Sérialise un Document en dict JSON-compatible."""
    from services.file_access import chemin_affichage
    return {
        "id": str(doc.id),
        "nom": doc.nom,
        "chemin": doc.chemin,
        "chemin_copie": chemin_affichage(doc.chemin or ""),  # forme UNC pour l'explorateur
        "extension": doc.extension,
        "type_mime": doc.type_mime,
        "taille_octets": doc.taille_octets,
        "statut": doc.statut,
        "source": doc.source,
        "hash_sha256": doc.hash_sha256,
        "date_import": doc.date_import.isoformat() if doc.date_import else None,
        "date_modification_fichier": doc.date_modification_fichier.isoformat() if doc.date_modification_fichier else None,
        "date_derniere_extraction": doc.date_derniere_extraction.isoformat() if doc.date_derniere_extraction else None,
        "erreur": doc.erreur,
        "tags": (doc.metadonnees_ia.tags or []) if doc.metadonnees_ia else [],
    }


def _meta_to_dict(meta: MetadonneeIA) -> dict:
    """Sérialise MetadonneeIA en dict."""
    return {
        "id": str(meta.id),
        "categorie": meta.categorie,
        "sous_categorie": meta.sous_categorie,
        "tags": meta.tags or [],
        "resume": meta.resume,
        "langue": meta.langue,
        "entites": meta.entites or {},
        "mots_cles": meta.mots_cles or [],
        "niveau_confidentialite": meta.niveau_confidentialite,
        "modele_utilise": meta.modele_utilise,
        "created_at": meta.created_at.isoformat() if meta.created_at else None,
    }


@router.get("/documents")
async def list_documents(
    page: int = Query(default=1, ge=1, description="Numéro de page"),
    page_size: int = Query(default=20, ge=1, le=100, description="Documents par page"),
    statut: str | None = Query(default=None, description="Filtrer par statut (pending|extracted|enriched|error)"),
    extension: str | None = Query(default=None, description="Filtrer par extension (pdf, docx...)"),
    source: str | None = Query(default=None, description="Filtrer par source (watch|upload|drag_drop)"),
    q: str | None = Query(default=None, description="Recherche par nom de fichier"),
    tag: str | None = Query(default=None, description="Filtrer par tag (ex: OFFRE_MASSON)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Liste les documents indexés avec pagination et filtres optionnels.
    """
    stmt = select(Document).options(selectinload(Document.metadonnees_ia))

    if statut:
        stmt = stmt.where(Document.statut == statut)
    if extension:
        stmt = stmt.where(Document.extension == extension.lstrip(".").lower())
    if source:
        stmt = stmt.where(Document.source == source)
    if q:
        stmt = stmt.where(Document.nom.ilike(f"%{q}%"))
    if tag:
        stmt = stmt.join(MetadonneeIA).where(MetadonneeIA.tags.contains([tag]))

    # Total
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Pagination
    offset = (page - 1) * page_size
    stmt = stmt.order_by(Document.date_import.desc()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    docs = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "documents": [_doc_to_dict(d) for d in docs],
    }


@router.get("/documents/stats")
async def get_documents_stats(db: AsyncSession = Depends(get_db)):
    """
    Retourne des statistiques globales sur les documents indexés :
    - Total par statut
    - Taille totale
    - Top 10 catégories
    """
    from services.ged_service import GEDService
    service = GEDService()
    return await service.get_stats(db)


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retourne le détail complet d'un document (avec métadonnées IA si disponibles)."""
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de document invalide")

    stmt = (
        select(Document)
        .where(Document.id == doc_uuid)
        .options(selectinload(Document.metadonnees_ia))
    )
    result = await db.execute(stmt)
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Document non trouvé")

    data = _doc_to_dict(doc)
    data["metadonnees_ia"] = _meta_to_dict(doc.metadonnees_ia) if doc.metadonnees_ia else None
    return data


@router.get("/documents/{document_id}/file")
async def get_document_file(
    document_id: str,
    download: bool = Query(default=False, description="true = téléchargement, false = aperçu inline"),
    db: AsyncSession = Depends(get_db),
):
    """
    Sert le fichier original d'un document (aperçu inline ou téléchargement).
    Gère les chemins locaux ET SMB (téléchargé à la volée depuis le NAS).
    """
    from services.file_access import resolve_to_local

    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de document invalide")

    doc = (await db.execute(select(Document).where(Document.id == doc_uuid))).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document non trouvé")

    try:
        local, temporaire = await resolve_to_local(doc, db)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Mime fiable pour l'aperçu : Tika stocke souvent octet-stream → on devine sur l'extension
    media_type = doc.type_mime
    if not media_type or media_type == "application/octet-stream":
        import mimetypes
        media_type = mimetypes.guess_type(doc.nom or "")[0] or "application/octet-stream"

    # Nettoyage du fichier temporaire (cas SMB) une fois l'envoi terminé
    cleanup = BackgroundTask(os.unlink, local) if temporaire else None
    disposition = "attachment" if download else "inline"
    return FileResponse(
        local,
        media_type=media_type,
        filename=doc.nom,
        content_disposition_type=disposition,
        background=cleanup,
    )


@router.get("/documents/{document_id}/text")
async def get_document_text(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retourne le texte brut extrait d'un document."""
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de document invalide")

    result = await db.execute(
        select(Document.texte_extrait, Document.nom).where(Document.id == doc_uuid)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Document non trouvé")

    texte, nom = row
    return {
        "document_id": document_id,
        "nom": nom,
        "texte": texte or "",
        "nb_caracteres": len(texte) if texte else 0,
    }


@router.get("/documents/{document_id}/metadata")
async def get_document_metadata(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retourne les métadonnées IA d'un document."""
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de document invalide")

    result = await db.execute(
        select(MetadonneeIA).where(MetadonneeIA.document_id == doc_uuid)
    )
    meta = result.scalar_one_or_none()

    if not meta:
        raise HTTPException(status_code=404, detail="Métadonnées IA non disponibles pour ce document")

    return _meta_to_dict(meta)


@router.patch("/documents/{document_id}/metadata")
async def update_document_metadata(
    document_id: str,
    data: MetadataUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Met à jour les métadonnées IA d'un document (tags, catégorie, résumé…).
    Seuls les champs fournis sont modifiés (null = non modifié).
    """
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de document invalide")

    result = await db.execute(
        select(MetadonneeIA).where(MetadonneeIA.document_id == doc_uuid)
    )
    meta = result.scalar_one_or_none()

    if not meta:
        raise HTTPException(status_code=404, detail="Métadonnées IA non disponibles pour ce document")

    if data.tags is not None:
        meta.tags = data.tags
    if data.categorie is not None:
        meta.categorie = data.categorie
    if data.sous_categorie is not None:
        meta.sous_categorie = data.sous_categorie
    if data.resume is not None:
        meta.resume = data.resume
    if data.niveau_confidentialite is not None:
        meta.niveau_confidentialite = data.niveau_confidentialite
    if data.mots_cles is not None:
        meta.mots_cles = data.mots_cles

    await db.flush()
    log.info("Métadonnées mises à jour", document_id=document_id)
    return _meta_to_dict(meta)


@router.get("/documents/{document_id}/versions")
async def get_document_versions(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retourne l'historique des versions d'un document."""
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de document invalide")

    # Vérifier que le document existe
    doc_exists = await db.execute(select(Document.id).where(Document.id == doc_uuid))
    if not doc_exists.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Document non trouvé")

    result = await db.execute(
        select(Version)
        .where(Version.document_id == doc_uuid)
        .order_by(Version.numero_version.desc())
    )
    versions = result.scalars().all()

    return {
        "document_id": document_id,
        "versions": [
            {
                "id": str(v.id),
                "numero_version": v.numero_version,
                "hash_sha256": v.hash_sha256,
                "taille_octets": v.taille_octets,
                "date_detection": v.date_detection.isoformat() if v.date_detection else None,
                "diff_resume": v.diff_resume,
            }
            for v in versions
        ],
    }


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Supprime un document de l'index (DB uniquement, le fichier source n'est pas supprimé).
    Les embeddings et métadonnées associés sont supprimés en cascade.
    """
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de document invalide")

    result = await db.execute(select(Document).where(Document.id == doc_uuid))
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Document non trouvé")

    nom = doc.nom
    await db.delete(doc)
    await db.flush()

    log.info("Document supprimé de l'index", doc_id=document_id, nom=nom)
    return {"message": f"Document '{nom}' supprimé de l'index", "document_id": document_id}


@router.get("/documents/{document_id}/jobs")
async def get_document_jobs(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retourne les jobs associés à un document (utile pour suivre l'avancement)."""
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de document invalide")

    result = await db.execute(
        select(Job)
        .where(Job.document_id == doc_uuid)
        .order_by(Job.created_at.desc())
    )
    jobs = result.scalars().all()

    return {
        "document_id": document_id,
        "jobs": [
            {
                "id": str(j.id),
                "type": j.type,
                "statut": j.statut,
                "erreur": j.erreur,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            }
            for j in jobs
        ],
    }


# Priorité de conservation par statut (plus grand = meilleur)
_STATUT_PRIO = {"enriched": 3, "extracted": 2, "pending": 1, "error": 0}


def _meilleur(docs: list[Document]) -> Document:
    """Retourne le document à conserver parmi un groupe de doublons."""
    return max(
        docs,
        key=lambda d: (_STATUT_PRIO.get(d.statut, 0), d.created_at or 0),
    )


@router.post("/documents/purge-duplicates")
async def purge_duplicates(db: AsyncSession = Depends(get_db)):
    """
    Supprime les doublons de l'index :
    - même hash SHA256 (contenu identique, plusieurs entrées)
    - même chemin absolu (fichier re-scanné plusieurs fois sans commit intermédiaire)
    Conserve le document le mieux enrichi (enriched > extracted > pending > error),
    puis le plus récent en cas d'égalité.
    """
    supprimes = 0

    # 1. Doublons par hash_sha256
    hashes_dup = (
        await db.execute(
            select(Document.hash_sha256)
            .group_by(Document.hash_sha256)
            .having(func.count() > 1)
        )
    ).scalars().all()

    for h in hashes_dup:
        result = await db.execute(select(Document).where(Document.hash_sha256 == h))
        docs = result.scalars().all()
        garder = _meilleur(docs)
        for d in docs:
            if d.id != garder.id:
                await db.delete(d)
                supprimes += 1

    # 2. Doublons par chemin absolu (scans concurrents)
    chemins_dup = (
        await db.execute(
            select(Document.chemin)
            .group_by(Document.chemin)
            .having(func.count() > 1)
        )
    ).scalars().all()

    for chemin in chemins_dup:
        result = await db.execute(select(Document).where(Document.chemin == chemin))
        docs = result.scalars().all()
        garder = _meilleur(docs)
        for d in docs:
            if d.id != garder.id:
                await db.delete(d)
                supprimes += 1

    await db.flush()
    log.info("Purge doublons terminée", nb_supprimes=supprimes)
    return {"supprimes": supprimes, "message": f"{supprimes} doublon(s) supprimé(s)"}
