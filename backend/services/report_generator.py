"""
Service Génération de rapports — Orchestrateur principal
=========================================================
Construit le contexte à partir des documents sélectionnés et
génère un rapport via Ollama (streaming SSE vers le frontend).

Contrainte contexte : Mixtral = 32k tokens max.
Si les documents combinés dépassent, on tronque intelligemment
ou on utilise les chunks les plus pertinents (recherche sémantique).
"""

from collections.abc import AsyncGenerator

from config import get_settings
from logger import get_logger

log = get_logger(__name__)
settings = get_settings()

# Nombre max de caractères à envoyer à Ollama (approximation tokens)
# ~32k tokens × ~4 chars/token = ~128k chars, garder 80% de marge
MAX_CONTEXT_CHARS = 100_000


class ReportGenerator:
    """Génère des rapports à partir de documents et d'un prompt."""

    def __init__(self, ollama_service):
        self.ollama = ollama_service

    async def generate_stream(
        self,
        document_ids: list[str],
        prompt: str,
        model: str | None = None,
        documents_texts: list[dict] | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Génère un rapport en streaming.

        Args:
            document_ids: UUIDs des documents à inclure
            prompt: Instruction utilisateur
            model: Modèle Ollama (défaut : mixtral)
            documents_texts: Liste de {nom, texte} si déjà récupérés

        Yields:
            Morceaux de texte du rapport
        """
        # TODO Phase 2 :
        # 1. Récupérer les textes depuis la DB si non fournis
        # 2. Construire le contexte (cf. build_context())
        # 3. self.ollama.generate_stream(contexte, model=model)
        raise NotImplementedError("TODO Phase 2")

    def build_context(self, documents: list[dict], prompt: str) -> str:
        """
        Construit le prompt complet avec les textes des documents.
        Tronque si le total dépasse MAX_CONTEXT_CHARS.

        Args:
            documents: Liste de {nom, texte_extrait}
            prompt: Instruction utilisateur

        Returns:
            Prompt complet pour Ollama
        """
        parts = []
        total_chars = len(prompt)

        for doc in documents:
            header = f"\n--- Document : {doc['nom']} ---\n"
            texte = doc.get("texte_extrait", "")

            # Tronquer si nécessaire pour rester dans la limite de contexte
            available = MAX_CONTEXT_CHARS - total_chars - len(header)
            if available <= 0:
                log.warning("Contexte plein, documents ignorés", document=doc["nom"])
                break

            if len(texte) > available:
                texte = texte[:available] + "\n[...tronqué...]"
                log.warning("Document tronqué", document=doc["nom"], chars_originaux=len(doc.get("texte_extrait", "")))

            parts.append(header + texte)
            total_chars += len(header) + len(texte)

        context = "\n".join(parts)
        return f"{context}\n\n--- Instruction ---\n{prompt}"
