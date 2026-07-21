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
import logging.handlers
import sys
from pathlib import Path

import structlog
from structlog.types import FilteringBoundLogger

# État du handler FICHIER, renseigné par `configure_logging`. Permet à `/api/logs/tail` de dire
# « je suis aveugle et voici pourquoi » au lieu de renvoyer une liste vide indistinguable d'un
# fichier légitimement vide.
_ETAT_FICHIER: dict = {"actif": False, "chemin": None, "erreur": "logging non configuré"}


def etat_fichier_log() -> dict:
    """{actif, chemin, erreur} — le fichier de log est-il réellement écrit ?"""
    return dict(_ETAT_FICHIER)


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
        # Tolérant aux pannes : si le fichier de log n'est pas accessible en
        # écriture (ex : conteneur non-root sur un bind-mount non chown'é), on
        # NE crashe PAS — la sortie stdout (docker logs) reste assurée.
        # ⚠️ Mais on MÉMORISE l'échec (`etat_fichier()`) : avant, la bascule sur stdout
        # était totalement silencieuse et la page Logs affichait « aucune ligne » sans
        # pouvoir dire qu'elle était aveugle (prod aveugle pendant des jours).
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            # ROTATION obligatoire : sans elle le fichier grossit sans fin (261 Mo constatés en
            # dev) et finit par remplir le disque — on a déjà eu deux pannes pour disque plein.
            # 10 Mo × 3 archives = 40 Mo max, largement suffisant pour du diagnostic.
            file_handler = logging.handlers.RotatingFileHandler(
                log_path, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8",
            )
            handlers.append(file_handler)
            _ETAT_FICHIER.update(actif=True, chemin=str(log_path), erreur=None)
        except OSError as exc:
            _ETAT_FICHIER.update(actif=False, chemin=log_file, erreur=str(exc))
            print(
                f"[logger] Fichier de log '{log_file}' inaccessible "
                f"({exc}) — sortie stdout uniquement.",
                file=sys.stderr,
            )
    else:
        _ETAT_FICHIER.update(actif=False, chemin=None, erreur="LOG_FILE non configuré")

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
        logger_factory=structlog.stdlib.LoggerFactory(),
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
