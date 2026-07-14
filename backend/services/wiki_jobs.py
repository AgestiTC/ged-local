"""
Handler de job — indexation du wiki BookStack (② : livres cherchables).
=======================================================================
1 document par PAGE BookStack : texte (HTML→texte) + embeddings, catégorie
forcée « livre ». Idempotent (hash du texte) ; supprime les pages disparues.

Module SÉPARÉ de `job_handlers.py` (WIP concurrent). Importé au démarrage
(main.py + worker.py) pour enregistrer le handler `index_wiki`.
"""
import hashlib
import html as _html
import re

from sqlalchemy import delete, select

from database import AsyncSessionLocal
from logger import get_logger
from models.document import Document
from models.embedding import Embedding
from models.metadata import MetadonneeIA
from services.job_worker import JobContext, register

log = get_logger(__name__)

_TAG = re.compile(r"<[^>]+>")


def _html_to_text(h: str) -> str:
    """HTML → texte brut (indexation), sans dépendance externe."""
    h = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)\s*>", "\n", h)
    h = re.sub(r"(?i)<br\s*/?>", "\n", h)
    t = _html.unescape(_TAG.sub(" ", h))
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


@register("index_wiki")
async def handler_index_wiki(ctx: JobContext) -> dict:
    """Indexe toutes les pages des livres BookStack (catégorie « livre »)."""
    from routers.upload import _get_extraction_service
    from services.bookstack_service import BookStackService

    svc = BookStackService()
    if not svc.configured:
        raise ValueError("BookStack non configuré (Paramètres → BookStack)")

    await ctx.report(2, "Lecture des livres…")
    books = await svc.list_books_detailed()

    # Énumère toutes les pages : livre → pages directes + pages des chapitres.
    pages: list[tuple[str, int, str]] = []  # (nom_livre, page_id, nom_page)
    for b in books:
        try:
            detail = await svc.get_book(b["id"])
        except Exception as e:  # noqa: BLE001
            log.warning("Livre illisible", book=b.get("id"), erreur=str(e))
            continue
        for item in detail.get("contents", []):
            if item.get("type") == "page":
                pages.append((b["name"], item["id"], item.get("name", "")))
            elif item.get("type") == "chapter":
                for pg in item.get("pages", []) or []:
                    pages.append((b["name"], pg["id"], pg.get("name", "")))

    total = len(pages)
    log.info("Indexation wiki", nb_livres=len(books), nb_pages=total)
    service = _get_extraction_service()

    fait = indexes = inchanges = 0
    for book_name, pid, page_name in pages:
        try:
            page = await svc.get_page(pid)
            texte = _html_to_text(page.get("html") or "")
            if not texte:
                continue
            chemin = f"wiki://{pid}"
            h = hashlib.sha256(texte.encode("utf-8", "replace")).hexdigest()
            async with AsyncSessionLocal() as db:
                doc = (await db.execute(select(Document).where(Document.chemin == chemin))).scalar_one_or_none()
                if doc and doc.hash_sha256 == h:
                    inchanges += 1
                    continue
                nom = page.get("name") or page_name or f"page {pid}"
                if doc:
                    doc.hash_sha256 = h
                    doc.texte_extrait = texte
                    doc.nom = nom
                    await db.execute(delete(Embedding).where(Embedding.document_id == doc.id))
                else:
                    doc = Document(
                        chemin=chemin, nom=nom, extension="wiki",
                        hash_sha256=h, taille_octets=len(texte.encode("utf-8", "replace")),
                        statut="enriched", source="wiki", texte_extrait=texte,
                    )
                    db.add(doc)
                    await db.flush()
                # Métadonnées : catégorie forcée « livre » + nom du livre en sous-catégorie.
                meta = (await db.execute(select(MetadonneeIA).where(MetadonneeIA.document_id == doc.id))).scalar_one_or_none()
                if meta:
                    meta.categorie = "livre"
                    meta.sous_categorie = book_name
                else:
                    db.add(MetadonneeIA(document_id=doc.id, categorie="livre", sous_categorie=book_name, tags=[book_name]))
                doc.statut = "enriched"
                await db.flush()
                await service.embeddings.embed_document(str(doc.id), texte, db)
                await db.commit()
            indexes += 1
        except Exception as e:  # noqa: BLE001 — une page en échec ne stoppe pas l'indexation
            log.error("Erreur indexation page wiki", page=pid, erreur=str(e))
        finally:
            fait += 1
            if fait % 3 == 0 or fait == total:
                await ctx.report(round(fait / total * 100) if total else 100, f"{fait}/{total} — {indexes} indexée(s)")

    # Nettoyage : docs `wiki://` dont la page n'existe plus côté BookStack.
    presents = {f"wiki://{pid}" for _, pid, _ in pages}
    supprimes = 0
    async with AsyncSessionLocal() as db:
        anciens = (await db.execute(select(Document).where(Document.source == "wiki"))).scalars().all()
        for d in anciens:
            if d.chemin not in presents:
                await db.delete(d)
                supprimes += 1
        if supprimes:
            await db.commit()

    log.info("Indexation wiki terminée", total=total, indexes=indexes, inchanges=inchanges, supprimes=supprimes)
    return {"pages": total, "indexes": indexes, "inchanges": inchanges, "supprimes": supprimes}
