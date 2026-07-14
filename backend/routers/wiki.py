"""
Wiki — lecture des livres BookStack
====================================
Liste des livres + détail (sommaire chapitres/pages) + page (HTML rendu) +
couverture proxifiée. Service INTERNE configuré (bookstack_url) — pas de
« Demandes Mise à jour internet » (contrairement à HuggingFace = internet).
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from services import job_worker
from services.bookstack_service import BookStackService

log = get_logger(__name__)
router = APIRouter()


@router.get("/wiki/books", tags=["Wiki"])
async def wiki_books() -> dict:
    """Liste des livres avec description + URL de couverture proxifiée."""
    svc = BookStackService()
    if not svc.configured:
        return {"configured": False, "base_url": svc.base_url, "books": []}
    books = await svc.list_books_detailed()
    for b in books:
        b["cover_url"] = f"/api/wiki/books/{b['id']}/cover" if b.get("has_cover") else None
    return {"configured": True, "base_url": svc.base_url, "books": books}


@router.get("/wiki/books/{book_id}", tags=["Wiki"])
async def wiki_book(book_id: int) -> dict:
    """Détail d'un livre : description + `contents` (chapitres/pages) + URL BookStack."""
    svc = BookStackService()
    if not svc.configured:
        raise HTTPException(status_code=503, detail="BookStack non configuré")
    book = await svc.get_book(book_id)
    return {
        "id": book["id"],
        "name": book["name"],
        "slug": book.get("slug"),
        "description": book.get("description") or "",
        "contents": book.get("contents", []),
        "url": svc.book_url(book),
        "has_cover": bool(book.get("cover")),
    }


@router.get("/wiki/pages/{page_id}", tags=["Wiki"])
async def wiki_page(page_id: int) -> dict:
    """Contenu HTML rendu d'une page + son URL publique."""
    svc = BookStackService()
    if not svc.configured:
        raise HTTPException(status_code=503, detail="BookStack non configuré")
    page = await svc.get_page(page_id)
    return {
        "id": page["id"],
        "name": page["name"],
        "html": page.get("html") or "",
        "url": svc.page_url(page),
    }


@router.get("/wiki/books/{book_id}/cover", tags=["Wiki"])
async def wiki_book_cover(book_id: int) -> Response:
    """Couverture d'un livre (image proxifiée — l'accès BookStack est authentifié)."""
    svc = BookStackService()
    if not svc.configured:
        raise HTTPException(status_code=404, detail="BookStack non configuré")
    res = await svc.cover_image(book_id)
    if not res:
        raise HTTPException(status_code=404, detail="Pas de couverture")
    content, ctype = res
    return Response(content=content, media_type=ctype, headers={"Cache-Control": "public, max-age=3600"})


@router.post("/wiki/index", tags=["Wiki"])
async def wiki_index(db: AsyncSession = Depends(get_db)) -> dict:
    """Lance l'indexation du wiki (job durable) : 1 document par page, catégorie « livre »."""
    if not BookStackService().configured:
        raise HTTPException(status_code=400, detail="BookStack non configuré")
    job_id = await job_worker.enqueue(db, "index_wiki", {})
    await db.commit()
    return {"job_id": job_id, "statut": "pending"}
