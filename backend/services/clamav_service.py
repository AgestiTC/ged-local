"""
Service Antivirus — ClamAV (clamd)
==================================
Scanne les fichiers AVANT indexation. Un fichier détecté infecté n'est pas
indexé (marqué en erreur). Dégradation gracieuse : si ClamAV est désactivé,
injoignable, ou si le fichier dépasse la limite INSTREAM, on NE bloque PAS
l'indexation (on log) — la sécurité ne doit pas casser le pipeline.

Convention modèle AgestiTC : sécurité maintenue, jamais de secret en log.
"""

import asyncio

from config import get_settings
from logger import get_logger

log = get_logger(__name__)
settings = get_settings()


def _enabled() -> bool:
    return bool(settings.clamav_enabled and settings.clamav_host)


def _client():
    import clamd
    return clamd.ClamdNetworkSocket(host=settings.clamav_host, port=settings.clamav_port, timeout=60)


def _scan_sync(path: str) -> tuple[bool, str | None]:
    """Retourne (clean, signature). clean=True si sain OU non scannable (gracieux)."""
    try:
        with open(path, "rb") as f:
            res = _client().instream(f)
        status, sig = res.get("stream", ("OK", None))
        if status == "FOUND":
            return False, sig
        return True, None
    except Exception as exc:
        # Trop gros (StreamMaxLength), clamd indisponible, etc. → on ne bloque pas
        log.warning("Scan antivirus impossible — fichier laissé passer", fichier=path, erreur=str(exc))
        return True, None


def _ping_sync() -> bool:
    try:
        return _client().ping() == "PONG"
    except Exception:
        return False


async def scan_file(path: str) -> tuple[bool, str | None]:
    """Scanne un fichier. Retourne (clean: bool, signature: str | None)."""
    if not _enabled():
        return True, None
    return await asyncio.to_thread(_scan_sync, path)


async def check_health() -> bool:
    """Vrai si ClamAV est activé ET répond (PONG)."""
    if not _enabled():
        return False
    return await asyncio.to_thread(_ping_sync)
