"""
Router BookStack — /api/bookstack
==================================
Publication de tutos sur le wiki BookStack externe.

  GET  /bookstack/targets   → livres et chapitres disponibles (cibles)
  POST /bookstack/publish   → crée une page wiki à partir d'un markdown
                              (ou du texte extrait d'un document indexé) ;
                              cible existante OU créée à la volée (new_book/new_chapter)
  POST /bookstack/suggest   → propose titre + emplacement (LLM)

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
    soit du texte extrait d'un document (`document_id`).

    La cible est un livre/chapitre **existant** (`book_id` / `chapter_id`) OU
    **créé à la volée** : `new_book` (nom d'un nouveau livre) et/ou `new_chapter`
    (nom d'un nouveau chapitre, rattaché à `book_id` ou `new_book`).
    """
    titre: str = Field(..., min_length=1, max_length=255, description="Titre de la page wiki")
    markdown: str | None = Field(default=None, description="Contenu Markdown (si pas de document_id)")
    document_id: str | None = Field(default=None, description="ID d'un document indexé à publier")
    book_id: int | None = Field(default=None, description="Livre cible existant")
    chapter_id: int | None = Field(default=None, description="Chapitre cible existant")
    new_book: str | None = Field(default=None, max_length=255, description="Nom d'un livre à créer")
    new_chapter: str | None = Field(default=None, max_length=255, description="Nom d'un chapitre à créer")

    @model_validator(mode="after")
    def _check(self) -> "PublishRequest":
        if not self.markdown and not self.document_id:
            raise ValueError("Fournir 'markdown' ou 'document_id'.")
        has_target = any([self.book_id, self.chapter_id, self.new_book, self.new_chapter])
        if not has_target:
            raise ValueError("Fournir une cible : 'book_id', 'chapter_id', 'new_book' ou 'new_chapter'.")
        # Un nouveau chapitre exige un livre parent (existant ou à créer).
        if self.new_chapter and not (self.book_id or self.new_book):
            raise ValueError("Un nouveau chapitre exige un livre parent ('book_id' ou 'new_book').")
        return self


class SuggestRequest(BaseModel):
    """Demande de suggestion de titre + emplacement à partir du contenu."""
    markdown: str | None = Field(default=None, description="Contenu Markdown")
    document_id: str | None = Field(default=None, description="ID d'un document indexé")

    @model_validator(mode="after")
    def _check(self) -> "SuggestRequest":
        if not self.markdown and not self.document_id:
            raise ValueError("Fournir 'markdown' ou 'document_id'.")
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


