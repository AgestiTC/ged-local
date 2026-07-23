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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, text, update

from database import AsyncSessionLocal
from logger import get_logger
from models.job import Job

log = get_logger(__name__)

# Nombre de jobs exécutés en parallèle par le worker.
CONCURRENCE = 2

# Au-delà de ce nombre de reprises (running→pending après crash), un job est déclaré `failed`
# plutôt que relancé en boucle (jobs fantômes qui bloqueraient la file).
MAX_REPRISES = 3

# Un job `pending` d'un type SANS handler (ex. `rapport`, traité par une background task API et non
# par le worker) qui dépasse cet âge n'a jamais démarré → il est annulé (fantôme). Grâce assez
# longue pour laisser la background task le passer `running`.
AGE_PENDING_FANTOME_MIN = 15.0

# Registre { type_de_job -> handler async(ctx) -> dict|None }
_HANDLERS: dict = {}
# Ids de jobs `running` dont l'annulation a été demandée (best effort : le handler doit
# vérifier `ctx.cancelled` à des points sûrs).
_cancel_requested: set[str] = set()
_worker_task: asyncio.Task | None = None
_backup_task: asyncio.Task | None = None
_sync_task: asyncio.Task | None = None
_prewarm_task: asyncio.Task | None = None


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
    """
    Insère un job `pending` et renvoie son id (le commit reste à la charge de l'appelant).
    Injecte un **`correlation_id`** dans les paramètres s'il n'y en a pas → tout job est traçable
    de l'enfilement (API) jusqu'à son exécution (worker) sous le même identifiant (audit Phase 2).
    """
    from services import audit
    params = dict(parametres or {})
    cid = params.get("correlation_id") or audit.new_correlation_id()
    params["correlation_id"] = cid
    job = Job(type=type, statut="pending", parametres=params, progress=0, document_id=document_id)
    db.add(job)
    await db.flush()
    await audit.emit(type, "queued", acteur="api", correlation_id=cid,
                     cible=params.get("cible") or (str(document_id) if document_id else None),
                     detail={"job_id": str(job.id)})
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
        # Recharge la config runtime AVANT chaque job → le worker prend les derniers
        # réglages UI (URLs, tokens re-saisis) sans redémarrage du conteneur.
        try:
            from services import runtime_config
            await runtime_config.load(db)
        except Exception as e:  # noqa: BLE001 — un échec de reload ne doit pas bloquer le job
            log.warning("Reload runtime_config avant job impossible", erreur=str(e))

    # Audit (Phase 2) : `correlation_id` porté par les paramètres du job (posé à l'enqueue) →
    # relie l'événement worker à l'action API/UI qui l'a déclenché. `cible` = ce qui est traité.
    from services import audit
    import time as _time
    cid = ctx.parametres.get("correlation_id")
    cible = ctx.parametres.get("cible") or (str(ctx.document_id) if ctx.document_id else None)
    t0 = _time.monotonic()
    await audit.emit(ctx.type, "start", acteur="worker", correlation_id=cid, cible=cible,
                     detail={"job_id": job_id})

    handler = _HANDLERS.get(ctx.type)
    if handler is None:
        log.warning("Aucun handler pour le job", job_id=job_id, type=ctx.type)
        await _finaliser(job_id, "failed", erreur=f"Aucun handler pour le type '{ctx.type}'")
        await audit.emit(ctx.type, "error", acteur="worker", correlation_id=cid, cible=cible,
                         message=f"Aucun handler pour le type '{ctx.type}'")
        _cancel_requested.discard(job_id)
        return

    def _ms() -> int:
        return int((_time.monotonic() - t0) * 1000)

    try:
        resultat = await handler(ctx)
        if ctx.cancelled:
            await _finaliser(job_id, "cancelled", resultat=resultat if isinstance(resultat, dict) else None)
            log.info("Job annulé", job_id=job_id, type=ctx.type)
            await audit.emit(ctx.type, "cancelled", acteur="worker", correlation_id=cid, cible=cible, duree_ms=_ms())
        else:
            await _finaliser(job_id, "completed", resultat=resultat if isinstance(resultat, dict) else {}, progress=100)
            log.info("Job terminé", job_id=job_id, type=ctx.type)
            await audit.emit(ctx.type, "success", acteur="worker", correlation_id=cid, cible=cible,
                             duree_ms=_ms(), detail=resultat if isinstance(resultat, dict) else None)
    except Exception as e:  # noqa: BLE001 — un job qui échoue ne doit pas tuer le worker
        log.error("Job échoué", job_id=job_id, type=ctx.type, erreur=str(e))
        await _finaliser(job_id, "failed", erreur=str(e))
        await audit.emit(ctx.type, "error", acteur="worker", correlation_id=cid, cible=cible,
                         duree_ms=_ms(), message=f"{type(e).__name__}: {e}")
    finally:
        _cancel_requested.discard(job_id)


