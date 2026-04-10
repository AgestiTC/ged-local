"""
Service Template Filler — Remplissage de templates DOCX
========================================================
Utilise docxtpl (Jinja2) pour remplir les champs {{ champ }}
d'un template DOCX avec les valeurs extraites par le LLM.

Flux :
  1. Analyser le template → détecter les champs {{ ... }}
  2. Demander au LLM de retourner un JSON {champ: valeur}
  3. Remplir le template avec docxtpl
"""

from pathlib import Path

from logger import get_logger

log = get_logger(__name__)


class TemplateFiller:
    """Remplit les templates DOCX avec des données extraites par IA."""

    def __init__(self, ollama_service, templates_dir: str):
        self.ollama = ollama_service
        self.templates_dir = Path(templates_dir)

    def detect_fields(self, template_path: Path) -> list[str]:
        """
        Détecte les champs Jinja2 dans un template DOCX.

        Returns:
            Liste des noms de champs trouvés
        """
        # TODO Phase 2 :
        # Ouvrir le DOCX, lire tous les paragraphes
        # Extraire les {{ champ }} avec regex
        raise NotImplementedError("TODO Phase 2")

    async def fill(
        self,
        template_id: str,
        document_ids: list[str],
        instructions: str,
        model: str | None = None,
    ) -> Path:
        """
        Remplit un template avec les données extraites des documents.

        Returns:
            Chemin vers le fichier DOCX rempli
        """
        # TODO Phase 2 :
        # 1. Charger le template depuis la DB + fichier
        # 2. Détecter les champs
        # 3. Construire un prompt demandant au LLM de retourner JSON {champ: valeur}
        # 4. Appeler Ollama
        # 5. Parser le JSON
        # 6. docxtpl.DocxTemplate(template_path).render(valeurs) → sauvegarder
        raise NotImplementedError("TODO Phase 2")
