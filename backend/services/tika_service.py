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

from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings
from logger import get_logger

log = get_logger(__name__)
settings = get_settings()


class TikaService:
    """Client async pour Apache Tika Server."""

    def __init__(self):
        self.base_url = settings.tika_url
        self.timeout = settings.tika_timeout

    def _get_client(self) -> httpx.AsyncClient:
        """Retourne un client httpx configuré."""
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def extract_text(self, file_path: Path) -> str:
        """
        Extrait le texte brut d'un fichier via Tika.

        Args:
            file_path: Chemin vers le fichier à extraire

        Returns:
            Texte brut extrait
        """
        log.info("Extraction texte Tika", fichier=file_path.name, taille=file_path.stat().st_size)

        async with self._get_client() as client:
            with open(file_path, "rb") as f:
                response = await client.put(
                    "/tika",
                    content=f.read(),
                    headers={"Accept": "text/plain"},
                )
            response.raise_for_status()
            texte = response.text

        log.info("Extraction texte OK", fichier=file_path.name, nb_caracteres=len(texte))
        return texte

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
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

        async with self._get_client() as client:
            with open(file_path, "rb") as f:
                response = await client.put(
                    "/rmeta/text",
                    content=f.read(),
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
