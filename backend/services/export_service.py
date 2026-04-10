"""
Service Export — Génération de fichiers PDF et DOCX
====================================================
Convertit le texte Markdown d'un rapport en PDF (weasyprint)
ou en DOCX (python-docx).
"""

from pathlib import Path

from logger import get_logger

log = get_logger(__name__)


class ExportService:
    """Gère l'export des rapports en PDF et DOCX."""

    def __init__(self, exports_dir: str):
        self.exports_dir = Path(exports_dir)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    async def to_pdf(self, content: str, title: str) -> Path:
        """
        Convertit du Markdown en PDF via weasyprint.

        Args:
            content: Contenu Markdown du rapport
            title: Titre du rapport (utilisé pour le nom du fichier)

        Returns:
            Chemin vers le fichier PDF généré (sur le volume hôte)
        """
        # TODO Phase 2 :
        # 1. Convertir Markdown → HTML (markdown lib)
        # 2. Appliquer un template HTML avec CSS
        # 3. weasyprint.HTML(string=html).write_pdf(output_path)
        raise NotImplementedError("TODO Phase 2")

    async def to_docx(self, content: str, title: str) -> Path:
        """
        Convertit du Markdown en DOCX via python-docx.

        Returns:
            Chemin vers le fichier DOCX généré (sur le volume hôte)
        """
        # TODO Phase 2 :
        # 1. Parser le Markdown en sections
        # 2. Créer un Document python-docx
        # 3. Ajouter heading, paragraphes, listes
        raise NotImplementedError("TODO Phase 2")
