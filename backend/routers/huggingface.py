"""
Router HuggingFace — Catalogue de modèles (exploration du hub)
==============================================================
Interroge l'API publique HuggingFace pour proposer des modèles récents et maintenus,
regroupés par catégorie (fonction). **Sortie Internet** : appelé uniquement sur action
confirmée côté UI. N'envoie QUE le token (auth) + des filtres publics — jamais de donnée
document (cf. règle « 100% local / zéro fuite »).

Endpoint :
  GET /huggingface/catalog?category=&max_age_years=&maintained_days=&maintained_only=&sort=&limit=
"""

import datetime as dt
import re
import time

import httpx
from fastapi import APIRouter, Query

from logger import get_logger
from services import runtime_config

log = get_logger(__name__)
router = APIRouter()

_HF_API = "https://huggingface.co/api/models"

# Catégorie projet → pipeline_tag HuggingFace
_CATEGORIES: dict[str, str] = {
    "llm": "text-generation",
    "embeddings": "feature-extraction",
    "vision": "image-text-to-text",
    "audio": "automatic-speech-recognition",
}

# Heuristique « sans censure » (HF n'a pas de flag officiel).
_UNCENSORED_RE = re.compile(r"uncensored|uncensured|abliterat|dolphin", re.IGNORECASE)

# Cache mémoire court pour limiter les appels réseau : {clé: (timestamp, payload)}
_cache: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 600  # 10 min


def _token() -> str | None:
    """Token HF déchiffré depuis la config (ou None)."""
    from services.crypto import decrypt, is_encrypted

    raw = runtime_config.effective("huggingface_token")
    if not raw:
        return None
    return decrypt(raw) if is_encrypted(raw) else raw


def _parse_date(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _normaliser(m: dict, maintained_days: int, now: dt.datetime) -> dict:
    """Transforme une entrée brute HF en carte normalisée pour l'UI."""
    idd = m.get("id", "")
    tags = m.get("tags") or []
    dmod = _parse_date(m.get("lastModified"))
    maintained = bool(dmod and (now - dmod).days <= maintained_days)
    uncensored = bool(_UNCENSORED_RE.search(idd) or any(_UNCENSORED_RE.search(str(t)) for t in tags))
    lib = (m.get("library_name") or "").lower()
    gguf = "gguf" in lib or any(str(t).lower() == "gguf" for t in tags)
    return {
        "id": idd,
        "categorie": m.get("pipeline_tag"),
        "created_at": m.get("createdAt"),
        "last_modified": m.get("lastModified"),
        "maintained": maintained,
        "uncensored": uncensored,
        "gated": bool(m.get("gated")),
        "downloads": m.get("downloads", 0),
        "likes": m.get("likes", 0),
        "gguf": gguf,
        "tags": [str(t) for t in tags[:12]],
    }


@router.get("/huggingface/catalog", tags=["HuggingFace"])
async def catalog(
    category: str = Query("llm", pattern="^(llm|embeddings|vision|audio)$"),
    max_age_years: float = Query(2.0, ge=0.5, le=10),
    maintained_days: int = Query(180, ge=30, le=730, description="Fenêtre « maintenu » (jours)"),
    maintained_only: bool = Query(False),
    sort: str = Query("downloads", pattern="^(downloads|likes|lastModified)$"),
    limit: int = Query(40, ge=1, le=100),
) -> dict:
    """
    Catalogue HuggingFace filtré (âge ≤ `max_age_years`, activité récente), regroupé par
    catégorie/fonction. **Appel réseau** (confirmé côté UI) — n'envoie que le token + les filtres.
    """
    key = f"{category}|{sort}|{limit}|{max_age_years}|{maintained_days}|{maintained_only}"
    now_ts = time.time()
    cached = _cache.get(key)
    if cached and (now_ts - cached[0]) < _CACHE_TTL:
        return {**cached[1], "cache": True}

    pipeline = _CATEGORIES[category]
    params = {
        "pipeline_tag": pipeline,
        "sort": sort,
        "direction": "-1",
        # on récupère plus large puis on filtre par âge/maintenu côté serveur
        "limit": min(limit * 3, 200),
        "full": "true",
    }
    headers: dict[str, str] = {}
    tok = _token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(_HF_API, params=params, headers=headers)
        resp.raise_for_status()
        raw = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("Catalogue HF injoignable", erreur=str(exc))
        return {"ok": False, "erreur": str(exc), "category": category, "models": []}

    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=int(365 * max_age_years))
    out: list[dict] = []
    for m in raw:
        # Âge / activité : basé sur lastModified (retombe sur createdAt si absent).
        ref = _parse_date(m.get("lastModified")) or _parse_date(m.get("createdAt"))
        if ref and ref < cutoff:
            continue
        card = _normaliser(m, maintained_days, now)
        if maintained_only and not card["maintained"]:
            continue
        out.append(card)
        if len(out) >= limit:
            break

    payload = {"ok": True, "category": category, "count": len(out), "models": out, "cache": False}
    _cache[key] = (now_ts, payload)
    log.info("Catalogue HF récupéré", category=category, count=len(out))
    return payload


