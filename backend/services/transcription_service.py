"""
Service Transcription audio — parole → texte (local)
====================================================
Transcrit les fichiers audio (dictaphone Plaud/openplaud, mémos, réunions…) pour
les rendre **indexables et recherchables** dans la GED, au même titre qu'un document
texte. 100 % local : appelle un **serveur de transcription auto-hébergé** exposant
l'API **compatible OpenAI** `POST /v1/audio/transcriptions` — standard couvrant
faster-whisper-server / Speaches, LocalAI, whisper.cpp (mode server), vLLM…

Configuration (Paramètres → Transcription audio, surchargeable en base) :
  - `transcription_url`     : URL de base du serveur (ex. `http://localhost:8001`) ; vide = désactivé ;
  - `transcription_model`   : modèle (ex. `Systran/faster-whisper-large-v3`, `whisper-1`) ;
  - `transcription_langue`  : langue attendue (ex. `fr`) — indice, améliore la précision ;
  - `transcription_api_key` : clé d'API éventuelle (chiffrée) — souvent inutile en local.

Aucun envoi réseau externe : le seul flux part vers TON serveur de transcription.
"""
from __future__ import annotations

from pathlib import Path

import httpx

from logger import get_logger
from services import crypto, runtime_config

log = get_logger(__name__)

# Extensions audio prises en charge (parole). Les vidéos ne sont pas transcrites ici.
AUDIO_EXTENSIONS = {
    "mp3", "wav", "flac", "aac", "ogg", "wma", "m4a", "opus", "aiff", "alac", "amr", "3ga",
}

# Timeout généreux : une longue dictée peut être lente à transcrire (facteur temps réel).
_TIMEOUT = httpx.Timeout(connect=10.0, read=1800.0, write=60.0, pool=10.0)


class TranscriptionError(RuntimeError):
    pass


def _base_url() -> str:
    """URL de base du serveur de transcription (sans slash final), ou '' si non configurée."""
    return (runtime_config.effective("transcription_url") or "").strip().rstrip("/")


def is_enabled() -> bool:
    """La transcription est active dès qu'une URL de serveur est configurée."""
    return bool(_base_url())


def _api_key() -> str:
    brut = runtime_config.effective("transcription_api_key") or ""
    return crypto.decrypt(brut).strip() if brut else ""


def _headers() -> dict:
    key = _api_key()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _content_type(ext: str) -> str:
    return {
        "mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "ogg": "audio/ogg",
        "m4a": "audio/mp4", "aac": "audio/aac", "opus": "audio/opus", "wma": "audio/x-ms-wma",
    }.get(ext, "application/octet-stream")


def _extraire_texte(payload: object) -> str:
    """Extrait le texte d'une réponse (JSON `{text}` / segments, ou texte brut)."""
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        if isinstance(payload.get("text"), str):
            return payload["text"].strip()
        segs = payload.get("segments")
        if isinstance(segs, list):
            return " ".join(s.get("text", "").strip() for s in segs if isinstance(s, dict)).strip()
    return ""


async def transcribe(file_path: str | Path) -> str:
    """
    Transcrit un fichier audio en texte via le serveur configuré. Lève `TranscriptionError`
    si le service est indisponible ou répond en erreur (l'appelant retombe alors sur le
    catalogage média sans texte).
    """
    base = _base_url()
    if not base:
        raise TranscriptionError("Transcription non configurée (URL manquante)")

    p = Path(file_path)
    ext = p.suffix.lstrip(".").lower()
    model = (runtime_config.effective("transcription_model") or "whisper-1").strip()
    langue = (runtime_config.effective("transcription_langue") or "").strip()

    data = {"model": model, "response_format": "json"}
    if langue:
        data["language"] = langue

    try:
        with p.open("rb") as fh:
            files = {"file": (p.name, fh, _content_type(ext))}
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_headers()) as client:
                r = await client.post(f"{base}/v1/audio/transcriptions", data=data, files=files)
    except httpx.HTTPError as exc:
        raise TranscriptionError(f"Serveur de transcription injoignable : {exc}") from exc

    if r.status_code >= 400:
        raise TranscriptionError(f"Transcription HTTP {r.status_code} : {r.text[:200]}")

    try:
        payload = r.json()
    except ValueError:
        payload = r.text
    texte = _extraire_texte(payload)
    log.info("Transcription audio", fichier=p.name, modele=model, nb_chars=len(texte))
    return texte


async def check_health() -> bool:
    """Teste la joignabilité du serveur (liste des modèles ou racine). Non bloquant."""
    base = _base_url()
    if not base:
        return False
    for chemin in ("/v1/models", "/health", "/"):
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=_headers()) as client:
                r = await client.get(f"{base}{chemin}")
            if r.status_code < 500:
                return True
        except httpx.HTTPError:
            continue
    return False
