"""
Service Folder Watcher — Surveillance de dossiers
==================================================
Détecte les nouveaux fichiers et les modifications dans les dossiers
configurés, puis déclenche le pipeline d'extraction.

Note : n8n gère la surveillance en production (workflow folder-watcher.json).
Ce service est un fallback pour les cas où n8n n'est pas disponible.
"""

from logger import get_logger

log = get_logger(__name__)


class FolderWatcher:
    """Surveille des dossiers et déclenche l'extraction des nouveaux fichiers."""

    def __init__(self, extraction_service):
        self.extraction = extraction_service
        self._running = False

    async def start(self, folders: list[dict]) -> None:
        """
        Démarre la surveillance des dossiers.

        Args:
            folders: Liste de {chemin, recursive, extensions_filtrees, intervalle_scan_secondes}
        """
        # TODO Phase 1 :
        # Pour chaque dossier, scanner périodiquement
        # Comparer les fichiers trouvés avec la DB (par chemin + mtime)
        # Déclencher extraction_service.process_file() pour les nouveaux
        raise NotImplementedError("TODO Phase 1 / n8n gère ça")

    async def stop(self) -> None:
        """Arrête la surveillance."""
        self._running = False
        log.info("Folder watcher arrêté")
