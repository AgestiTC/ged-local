"""
Handlers de jobs — tâches réelles exécutées par le worker durable
=================================================================
Chaque handler est enregistré par type via `@job_worker.register(...)`. Ce module est
importé au démarrage (main.py) pour peupler le registre avant le lancement du worker.

Les imports lourds (extraction, ollama…) sont faits **à l'intérieur** des handlers pour
éviter tout cycle d'import au chargement.
"""

import uuid

from database import AsyncSessionLocal
from logger import get_logger
from models.document import Document
from services.job_worker import JobContext, register

log = get_logger(__name__)


@register("enrich")
async def handler_enrich(ctx: JobContext) -> dict:
    """
    Relance l'enrichissement IA (résumé, catégorie, tags…) d'un document à partir de son
    texte déjà extrait. Paramètre attendu : `document_id`.
    """
    from services.extraction import ExtractionService
    from services.ollama_service import OllamaService

    doc_id = ctx.parametres.get("document_id") or (str(ctx.document_id) if ctx.document_id else None)
    if not doc_id:
        raise ValueError("document_id manquant")

    await ctx.report(15, "Chargement du document…")
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, uuid.UUID(doc_id))
        if not doc:
            raise ValueError("Document introuvable")
        if not (doc.texte_extrait or "").strip():
            raise ValueError("Aucun texte à analyser (média ou extraction vide)")

        await ctx.report(30, "Analyse IA en cours…")
        service = ExtractionService(None, OllamaService(), None)  # _enrich n'utilise que l'IA
        ok = await service._enrich(doc, doc.texte_extrait, db)
        doc.statut = "enriched" if ok else "extracted"
        await db.commit()
        statut = doc.statut

    log.info("Job enrich terminé", document_id=doc_id, ok=ok)
    return {"ok": ok, "statut": statut, "document_id": doc_id}
