"""
Module de logging centralisé — DocFlow AI
=========================================
Utilise structlog pour un logging structuré en JSON (production)
ou en format console coloré (développement).

Usage dans les autres modules :
    from logger import get_logger
    logger = get_logger(__name__)
    logger.info("message", document_id=doc_id, action="extraction")

Format JSON (production) :
    {"timestamp": "...", "level": "info", "logger": "...", "event": "...", "document_id": "..."}

Format console (développement) :
    2026-04-10 10:00:00 [info     ] message     [document_id=... action=...]
"""

import logging
import sys
from pathlib import Path

import structlog
from structlog.types import FilteringBoundLogger


def configure_logging(
    level: str = "INFO",
    log_format: str = "json",
    log_file: str | None = None,
) -> None:
    """
    Configure le système de logging global.
    À appeler une seule fois au démarrage de l'application.

    Args:
        level: Niveau de log (DEBUG, INFO, WARNING, ERROR)
        log_format: "json" pour la production, "console" pour le développement
        log_file: Chemin vers le fichier de log (None = console seulement)
    """
    # Niveau de log Python standard
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Handlers : console + fichier si configuré
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        handlers.append(file_handler)

    # Configuration logging standard Python
    logging.basicConfig(
        level=log_level,
        handlers=handlers,
        format="%(message)s",
    )

    # Processors structlog communs
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if log_format == "json":
        # Format JSON pour la production (parsing facile, Grafana, ELK...)
        processors = shared_processors + [
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Format console coloré pour le développement
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> FilteringBoundLogger:
    """
    Retourne un logger structlog pour le module donné.

    Args:
        name: Nom du module (utiliser __name__)

    Returns:
        Logger structlog configuré
    """
    return structlog.get_logger(name)
