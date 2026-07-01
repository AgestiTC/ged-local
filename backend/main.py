"""
Point d'entrée FastAPI — DocFlow AI
=====================================
Initialise l'application, configure le logging, monte les routers.
"""

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from config import get_settings
from database import AsyncSessionLocal, close_db, init_db
from logger import configure_logging, get_logger
from routers import assistant, bookstack, compare, corbeille, documents, duplicates, export, extract, folders, generate, jobs, organize, presentations, prompts, search, sources, system, templates, upload
from services.ollama_service import OllamaService
from services.tika_service import TikaService

settings = get_settings()

# Configurer le logging en premier (avant tout import qui loguerait)
configure_logging(
    level=settings.log_level,
    log_format=settings.log_format,
    log_file=settings.log_file,
)

log = get_logger(__name__)


async def _seed_prompts() -> None:
    """
    Insère les prompts par défaut (scripts/seed-prompts.json) si la table est vide.
    Idempotent : n'insère rien si des prompts existent déjà.
    """
    from sqlalchemy import func, select
    from models.prompt import PromptPreset

    seed_file = Path(__file__).parent.parent / "scripts" / "seed-prompts.json"
    if not seed_file.exists():
        return

    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(func.count()).select_from(PromptPreset))).scalar_one()
        if count > 0:
            return  # Déjà peuplé

        try:
            presets = json.loads(seed_file.read_text(encoding="utf-8"))
        except Exception:
            return

        for data in presets:
            db.add(PromptPreset(
                nom=data["nom"],
                description=data.get("description"),
                prompt_text=data["prompt_text"],
                categorie=data.get("categorie"),
                modele_prefere=data.get("modele_prefere"),
            ))

        await db.commit()
        log.info("Prompts par défaut insérés", nb=len(presets))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Cycle de vie de l'application : startup → yield → shutdown."""
    log.info(
        "DocFlow AI démarrage",
        version=settings.app_version,
        debug=settings.debug,
        tika_url=settings.tika_url,
        ollama_url=settings.ollama_url,
    )

    # Initialiser la base de données (crée les tables si besoin en dev)
    try:
        await init_db()
        log.info("Base de données initialisée")
    except Exception as e:
        log.error("Erreur initialisation DB", erreur=str(e))
        raise

    # Insérer les prompts par défaut (si la table est vide)
    try:
        await _seed_prompts()
        log.info("Prompts par défaut vérifiés")
    except Exception as e:
        log.warning("Impossible de seeder les prompts", erreur=str(e))

    # Charger la config runtime (surcharges URLs/modèle depuis la base)
    try:
        from services import runtime_config
        async with AsyncSessionLocal() as db:
            await runtime_config.load(db)
    except Exception as e:
        log.warning("Impossible de charger la config runtime", erreur=str(e))

    # Vérifier la connectivité des services externes (non bloquant)
    tika = TikaService()
    ollama = OllamaService()

    tika_ok = await tika.check_health()
    ollama_ok = await ollama.check_health()

    if tika_ok:
        log.info("Tika disponible", url=settings.tika_url)
    else:
        log.warning("Tika NON disponible — extraction documentaire indisponible", url=settings.tika_url)

    if ollama_ok:
        try:
            modeles = await ollama.list_models()
            log.info("Ollama disponible", url=settings.ollama_url, nb_modeles=len(modeles))
        except Exception:
            log.info("Ollama disponible", url=settings.ollama_url)
    else:
        log.warning("Ollama NON disponible — génération et embeddings indisponibles", url=settings.ollama_url)

    # Démarrer le worker de tâches durables (file `jobs`) + reprise des jobs orphelins.
    # Importer les handlers réels AVANT le start pour peupler le registre.
    try:
        from services import job_handlers  # noqa: F401 — enregistre les handlers (@register)
        from services import job_worker
        await job_worker.start()
    except Exception as e:
        log.error("Impossible de démarrer le worker de jobs", erreur=str(e))

    yield

    # Shutdown
    log.info("DocFlow AI arrêt")
    try:
        from services import job_worker
        await job_worker.stop()
    except Exception:
        pass
    await close_db()


