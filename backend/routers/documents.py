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
    from utils.file_utils import creation_date_from_tika
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
        "date_creation": creation_date_from_tika(doc.tika_metadata),
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
    categorie: str | None = Query(default=None, description="Filtrer par catégorie IA ('__sans__' = non classé)"),
    texte: bool | None = Query(default=None, description="true = uniquement les docs avec texte extrait (exclut les médias catalogués)"),
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
    if categorie is not None:
        if categorie == "__sans__":
            stmt = stmt.outerjoin(MetadonneeIA).where(MetadonneeIA.categorie.is_(None))
        else:
            stmt = stmt.join(MetadonneeIA).where(MetadonneeIA.categorie == categorie)
    if texte:
        # Uniquement les documents porteurs de texte (exclut les médias catalogués)
        stmt = stmt.where(Document.texte_extrait.isnot(None)).where(Document.texte_extrait != "")

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


@router.get("/documents/groups")
async def document_groups(
    by: str = Query(description="Critère de regroupement : extension | categorie | tag"),
    db: AsyncSession = Depends(get_db),
):
    """
    Compte les documents par groupe (pour la vue groupée de la GED).
    Retourne [{valeur, nb}] trié par effectif décroissant.
    `valeur` peut être null pour la catégorie (= documents non classés).
    """
    if by not in ("extension", "categorie", "tag"):
        raise HTTPException(status_code=422, detail="by doit être extension | categorie | tag")

    if by == "extension":
        rows = (await db.execute(
            select(Document.extension, func.count())
            .group_by(Document.extension)
            .order_by(func.count().desc())
        )).all()
        groupes = [{"valeur": e, "nb": n} for e, n in rows]

    elif by == "categorie":
        rows = (await db.execute(
            select(MetadonneeIA.categorie, func.count())
            .select_from(Document)
            .join(MetadonneeIA, MetadonneeIA.document_id == Document.id, isouter=True)
            .group_by(MetadonneeIA.categorie)
            .order_by(func.count().desc())
        )).all()
        groupes = [{"valeur": c, "nb": n} for c, n in rows]  # c == None → non classé

    else:  # tag — un document peut porter plusieurs tags
        tag_col = func.unnest(MetadonneeIA.tags).label("tag")
        sub = select(tag_col).select_from(MetadonneeIA).subquery()
        rows = (await db.execute(
            select(sub.c.tag, func.count()).group_by(sub.c.tag).order_by(func.count().desc())
        )).all()
        groupes = [{"valeur": t, "nb": n} for t, n in rows]

    return {"by": by, "nb_groupes": len(groupes), "groupes": groupes}


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


