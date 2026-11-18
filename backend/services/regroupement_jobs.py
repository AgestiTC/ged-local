"""
Handler de job — analyse d'un REGROUPEMENT de documents.
========================================================
Réutilise le pipeline de génération de rapport : construit le contexte à partir des
documents du groupe + la consigne (prompt du groupe ou override), appelle le LLM
(modèle du groupe ou usage « rapport ») et **stocke le rendu** (markdown) dans le
regroupement (`dernier_rendu`). Tâche durable → survit à la fermeture du navigateur.

Module SÉPARÉ (pas dans job_handlers.py, WIP concurrent). Importé au démarrage.
"""
from services.ollama_service import avec_usage  # usage IA déclaré (prompts A3b)
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from database import AsyncSessionLocal
from logger import get_logger
from models.document import Document
from models.regroupement import Regroupement
from services.job_worker import JobContext, register

log = get_logger(__name__)


@register("analyse_regroupement")
@avec_usage("rapport")
async def handler_analyse_regroupement(ctx: JobContext) -> dict:
    """Paramètres : `regroupement_id` ; optionnels `prompt`, `model` (overrides)."""
    from routers.generate import _construire_contexte
    from services import runtime_config
    from services.ollama_service import OllamaService

    p = ctx.parametres
    rid = p.get("regroupement_id")
    if not rid:
        raise ValueError("regroupement_id manquant")

    async with AsyncSessionLocal() as db:
        rg = await db.get(Regroupement, uuid.UUID(rid))
        if not rg:
            raise ValueError("Regroupement introuvable")
        consigne = (p.get("prompt") or rg.prompt or "Analyse et synthétise ces documents de façon structurée.").strip()
        model = p.get("model") or rg.modele or runtime_config.model_for("rapport")
        # Le modèle préféré du groupe peut être GECO sans être dans les paramètres : recontrôle aussi.
        from services import modeles_externes
        if refus := await modeles_externes.controle_job(ctx.type, p, model):
            raise ValueError(refus)

        ids = []
        for x in (rg.document_ids or []):
            try:
                ids.append(uuid.UUID(str(x)))
            except ValueError:
                pass
        docs = (await db.execute(select(Document).where(Document.id.in_(ids)))).scalars().all() if ids else []
        if not docs:
            raise ValueError("Le regroupement ne contient aucun document valide")

        await ctx.report(20, f"Analyse de {len(docs)} document(s) — modèle {model}…")
        prompt_complet = _construire_contexte(docs, consigne)
        rendu = await OllamaService().generate(prompt_complet, model=model)

        rg.dernier_rendu = rendu
        rg.dernier_modele = model
        rg.dernier_analyse_at = datetime.now(tz=timezone.utc)
        await db.commit()

    log.info("Analyse de regroupement terminée", regroupement_id=rid, modele=model, nb_docs=len(docs), longueur=len(rendu))
    return {"regroupement_id": rid, "modele": model, "nb_docs": len(docs), "longueur": len(rendu)}
