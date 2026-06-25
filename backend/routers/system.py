"""
Router Système — /api/version, /api/logs/tail
==============================================
Endpoints d'exploitation imposés par le modèle docker AgestiTC :

  GET /api/version      → version embarquée (source de vérité : fichier VERSION)
  GET /api/logs/tail    → N dernières lignes du fichier de log applicatif

Le liveness probe /healthz (sans préfixe) est défini dans main.py.
"""

from pathlib import Path

from fastapi import APIRouter, Query

from config import get_settings
from logger import get_logger

log = get_logger(__name__)
settings = get_settings()
router = APIRouter()


@router.get("/version", tags=["Système"])
async def get_version() -> dict:
    """Retourne la version de l'application (lue depuis le fichier VERSION racine)."""
    return {"name": settings.app_name, "version": settings.app_version}


def _tail(path: Path, n: int) -> list[str]:
    """Retourne les `n` dernières lignes d'un fichier texte (lecture robuste)."""
    if not path.exists():
        return []
    # Lecture simple ligne à ligne : suffisant pour un log applicatif rotatif.
    with path.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return [line.rstrip("\n") for line in lines[-n:]]


@router.get("/logs/tail", tags=["Système"])
async def logs_tail(
    lines: int = Query(default=100, ge=1, le=2000, description="Nombre de lignes à retourner"),
) -> dict:
    """
    Retourne les dernières lignes du log applicatif.

    NOTE : le modèle prévoit une protection « admin » sur cet endpoint.
    DocFlow AI n'a pas encore d'authentification ; la protection devra être
    ajoutée en même temps que le module auth (cf. ROADMAP).
    """
    log_file = settings.log_file
    if not log_file:
        return {"lines": [], "count": 0, "source": None}

    path = Path(log_file)
    tail = _tail(path, lines)
    return {"lines": tail, "count": len(tail), "source": str(path)}