async def _claim(libres: int) -> list[str]:
    """Réserve atomiquement jusqu'à `libres` jobs pending → running (FOR UPDATE SKIP LOCKED).

    ⚠️ On ne réclame QUE les types possédant un handler enregistré. Certains « jobs » de la table
    (ex. `rapport`) ne sont PAS traités par ce worker mais par une *background task* FastAPI dans
    l'API — la ligne `jobs` ne sert qu'au suivi. Sans ce filtre, le worker rafle ces jobs, ne
    trouve pas de handler et les marque `failed` (« Aucun handler pour le type 'rapport' »). C'était
    masqué tant que la file était saturée de synchros ; dès qu'elle se vide, la course se perd."""
    if libres <= 0:
        return []
    types = list(_HANDLERS.keys())
    if not types:
        return []
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Job.id).where(Job.statut == "pending", Job.type.in_(types))
            .order_by(Job.created_at).limit(libres).with_for_update(skip_locked=True)
        )).scalars().all()
        ids = [str(r) for r in rows]
        if ids:
            await db.execute(
                update(Job).where(Job.id.in_(rows)).values(statut="running", started_at=_now(), progress=0)
            )
            await db.commit()
        return ids


async def _purger_pending_fantomes() -> None:
    """
    Annule les jobs `pending` d'un type SANS handler (ex. `rapport`) plus vieux que
    `AGE_PENDING_FANTOME_MIN` : ils ne seront jamais réclamés par le worker (`_claim` filtre par
    type) et resteraient `pending` à vie. C'est ce qu'on a dû nettoyer à la main le 23/07.
    """
    types = list(_HANDLERS.keys())
    limite = _now() - timedelta(minutes=AGE_PENDING_FANTOME_MIN)
    async with AsyncSessionLocal() as db:
        cond = (Job.statut == "pending") & (Job.created_at < limite)
        if types:
            cond = cond & Job.type.notin_(types)
        res = await db.execute(update(Job).where(cond).values(
            statut="cancelled", completed_at=_now(),
            erreur="Annulé automatiquement (job pending fantôme : aucun handler)"))
        await db.commit()
        if res.rowcount:
            log.warning("Jobs pending fantômes annulés", nb=res.rowcount)


async def _relire_annulations() -> None:
    """
    Peuple `_cancel_requested` depuis la BASE : l'annulation est demandée par l'API (autre
    process) via la colonne `jobs.annulation_demandee`. Le worker la relit à chaque tick pour que
    `ctx.cancelled` (synchrone, lit le set local) la voie — c'est ce qui manquait (« Annuler »
    sans effet en déploiement API/worker séparés).
    """
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Job.id).where(Job.statut == "running", Job.annulation_demandee.is_(True))
        )).scalars().all()
    for r in rows:
        _cancel_requested.add(str(r))


async def _worker_loop() -> None:
    en_cours: set[asyncio.Task] = set()
    while True:
        try:
            await _relire_annulations()   # propage les annulations demandées via la base
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


# Clé de verrou d'avis Postgres pour la reprise des orphelins (arbitraire, propre à ce projet).
_REPRISE_LOCK = 918273645


def purger_temporaires(age_heures: float = 6.0) -> int:
    """
    Supprime les temporaires ORPHELINS (`/tmp/tmp*`) laissés par les fetch SMB interrompus.

    Les appelants suppriment normalement leur temporaire dans un `finally` — mais celui-ci **ne
    s'exécute pas** si le process est tué (conteneur redémarré, disque plein, job annulé). Résultat
    vécu le 21/07 : **3 740 fichiers / 15 Go** dans le worker (dont un ZIP de 8,9 Go), disque saturé
    et PostgreSQL bloqué. On ne touche qu'aux fichiers plus vieux que `age_heures` : les traitements
    en cours (récents) sont épargnés.
    """
    import tempfile as _tf
    import time as _t

    limite = _t.time() - age_heures * 3600
    nb, octets = 0, 0
    try:
        for f in Path(_tf.gettempdir()).glob("tmp*"):
            try:
                st = f.stat()
                if f.is_file() and st.st_mtime < limite:
                    octets += st.st_size
                    f.unlink()
                    nb += 1
            except OSError:
                pass
    except OSError:
        return 0
    if nb:
        log.warning("Temporaires orphelins purgés", nb=nb, octets=octets, age_heures=age_heures)
    return nb


