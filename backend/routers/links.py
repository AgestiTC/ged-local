"""
Router Liens documentaires — /api/links
=======================================
Détecte et gère les liens entre documents (BC ↔ facture, devis ↔ commande…),
partageant une **référence** commune. Flux : `scan` (propose) → l'utilisateur
**valide** ou **rejette** → les liens validés s'affichent sur la fiche document.

Endpoints :
  POST   /links/scan              → détecte les paires candidates, enregistre les nouvelles (statut suggéré)
  GET    /links                   → liste les liens (filtre par statut), enrichis des noms de documents
  GET    /links/document/{id}     → liens validés touchant un document (pour la fiche)
  POST   /links                   → crée un lien MANUEL (validé d'office)
  POST   /links/{id}/validate     → valide une suggestion
  POST   /links/{id}/reject       → rejette une suggestion (ne sera plus reproposée)
  DELETE /links/{id}              → supprime un lien
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.document import Document
from models.document_link import DocumentLink
from services import link_service

log = get_logger(__name__)
router = APIRouter()

# Plafond de documents chargés pour un scan (borne le coût mémoire/CPU du texte extrait).
_SCAN_CAP = 5000


class ScanRequest(BaseModel):
    prefixe: str | None = None  # limite le scan à un dossier (préfixe de chemin)


class ManualLinkRequest(BaseModel):
    source_document_id: str
    cible_document_id: str
    type_lien: str = "manuel"


def _lien_dto(lien: DocumentLink, docs: dict[uuid.UUID, Document]) -> dict:
    """Sérialise un lien en injectant nom/chemin des deux documents (peuvent avoir disparu)."""
    src = docs.get(lien.source_document_id)
    cible = docs.get(lien.cible_document_id)
    def _doc(d: Document | None, did: uuid.UUID) -> dict:
        return {
            "id": str(did),
            "nom": d.nom if d else "(document supprimé)",
            "chemin": d.chemin if d else None,
            "existe": d is not None,
        }
    return {
        "id": str(lien.id),
        "type_lien": lien.type_lien,
        "reference": lien.reference,
        "score": lien.score,
        "statut": lien.statut,
        "origine": lien.origine,
        "source": _doc(src, lien.source_document_id),
        "cible": _doc(cible, lien.cible_document_id),
    }


async def _charger_docs(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, Document]:
    if not ids:
        return {}
    rows = (await db.execute(select(Document).where(Document.id.in_(ids)))).scalars().all()
    return {d.id: d for d in rows}


@router.post("/links/scan", tags=["Liens"])
async def scan_links(body: ScanRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Analyse le texte des documents indexés, propose les paires partageant une référence,
    et **enregistre les nouvelles** au statut `suggere`. N'écrase jamais un lien existant
    (une paire déjà validée/rejetée est ignorée → une décision n'est jamais reproposée).
    """
    stmt = select(
        Document.id, Document.nom, Document.texte_extrait
    ).where(Document.texte_extrait.isnot(None))
    if body.prefixe and body.prefixe.strip():
        like = body.prefixe.strip().rstrip("/") + "%"
        stmt = stmt.where(Document.chemin.like(like))
    stmt = stmt.limit(_SCAN_CAP)
    rows = (await db.execute(stmt)).all()
    docs = [{"id": r.id, "nom": r.nom, "texte": r.texte_extrait} for r in rows]

    suggestions = link_service.find_link_suggestions(docs)

    # Paires déjà connues (tout statut) → à ne pas re-proposer.
    existants = (await db.execute(select(
        DocumentLink.source_document_id, DocumentLink.cible_document_id
    ))).all()
    connus = {(str(s), str(c)) for s, c in existants}

    nouvelles = 0
    for sg in suggestions:
        if (sg["source_document_id"], sg["cible_document_id"]) in connus:
            continue
        db.add(DocumentLink(
            source_document_id=uuid.UUID(sg["source_document_id"]),
            cible_document_id=uuid.UUID(sg["cible_document_id"]),
            type_lien=sg["type_lien"], reference=sg["reference"],
            score=sg["score"], statut="suggere", origine="auto",
        ))
        connus.add((sg["source_document_id"], sg["cible_document_id"]))
        nouvelles += 1

    if nouvelles:
        await db.flush()
    log.info("Scan liens terminé", documents=len(docs), suggestions=len(suggestions), nouvelles=nouvelles)
    return {"documents_analyses": len(docs), "suggestions_trouvees": len(suggestions),
            "nouvelles": nouvelles}


