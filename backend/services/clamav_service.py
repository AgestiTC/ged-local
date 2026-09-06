"""
Service Antivirus — ClamAV (clamd)
==================================
Scanne les fichiers AVANT indexation. Un fichier détecté infecté n'est pas indexé
(marqué en erreur).

**Dégradation gracieuse, mais pas amnésique.** Si ClamAV est désactivé, injoignable, ou si
le fichier dépasse la limite INSTREAM de `clamd`, on ne bloque pas l'indexation — la sécurité
ne doit pas casser le pipeline. Mais on ne fait plus passer ces cas pour « sain » : l'état du
scan est rendu séparément du verdict, et enregistré sur le document.

Pourquoi ça compte (défaut signalé par la session AIGUILLEUR, 06/09/2026) : la version
précédente renvoyait `(True, None)` aussi bien pour « scanné et sain » que pour « pas pu être
scanné ». L'appelant ne pouvait pas les distinguer, l'information était perdue à l'indexation,
et **plus un fichier était gros, moins il était protégé** — il suffisait de le rembourrer
au-delà de `StreamMaxLength` pour qu'il soit réputé propre. Rien ne permettait ensuite de
retrouver les documents qui n'avaient jamais été examinés. Ils sont maintenant marqués
`non_scanne`, donc retrouvables et re-scannables.

Convention modèle AgestiTC : sécurité maintenue, jamais de secret en log.
"""

import asyncio

from config import get_settings
from logger import get_logger

log = get_logger(__name__)
settings = get_settings()

# États possibles d'un document vis-à-vis de l'antivirus. « sain » est le SEUL qui affirme
# quelque chose ; les autres disent l'absence d'examen, chacun pour une raison différente.
SAIN = "sain"
INFECTE = "infecte"
NON_SCANNE = "non_scanne"     # trop gros, clamd muet, erreur de lecture — non examiné
DESACTIVE = "desactive"       # antivirus éteint dans la configuration


def _enabled() -> bool:
    return bool(settings.clamav_enabled and settings.clamav_host)


def _client():
    import clamd
    return clamd.ClamdNetworkSocket(host=settings.clamav_host, port=settings.clamav_port, timeout=60)


def _scan_sync(path: str) -> tuple[bool, str | None, str]:
    """
    Retourne `(indexable, signature, etat)`.

    `indexable` reste vrai quand le scan n'a pas pu avoir lieu — c'est la dégradation
    gracieuse — mais `etat` dit alors `non_scanne`, et ne se confond plus avec `sain`.
    """
    try:
        with open(path, "rb") as f:
            res = _client().instream(f)
        status, sig = res.get("stream", ("OK", None))
        if status == "FOUND":
            return False, sig, INFECTE
        return True, None, SAIN
    except Exception as exc:
        # Trop gros (StreamMaxLength), clamd indisponible, fichier illisible… On laisse
        # passer, mais on le DIT : « non examiné » n'est pas « propre ».
        log.warning("Scan antivirus impossible — fichier indexé mais NON EXAMINÉ",
                    fichier=path, erreur=str(exc))
        return True, None, NON_SCANNE


def _ping_sync() -> bool:
    try:
        return _client().ping() == "PONG"
    except Exception:
        return False


async def scan_file(path: str) -> tuple[bool, str | None, str]:
    """Scanne un fichier. Retourne `(indexable, signature, etat)` — cf. `_scan_sync`."""
    if not _enabled():
        return True, None, DESACTIVE
    return await asyncio.to_thread(_scan_sync, path)


async def check_health() -> bool:
    """Vrai si ClamAV est activé ET répond (PONG)."""
    if not _enabled():
        return False
    return await asyncio.to_thread(_ping_sync)