async def _purger_rapports_anciens() -> None:
    """Supprime les rapports de l'historique plus vieux que `rapports_purge_jours` (0 = jamais)."""
    from services import runtime_config
    try:
        jours = int(float(runtime_config.effective("rapports_purge_jours") or 0))
    except (TypeError, ValueError):
        jours = 0
    if jours <= 0:
        return
    from sqlalchemy import delete as _delete
    from models.rapport import Rapport
    limite = _now() - timedelta(days=jours)
    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(_delete(Rapport).where(Rapport.created_at < limite))
            await db.commit()
            if res.rowcount:
                log.info("Historique des rapports purgé", supprimes=res.rowcount, jours=jours)
    except Exception as e:  # noqa: BLE001
        log.warning("Purge de l'historique échouée", erreur=str(e))


async def _backup_scheduler() -> None:
    """
    Sauvegarde AUTOMATIQUE de la base par le worker : `pg_dump` toutes les N heures + purge des
    plus anciennes (config `backup_auto_heures` / `backup_retention`, éditables à chaud).

    Tourne dans le worker (process unique), pas dans l'API (multi-uvicorn). Une sauvegarde ratée
    est journalisée mais **ne tue pas** le planificateur. Délai initial pour ne pas dumper au boot.
    """
    from services import backup, runtime_config

    def _heures() -> float:
        try:
            return float(runtime_config.effective("backup_auto_heures") or 0)
        except (TypeError, ValueError):
            return 0.0

    await asyncio.sleep(300)   # laisse le démarrage se stabiliser
    while True:
        # Purge périodique des temporaires orphelins : sur une indexation longue (65k fichiers),
        # /tmp ne doit jamais gonfler même si des traitements ont été interrompus.
        purger_temporaires()
        # Purge de l'historique des rapports (rapports_purge_jours ; 0 = jamais).
        await _purger_rapports_anciens()
        # Annule les jobs pending fantômes (type sans handler resté pending trop longtemps).
        try:
            await _purger_pending_fantomes()
        except Exception as e:  # noqa: BLE001
            log.warning("Purge des pending fantômes échouée", erreur=str(e))
        heures = _heures()
        if heures <= 0:
            await asyncio.sleep(1800)   # désactivé : on relit la config dans 30 min
            continue
        try:
            garder = int(runtime_config.effective("backup_retention") or 4)
        except (TypeError, ValueError):
            garder = 4
        try:
            # Purge AVANT le dump : libère la place du plus ancien pour accueillir le nouveau
            # (sur un petit disque, purger après ne servait à rien — le dump échouait avant).
            backup.prune(max(garder - 1, 1))
            info = await backup.dump()
            log.info("Sauvegarde auto effectuée", **info, retention=garder)
        except Exception as e:  # noqa: BLE001 — ne jamais laisser une sauvegarde ratée arrêter le cycle
            log.error("Sauvegarde auto échouée", erreur=str(e), libre=backup.espace_libre())
        finally:
            # Purge même en cas d'ÉCHEC : sinon les tentatives ratées s'accumulaient sans
            # jamais nettoyer (incident 21/07 : 12 fichiers résiduels + disque plein).
            try:
                backup.prune(garder)
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(max(_heures(), 0.1) * 3600)


# Clé de verrou d'avis Postgres pour la planification des synchros (un seul process planifie).
_SYNC_LOCK = 918273646

# Périodicité du tick de planification. Ce n'est PAS l'intervalle des synchros (réglé par source) :
# c'est la fréquence à laquelle on regarde si l'une d'elles est due.
TICK_SYNC_S = 300


def synchro_due(dernier_sync: datetime | None, intervalle_minutes: int | None,
                maintenant: datetime | None = None) -> bool:
    """
    Une synchro est-elle due ? Fonction PURE (testable sans base).

    - intervalle absent/nul/négatif → synchro auto désactivée ;
    - jamais synchronisée → due immédiatement ;
    - sinon due une fois l'intervalle écoulé depuis le dernier passage.
    """
    if not intervalle_minutes or intervalle_minutes <= 0:
        return False
    if dernier_sync is None:
        return True
    return dernier_sync + timedelta(minutes=intervalle_minutes) <= (maintenant or _now())


