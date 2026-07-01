"""
Worker de tâches durables — file `jobs` en base
================================================
Un worker asyncio unique, démarré au startup, consomme les jobs `pending` de la table
`jobs` (FIFO), les exécute via un **handler enregistré par type**, écrit progression et
résultat **en base** (donc consultables depuis n'importe où / survivent au changement de
page ou à la fermeture du navigateur). Au démarrage, les jobs restés `running` après un
crash sont **remis en attente** (reprise).

Enregistrer un handler ::

    from services import job_worker

    @job_worker.register("mon_type")
    async def _handler(ctx: job_worker.JobContext) -> dict:
        await ctx.report(progress=50, message="à mi-parcours…")
        if ctx.cancelled:
            return {}
        return {"resultat": "..."}

Mettre un job en file (dans un endpoint) ::

    job_id = await job_worker.enqueue(db, "mon_type", {"param": 1})
"""

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update

from database import AsyncSessionLocal
from logger import get_logger
from models.job import Job

log = get_logger(__name__)

# Nombre de jobs exécutés en parallèle par le worker.
CONCURRENCE = 2

# Registre { type_de_job -> handler async(ctx) -> dict|None }
_HANDLERS: dict = {}
# Ids de jobs `running` dont l'annulation a été demandée (best effort : le handler doit
# vérifier `ctx.cancelled` à des points sûrs).
_cancel_requested: set[str] = set()
_worker_task: asyncio.Task | None = None


def register(job_type: str):
    """Décorateur : enregistre un handler pour un type de job."""
    def deco(fn):
        _HANDLERS[job_type] = fn
        return fn
    return deco


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class JobContext:
    """Contexte passé au handler : paramètres du job + rapport de progression + annulation."""

    def __init__(self, job_id: str, type: str, parametres: dict | None, document_id):
        self.job_id = job_id
        self.type = type
        self.parametres = parametres or {}
        self.document_id = document_id

    @property
    def cancelled(self) -> bool:
        return self.job_id in _cancel_requested

    async def report(self, progress: int | None = None, message: str | None = None) -> None:
        """Écrit la progression du job en base (visible via GET /api/jobs/{id})."""
        vals: dict = {}
        if progress is not None:
            vals["progress"] = max(0, min(100, int(progress)))
        if message is not None:
            vals["progress_message"] = message[:500]
        if not vals:
            return
        async with AsyncSessionLocal() as db:
            await db.execute(update(Job).where(Job.id == uuid.UUID(self.job_id)).values(**vals))
            await db.commit()


async def enqueue(db, type: str, parametres: dict | None = None, document_id=None) -> str:
    """Insère un job `pending` et renvoie son id (le commit reste à la charge de l'appelant)."""
    job = Job(type=type, statut="pending", parametres=parametres or {}, progress=0, document_id=document_id)
    db.add(job)
    await db.flush()
    return str(job.id)


async def _finaliser(job_id: str, statut: str, *, resultat: dict | None = None, erreur: str | None = None,
                     progress: int | None = None) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, uuid.UUID(job_id))
        if not job:
            return
        job.statut = statut
        job.completed_at = _now()
        if resultat is not None:
            job.resultat = resultat
        if erreur is not None:
            job.erreur = erreur[:1000]
        if progress is not None:
            job.progress = progress
        await db.commit()


async def _run(job_id: str) -> None:
    """Exécute un job déjà passé en `running` : dispatch vers le handler, finalise le statut."""
    # Charger les paramètres (valeurs simples, détachées de la session)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, uuid.UUID(job_id))
        if not job:
            return
        ctx = JobContext(job_id, job.type, job.parametres, job.document_id)

    handler = _HANDLERS.get(ctx.type)
    if handler is None:
        log.warning("Aucun handler pour le job", job_id=job_id, type=ctx.type)
        await _finaliser(job_id, "failed", erreur=f"Aucun handler pour le type '{ctx.type}'")
        _cancel_requested.discard(job_id)
        return

    try:
        resultat = await handler(ctx)
        if ctx.cancelled:
            await _finaliser(job_id, "cancelled", resultat=resultat if isinstance(resultat, dict) else None)
            log.info("Job annulé", job_id=job_id, type=ctx.type)
        else:
            await _finaliser(job_id, "completed", resultat=resultat if isinstance(resultat, dict) else {}, progress=100)
            log.info("Job terminé", job_id=job_id, type=ctx.type)
    except Exception as e:  # noqa: BLE001 — un job qui échoue ne doit pas tuer le worker
        log.error("Job échoué", job_id=job_id, type=ctx.type, erreur=str(e))
        await _finaliser(job_id, "failed", erreur=str(e))
    finally:
        _cancel_requested.discard(job_id)


async def _claim(libres: int) -> list[str]:
    """Réserve atomiquement jusqu'à `libres` jobs pending → running (FOR UPDATE SKIP LOCKED)."""
    if libres <= 0:
        return []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Job.id).where(Job.statut == "pending")
            .order_by(Job.created_at).limit(libres).with_for_update(skip_locked=True)
        )).scalars().all()
        ids = [str(r) for r in rows]
        if ids:
            await db.execute(
                update(Job).where(Job.id.in_(rows)).values(statut="running", started_at=_now(), progress=0)
            )
            await db.commit()
        return ids


async def _worker_loop() -> None:
    en_cours: set[asyncio.Task] = set()
    while True:
        try:
            ids = await _claim(CONCURRENCE - len(en_cours))
            for jid in ids:
                t = asyncio.create_task(_run(jid))
                en_cours.add(t)
                t.add_done_callback(en_cours.discard)
            # Rythme : court s'il reste des slots occupés, plus long si tout est vide.
            await asyncio.sleep(0.3 if (ids or en_cours) else 1.0)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — le worker ne doit jamais s'arrêter sur une erreur
            log.error("Erreur dans la boucle worker", erreur=str(e))
            await asyncio.sleep(1.0)


async def start() -> None:
    """Démarre le worker : reprise des jobs orphelins puis lancement de la boucle."""
    global _worker_task
    # Reprise : jobs restés 'running' après un crash → remis 'pending'.
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            update(Job).where(Job.statut == "running").values(statut="pending", started_at=None, progress=0)
        )
        await db.commit()
        if res.rowcount:
            log.warning("Jobs orphelins remis en attente au démarrage", nb=res.rowcount)
    _worker_task = asyncio.create_task(_worker_loop())
    log.info("Worker de jobs démarré", concurrence=CONCURRENCE, handlers=sorted(_HANDLERS))


async def stop() -> None:
    """Arrête proprement la boucle worker."""
    global _worker_task
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None


async def request_cancel(db, job_id: str) -> str | None:
    """Demande l'annulation d'un job. `pending` → annulé direct ; `running` → best effort."""
    job = await db.get(Job, uuid.UUID(job_id))
    if not job:
        return None
    if job.statut == "pending":
        job.statut = "cancelled"
        job.completed_at = _now()
        await db.commit()
    elif job.statut == "running":
        _cancel_requested.add(str(job.id))
    return job.statut


# ─── Handler de démonstration (preuve de bout en bout, sans effet de bord) ──────────────
@register("demo")
async def _handler_demo(ctx: JobContext) -> dict:
    """Job de démo : progresse par étapes en dormant, pour valider le pipeline durable."""
    etapes = int(ctx.parametres.get("etapes", 5))
    for i in range(etapes):
        if ctx.cancelled:
            break
        await asyncio.sleep(1.0)
        await ctx.report(progress=round((i + 1) / etapes * 100), message=f"Étape {i + 1}/{etapes}")
    return {"message": "Démo terminée", "etapes": etapes}