async def _resolve_markdown(markdown: str | None, document_id: str | None, db: AsyncSession) -> str:
    """Contenu à publier : markdown direct, sinon texte extrait du document."""
    if markdown:
        return markdown
    if not document_id:
        return ""
    from models.document import Document
    try:
        doc_id = uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="document_id invalide.")
    doc = (await db.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable.")
    if not doc.texte_extrait:
        raise HTTPException(status_code=400, detail="Le document n'a pas de texte extrait.")
    return doc.texte_extrait


@router.post("/bookstack/publish", tags=["BookStack"])
async def publish(body: PublishRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Crée une page (tuto) dans le wiki BookStack.
    Résout la cible (création à la volée d'un livre/chapitre si demandé, idempotente),
    puis renvoie l'identifiant et l'URL de la page créée.
    """
    service = BookStackService()
    if not service.configured:
        raise HTTPException(status_code=400, detail="BookStack non configuré (URL ou jeton manquant).")

    markdown = await _resolve_markdown(body.markdown, body.document_id, db)

    # Résolution de la cible : création à la volée (idempotente) puis page.
    try:
        book_id = body.book_id
        chapter_id = body.chapter_id
        if body.new_book:
            book_id = (await service.ensure_book(body.new_book))["id"]
        if body.new_chapter:
            # book_id est garanti par la validation (existant ou fraîchement créé).
            chapter_id = (await service.ensure_chapter(book_id, body.new_chapter))["id"]

        page = await service.create_page(
            name=body.titre,
            markdown=markdown or "",
            # Le chapitre prime sur le livre (page rangée dans le chapitre).
            book_id=None if chapter_id else book_id,
            chapter_id=chapter_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Échec publication BookStack", erreur=str(exc))
        raise HTTPException(status_code=502, detail=f"Erreur BookStack : {exc}")

    return {
        "success": True,
        "page_id": page.get("id"),
        "page_url": service.page_url(page),
        "titre": body.titre,
    }


@router.post("/bookstack/suggest", tags=["BookStack"])
async def suggest(body: SuggestRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Propose un **titre** et un **emplacement** (livre existant ou nouveau, + chapitre
    éventuel) par rapprochement thématique avec les livres/chapitres existants.

    Renvoie : { titre, book_id|null, nouveau_livre|null, chapitre|null, raison }.
    """
    service = BookStackService()
    if not service.configured:
        raise HTTPException(status_code=400, detail="BookStack non configuré (URL ou jeton manquant).")

    markdown = await _resolve_markdown(body.markdown, body.document_id, db)
    if not markdown.strip():
        raise HTTPException(status_code=400, detail="Contenu vide : rien à analyser.")

    try:
        livres = await service.list_books()
        chapitres = await service.list_chapters()
    except Exception as exc:
        log.warning("BookStack injoignable (suggest)", erreur=str(exc))
        raise HTTPException(status_code=502, detail=f"BookStack injoignable : {exc}")

    # Contexte compact pour le LLM : id + nom des livres, chapitres rattachés.
    lignes_livres = "\n".join(
        f"- livre #{b['id']} : {b['name']}" for b in livres
    ) or "(aucun livre existant)"
    lignes_chapitres = "\n".join(
        f"- chapitre « {c['name']} » (dans livre #{c['book_id']})" for c in chapitres
    ) or "(aucun chapitre)"

    extrait = markdown.strip()[:4000]
    prompt = f"""Tu organises un wiki de documentation technique (BookStack).

Livres existants :
{lignes_livres}

Chapitres existants :
{lignes_chapitres}

Contenu à publier (extrait) :
\"\"\"
{extrait}
\"\"\"

Tâche : propose un titre de page court et explicite, et le meilleur emplacement.
- Si un livre existant convient thématiquement, renvoie son identifiant dans "book_id".
- Sinon, propose le nom d'un nouveau livre dans "nouveau_livre" (et laisse "book_id" à null).
- Tu peux proposer un nom de chapitre dans "chapitre" (sinon null).
Réponds UNIQUEMENT en JSON avec les clés exactes :
{{"titre": str, "book_id": int|null, "nouveau_livre": str|null, "chapitre": str|null, "raison": str}}"""

    from services.ollama_service import OllamaService
    import json as _json

    try:
        brut = await OllamaService().generate(prompt=prompt, format="json")
        data = _json.loads(brut)
    except Exception as exc:
        log.warning("Suggestion LLM indisponible", erreur=str(exc))
        raise HTTPException(status_code=502, detail=f"Suggestion impossible : {exc}")

    # Normalisation défensive de la sortie LLM.
    book_id = data.get("book_id")
    book_id = int(book_id) if isinstance(book_id, (int, str)) and str(book_id).isdigit() else None
    valides = {b["id"] for b in livres}
    if book_id not in valides:
        book_id = None  # le LLM a halluciné un id → on ignore
    nom_livre = book_id and next((b["name"] for b in livres if b["id"] == book_id), None)

    return {
        "titre": (data.get("titre") or "").strip()[:255],
        "book_id": book_id,
        "book_name": nom_livre or None,
        "nouveau_livre": (data.get("nouveau_livre") or "").strip() or None if not book_id else None,
        "chapitre": (data.get("chapitre") or "").strip() or None,
        "raison": (data.get("raison") or "").strip() or None,
    }
