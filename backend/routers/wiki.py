"""
Wiki — lecture des livres BookStack
====================================
Liste des livres + détail (sommaire chapitres/pages) + page (HTML rendu) +
couverture proxifiée. Service INTERNE configuré (bookstack_url) — pas de
« Demandes Mise à jour internet » (contrairement à HuggingFace = internet).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from services import job_worker
from services.bookstack_service import BookStackService

log = get_logger(__name__)
router = APIRouter()


class RenommerInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class DeplacerInput(BaseModel):
    # Déplacement d'un livre entre étagères : ajoute à `to_shelf_id`, retire de `from_shelf_id`.
    # `to_shelf_id` = null → simple détachement (dépôt sur « Sans étagère »).
    from_shelf_id: int | None = None
    to_shelf_id: int | None = None


@router.get("/wiki/books", tags=["Wiki"])
async def wiki_books() -> dict:
    """Liste des livres (+ couverture proxifiée) et des étagères qui les regroupent (Lot 1b).

    `shelves` : [{id, name, book_ids}] — permet au menu Wiki de regrouper les livres par étagère.
    Un livre peut n'appartenir à aucune étagère (→ groupe « Sans étagère » côté front)."""
    svc = BookStackService()
    if not svc.configured:
        return {"configured": False, "base_url": svc.base_url, "books": [], "shelves": []}
    books = await svc.list_books_detailed()
    for b in books:
        b["cover_url"] = f"/api/wiki/books/{b['id']}/cover" if b.get("has_cover") else None

    # Étagères : un GET détaillé par étagère pour récupérer ses livres (peu d'étagères → coût négligeable).
    shelves: list[dict] = []
    try:
        for s in await svc.list_shelves():
            detail = await svc.get_shelf(s["id"])
            book_ids = [bk["id"] for bk in (detail.get("books") or [])]
            shelves.append({"id": s["id"], "name": s.get("name"), "book_ids": book_ids})
    except Exception as e:  # noqa: BLE001 — le wiki reste consultable même si l'API étagères échoue
        log.warning("Wiki : lecture des étagères échouée", erreur=str(e))

    return {"configured": True, "base_url": svc.base_url, "books": books, "shelves": shelves}


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


async def _publication_cockpit(db: AsyncSession, page_id: int):
    """La publication d'une page déposée par le cockpit (sinon None) : seules celles-là se proposent."""
    from sqlalchemy import select

    from models.publication import Publication
    from services import docs_cockpit

    pub = (await db.execute(select(Publication).where(Publication.page_id == page_id))).scalars().first()
    return pub if pub is not None and docs_cockpit.depose_par_cockpit(pub.projet) else None


