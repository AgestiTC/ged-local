"""
Runtime config — surcharge à chaud des paramètres (URLs services, modèle défaut)
================================================================================
Les valeurs en base (table `config`) surchargent l'environnement (`settings`).
Un cache mémoire est chargé au démarrage et mis à jour à chaque écriture, pour
que les services (Tika, Ollama, n8n) lus par requête prennent l'effet immédiatement.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from logger import get_logger
from models.config import Config

log = get_logger(__name__)
settings = get_settings()

def _default_extensions() -> str:
    """Liste d'extensions par défaut (la même que le watcher), en chaîne CSV."""
    from services.folder_watcher import EXTENSIONS_ACCEPTEES  # import local : évite le cycle
    return ",".join(sorted(EXTENSIONS_ACCEPTEES))


# Clés gérées + provenance du défaut (variable d'environnement / config)
_DEFAULTS = {
    "tika_url": lambda: settings.tika_url,
    "ollama_url": lambda: settings.ollama_url,
    "n8n_url": lambda: settings.n8n_url,
    "default_model": lambda: settings.ollama_model_default,
    # Modèle vision (fallback OCR / description d'image quand Tesseract/Tika ne rend rien).
    # Défaut glm-ocr (installé) ; recommandé : qwen2.5vl:7b après `ollama pull qwen2.5vl:7b`.
    "vision_model": lambda: "glm-ocr:latest",
    "extensions": _default_extensions,
    # BookStack (wiki). Le secret est stocké chiffré (enc::…) ; le service le déchiffre.
    "bookstack_url": lambda: settings.bookstack_url,
    "bookstack_token_id": lambda: settings.bookstack_token_id or "",
    "bookstack_token_secret": lambda: settings.bookstack_token_secret or "",
    # HuggingFace (token API et/ou identifiant + mot de passe). Secrets chiffrés en base.
    # Stockage local uniquement — aucune requête réseau HF sans action confirmée par l'utilisateur.
    "huggingface_token": lambda: "",
    "huggingface_user": lambda: "",
    "huggingface_password": lambda: "",
}

# Clés dont la valeur est un secret : à chiffrer en écriture, à masquer en lecture.
SECRET_KEYS = {"bookstack_token_secret", "huggingface_token", "huggingface_password"}


def effective_extensions() -> set[str]:
    """Ensemble des extensions indexées (config base > défaut), normalisées."""
    raw = effective("extensions")
    return {e.strip().lstrip(".").lower() for e in raw.replace("\n", ",").split(",") if e.strip()}

# Cache mémoire des surcharges (clé → valeur)
_overrides: dict[str, str] = {}


def effective(cle: str) -> str:
    """Valeur effective : surcharge base si présente, sinon défaut env."""
    if cle in _overrides and _overrides[cle]:
        return _overrides[cle]
    default = _DEFAULTS.get(cle)
    return default() if default else ""


def all_effective() -> dict[str, str]:
    """Toutes les valeurs effectives + indication de la source (base/env)."""
    return {
        cle: {"valeur": effective(cle), "source": "base" if _overrides.get(cle) else "env"}
        for cle in _DEFAULTS
    }


async def load(db: AsyncSession) -> None:
    """Charge les surcharges depuis la base dans le cache mémoire."""
    rows = (await db.execute(select(Config))).scalars().all()
    _overrides.clear()
    for row in rows:
        if row.cle in _DEFAULTS:
            _overrides[row.cle] = row.valeur
    log.info("Runtime config chargée", surcharges=list(_overrides.keys()))


async def set_many(db: AsyncSession, data: dict[str, str]) -> None:
    """Upsert des surcharges en base + mise à jour du cache."""
    for cle, valeur in data.items():
        if cle not in _DEFAULTS:
            continue
        existing = await db.get(Config, cle)
        if existing:
            existing.valeur = valeur
        else:
            db.add(Config(cle=cle, valeur=valeur))
        _overrides[cle] = valeur
    await db.flush()
    log.info("Runtime config mise à jour", cles=list(data.keys()))
