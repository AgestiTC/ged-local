"""
Handlers de jobs — tâches réelles exécutées par le worker durable
=================================================================
Chaque handler est enregistré par type via `@job_worker.register(...)`. Ce module est
importé au démarrage (main.py) pour peupler le registre avant le lancement du worker.

Les imports lourds (extraction, ollama…) sont faits **à l'intérieur** des handlers pour
éviter tout cycle d'import au chargement.
"""

import uuid

from sqlalchemy import select

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


async def _resoudre_fichier(doc: Document, db, ctx: JobContext):
    """
    Retourne `(Path, cleanup)` pour accéder au **contenu** d'un document :
    - **local** → chemin filesystem existant, `cleanup` = no-op ;
    - **`smb://`** → **fetch temporaire** (NAS → /tmp), `cleanup` = `os.unlink(tmp)`.

    Le secret SMB est **déchiffré depuis la Source** (retrouvée par hôte), jamais stocké dans
    les paramètres du job. Aucun fichier n'est conservé : l'appelant appelle `cleanup()`.
    """
    import os
    from pathlib import Path

    from models.source import Source
    from services import crypto, smb_service

    chemin = doc.chemin or ""

    if chemin.startswith("smb://"):
        # Re-parse `smb://{hote}/{partage}{rel}` (rel commence par « / »).
        raw = chemin[len("smb://"):]
        try:
            hote, rest = raw.split("/", 1)
            partage, tail = rest.split("/", 1)
        except ValueError:
            raise ValueError(f"Chemin SMB invalide : {chemin}")
        rel = "/" + tail

        src = (await db.execute(
            select(Source).where(Source.type == "smb", Source.hote == hote)
        )).scalars().first()
        if not src:
            raise ValueError(f"Aucune source SMB configurée pour l'hôte {hote}")
        secret = crypto.decrypt(src.secret_chiffre) if src.secret_chiffre else None

        await ctx.report(35, "Téléchargement depuis le NAS…")
        tmp = await smb_service.fetch_to_temp(hote, partage, rel, src.identifiant, secret, src.domaine)

        def cleanup():
            try:
                os.unlink(tmp)
            except OSError:
                pass

        return Path(tmp), cleanup

    # Local : le fichier doit être accessible dans le conteneur.
    p = Path(chemin)
    if not p.exists():
        raise ValueError(f"Fichier introuvable localement : {chemin}")
    return p, (lambda: None)


@register("analyze")
async def handler_analyze(ctx: JobContext) -> dict:
    """
    Analyse le **contenu** d'un document existant (média catalogué ou doc au texte vide),
    local ou SMB. Fetch SMB → temporaire éphémère → `analyze_existing` (met à jour le doc
    EXISTANT, **zéro doublon**) → suppression du tmp. Paramètre : `document_id`.
    """
    from routers.upload import _get_extraction_service

    doc_id = ctx.parametres.get("document_id") or (str(ctx.document_id) if ctx.document_id else None)
    if not doc_id:
        raise ValueError("document_id manquant")

    await ctx.report(15, "Résolution du fichier…")
    async with AsyncSessionLocal() as db:
        doc = await db.get(Document, uuid.UUID(doc_id))
        if not doc:
            raise ValueError("Document introuvable")

        file_path, cleanup = await _resoudre_fichier(doc, db, ctx)
        try:
            await ctx.report(55, "Extraction du contenu (Tika + IA)…")
            service = _get_extraction_service()
            ok = await service.analyze_existing(doc, file_path, db)
            statut = doc.statut
        finally:
            cleanup()  # ⚠️ suppression du fichier temporaire (aucune copie conservée)

    log.info("Job analyze terminé", document_id=doc_id, ok=ok, statut=statut)
    return {"ok": ok, "statut": statut, "document_id": doc_id}


async def _smb_creds(db, host: str, cache: dict):
    """Identifiants SMB (déchiffrés) pour un hôte, mis en cache. None si aucune source."""
    if host in cache:
        return cache[host]
    from models.source import Source
    from services import crypto
    src = (await db.execute(
        select(Source).where(Source.type == "smb", Source.hote == host)
    )).scalars().first()
    c = None if not src else (src.identifiant, crypto.decrypt(src.secret_chiffre) if src.secret_chiffre else None, src.domaine)
    cache[host] = c
    return c