# --- Application FastAPI ---
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Plateforme locale de gestion documentaire intelligente",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# --- Gestionnaires d'erreurs globaux ---

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Retourne un message lisible pour les erreurs de validation Pydantic (422)."""
    errors = exc.errors()
    detail = "; ".join(
        f"{' → '.join(str(l) for l in e['loc'])}: {e['msg']}"
        for e in errors
    )
    log.warning("Erreur de validation", path=str(request.url.path), detail=detail)
    return JSONResponse(status_code=422, content={"detail": detail})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    """Capture toute exception non gérée — évite les stack traces en prod."""
    log.error(
        "Erreur interne non gérée",
        path=str(request.url.path),
        erreur=str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Erreur interne du serveur. Consultez les logs pour le détail."},
    )


# --- CORS ---
# Origines autorisées : depuis CORS_ORIGINS (CSV) ou les valeurs par défaut
_cors_origins_env = os.environ.get("CORS_ORIGINS", "")
_cors_origins = (
    [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
    if _cors_origins_env
    else ["http://localhost:3001", "http://localhost:3003", "http://localhost:5173"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers ---
API_PREFIX = "/api"

app.include_router(compare.router,    prefix=API_PREFIX, tags=["Comparatif"])
app.include_router(upload.router,     prefix=API_PREFIX, tags=["Upload"])
app.include_router(extract.router,    prefix=API_PREFIX, tags=["Extraction"])
app.include_router(documents.router,  prefix=API_PREFIX, tags=["Documents"])
app.include_router(duplicates.router, prefix=API_PREFIX, tags=["Doublons"])
app.include_router(corbeille.router,  prefix=API_PREFIX, tags=["Corbeille"])
app.include_router(presentations.router, prefix=API_PREFIX, tags=["Présentations"])
app.include_router(assistant.router,  prefix=API_PREFIX, tags=["Assistant"])
app.include_router(organize.router,   prefix=API_PREFIX, tags=["Réorganisation"])
app.include_router(generate.router,   prefix=API_PREFIX, tags=["Génération"])
app.include_router(export.router,     prefix=API_PREFIX, tags=["Export"])
app.include_router(search.router,     prefix=API_PREFIX, tags=["Recherche"])
app.include_router(folders.router,    prefix=API_PREFIX, tags=["Dossiers"])
app.include_router(sources.router,    prefix=API_PREFIX, tags=["Sources"])
app.include_router(templates.router,  prefix=API_PREFIX, tags=["Templates"])
app.include_router(prompts.router,    prefix=API_PREFIX, tags=["Prompts"])
app.include_router(bookstack.router,  prefix=API_PREFIX, tags=["BookStack"])
app.include_router(system.router,     prefix=API_PREFIX, tags=["Système"])
app.include_router(jobs.router,       prefix=API_PREFIX, tags=["Jobs"])


# --- Liveness probe (modèle docker AgestiTC) ---
@app.get("/healthz", tags=["Système"])
async def healthz():
    """
    Liveness probe minimaliste : ne fait aucun appel externe.
    Utilisé par le smoke test CI et l'orchestrateur. Retourne toujours 200
    si le process répond.
    """
    return {"status": "ok"}


# --- Health check ---
@app.get("/health", tags=["Système"])
async def health_check():
    """Vérification rapide de l'état de l'application."""
    import httpx

    from services import runtime_config

    tika = TikaService()
    ollama = OllamaService()
    n8n_url = runtime_config.effective("n8n_url")

    tika_ok = await tika.check_health()
    ollama_ok = await ollama.check_health()

    n8n_ok = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{n8n_url}/healthz")
            n8n_ok = resp.status_code == 200
    except Exception:
        pass

    return {
        "status": "ok",
        "version": settings.app_version,
        "services": {
            "tika": {"url": tika.base_url, "disponible": tika_ok},
            "ollama": {"url": ollama.base_url, "disponible": ollama_ok},
            "n8n": {"url": n8n_url, "disponible": n8n_ok},
        },
    }
