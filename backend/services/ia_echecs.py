"""
Suivi des appels IA en échec, par modèle
========================================
`noter()` enregistre un échec ; `resume()` les agrège par modèle pour la page Journaux.

`noter()` ne lève JAMAIS : c'est un témoin, pas un chemin critique. Un échec d'écriture
(base indisponible, tests sans table) est journalisé puis oublié — l'appel IA, lui, garde son
comportement d'origine (l'exception d'origine est relevée par l'appelant).
"""

from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger

log = get_logger(__name__)

MESSAGE_MAX = 300
CONSERVATION_JOURS = 30


def classer(exc: BaseException | None) -> tuple[str, int | None]:
    """(nature, code HTTP) d'une exception d'appel IA."""
    if isinstance(exc, httpx.HTTPStatusError):
        return "http", exc.response.status_code
    if isinstance(exc, httpx.TimeoutException):
        return "delai", None
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return "connexion", None
    return "autre", None


def _message(exc: BaseException | None, message: str | None) -> str | None:
    if message:
        return message[:MESSAGE_MAX]
    if exc is None:
        return None
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            corps = (exc.response.text or "").strip()
        except Exception:  # noqa: BLE001 — réponse en flux non lue
            corps = ""
        return f"HTTP {exc.response.status_code} {corps}".strip()[:MESSAGE_MAX]
    return (str(exc) or type(exc).__name__)[:MESSAGE_MAX]


async def noter(modele: str | None, operation: str, exc: BaseException | None = None, *,
                nature: str | None = None, message: str | None = None,
                base_url: str | None = None) -> None:
    """Enregistre un appel IA en échec. Ne lève jamais."""
    from database import AsyncSessionLocal
    from models.ia_echec import IAEchec

    nat, code = classer(exc) if nature is None else (nature, None)
    texte = _message(exc, message)
    log.warning("Appel IA en échec", modele=modele, operation=operation, nature=nat,
                code_http=code, message=texte)
    try:
        async with AsyncSessionLocal() as db:
            db.add(IAEchec(modele=modele or "?", operation=operation, nature=nat, code_http=code,
                           message=texte, base_url=base_url))
            await db.commit()
    except Exception as e:  # noqa: BLE001 — témoin best-effort, jamais bloquant
        log.debug("Échec IA non enregistré", erreur=str(e) or type(e).__name__)


async def resume(db: AsyncSession, heures: int = 24) -> dict:
    """Échecs des N dernières heures, par modèle : nombre, natures, dernier message."""
    from models.ia_echec import IAEchec

    depuis = datetime.now(timezone.utc) - timedelta(hours=heures)
    lignes = (await db.execute(
        select(IAEchec.modele, IAEchec.nature, IAEchec.code_http, func.count(),
               func.max(IAEchec.created_at))
        .where(IAEchec.created_at >= depuis)
        .group_by(IAEchec.modele, IAEchec.nature, IAEchec.code_http)
    )).all()

    par_modele: dict[str, dict] = {}
    for modele, nature, code, n, dernier in lignes:
        m = par_modele.setdefault(modele, {"modele": modele, "total": 0, "natures": [], "dernier": None})
        m["total"] += n
        m["natures"].append({"nature": nature, "code_http": code, "nombre": n})
        if dernier and (m["dernier"] is None or dernier > m["dernier"]):
            m["dernier"] = dernier

    for m in par_modele.values():
        m["natures"].sort(key=lambda x: -x["nombre"])
        dernier_msg = (await db.execute(
            select(IAEchec.message, IAEchec.operation)
            .where(IAEchec.modele == m["modele"], IAEchec.created_at >= depuis)
            .order_by(IAEchec.created_at.desc()).limit(1)
        )).first()
        m["dernier_message"], m["derniere_operation"] = (dernier_msg or (None, None))
        m["dernier"] = m["dernier"].isoformat() if m["dernier"] else None

    modeles = sorted(par_modele.values(), key=lambda m: -m["total"])
    return {"heures": heures, "total": sum(m["total"] for m in modeles), "modeles": modeles}


async def purger(jours: int = CONSERVATION_JOURS) -> int:
    """Supprime les échecs de plus de N jours (appelé par la boucle du worker)."""
    from database import AsyncSessionLocal
    from models.ia_echec import IAEchec

    limite = datetime.now(timezone.utc) - timedelta(days=jours)
    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(delete(IAEchec).where(IAEchec.created_at < limite))
            await db.commit()
            return res.rowcount or 0
    except Exception as e:  # noqa: BLE001
        log.warning("Purge des échecs IA échouée", erreur=str(e) or type(e).__name__)
        return 0