async def _planifier_syncs() -> int:
    """
    Enfile une synchro pour chaque source dont l'intervalle est écoulé. Renvoie le nombre de
    sources déclenchées.

    Trois garde-fous :
    - **verrou d'avis Postgres** : en multi-process, un seul planifie (sinon N fois les jobs) ;
    - **jamais deux fois la même source** : si un `sync_source` ou une `indexation` de cette
      source est déjà en attente/en cours, on passe son tour (une synchro pendant une indexation
      manuelle se marcheraient dessus) ;
    - `dernier_sync` est daté **à l'enfilement**, pas à la fin : un scan long ne provoque pas
      une rafale de re-planifications au tick suivant.
    """
    from models.source import Source
    from routers.sources import _scopes_indexes

    declenchees = 0
    async with AsyncSessionLocal() as db:
        # Verrou **transactionnel** (`_xact_`) : libéré automatiquement au COMMIT/ROLLBACK.
        # ⚠️ Ne PAS utiliser `pg_try_advisory_lock` ici : un `commit()` rend la connexion au pool,
        # et l'`unlock` du `finally` s'exécuterait alors sur une AUTRE connexion — il ne libérerait
        # rien et le verrou resterait pris à vie (constaté : tous les ticks suivants renonçaient
        # en silence, `pg_locks` montrait le verrou tenu par une connexion `idle`).
        got = (await db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _SYNC_LOCK})).scalar()
        if not got:
            return 0
        sources = (await db.execute(
            select(Source).where(Source.actif.is_(True), Source.sync_intervalle_minutes > 0)
        )).scalars().all()

        for src in sources:
            if not synchro_due(src.dernier_sync, src.sync_intervalle_minutes):
                continue

            occupee = (await db.execute(text(
                "SELECT 1 FROM jobs WHERE statut IN ('pending','running') "
                "AND type IN ('sync_source','indexation') "
                "AND parametres->>'source_id' = :sid LIMIT 1"
            ), {"sid": str(src.id)})).scalar()
            if occupee:
                log.info("Synchro auto reportée — la source est déjà occupée", source=src.libelle)
                continue

            scopes = await _scopes_indexes(db, src)
            if not scopes:
                continue   # rien d'indexé : rien à comparer

            for sc in scopes:
                await enqueue(db, "sync_source", {"source_id": str(src.id),
                                                  "chemin": sc["chemin"], "partage": sc["partage"],
                                                  "auto": True})
            src.dernier_sync = _now()
            declenchees += 1
            log.info("Synchro auto planifiée", source=src.libelle, nb_scopes=len(scopes),
                     intervalle_min=src.sync_intervalle_minutes)

        # Un seul commit, en fin de transaction : il valide les jobs enfilés ET libère le verrou.
        await db.commit()
    return declenchees


async def _sync_scheduler() -> None:
    """Tick de planification des synchros automatiques. Une erreur n'arrête jamais le cycle."""
    await asyncio.sleep(120)   # laisse le démarrage se stabiliser
    while True:
        try:
            await _planifier_syncs()
        except Exception as e:  # noqa: BLE001
            log.error("Planification des synchros échouée", erreur=str(e))
        await asyncio.sleep(TICK_SYNC_S)


async def _prewarm_scheduler() -> None:
    """
    Maintient le GROS modèle de rapport **résident** en mémoire, pour éviter qu'un premier rapport
    après inactivité doive le recharger à froid (43 Go → plusieurs minutes, risque de 502 via le
    proxy). Modèle **lu dans les Paramètres** (`model_for("rapport")`), jamais en dur → suit un
    changement de modèle sans redéploiement. Période < `keep_alive` pour ne jamais se décharger.

    Best effort : Ollama injoignable ou modèle absent ⇒ on log et on réessaie au tour suivant,
    jamais d'arrêt du planificateur. Cf. mémoire cold-load — approche à améliorer plus tard.
    """
    from config import get_settings
    from services import runtime_config
    from services.ollama_service import OllamaService

    settings = get_settings()
    if not settings.ollama_prewarm_enabled:
        log.info("Pré-chargement du modèle désactivé (OLLAMA_PREWARM_ENABLED=false)")
        return

    ollama = OllamaService()
    await asyncio.sleep(30)   # laisse le démarrage se stabiliser avant de charger 43 Go
    while True:
        modele = runtime_config.model_for("rapport")
        try:
            if modele and not await ollama.is_loaded(modele):
                ok = await ollama.warm(modele)
                if ok:
                    log.info("Modèle de rapport pré-chargé (maintenu chaud)", modele=modele)
        except Exception as e:  # noqa: BLE001 — ne jamais laisser le prewarm tuer le worker
            log.warning("Pré-chargement — cycle en erreur", erreur=str(e) or type(e).__name__)
        minutes = max(settings.ollama_prewarm_minutes, 1.0)
        await asyncio.sleep(minutes * 60)


