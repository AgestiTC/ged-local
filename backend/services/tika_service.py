"""
Service Tika — Extraction de texte et métadonnées
===================================================
Client async pour Apache Tika Server.
Supporte tous les formats : PDF, DOCX, PPTX, PPSX, XLSX, ZIP.

Endpoints Tika utilisés :
  PUT /tika        → texte brut uniquement
  PUT /rmeta/text  → texte + métadonnées complètes (JSON)
  PUT /rmeta       → métadonnées uniquement

Pour les ZIP : /rmeta retourne un document par fichier dans le ZIP.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from config import get_settings
from logger import get_logger

log = get_logger(__name__)
settings = get_settings()

# Taille de bloc pour l'upload en flux vers Tika (borne le pic RAM sur les gros fichiers).
_CHUNK = 1 << 20  # 1 Mo


async def _stream_file(path: Path, chunk: int = _CHUNK) -> AsyncIterator[bytes]:
    """
    Envoie un fichier à Tika PAR BLOCS (upload chunké) au lieu de le charger entièrement
    en mémoire : le pic RAM reste ~1 bloc, pas la taille du fichier (utile pour les gros
    PDF/PPTX/ZIP). Les lectures disque se font hors event-loop (`to_thread`).
    """
    f = await asyncio.to_thread(open, path, "rb")
    try:
        while True:
            data = await asyncio.to_thread(f.read, chunk)
            if not data:
                break
            yield data
    finally:
        await asyncio.to_thread(f.close)


# ─── Ne pas engorger Tika ────────────────────────────────────────────────────
#
# Mesuré le 09/10/2026 sur 2 cœurs (la prod) : un PDF scanné de 40 pages demande ~90 s d'OCR, et
# le worker pouvait envoyer 5 fichiers à la fois (2 indexations + 3 synchros) avec 60 s de délai
# et 3 essais. Chaque délai dépassé renvoyait le MÊME fichier pendant que Tika travaillait encore
# sur l'envoi précédent : 300 documents en erreur « ReadTimeout », et côté Tika 4
# `CLIENT_UNAVAILABLE_WITHIN_MS`. Trois règles, donc :
#   1. un nombre borné d'extractions à la fois par processus (`tika_concurrence`) — l'attente se
#      fait ICI, sans limite, et non dans Tika qui refuse au bout d'un moment ;
#   2. un délai de lecture à la mesure d'un gros scan (`TIKA_TIMEOUT_MS`, 10 min par défaut) ;
#   3. JAMAIS de nouvel essai sur un délai dépassé : ce serait doubler une charge déjà trop forte.
_PAS_DE_NOUVEL_ESSAI = retry_if_not_exception_type(httpx.TimeoutException)

_verrous: dict[int, asyncio.Semaphore] = {}


def _verrou_tika() -> asyncio.Semaphore:
    """Sémaphore du processus, créé dans la boucle qui s'en sert (une par worker / par test)."""
    boucle = id(asyncio.get_running_loop())
    if boucle not in _verrous:
        _verrous.clear()                       # boucle précédente terminée : son verrou ne sert plus
        _verrous[boucle] = asyncio.Semaphore(max(1, settings.tika_concurrence))
    return _verrous[boucle]


class TikaService:
    """Client async pour Apache Tika Server."""

    def __init__(self, base_url: str | None = None):
        # URL effective : surcharge base (runtime_config) > variable d'env.
        from services.runtime_config import effective
        self.base_url = base_url or effective("tika_url")
        self.timeout = settings.tika_timeout

    def _get_client(self) -> httpx.AsyncClient:
        """Retourne un client httpx configuré."""
        return httpx.AsyncClient(
            base_url=self.base_url,
            # Seule la LECTURE peut être longue (OCR) ; un Tika injoignable doit se voir vite.
            timeout=httpx.Timeout(self.timeout, connect=10.0),
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=_PAS_DE_NOUVEL_ESSAI,
    )
    async def extract_text(self, file_path: Path) -> str:
        """
        Extrait le texte brut d'un fichier via Tika.

        Args:
            file_path: Chemin vers le fichier à extraire

        Returns:
            Texte brut extrait
        """
        log.info("Extraction texte Tika", fichier=file_path.name)

        async with _verrou_tika(), self._get_client() as client:
            response = await client.put(
                "/tika",
                content=_stream_file(file_path),   # upload par blocs → pic RAM borné
                headers={"Accept": "text/plain"},
            )
            response.raise_for_status()
            texte = response.text

        log.info("Extraction texte OK", fichier=file_path.name, nb_caracteres=len(texte))
        return texte

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=_PAS_DE_NOUVEL_ESSAI,
    )
    async def extract_metadata(self, file_path: Path) -> list[dict]:
        """
        Extrait texte + métadonnées d'un fichier (ou d'un ZIP) via Tika /rmeta.
        Pour un ZIP, retourne une liste de dicts (un par fichier dans le ZIP).

        Args:
            file_path: Chemin vers le fichier

        Returns:
            Liste de dicts avec X-TIKA:content (texte) + métadonnées Tika
        """
        log.info("Extraction métadonnées Tika", fichier=file_path.name)

        async with _verrou_tika(), self._get_client() as client:
            response = await client.put(
                "/rmeta/text",
                content=_stream_file(file_path),   # upload par blocs → pic RAM borné
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            metadata = response.json()

        # Tika retourne toujours une liste
        if not isinstance(metadata, list):
            metadata = [metadata]

        log.info(
            "Extraction métadonnées OK",
            fichier=file_path.name,
            nb_documents=len(metadata),
        )
        return metadata

    async def check_health(self) -> bool:
        """Vérifie que Tika est disponible."""
        try:
            async with self._get_client() as client:
                response = await client.get("/tika")
                return response.status_code == 200
        except Exception as e:
            log.warning("Tika non disponible", erreur=str(e))
            return False


# TODO Phase 1 : instancier et injecter via FastAPI Depends()
