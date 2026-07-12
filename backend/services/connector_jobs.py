"""
Handler de job — indexation d'un compte CONNECTEUR (cloud / NAS DSM).
=====================================================================
Miroir de `_index_smb` mais via l'interface `SourceConnector` : walk → (média =
catalogue léger) / (document = fetch temporaire → pipeline complet). Chaque fichier
distant reçoit un chemin `"{type}://{source_id}{rel}"` (self-contained, re-fetchable).

Module SÉPARÉ de `job_handlers.py` (pour ne pas toucher au WIP concurrent). Importé au
démarrage (main.py + worker.py) pour enregistrer le handler.
"""
import os
import uuid
from pathlib import Path

from database import AsyncSessionLocal
from logger import get_logger
from models.document import Document
from models.source import Source
from services.job_worker import JobContext, register

log = get_logger(__name__)


@register("index_connector")
async def handler_index_connector(ctx: JobContext) -> dict:
    """Indexe (récursivement) un compte connecteur. Paramètres : `source_id`, `chemin` (racine)."""
    from routers.upload import _get_extraction_service
    from services import runtime_config
    from services.connectors import get_connector
    from services.folder_watcher import MEDIA_EXTENSIONS

    p = ctx.parametres
    source_id = p.get("source_id")
    chemin = p.get("chemin") or "/"
    if not source_id:
        raise ValueError("source_id manquant")

    async with AsyncSessionLocal() as db:
        src = await db.get(Source, uuid.UUID(source_id))
        if not src:
            raise ValueError("Source introuvable")
        conn = get_connector(src.type)
        if not conn:
            raise ValueError(f"Type '{src.type}' sans connecteur")
        stype, sid = src.type, str(src.id)

    await ctx.report(2, "Énumération des fichiers…")
    fichiers = await conn.walk_files(src, chemin, runtime_config.effective_extensions())
    total = len(fichiers)
    log.info("Indexation connecteur", type=stype, source_id=sid, nb=total)

    service = _get_extraction_service()
    fait = indexes = 0
    for entry in fichiers:
        rel, taille = entry["rel"], entry.get("taille")
        chemin_doc = f"{stype}://{sid}{rel}"
        ext = Path(rel).suffix.lstrip(".").lower()
        try:
            if ext in MEDIA_EXTENSIONS:
                async with AsyncSessionLocal() as db:
                    await service.catalogue_media(chemin=chemin_doc, nom=Path(rel).name, taille=taille or 0, source="connector", db=db)
                    await db.commit()
            else:
                tmp = None
                try:
                    tmp = await conn.fetch_to_temp(src, rel)
                    async with AsyncSessionLocal() as db:
                        doc_id = await service.process_file(Path(tmp), source="connector", db=db)
                        doc = await db.get(Document, uuid.UUID(doc_id))
                        if doc:
                            doc.chemin = chemin_doc
                            doc.nom = Path(rel).name
                        await db.commit()
                finally:
                    if tmp and os.path.exists(tmp):
                        os.unlink(tmp)
            indexes += 1
        except Exception as e:  # noqa: BLE001 — un fichier en échec ne stoppe pas l'indexation
            log.error("Erreur indexation connecteur", fichier=rel, erreur=str(e))
        finally:
            fait += 1
            if fait % 3 == 0 or fait == total:
                await ctx.report(round(fait / total * 100) if total else 100, f"{fait}/{total} — {indexes} indexé(s)")

    log.info("Indexation connecteur terminée", source_id=sid, total=total, indexes=indexes)
    return {"total": total, "indexes": indexes, "source_id": sid}
