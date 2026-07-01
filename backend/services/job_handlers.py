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


@register("presentation")
async def handler_presentation(ctx: JobContext) -> dict:
    """Génère un diaporama (slides IA) à partir de documents et le stocke. Résultat : presentation_id."""
    from models.presentation import Presentation
    from services import presentation_service

    doc_ids = ctx.parametres.get("document_ids") or []
    if len(doc_ids) < 2:
        raise ValueError("Sélectionnez au moins 2 documents")

    await ctx.report(20, "Génération des diapositives (IA)…")
    async with AsyncSessionLocal() as db:
        data = await presentation_service.generer_slides(
            doc_ids, db, ctx.parametres.get("consigne"), ctx.parametres.get("model")
        )
        p = Presentation(
            titre=data["titre"], theme=data.get("theme"), slides=data["slides"],
            document_ids=doc_ids, modele_utilise=data.get("modele_utilise"),
        )
        db.add(p)
        await db.flush()
        result = {"presentation_id": str(p.id), "titre": p.titre, "nb_slides": len(data["slides"])}
        await db.commit()

    log.info("Job présentation terminé", presentation_id=result["presentation_id"], nb_slides=result["nb_slides"])
    return result


@register("fill_template")
async def handler_fill_template(ctx: JobContext) -> dict:
    """Remplit un template DOCX avec les infos extraites des documents. Résultat : chemin du fichier."""
    from services.ollama_service import OllamaService
    from services.template_filler import TemplateFiller

    params = ctx.parametres
    if not params.get("template_id"):
        raise ValueError("template_id manquant")

    await ctx.report(25, "Remplissage du modèle (IA)…")
    async with AsyncSessionLocal() as db:
        filler = TemplateFiller(ollama_service=OllamaService())
        chemin = await filler.fill(
            template_id=params["template_id"],
            document_ids=params.get("document_ids") or [],
            instructions=params.get("instructions"),
            model=params.get("model"),
            db=db,
        )

    log.info("Job fill_template terminé", fichier=chemin.name)
    return {"path": str(chemin), "filename": chemin.name}


@register("indexation")
async def handler_indexation(ctx: JobContext) -> dict:
    """
    Indexe un dossier d'une source (local ou SMB) comme tâche durable. Le secret SMB est
    **déchiffré depuis la source** (jamais stocké dans le job). Réutilise la logique
    `_index_local`/`_index_smb` (barre de progression mémoire UI inchangée) et **miroir** cette
    progression dans le job (progress + message), pour la visibilité/durabilité côté jobs.
    """
    import asyncio

    from models.source import Source
    from routers import sources as srcmod
    from services import crypto

    p = ctx.parametres
    sid = p.get("source_id")
    if not sid:
        raise ValueError("source_id manquant")

    async with AsyncSessionLocal() as db:
        src = await db.get(Source, uuid.UUID(sid))
        if not src:
            raise ValueError("Source introuvable")
        stype = src.type
        chemin_base, hote, identifiant, domaine = src.chemin_base, src.hote, src.identifiant, src.domaine
        secret = crypto.decrypt(src.secret_chiffre) if src.secret_chiffre else None

    # Garantit que la barre existe (utile aussi après un reboot : `_progression` en mémoire est vide).
    srcmod._prog_demarrer(sid)

    if stype == "local":
        task = asyncio.create_task(
            srcmod._index_local(chemin_base, p.get("chemin", "/"), p.get("recursive", True), sid)
        )
    elif stype == "smb":
        if not p.get("partage"):
            raise ValueError("partage requis pour une source SMB")
        task = asyncio.create_task(
            srcmod._index_smb(hote, p["partage"], p.get("chemin", "/"), identifiant, secret, domaine, sid)
        )
    else:
        raise ValueError(f"type de source inconnu : {stype}")

    # Miroir progression mémoire → job (throttlé à ~1 s tant que l'indexation tourne).
    while not task.done():
        prg = srcmod._progression.get(sid) or {}
        total, fait, phase = prg.get("total") or 0, prg.get("fait") or 0, prg.get("phase", "enumeration")
        if phase == "enumeration":
            await ctx.report(progress=0, message="Énumération des fichiers…")
        else:
            await ctx.report(progress=round(fait / total * 100) if total else 0, message=f"{fait}/{total} fichiers")
        await asyncio.sleep(1.0)

    await task  # propage une éventuelle exception (ex. échec d'auth SMB à la racine)
    prg = srcmod._progression.get(sid) or {}
    log.info("Job indexation terminé", source_id=sid, total=prg.get("total"), fait=prg.get("fait"))
    return {"total": prg.get("total"), "indexes": prg.get("fait")}