@router.get("/wiki/pages/{page_id}", tags=["Wiki"])
async def wiki_page(page_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    """Contenu HTML rendu d'une page + son URL publique. `projet` : le projet d'où elle est publiée
    (dépôt du cockpit) — sa source est alors le `.md` du projet, et elle se corrige par une proposition."""
    svc = BookStackService()
    if not svc.configured:
        raise HTTPException(status_code=503, detail="BookStack non configuré")
    page = await svc.get_page(page_id)
    pub = await _publication_cockpit(db, page_id)
    return {
        "id": page["id"],
        "name": page["name"],
        "html": page.get("html") or "",
        "url": svc.page_url(page),
        "projet": pub.projet if pub else None,
        "cle": pub.cle if pub else None,
    }


@router.get("/wiki/pages/{page_id}/source", tags=["Wiki"])
async def wiki_page_source(page_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    """Le Markdown d'une page publiée par le cockpit, sans le bandeau (point de départ d'une proposition)."""
    from services import publication_service

    pub = await _publication_cockpit(db, page_id)
    if pub is None:
        raise HTTPException(status_code=404, detail="Cette page ne vient pas d'un dépôt du cockpit.")
    svc = BookStackService()
    if not svc.configured:
        raise HTTPException(status_code=503, detail="BookStack non configuré")
    page = await svc.get_page(page_id)
    return {"id": page_id, "titre": page["name"], "projet": pub.projet, "cle": pub.cle,
            "markdown": publication_service.retirer_bandeau(page.get("markdown") or "")}


class PropositionInput(BaseModel):
    markdown: str = Field(min_length=1)
    commentaire: str = ""


@router.post("/wiki/pages/{page_id}/proposition", tags=["Wiki"], status_code=201)
async def proposer_modification(page_id: int, body: PropositionInput, request: Request,
                                db: AsyncSession = Depends(get_db)) -> dict:
    """Propose une modification d'une page publiée par le cockpit (tout utilisateur). L'AUTEUR est celui de
    la session (SSO) ; la proposition est déposée à côté du manifeste, le cockpit l'applique au projet."""
    from services import docs_cockpit, publication_service
    from services.acces import role_appelant

    pub = await _publication_cockpit(db, page_id)
    if pub is None:
        raise HTTPException(status_code=404, detail="Cette page ne vient pas d'un dépôt du cockpit.")
    svc = BookStackService()
    if not svc.configured:
        raise HTTPException(status_code=503, detail="BookStack non configuré")
    page = await svc.get_page(page_id)
    user = getattr(request.state, "utilisateur", None)
    auteur = ({"identifiant": user.identifiant, "nom": user.nom, "email": user.email} if user is not None
              else {"identifiant": role_appelant(request)[1], "nom": None, "email": None})
    try:
        chemin = await docs_cockpit.deposer_proposition(
            db, pub, titre=page["name"], page_url=svc.page_url(page),
            avant=publication_service.retirer_bandeau(page.get("markdown") or ""),
            propose=body.markdown, commentaire=body.commentaire, auteur=auteur)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"projet": pub.projet, "cle": pub.cle, "fichier": chemin, "auteur": auteur}


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


@router.patch("/wiki/books/{book_id}", tags=["Wiki"])
async def renommer_livre(book_id: int, body: RenommerInput) -> dict:
    """Renomme un livre BookStack (répercuté immédiatement — pas d'étape de synchro séparée)."""
    svc = BookStackService()
    if not svc.configured:
        raise HTTPException(status_code=503, detail="BookStack non configuré")
    try:
        data = await svc.renommer_livre(book_id, body.name)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Renommage impossible : {e}")
    return {"id": data.get("id", book_id), "name": data.get("name", body.name)}


@router.patch("/wiki/shelves/{shelf_id}", tags=["Wiki"])
async def renommer_etagere(shelf_id: int, body: RenommerInput) -> dict:
    """Renomme une étagère BookStack (sa liste de livres est préservée)."""
    svc = BookStackService()
    if not svc.configured:
        raise HTTPException(status_code=503, detail="BookStack non configuré")
    try:
        data = await svc.renommer_etagere(shelf_id, body.name)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Renommage impossible : {e}")
    return {"id": data.get("id", shelf_id), "name": data.get("name", body.name)}


@router.post("/wiki/books/{book_id}/deplacer", tags=["Wiki"])
async def deplacer_livre(book_id: int, body: DeplacerInput) -> dict:
    """Déplace un livre entre étagères : ajoute à la cible PUIS retire de la source (jamais orphelin).
    `to_shelf_id` null = détacher (dépôt sur « Sans étagère »). Répercuté direct dans BookStack."""
    svc = BookStackService()
    if not svc.configured:
        raise HTTPException(status_code=503, detail="BookStack non configuré")
    if body.to_shelf_id and body.from_shelf_id == body.to_shelf_id:
        return {"ok": True, "inchange": True}
    try:
        # 1) Rattachement à la cible d'abord (le livre reste toujours rangé quelque part).
        if body.to_shelf_id:
            await svc.ensure_book_in_shelf(body.to_shelf_id, book_id)
        # 2) Retrait de la source ensuite.
        if body.from_shelf_id:
            await svc.retirer_livre_etagere(body.from_shelf_id, book_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Déplacement impossible : {e}")
    return {"ok": True, "book_id": book_id, "to_shelf_id": body.to_shelf_id, "from_shelf_id": body.from_shelf_id}


@router.post("/wiki/index", tags=["Wiki"])
async def wiki_index(db: AsyncSession = Depends(get_db)) -> dict:
    """Lance l'indexation du wiki (job durable) : 1 document par page, catégorie « livre »."""
    if not BookStackService().configured:
        raise HTTPException(status_code=400, detail="BookStack non configuré")
    job_id = await job_worker.enqueue(db, "index_wiki", {})
    await db.commit()
    return {"job_id": job_id, "statut": "pending"}
