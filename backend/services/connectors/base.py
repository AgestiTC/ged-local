"""
Interface commune des connecteurs de sources + registre.
========================================================
Un connecteur donne accès EN LECTURE aux fichiers d'une `Source` distante
(cloud, NAS DSM…). Même contrat que `smb_service` : test / browse / walk / fetch.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from models.source import Source


@runtime_checkable
class SourceConnector(Protocol):
    """Contrat d'un connecteur (lecture seule)."""

    type: str  # ex. "synology", "gdrive", "dropbox", "webdav"

    async def test(self, src: Source) -> bool:
        """Vérifie la connexion (auth + joignabilité)."""
        ...

    async def browse(self, src: Source, chemin: str = "/") -> list[dict]:
        """Liste un dossier : [{nom, dossier: bool, taille: int|None, chemin}]."""
        ...

    async def walk_files(self, src: Source, chemin: str, extensions: set[str] | None) -> list[dict]:
        """Liste RÉCURSIVE des fichiers : [{rel, taille}] (rel = chemin distant)."""
        ...

    async def fetch_to_temp(self, src: Source, rel: str) -> str:
        """Télécharge un fichier distant dans un temporaire local, retourne son chemin."""
        ...

    async def stream_file(self, src: Source, rel: str) -> AsyncIterator[bytes]:
        """(optionnel) Flux binaire d'un fichier distant, par blocs."""
        ...


# ─── Registre type → connecteur ───────────────────────────────────────────────
_REGISTRY: dict[str, SourceConnector] = {}


def register(connector: SourceConnector) -> SourceConnector:
    """Enregistre un connecteur (décorateur ou appel direct)."""
    _REGISTRY[connector.type] = connector
    return connector


def get_connector(type_: str) -> SourceConnector | None:
    """Connecteur pour un `Source.type`, ou None si non géré (local/smb = hors registre)."""
    return _REGISTRY.get(type_)


def types_supportes() -> list[str]:
    """Types de sources gérés par un connecteur (hors local/smb)."""
    return sorted(_REGISTRY)
