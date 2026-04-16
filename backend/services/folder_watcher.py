"""
Service Folder Watcher — Surveillance de dossiers
==================================================
Détecte les nouveaux fichiers et les modifications dans les dossiers
configurés, puis déclenche le pipeline d'extraction.

Note : n8n gère la surveillance en production (workflow folder-watcher.json).
Ce service est un fallback Python pour les cas où n8n n'est pas disponible.

Il est lancé en tâche de fond au démarrage via lifespan() si des dossiers
sont configurés.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from logger import get_logger

log = get_logger(__name__)

# Extensions acceptées pour l'indexation automatique
EXTENSIONS_ACCEPTEES = {
    "pdf", "docx", "pptx", "ppsx", "xlsx", "odt", "ods", "odp",
    "txt", "md", "csv", "zip",
}


class FolderWatcher:
    """
    Surveille des dossiers périodiquement et déclenche l'extraction
    des fichiers nouveaux ou modifiés.
    """

    def __init__(self, extraction_service):
        self.extraction = extraction_service
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Démarre la surveillance en tâche de fond."""
        if self._running:
            log.warning("FolderWatcher déjà en cours")
            return

        self._running = True
        self._task = asyncio.create_task(self._boucle_principale())
        log.info("FolderWatcher démarré")

    async def stop(self) -> None:
        """Arrête la surveillance proprement."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("FolderWatcher arrêté")

    async def _boucle_principale(self) -> None:
        """Boucle principale de surveillance — tourne jusqu'à stop()."""
        while self._running:
            try:
                await self._scanner_tous_dossiers()
            except Exception as e:
                log.error("Erreur boucle FolderWatcher", erreur=str(e))

            # Attendre avant le prochain scan (intervalle minimal : 60 secondes)
            await asyncio.sleep(60)

    async def _scanner_tous_dossiers(self) -> None:
        """Récupère les dossiers configurés et les scanne."""
        from database import AsyncSessionLocal
        from models.folder import DossierSurveille

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DossierSurveille).where(DossierSurveille.actif == True)  # noqa: E712
            )
            dossiers = result.scalars().all()

        if not dossiers:
            return

        log.debug("Scan périodique", nb_dossiers=len(dossiers))

        for dossier in dossiers:
            try:
                await self._scanner_dossier(dossier)
            except Exception as e:
                log.error("Erreur scan dossier", chemin=dossier.chemin, erreur=str(e))

    async def _scanner_dossier(self, dossier) -> None:
        """
        Scanne un dossier et indexe les fichiers nouveaux ou modifiés.

        Args:
            dossier: Objet DossierSurveille depuis la DB
        """
        from database import AsyncSessionLocal
        from models.document import Document
        from models.folder import DossierSurveille

        chemin = Path(dossier.chemin)
        if not chemin.exists() or not chemin.is_dir():
            log.warning("Dossier inaccessible", chemin=str(chemin))
            return

        # Collecter les fichiers du dossier
        extensions_filtrees = set(dossier.extensions_filtrees or []) or EXTENSIONS_ACCEPTEES
        fichiers = _lister_fichiers(chemin, recursive=dossier.recursive, extensions=extensions_filtrees)

        if not fichiers:
            return

        # Comparer avec la DB pour trouver les nouveaux/modifiés
        async with AsyncSessionLocal() as db:
            # Récupérer les chemins déjà indexés
            result = await db.execute(
                select(Document.chemin, Document.date_modification_fichier)
            )
            indexes: dict[str, datetime | None] = {row.chemin: row.date_modification_fichier for row in result}

        nouveaux = []
        for fichier in fichiers:
            chemin_str = str(fichier)
            mtime = datetime.fromtimestamp(fichier.stat().st_mtime, tz=timezone.utc)

            if chemin_str not in indexes:
                # Nouveau fichier
                nouveaux.append(fichier)
            else:
                # Vérifier si modifié
                indexed_mtime = indexes[chemin_str]
                if indexed_mtime and mtime > indexed_mtime:
                    nouveaux.append(fichier)

        if not nouveaux:
            log.debug("Aucun nouveau fichier", dossier=str(chemin))
        else:
            log.info("Nouveaux fichiers détectés", dossier=str(chemin), nb=len(nouveaux))

        # Indexer les nouveaux fichiers (séquentiellement pour éviter les surcharges)
        for fichier in nouveaux:
            try:
                async with AsyncSessionLocal() as db:
                    await self.extraction.process_file(
                        file_path=fichier,
                        source="watch",
                        db=db,
                    )
                log.info("Fichier indexé par watcher", fichier=fichier.name)
            except Exception as e:
                log.error("Erreur indexation watcher", fichier=str(fichier), erreur=str(e))

        # Mettre à jour la date de dernier scan
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DossierSurveille).where(DossierSurveille.id == dossier.id)
            )
            obj = result.scalar_one_or_none()
            if obj:
                obj.dernier_scan = datetime.now(tz=timezone.utc)
                await db.commit()

    async def scanner_dossier_maintenant(self, dossier_id: str) -> int:
        """
        Scan immédiat d'un dossier (déclenché via API).

        Returns:
            Nombre de fichiers indexés
        """
        from database import AsyncSessionLocal
        from models.folder import DossierSurveille

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(DossierSurveille).where(DossierSurveille.id == dossier_id)
            )
            dossier = result.scalar_one_or_none()

        if not dossier:
            raise ValueError(f"Dossier {dossier_id} non trouvé")

        await self._scanner_dossier(dossier)
        return 0  # Le compte précis nécessiterait un suivi plus fin


def _lister_fichiers(
    dossier: Path,
    recursive: bool = True,
    extensions: set[str] | None = None,
) -> list[Path]:
    """
    Liste les fichiers d'un dossier selon les filtres.

    Args:
        dossier: Dossier à parcourir
        recursive: Inclure les sous-dossiers
        extensions: Extensions acceptées (sans le point)

    Returns:
        Liste de chemins de fichiers
    """
    extensions = extensions or EXTENSIONS_ACCEPTEES
    fichiers = []

    try:
        if recursive:
            for entry in dossier.rglob("*"):
                if entry.is_file() and not _est_cache(entry):
                    ext = entry.suffix.lstrip(".").lower()
                    if ext in extensions:
                        fichiers.append(entry)
        else:
            for entry in dossier.iterdir():
                if entry.is_file() and not _est_cache(entry):
                    ext = entry.suffix.lstrip(".").lower()
                    if ext in extensions:
                        fichiers.append(entry)
    except PermissionError:
        log.warning("Permission refusée", dossier=str(dossier))

    return fichiers


def _est_cache(path: Path) -> bool:
    """Vérifie si un fichier est un fichier temporaire / caché."""
    nom = path.name
    return (
        nom.startswith(".")
        or nom.startswith("~$")  # Fichiers temporaires Office
        or nom.endswith(".tmp")
        or nom.endswith(".bak")
        or "/.git/" in str(path)
        or "__pycache__" in str(path)
    )
