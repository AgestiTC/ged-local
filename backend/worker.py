"""
Entrypoint du WORKER de tâches durables — process/conteneur DÉDIÉ.
==================================================================
Isole l'exécution des jobs (indexation, analyse, enrichissement, réorganisation…)
HORS du process de l'API. Ainsi une opération lourde ou synchrone d'un handler ne
peut plus geler les routes FastAPI (l'API et le worker ne partagent plus d'event-loop).

En déploiement : l'API tourne avec **RUN_WORKER=false** (elle ne fait qu'ENFILER des
jobs) et CE process est le SEUL à exécuter le worker → une seule reprise des jobs
orphelins au démarrage (plus de double avec `uvicorn --workers`).

Lancement : `python worker.py` (voir le service `worker` des docker-compose).
"""
import asyncio

from config import get_settings
from logger import configure_logging, get_logger

settings = get_settings()
configure_logging(level=settings.log_level, log_format=settings.log_format, log_file=settings.log_file)
log = get_logger(__name__)


async def main() -> None:
    log.info("Worker dédié — démarrage", version=settings.app_version)

    # Schéma idempotent (le worker peut démarrer avant/sans l'API).
    from database import init_db
    await init_db()

    # Config runtime (URLs/modèles surchargés en base).
    try:
        from database import AsyncSessionLocal
        from services import runtime_config
        async with AsyncSessionLocal() as db:
            await runtime_config.load(db)
    except Exception as e:  # noqa: BLE001 — non bloquant
        log.warning("Config runtime non chargée (worker)", erreur=str(e))

    # Enregistrer les handlers réels (@register) PUIS démarrer la boucle.
    from services import job_handlers  # noqa: F401
    from services import connector_jobs  # noqa: F401 — handler index_connector
    from services import job_worker
    await job_worker.start()
    log.info("Worker dédié prêt — en attente de jobs", concurrence=job_worker.CONCURRENCE)

    try:
        await asyncio.Event().wait()  # tourne indéfiniment
    finally:
        await job_worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
