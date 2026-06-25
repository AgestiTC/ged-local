"""
Router Système — /api/version, /api/logs/tail
==============================================
Endpoints d'exploitation imposés par le modèle docker AgestiTC :

  GET /api/version      → version embarquée (source de vérité : fichier VERSION)
  GET /api/logs/tail    → N dernières lignes du fichier de log applicatif

Le liveness probe /healthz (sans préfixe) est défini dans main.py.
"""

from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from logger import get_logger
from services import runtime_config
from services.ollama_service import OllamaService
from services.tika_service import TikaService

log = get_logger(__name__)
settings = get_settings()
router = APIRouter()


class ConfigUpdate(BaseModel):
    """Surcharges de configuration éditables (toutes optionnelles)."""
    tika_url: str | None = None
    ollama_url: str | None = None
    n8n_url: str | None = None
    default_model: str | None = None
    extensions: str | None = None   # liste CSV des extensions indexées (perso)


@router.get("/version", tags=["Système"])
async def get_version() -> dict:
    """Retourne la version de l'application (lue depuis le fichier VERSION racine)."""
    return {"name": settings.app_name, "version": settings.app_version}


# ─── Configuration éditable (URLs services + modèle par défaut) ───────────────

@router.get("/system/config", tags=["Système"])
async def get_config() -> dict:
    """Configuration effective (surcharges base + défauts env, avec la source)."""
    return {"config": runtime_config.all_effective()}


@router.put("/system/config", tags=["Système"])
async def update_config(body: ConfigUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    """Met à jour les surcharges de configuration (persistées en base, effet immédiat)."""
    data = {k: v for k, v in body.model_dump().items() if v is not None and v.strip()}
    if data:
        await runtime_config.set_many(db, data)
    return {"config": runtime_config.all_effective(), "mis_a_jour": list(data.keys())}


# ─── Statut des services (sous /api → fiable derrière le proxy) ───────────────

async def _ping_n8n(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            return (await client.get(f"{url}/healthz")).status_code == 200
    except Exception:
        return False


@router.get("/system/services", tags=["Système"])
async def services_status() -> dict:
    """Statut live des 3 services externes, avec leurs URLs effectives."""
    tika = TikaService()
    ollama = OllamaService()
    n8n_url = runtime_config.effective("n8n_url")
    from services import clamav_service
    clamav_url = f"{settings.clamav_host}:{settings.clamav_port}" if settings.clamav_host else "désactivé"
    return {
        "tika":   {"url": tika.base_url,   "ok": await tika.check_health()},
        "ollama": {"url": ollama.base_url, "ok": await ollama.check_health()},
        "n8n":    {"url": n8n_url,          "ok": await _ping_n8n(n8n_url)},
        "clamav": {"url": clamav_url,       "ok": await clamav_service.check_health()},
    }


# ─── Modèles IA disponibles (dynamique depuis Ollama) ─────────────────────────

@router.get("/system/models", tags=["Système"])
async def list_models(check_updates: bool = Query(default=False)) -> dict:
    """
    Liste les modèles Ollama installés (nom + taille). Si `check_updates=true`,
    ajoute par modèle `update: true|false|null` (MAJ dispo / à jour / inconnu)
    en comparant le digest local au registre Ollama (vérifs en parallèle).
    """
    import asyncio
    try:
        ollama = OllamaService()
        modeles = await ollama.list_models_detailed()
        if check_updates and modeles:
            verdicts = await asyncio.gather(
                *(ollama.check_update(m["name"], m.get("digest", "")) for m in modeles),
                return_exceptions=True,
            )
            for m, v in zip(modeles, verdicts):
                m["update"] = None if isinstance(v, BaseException) else v
        return {"models": modeles, "defaut": runtime_config.effective("default_model")}
    except Exception as exc:
        log.warning("Liste des modèles indisponible", erreur=str(exc))
        raise HTTPException(status_code=503, detail=f"Ollama injoignable : {exc}")


class PullRequest(BaseModel):
    """Modèle à télécharger / mettre à jour."""
    name: str


@router.post("/system/models/pull", tags=["Système"])
async def pull_model(body: PullRequest):
    """
    Met à jour (ou télécharge) un modèle via `ollama pull`, en streaming NDJSON
    (chaque ligne = progression). Le front lit le flux pour afficher l'avancement.
    """
    from fastapi.responses import StreamingResponse

    async def _stream():
        try:
            async for line in OllamaService().pull_stream(body.name):
                yield line + "\n"
        except Exception as exc:
            import json as _json
            yield _json.dumps({"error": str(exc)}) + "\n"

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


# ─── Test de connexion par service ────────────────────────────────────────────

@router.post("/system/test/{service}", tags=["Système"])
async def test_service(service: str, body: ConfigUpdate | None = None) -> dict:
    """
    Teste la connexion à un service (tika | ollama | n8n).
    Si une URL est fournie dans le body, teste CELLE-CI (avant de sauvegarder) ;
    sinon teste l'URL effective courante.
    """
    overrides = body.model_dump() if body else {}
    if service == "tika":
        url = overrides.get("tika_url") or runtime_config.effective("tika_url")
        ok = await TikaService(base_url=url).check_health()
        return {"service": "tika", "url": url, "ok": ok}
    if service == "ollama":
        url = overrides.get("ollama_url") or runtime_config.effective("ollama_url")
        ok = await OllamaService(base_url=url).check_health()
        return {"service": "ollama", "url": url, "ok": ok}
    if service == "n8n":
        url = overrides.get("n8n_url") or runtime_config.effective("n8n_url")
        ok = False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{url}/healthz")
                ok = resp.status_code == 200
        except Exception:
            ok = False
        return {"service": "n8n", "url": url, "ok": ok}
    raise HTTPException(status_code=400, detail="Service inconnu (tika | ollama | n8n)")


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
