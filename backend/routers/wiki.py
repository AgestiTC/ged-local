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


@router.get("/wiki/pages/{page_id}", tags=["Wiki"])
async def wiki_page(page_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    """Contenu HTML rendu d'une page + son URL publique. `origine` : d'où vient le texte (bookstack,
    cockpit, projet) — toute page se corrige par une PROPOSITION (16/11/2026)."""
    from services import propositions_wiki

    svc = BookStackService()
    if not svc.configured:
        raise HTTPException(status_code=503, detail="BookStack non configuré")
    page = await svc.get_page(page_id)
    origine, pub = await propositions_wiki.origine_page(db, page_id)
    return {
        "id": page["id"],
        "name": page["name"],
        "html": page.get("html") or "",
        "url": svc.page_url(page),
        "origine": origine,
        "projet": pub.projet if pub else None,
        "cle": pub.cle if pub else None,
    }


@router.get("/wiki/pages/{page_id}/source", tags=["Wiki"])
async def wiki_page_source(page_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    """Le texte à éditer pour proposer : Markdown de la page (sans bandeau), ou son HTML converti."""
    from services import propositions_wiki

    svc = BookStackService()
    if not svc.configured:
        raise HTTPException(status_code=503, detail="BookStack non configuré")
    s = await propositions_wiki.source(db, svc, page_id)
    pub = s["pub"]
    return {"id": page_id, "titre": s["page"]["name"], "origine": s["origine"], "converti": s["converti"],
            "projet": pub.projet if pub else None, "cle": pub.cle if pub else None, "markdown": s["markdown"]}


class PropositionInput(BaseModel):
    markdown: str = Field(min_length=1)
    commentaire: str = ""


def _auteur(request: Request) -> dict:
    """L'auteur : la session (SSO) — identifiant DSM, nom, e-mail."""
    from services.acces import role_appelant

    user = getattr(request.state, "utilisateur", None)
    if user is not None:
        return {"identifiant": user.identifiant, "nom": user.nom, "email": user.email}
    return {"identifiant": role_appelant(request)[1], "nom": None, "email": None}


@router.post("/wiki/pages/{page_id}/proposition", tags=["Wiki"], status_code=201)
async def proposer_modification(page_id: int, body: PropositionInput, request: Request,
                                db: AsyncSession = Depends(get_db)) -> dict:
    """Propose une modification de n'importe quelle page (tout utilisateur), avec son auteur. Rien n'est
    écrit dans BookStack : un administrateur applique (ou le cockpit, pour ses pages)."""
    from services import propositions_wiki

    svc = BookStackService()
    if not svc.configured:
        raise HTTPException(status_code=503, detail="BookStack non configuré")
    try:
        p = await propositions_wiki.proposer(db, svc, page_id, body.markdown, body.commentaire, _auteur(request))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return propositions_wiki.en_json(p)


# ─── Administration des propositions (administrateurs) ────────────────────────
@router.get("/wiki/propositions", tags=["Wiki"])
async def lister_propositions(toutes: bool = False, db: AsyncSession = Depends(get_db)) -> dict:
    """Les propositions ouvertes (à appliquer / à reporter), ou toutes (`toutes=true`), récentes d'abord."""
    from sqlalchemy import select

    from models.proposition_wiki import OUVERTS, PropositionWiki
    from services import propositions_wiki

    q = select(PropositionWiki).order_by(PropositionWiki.created_at.desc())
    if not toutes:
        q = q.where(PropositionWiki.statut.in_(OUVERTS))
    props = (await db.execute(q.limit(500))).scalars().all()
    return {"propositions": [propositions_wiki.en_json(p) for p in props]}


async def _proposition(db: AsyncSession, pid: str):
    import uuid as _uuid

    from models.proposition_wiki import PropositionWiki
    try:
        p = await db.get(PropositionWiki, _uuid.UUID(pid))
    except ValueError:
        p = None
    if p is None:
        raise HTTPException(status_code=404, detail="Proposition introuvable.")
    return p


@router.post("/wiki/propositions/{pid}/appliquer", tags=["Wiki"])
async def appliquer_proposition(pid: str, request: Request, forcer: bool = False,
                                db: AsyncSession = Depends(get_db)) -> dict:
    """Écrit la proposition dans BookStack. 409 si la page a changé depuis (relancer avec `forcer=true`)."""
    from services import propositions_wiki

    p = await _proposition(db, pid)
    svc = BookStackService()
    if not svc.configured:
        raise HTTPException(status_code=503, detail="BookStack non configuré")
    try:
        p = await propositions_wiki.appliquer(db, svc, p, propositions_wiki.nom_auteur(_auteur(request)), forcer=forcer)
    except propositions_wiki.Conflit as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return propositions_wiki.en_json(p)


class ClotureInput(BaseModel):
    motif: str = ""


@router.post("/wiki/propositions/{pid}/refuser", tags=["Wiki"])
async def refuser_proposition(pid: str, body: ClotureInput, request: Request,
                              db: AsyncSession = Depends(get_db)) -> dict:
    from services import propositions_wiki

    p = await _proposition(db, pid)
    try:
        p = await propositions_wiki.cloturer(db, p, "refusee", propositions_wiki.nom_auteur(_auteur(request)), body.motif)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return propositions_wiki.en_json(p)


@router.post("/wiki/propositions/{pid}/reportee", tags=["Wiki"])
async def proposition_reportee(pid: str, body: ClotureInput, request: Request,
                               db: AsyncSession = Depends(get_db)) -> dict:
    """Page d'un projet à jeton : la modification a été reportée À LA MAIN dans le projet."""
    from services import propositions_wiki

    p = await _proposition(db, pid)
    try:
        p = await propositions_wiki.cloturer(db, p, "appliquee", propositions_wiki.nom_auteur(_auteur(request)), body.motif)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return propositions_wiki.en_json(p)


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
