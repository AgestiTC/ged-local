"""
Client Plex (réseau local, LECTURE seule) — les titres des épisodes pour le Rangement.

Plex connaît déjà, en français, le titre de chaque épisode qu'il a identifié : on le lui demande au lieu
d'aller sur Internet (décision de Thomas, 15/11/2026). Deux appels : les bibliothèques de séries
(`/library/sections`), puis leurs épisodes (`/library/sections/{clé}/all?type=4`), chacun avec le chemin
du fichier tel que Plex le voit. Le jeton ne sort jamais d'ici : ni journal, ni message d'erreur.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

import httpx

from logger import get_logger

log = get_logger(__name__)
DELAI = httpx.Timeout(10.0, read=120.0)   # une grosse bibliothèque met du temps à se lister


class PlexIndisponible(Exception):
    """Plex injoignable, jeton refusé ou réponse illisible (message sans le jeton)."""


@dataclass(frozen=True)
class EpisodePlex:
    fichier: str          # chemin vu par Plex
    serie: str            # titre de la série (grandparentTitle)
    saison: int
    episode: int
    titre: str


@dataclass(frozen=True)
class Bibliotheque:
    titre: str
    dossiers: tuple[str, ...]     # emplacements de la bibliothèque, vus par Plex
    episodes: tuple[EpisodePlex, ...]


def nfc(texte: str) -> str:
    return unicodedata.normalize("NFC", texte)


def _entetes(jeton: str) -> dict[str, str]:
    return {"X-Plex-Token": jeton, "Accept": "application/json"}


async def _json(client: httpx.AsyncClient, url: str, jeton: str, **params: Any) -> dict:
    try:
        r = await client.get(url, headers=_entetes(jeton), params=params or None)
    except httpx.HTTPError as exc:
        raise PlexIndisponible(f"Plex injoignable ({type(exc).__name__})") from exc
    if r.status_code == 401:
        raise PlexIndisponible("jeton Plex refusé (401)")
    if r.status_code != 200:
        raise PlexIndisponible(f"Plex a répondu HTTP {r.status_code}")
    try:
        return r.json().get("MediaContainer") or {}
    except ValueError as exc:
        raise PlexIndisponible("réponse de Plex illisible") from exc


async def bibliotheques_series(url: str, jeton: str, client: httpx.AsyncClient | None = None) -> list[Bibliotheque]:
    """Toutes les bibliothèques de SÉRIES de ce Plex, avec leurs épisodes."""
    base = url.rstrip("/")
    propre = client is None
    client = client or httpx.AsyncClient(timeout=DELAI)
    try:
        sections = await _json(client, f"{base}/library/sections", jeton)
        sortie: list[Bibliotheque] = []
        for d in sections.get("Directory") or []:
            if d.get("type") != "show":
                continue
            dossiers = tuple(nfc(str(loc.get("path") or "")) for loc in d.get("Location") or [] if loc.get("path"))
            contenu = await _json(client, f"{base}/library/sections/{d.get('key')}/all", jeton, type=4)
            eps: list[EpisodePlex] = []
            for m in contenu.get("Metadata") or []:
                try:
                    saison, episode = int(m.get("parentIndex")), int(m.get("index"))
                except (TypeError, ValueError):
                    continue
                for media in m.get("Media") or []:
                    for part in media.get("Part") or []:
                        if part.get("file"):
                            eps.append(EpisodePlex(nfc(str(part["file"])), str(m.get("grandparentTitle") or ""),
                                                   saison, episode, str(m.get("title") or "")))
            sortie.append(Bibliotheque(str(d.get("title") or ""), dossiers, tuple(eps)))
        log.info("Plex lu", bibliotheques=len(sortie), episodes=sum(len(b.episodes) for b in sortie))
        return sortie
    finally:
        if propre:
            await client.aclose()


def relatif(fichier: str, dossiers: tuple[str, ...], rubriques: dict[str, str]) -> str | None:
    """Chemin d'un fichier de Plex RELATIF à l'emplacement : la bibliothèque dont le dossier s'appelle
    comme une rubrique du plan (`/media/Series` ↔ rubrique `Series`) donne `Series/<reste>`.
    `rubriques` : nom en minuscules → nom de la rubrique. None si le fichier n'est sous aucune."""
    for d in dossiers:
        racine = d.rstrip("/")
        if not fichier.startswith(racine + "/"):
            continue
        rubrique = rubriques.get(racine.rsplit("/", 1)[-1].casefold())
        if rubrique:
            return f"{rubrique}/{fichier[len(racine) + 1:]}"
    return None