def _readme_summary(text: str) -> str:
    """Extrait un court résumé « ce que fait le modèle » depuis le README (best-effort)."""
    if text.startswith("---"):  # retire le frontmatter YAML
        parts = text.split("---", 2)
        text = parts[2] if len(parts) >= 3 else text
    morceaux: list[str] = []
    total = 0
    for ln in text.splitlines():
        s = ln.strip()
        if not s or s.startswith(("#", "!", "|", "<", "```", "[![", "- [", "* [")):
            continue  # titres, images, tableaux, html, badges, code
        s = re.sub(r"[*_`>]", "", s)  # nettoie le markdown inline
        morceaux.append(s)
        total += len(s)
        if total > 400:
            break
    return " ".join(morceaux)[:500].strip()


@router.get("/huggingface/model", tags=["HuggingFace"])
async def model_detail(id: str = Query(..., description="org/model")) -> dict:
    """
    Détail d'un modèle HF : **résumé** (README), métadonnées, et référence d'installation Ollama.
    **Appel réseau** (dans la session catalogue déjà consentie). N'envoie que le token.
    """
    headers: dict[str, str] = {}
    tok = _token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    meta: dict = {}
    resume = ""
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{_HF_API}/{id}", params={"full": "true"}, headers=headers)
            if r.status_code == 200:
                meta = r.json()
            # README (best-effort — branche main puis master)
            for branch in ("main", "master"):
                rr = await client.get(f"https://huggingface.co/{id}/raw/{branch}/README.md", headers=headers)
                if rr.status_code == 200:
                    resume = _readme_summary(rr.text)
                    break
    except Exception as exc:  # noqa: BLE001
        log.warning("Détail HF injoignable", model=id, erreur=str(exc))
        return {"ok": False, "erreur": str(exc), "id": id}

    tags = meta.get("tags") or []
    card = meta.get("cardData") or {}
    lib = (meta.get("library_name") or "").lower()
    gguf = "gguf" in lib or any(str(t).lower() == "gguf" for t in tags)

    # Résumé en FRANÇAIS via l'IA LOCALE (Ollama) — 100% local, aucun envoi de données perso.
    resume_fr = ""
    resume_ia = False
    if resume:
        try:
            from services.ollama_service import OllamaService

            prompt = (
                "Résume en FRANÇAIS, en 1 à 2 phrases claires, CE QUE FAIT ce modèle d'IA "
                "(sa fonction, ses points forts). Réponds directement, sans introduction ni "
                "formule de politesse.\n\n"
                f"Nom : {id}\nType : {meta.get('pipeline_tag')}\n"
                f"Description (souvent en anglais) :\n{resume[:1500]}"
            )
            # Usage « resume_modele » (config Paramètres) > défaut runtime.
            modele = runtime_config.model_for("resume_modele")
            resume_fr = (await OllamaService().generate(prompt, model=modele)).strip()
            resume_ia = bool(resume_fr)
        except Exception as exc:  # noqa: BLE001 — on retombe sur le README brut
            log.warning("Résumé FR (Ollama) échoué", model=id, erreur=str(exc))

    return {
        "ok": True,
        "id": id,
        "resume": resume_fr or resume,   # français (IA locale) si dispo, sinon README brut
        "resume_ia": resume_ia,          # True = traduit/résumé par l'IA locale
        "resume_en": resume,             # texte brut du README (repli)
        "pipeline_tag": meta.get("pipeline_tag"),
        "license": card.get("license") or next((t.split(":", 1)[1] for t in tags if str(t).startswith("license:")), None),
        "downloads": meta.get("downloads", 0),
        "likes": meta.get("likes", 0),
        "gated": bool(meta.get("gated")),
        "gguf": gguf,
        "tags": [str(t) for t in tags[:20]],
        "ollama_ref": f"hf.co/{id}",  # pour `ollama pull hf.co/<id>`
    }
