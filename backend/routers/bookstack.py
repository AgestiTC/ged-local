"""
Router BookStack — /api/bookstack
==================================
Publication de tutos sur le wiki BookStack externe.

  GET  /bookstack/targets   → livres et chapitres disponibles (cibles)
  POST /bookstack/publish   → crée une page wiki à partir d'un markdown
                              (ou du texte extrait d'un document indexé)

Pré-requis : BookStack configuré (URL + jeton) via /api/system/config.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from services.bookstack_service import BookStackService

log = get_logger(__name__)
router = APIRouter()


class PublishRequest(BaseModel):
    """
    Demande de publication. Le contenu provient soit de `markdown` (direct),
    soit du texte extrait d'un document (`document_id`). La cible est un livre
    (`book_id`) OU un chapitre (`chapter_id`).
    """
    titre: str = Field(..., min_length=1, max_length=255, description="Titre de la page wiki")
    markdown: str | None = Field(default=None, description="Contenu Markdown (si pas de document_id)")
    document_id: str | None = Field(default=None, description="ID d'un document indexé à publier")
    book_id: int | None = Field(default=None, description="Livre cible")
    chapter_id: int | None = Field(default=None, description="Chapitre cible")

    @model_validator(mode="after")
    def _check(self) -> "PublishRequest":
        if not self.markdown and not self.document_id:
            raise ValueError("Fournir 'markdown' ou 'document_id'.")
        if not self.book_id and not self.chapter_id:
            raise ValueError("Fournir une cible : 'book_id' ou 'chapter_id'.")
        return self


@router.get("/bookstack/targets", tags=["BookStack"])
async def list_targets() -> dict:
    """Liste les livres et chapitres BookStack où publier."""
    service = BookStackService()
    if not service.configured:
        raise HTTPException(status_code=400, detail="BookStack non configuré (URL ou jeton manquant).")
    try:
        livres = await service.list_books()
        chapitres = await service.list_chapters()
    except Exception as exc:
        log.warning("BookStack targets indisponibles", erreur=str(exc))
        raise HTTPException(status_code=502, detail=f"BookStack injoignable : {exc}")
    return {"books": livres, "chapters": chapitres}


@router.post("/bookstack/publish", tags=["BookStack"])
async def publish(body: PublishRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Crée une page (tuto) dans le wiki BookStack.
    Renvoie l'identifiant et l'URL de la page créée.
    """
    service = BookStackService()
    if not service.configured:
        raise HTTPException(status_code=400, detail="BookStack non configuré (URL ou jeton manquant).")

    # Contenu : markdown direct, sinon texte extrait du document.
    markdown = body.markdown
    if not markdown and body.document_id:
        from models.document import Document
        try:
            doc_id = uuid.UUID(body.document_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="document_id invalide.")
        doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
        if not doc:
            raise HTTPException(status_code=404, detail="Document introuvable.")
        if not doc.texte_extrait:
            raise HTTPException(status_code=400, detail="Le document n'a pas de texte extrait.")
        markdown = doc.texte_extrait

    try:
        page = await service.create_page(
            name=body.titre,
            markdown=markdown or "",
            book_id=body.book_id,
            chapter_id=body.chapter_id,
        )
    except Exception as exc:
        log.error("Échec publication BookStack", erreur=str(exc))
        raise HTTPException(status_code=502, detail=f"Erreur BookStack : {exc}")

    return {
        "success": True,
        "page_id": page.get("id"),
        "page_url": service.page_url(page),
        "titre": body.titre,
    }