@router.post("/documents/{document_id}/enrich")
async def relancer_enrichissement(
    document_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Relance l'enrichissement IA d'un document à partir de son **texte déjà extrait**
    (résumé, catégorie, tags, entités) — sans re-télécharger ni re-extraire.

    L'analyse tourne désormais comme **tâche durable** (worker de jobs) : l'endpoint valide
    puis renvoie immédiatement un `job_id` à suivre via `GET /api/jobs/{id}` (l'action
    survit au changement de page / à la fermeture du navigateur).
    """
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de document invalide")

    doc = (await db.execute(select(Document).where(Document.id == doc_uuid))).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document non trouvé")
    if not (doc.texte_extrait or "").strip():
        raise HTTPException(status_code=422, detail="Aucun texte à analyser (média ou extraction vide)")

    # Garde anti-double-clic : une analyse déjà en attente/cours pour ce doc → on ne relance pas.
    encours = (await db.execute(
        select(Job).where(
            Job.type.in_(("enrich", "analyze")),
            Job.document_id == doc.id,
            Job.statut.in_(("pending", "running")),
        )
    )).scalars().first()
    if encours:
        return {"job_id": str(encours.id), "statut": encours.statut, "deja": True}

    from services import job_worker
    job_id = await job_worker.enqueue(db, "enrich", {"document_id": document_id}, document_id=doc.id)
    await db.commit()
    log.info("Enrichissement mis en file (job durable)", doc_id=document_id, job_id=job_id)
    return {"job_id": job_id, "statut": "pending", "deja": False}


@router.post("/documents/reenrich-batch")
async def relancer_enrichissement_lot(
    limit: int = Query(default=2000, ge=1, le=10000, description="Plafond de documents traités"),
    db: AsyncSession = Depends(get_db),
):
    """
    Relance l'enrichissement IA (résumé, catégorie, tags) en **lot** sur tous les documents
    **extraits mais non enrichis** (statut `extracted` ou `error`) possédant du texte — un job
    `enrich` durable par document. N'inclut pas les médias catalogués (pas de texte à analyser).
    """
    from services import job_worker

    stmt = (
        select(Document)
        .where(Document.statut.in_(("extracted", "error")))
        .where(func.length(func.coalesce(Document.texte_extrait, "")) > 0)
        .limit(limit)
    )
    docs = (await db.execute(stmt)).scalars().all()
    for doc in docs:
        await job_worker.enqueue(db, "enrich", {"document_id": str(doc.id)}, document_id=doc.id)
    await db.commit()
    enqueued = len(docs)
    log.info("Ré-enrichissement en lot mis en file", enqueued=enqueued)
    return {"enqueued": enqueued, "message": f"{enqueued} document(s) remis en analyse IA (tâches durables)"}


@router.post("/documents/{document_id}/analyze")
async def analyser_contenu(document_id: str, db: AsyncSession = Depends(get_db)):
    """
    Analyse le **contenu** d'un document (média catalogué ou doc au texte vide), **local ou
    SMB**, en **tâche durable** : fetch temporaire si distant, **mise à jour du doc existant**
    (zéro doublon), tmp supprimé. Renvoie un `job_id` à suivre via `GET /api/jobs/{id}`.
    """
    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de document invalide")
    doc = (await db.execute(select(Document).where(Document.id == doc_uuid))).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document non trouvé")

    # Garde anti-double-clic : analyse déjà en attente/cours pour ce doc → pas de relance.
    encours = (await db.execute(
        select(Job).where(
            Job.type.in_(("enrich", "analyze")),
            Job.document_id == doc.id,
            Job.statut.in_(("pending", "running")),
        )
    )).scalars().first()
    if encours:
        return {"job_id": str(encours.id), "statut": encours.statut, "deja": True}

    from services import job_worker
    job_id = await job_worker.enqueue(db, "analyze", {"document_id": document_id}, document_id=doc.id)
    await db.commit()
    log.info("Analyse contenu mise en file (job durable)", doc_id=document_id, job_id=job_id)
    return {"job_id": job_id, "statut": "pending", "deja": False}


def _scope_filter(scope: str):
    """Filtre SQL des candidats à l'analyse de contenu selon le scope."""
    vide = func.length(func.coalesce(Document.texte_extrait, "")) == 0
    if scope == "media":
        return Document.statut == "catalogued"
    if scope == "empty":
        return (Document.statut.in_(("extracted", "error"))) & vide
    # all : médias catalogués + docs extraits/erreur sans texte
    return (Document.statut == "catalogued") | ((Document.statut.in_(("extracted", "error"))) & vide)


@router.post("/documents/analyze-batch")
async def analyser_contenu_lot(
    scope: str = Query(default="empty", pattern="^(media|empty|all)$"),
    limit: int = Query(default=1000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
):
    """
    Met en file un job `analyze` durable par document **sans contenu exploitable**, selon
    `scope` : `empty` (extraits/erreur au texte vide), `media` (médias catalogués), `all`.
    """
    from services import job_worker

    # Garde anti-empilement : ne pas ré-enfiler un doc qui a déjà un job `analyze` en attente/cours
    # (sinon cliquer plusieurs fois lance des centaines de fetch NAS redondants).
    deja_en_file = select(Job.document_id).where(
        Job.type == "analyze",
        Job.statut.in_(("pending", "running")),
        Job.document_id.isnot(None),
    )
    stmt = (
        select(Document)
        .where(_scope_filter(scope))
        .where(~Document.id.in_(deja_en_file))
        .limit(limit)
    )
    docs = (await db.execute(stmt)).scalars().all()
    for doc in docs:
        await job_worker.enqueue(db, "analyze", {"document_id": str(doc.id)}, document_id=doc.id)
    await db.commit()
    enqueued = len(docs)
    log.info("Analyse contenu en lot mise en file", scope=scope, enqueued=enqueued)
    msg = (f"{enqueued} document(s) mis en analyse de contenu" if enqueued
           else "Aucun nouveau document à analyser (déjà en file d'attente)")
    return {"enqueued": enqueued, "message": msg}


@router.get("/documents/maintenance/counts")
async def compteurs_maintenance(db: AsyncSession = Depends(get_db)):
    """Compteurs réels pour les actions de maintenance (boutons Paramètres)."""
    avec_texte = func.length(func.coalesce(Document.texte_extrait, "")) > 0
    sans_texte = func.length(func.coalesce(Document.texte_extrait, "")) == 0

    async def _count(cond):
        return (await db.execute(select(func.count()).select_from(Document).where(cond))).scalar() or 0

    return {
        "reenrich": await _count((Document.statut.in_(("extracted", "error"))) & avec_texte),
        "sans_texte": await _count((Document.statut.in_(("extracted", "error"))) & sans_texte),
        "medias": await _count(Document.statut == "catalogued"),
    }


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