@router.get("/links", tags=["Liens"])
async def list_links(
    statut: str | None = Query(default=None, description="suggere | valide | rejete (défaut : tous)"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Liste les liens, du plus fiable au moins fiable, enrichis des noms de documents."""
    stmt = select(DocumentLink)
    if statut:
        stmt = stmt.where(DocumentLink.statut == statut)
    stmt = stmt.order_by(DocumentLink.score.desc(), DocumentLink.created_at.desc())
    liens = (await db.execute(stmt)).scalars().all()

    ids = {l.source_document_id for l in liens} | {l.cible_document_id for l in liens}
    docs = await _charger_docs(db, ids)
    return {"liens": [_lien_dto(l, docs) for l in liens], "nb": len(liens)}


@router.get("/links/document/{document_id}", tags=["Liens"])
async def links_of_document(document_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Liens **validés** touchant un document (pour la fiche document en GED)."""
    try:
        did = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Identifiant invalide")
    stmt = select(DocumentLink).where(
        DocumentLink.statut == "valide",
        or_(DocumentLink.source_document_id == did, DocumentLink.cible_document_id == did),
    ).order_by(DocumentLink.score.desc())
    liens = (await db.execute(stmt)).scalars().all()
    ids = {l.source_document_id for l in liens} | {l.cible_document_id for l in liens}
    docs = await _charger_docs(db, ids)
    return {"liens": [_lien_dto(l, docs) for l in liens], "nb": len(liens)}


@router.post("/links", tags=["Liens"])
async def create_manual_link(body: ManualLinkRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Crée un lien **manuel** entre deux documents (validé d'office)."""
    try:
        a, b = uuid.UUID(body.source_document_id), uuid.UUID(body.cible_document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Identifiant invalide")
    if a == b:
        raise HTTPException(status_code=400, detail="Un document ne peut être lié à lui-même")
    src, cible = (a, b) if str(a) < str(b) else (b, a)   # paire normalisée

    # Vérifie l'existence des deux documents.
    docs = await _charger_docs(db, {src, cible})
    if len(docs) < 2:
        raise HTTPException(status_code=404, detail="Document introuvable")

    existant = (await db.execute(select(DocumentLink).where(
        DocumentLink.source_document_id == src, DocumentLink.cible_document_id == cible,
    ))).scalar_one_or_none()
    if existant:
        existant.statut = "valide"
        existant.origine = "manuel"
        existant.type_lien = body.type_lien or existant.type_lien
        lien = existant
    else:
        lien = DocumentLink(
            source_document_id=src, cible_document_id=cible,
            type_lien=body.type_lien or "manuel", score=1.0,
            statut="valide", origine="manuel",
        )
        db.add(lien)
    await db.flush()
    return _lien_dto(lien, docs)


async def _get_lien(db: AsyncSession, link_id: str) -> DocumentLink:
    try:
        lid = uuid.UUID(link_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Identifiant invalide")
    lien = (await db.execute(select(DocumentLink).where(DocumentLink.id == lid))).scalar_one_or_none()
    if not lien:
        raise HTTPException(status_code=404, detail="Lien introuvable")
    return lien


@router.post("/links/{link_id}/validate", tags=["Liens"])
async def validate_link(link_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Valide une suggestion de lien."""
    lien = await _get_lien(db, link_id)
    lien.statut = "valide"
    await db.flush()
    docs = await _charger_docs(db, {lien.source_document_id, lien.cible_document_id})
    return _lien_dto(lien, docs)


@router.post("/links/{link_id}/reject", tags=["Liens"])
async def reject_link(link_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Rejette une suggestion (conservée au statut `rejete` → jamais reproposée)."""
    lien = await _get_lien(db, link_id)
    lien.statut = "rejete"
    await db.flush()
    docs = await _charger_docs(db, {lien.source_document_id, lien.cible_document_id})
    return _lien_dto(lien, docs)


@router.delete("/links/{link_id}", tags=["Liens"])
async def delete_link(link_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Supprime définitivement un lien (une paire supprimée pourra être re-proposée au prochain scan)."""
    lien = await _get_lien(db, link_id)
    await db.delete(lien)
    await db.flush()
    return {"supprime": True, "id": link_id}
