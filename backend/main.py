"""
Point d'entrée FastAPI — DocFlow AI
=====================================
Initialise l'application, configure le logging, monte les routers.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from logger import configure_logging, get_logger
from routers import documents, export, extract, folders, generate, prompts, search, templates, upload

settings = get_settings()

# Configurer le logging en premier (avant tout import qui loguerait)
configure_logging(
    level=settings.log_level,
    log_format=settings.log_format,
    log_file=settings.log_file,
)

log = get_logger(__name__)


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
    # TODO Phase 1 : initialiser le pool de connexions DB
    # TODO Phase 1 : vérifier la connectivité Tika + Ollama au démarrage
    yield
    log.info("DocFlow AI arrêt")


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

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001", "http://localhost:5173"],  # frontend dev + prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers ---
API_PREFIX = "/api"

app.include_router(upload.router,     prefix=API_PREFIX, tags=["Upload"])
app.include_router(extract.router,    prefix=API_PREFIX, tags=["Extraction"])
app.include_router(documents.router,  prefix=API_PREFIX, tags=["Documents"])
app.include_router(generate.router,   prefix=API_PREFIX, tags=["Génération"])
app.include_router(export.router,     prefix=API_PREFIX, tags=["Export"])
app.include_router(search.router,     prefix=API_PREFIX, tags=["Recherche"])
app.include_router(folders.router,    prefix=API_PREFIX, tags=["Dossiers"])
app.include_router(templates.router,  prefix=API_PREFIX, tags=["Templates"])
app.include_router(prompts.router,    prefix=API_PREFIX, tags=["Prompts"])


# --- Health check ---
@app.get("/health", tags=["Système"])
async def health_check():
    """Vérification de l'état de l'application."""
    return {
        "status": "ok",
        "version": settings.app_version,
        "services": {
            "tika": settings.tika_url,
            "ollama": settings.ollama_url,
        },
    }
