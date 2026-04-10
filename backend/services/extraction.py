"""
Service Extraction — Pipeline complet fichier → DB
====================================================
Orchestre : hash SHA256 → Tika → DB → enrichissement IA → embeddings.

Flux :
  1. Calcul hash + détection doublon
  2. Insertion dans documents (statut=pending)
  3. Appel Tika → texte + métadonnées
  4. Mise à jour documents (statut=extracted)
  5. Enrichissement IA via Ollama (catégorie, tags, résumé...)
  6. Génération embeddings par chunks
  7. Statut final = enriched
"""

from pathlib import Path

from logger import get_logger

log = get_logger(__name__)


class ExtractionService:
    """Pipeline d'extraction et d'enrichissement de documents."""

    def __init__(self, tika_service, ollama_service, embedding_service):
        self.tika = tika_service
        self.ollama = ollama_service
        self.embeddings = embedding_service

    async def process_file(self, file_path: Path, source: str = "watch") -> str:
        """
        Traite un fichier de bout en bout.

        Args:
            file_path: Chemin vers le fichier
            source: Origine du fichier (watch | upload | drag_drop)

        Returns:
            ID du document créé ou existant
        """
        # TODO Phase 1 :
        # 1. hash_utils.compute_sha256(file_path)
        # 2. Vérifier si le hash existe déjà en DB (doublon)
        # 3. Créer le document en DB (statut=pending)
        # 4. self.tika.extract_metadata(file_path)
        # 5. Mettre à jour le document (statut=extracted)
        # 6. self.ollama.generate(prompt_enrichissement, model=settings.ollama_model_fast)
        # 7. Parser le JSON retourné → MetadonneeIA
        # 8. self.embeddings.embed_document(document_id, texte_extrait)
        # 9. Mettre à jour statut=enriched
        raise NotImplementedError("TODO Phase 1")

    async def process_zip(self, zip_path: Path, source: str = "upload") -> list[str]:
        """
        Traite un fichier ZIP : extrait chaque fichier et le traite.

        Returns:
            Liste des IDs de documents créés
        """
        # TODO Phase 1 : utiliser Tika /rmeta qui gère les ZIP nativement
        raise NotImplementedError("TODO Phase 1")