@register("reorg_apply")
async def handler_reorg_apply(ctx: JobContext) -> dict:
    """
    Applique le plan de réorganisation AU NAS (déplacements SMB réels) + journal pour l'undo.
    Jamais de suppression ; collisions gérées par suffixe `_(n)`. Met à jour `documents.chemin`.
    """
    from models.reorg import ReorgMove, ReorgPlan
    from routers.organize import dest_rel, parse_smb
    from services import smb_service

    batch = uuid.UUID(ctx.parametres["batch_id"])
    cache: dict = {}
    await ctx.report(3, "Préparation des déplacements…")
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Document, ReorgPlan.dossier_cible).join(ReorgPlan, ReorgPlan.document_id == Document.id)
        )).all()
        total, fait, deplaces = len(rows), 0, 0
        for d, dossier in rows:
            fait += 1
            if fait % 5 == 0 or fait == total:
                await ctx.report(round(fait / total * 100) if total else 100, f"{fait}/{total} — {deplaces} déplacé(s)")
            parsed = parse_smb(d.chemin)
            if not parsed:
                continue
            host, share, rel = parsed
            drel = dest_rel(dossier, d.nom)
            if rel == drel:
                continue
            creds = await _smb_creds(db, host, cache)
            if not creds:
                continue
            ident, secret, domaine = creds
            try:
                parent = drel.rsplit("/", 1)[0] or "/"
                await smb_service.ensure_dir(host, share, parent, ident, secret, domaine)
                final = drel
                base, dot, ext = d.nom.rpartition(".")
                n = 1
                while await smb_service.exists(host, share, final, ident, secret, domaine):
                    nom_n = f"{base}_({n}).{ext}" if dot else f"{d.nom}_({n})"
                    final = dest_rel(dossier, nom_n)
                    n += 1
                    if n > 50:
                        break
                await smb_service.move_file(host, share, rel, final, ident, secret, domaine)
                dest_chemin = f"smb://{host}/{share}{final}"
                db.add(ReorgMove(batch_id=batch, document_id=d.id, chemin_source=d.chemin, chemin_dest=dest_chemin))
                d.chemin = dest_chemin
                deplaces += 1
                if deplaces % 20 == 0:
                    await db.commit()
            except Exception as e:  # noqa: BLE001 — on continue, le fichier reste à sa place
                log.warning("Déplacement réorg échoué", doc=str(d.id), erreur=str(e))
        await db.commit()
    log.info("Réorganisation appliquée", batch=str(batch), deplaces=deplaces, total=total)
    return {"batch_id": str(batch), "deplaces": deplaces, "total": total}


@register("reorg_undo")
async def handler_reorg_undo(ctx: JobContext) -> dict:
    """Annule une application : remet chaque fichier à son chemin d'origine (via le journal)."""
    from models.reorg import ReorgMove
    from routers.organize import parse_smb
    from services import smb_service

    batch = uuid.UUID(ctx.parametres["batch_id"])
    cache: dict = {}
    await ctx.report(3, "Annulation en cours…")
    async with AsyncSessionLocal() as db:
        moves = (await db.execute(select(ReorgMove).where(ReorgMove.batch_id == batch))).scalars().all()
        total, fait, remis = len(moves), 0, 0
        for m in moves:
            fait += 1
            if fait % 5 == 0 or fait == total:
                await ctx.report(round(fait / total * 100) if total else 100, f"{fait}/{total} remis")
            pd, ps = parse_smb(m.chemin_dest), parse_smb(m.chemin_source)
            if not pd or not ps:
                continue
            host, share, drel = pd
            _, _, srel = ps
            creds = await _smb_creds(db, host, cache)
            if not creds:
                continue
            ident, secret, domaine = creds
            try:
                parent = srel.rsplit("/", 1)[0] or "/"
                await smb_service.ensure_dir(host, share, parent, ident, secret, domaine)
                await smb_service.move_file(host, share, drel, srel, ident, secret, domaine)
                doc = await db.get(Document, m.document_id)
                if doc:
                    doc.chemin = m.chemin_source
                await db.delete(m)
                remis += 1
                if remis % 20 == 0:
                    await db.commit()
            except Exception as e:  # noqa: BLE001
                log.warning("Undo réorg échoué", move=str(m.id), erreur=str(e))
        await db.commit()
    log.info("Réorganisation annulée", batch=str(batch), remis=remis, total=total)
    return {"batch_id": str(batch), "remis": remis, "total": total}
