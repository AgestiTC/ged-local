"""
Vigie de la boucle asyncio — rend visibles les gels du backend.

Incident du 01/10/2026 : les deux process uvicorn ont cessé de répondre ~70 s (voyants tous
rouges, « Chargement de l'arborescence impossible ») sans une ligne d'erreur dans les logs.
Impossible de dire après coup ce qu'ils faisaient.

Deux niveaux :
  - un battement toutes les secondes ; s'il arrive en retard de plus de `seuil_lent`, on le
    journalise (la boucle a été bloquée par du code synchrone) ;
  - `faulthandler.dump_traceback_later`, réarmé à chaque battement : si la boucle ne revient
    pas sous `seuil_piles`, un thread C écrit la pile de TOUS les threads sur stderr. Il
    fonctionne même quand le GIL est confisqué par une extension C — le cas où le ping
    d'uvicorn échoue lui aussi, donc exactement celui qu'on veut attraper.
"""
from __future__ import annotations

import asyncio
import faulthandler
import sys
import time

import structlog

log = structlog.get_logger(__name__)

_PAS = 1.0

_tache: asyncio.Task | None = None


async def _battre(seuil_lent: float, seuil_piles: float) -> None:
    attendu = time.monotonic() + _PAS
    while True:
        faulthandler.dump_traceback_later(seuil_piles, repeat=False, file=sys.stderr)
        await asyncio.sleep(_PAS)
        maintenant = time.monotonic()
        retard = maintenant - attendu
        attendu = maintenant + _PAS
        if retard > seuil_lent:
            log.warning(
                "Boucle asyncio bloquée",
                retard_s=round(retard, 1),
                piles_ecrites=retard > seuil_piles,
            )


def start(seuil_lent: float = 2.0, seuil_piles: float = 10.0) -> None:
    """Démarre la vigie dans la boucle courante (idempotent)."""
    global _tache
    if _tache is not None and not _tache.done():
        return
    _tache = asyncio.get_running_loop().create_task(_battre(seuil_lent, seuil_piles))
    log.info("Vigie de boucle active", seuil_lent_s=seuil_lent, seuil_piles_s=seuil_piles)


async def stop() -> None:
    """Arrête la vigie et désarme faulthandler (sinon il viderait les piles à l'arrêt)."""
    global _tache
    faulthandler.cancel_dump_traceback_later()
    if _tache is None:
        return
    _tache.cancel()
    try:
        await _tache
    except asyncio.CancelledError:
        pass
    _tache = None