async def start() -> None:
    """Démarre le worker : reprise des jobs orphelins puis lancement de la boucle."""
    global _worker_task, _backup_task, _sync_task, _prewarm_task
    # Reprise : jobs restés 'running' après un crash → remis 'pending'.
    # ⚠️ En prod l'API tourne avec plusieurs process uvicorn (`--workers`), donc plusieurs boucles
    # worker. On protège la reprise par un **verrou d'avis Postgres** : UN SEUL process remet les
    # orphelins au démarrage (sinon double reset concurrent / risque de ré-injection d'un job en cours).
    async with AsyncSessionLocal() as db:
        # Verrou TRANSACTIONNEL : libéré par le commit. L'ancienne version prenait un verrou de
        # session puis committait avant de le relâcher — l'`unlock` tombait sur une autre
        # connexion du pool et le verrou FUYAIT, si bien que les démarrages suivants sautaient
        # définitivement la reprise (« déléguée à un autre worker » alors qu'il n'y en avait pas).
        got = (await db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _REPRISE_LOCK})).scalar()
        if got:
            # Jobs fantômes : au-delà de MAX_REPRISES tentatives de reprise, on déclare le job
            # `failed` au lieu de le relancer indéfiniment (un job qui crashe le worker à chaque
            # exécution le bloquerait sinon en boucle). Sinon : running→pending, reprises + 1.
            morts = await db.execute(
                update(Job).where(Job.statut == "running", Job.reprises >= MAX_REPRISES)
                .values(statut="failed", completed_at=_now(),
                        erreur=f"Abandonné après {MAX_REPRISES} reprises (job instable)")
            )
            res = await db.execute(
                update(Job).where(Job.statut == "running")
                .values(statut="pending", started_at=None, progress=0,
                        annulation_demandee=False, reprises=Job.reprises + 1)
            )
            await db.commit()
            if res.rowcount:
                log.warning("Jobs orphelins remis en attente au démarrage", nb=res.rowcount,
                            abandonnes=morts.rowcount or 0)
        else:
            log.info("Reprise des orphelins déléguée à un autre worker (verrou déjà pris)")
    # Nettoie les temporaires laissés par un arrêt brutal précédent (fetch SMB interrompu).
    purger_temporaires()
    _worker_task = asyncio.create_task(_worker_loop())
    _backup_task = asyncio.create_task(_backup_scheduler())   # sauvegarde auto de la base
    _sync_task = asyncio.create_task(_sync_scheduler())       # synchro auto des sources
    _prewarm_task = asyncio.create_task(_prewarm_scheduler()) # garde le modèle de rapport chaud
    log.info("Worker de jobs démarré", concurrence=CONCURRENCE, handlers=sorted(_HANDLERS))


async def stop() -> None:
    """Arrête proprement la boucle worker + les planificateurs (sauvegarde, synchro)."""
    global _worker_task, _backup_task, _sync_task, _prewarm_task
    for tache in (_worker_task, _backup_task, _sync_task, _prewarm_task):
        if tache:
            tache.cancel()
            try:
                await tache
            except asyncio.CancelledError:
                pass
    _worker_task = None
    _backup_task = None
    _sync_task = None
    _prewarm_task = None


async def request_cancel(db, job_id: str) -> str | None:
    """
    Demande l'annulation d'un job. `pending` → annulé direct ; `running` → drapeau EN BASE
    (`annulation_demandee`) que le worker relit à chaque tick (`_relire_annulations`). On met
    aussi à jour le set local au cas où API et worker partagent le process (mono-conteneur).
    """
    job = await db.get(Job, uuid.UUID(job_id))
    if not job:
        return None
    if job.statut == "pending":
        job.statut = "cancelled"
        job.completed_at = _now()
        await db.commit()
    elif job.statut == "running":
        job.annulation_demandee = True
        await db.commit()
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
