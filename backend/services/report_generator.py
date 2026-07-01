"""
Service Génération de rapports — Orchestrateur principal
=========================================================
Construit le contexte à partir des documents sélectionnés et
génère un rapport via Ollama (streaming SSE vers le frontend).

Contrainte contexte : Mixtral = 32k tokens max.
Si les documents combinés dépassent, on tronque intelligemment.
"""

from collections.abc import AsyncGenerator

from config import get_settings
from logger import get_logger
from services import runtime_config

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
            documents_texts: Liste de {nom, texte_extrait} si déjà récupérés,
                             sinon chargés depuis la DB.

        Yields:
            Morceaux de texte du rapport
        """
        # Récupérer les textes si non fournis
        if documents_texts is None:
            documents_texts = await self._charger_textes(document_ids)

        prompt_complet = self.build_context(documents_texts, prompt)
        model_utilise = model or runtime_config.model_for("rapport")

        log.info(
            "Génération rapport streaming",
            nb_docs=len(documents_texts),
            model=model_utilise,
            nb_chars_contexte=len(prompt_complet),
        )

        async for chunk in self.ollama.generate_stream(prompt_complet, model=model_utilise):
            yield chunk

    async def generate(
        self,
        document_ids: list[str],
        prompt: str,
        model: str | None = None,
        documents_texts: list[dict] | None = None,
    ) -> str:
        """
        Génère un rapport complet (mode non-streaming).

        Returns:
            Texte complet du rapport
        """
        if documents_texts is None:
            documents_texts = await self._charger_textes(document_ids)

        prompt_complet = self.build_context(documents_texts, prompt)
        model_utilise = model or runtime_config.model_for("rapport")

        return await self.ollama.generate(prompt_complet, model=model_utilise)

    def build_context(self, documents: list[dict], prompt: str) -> str:
        """
        Construit le prompt complet avec les textes des documents.
        Tronque intelligemment si le total dépasse MAX_CONTEXT_CHARS.

        Args:
            documents: Liste de {nom, texte_extrait}
            prompt: Instruction utilisateur

        Returns:
            Prompt complet pour Ollama
        """
        parts = []
        total_chars = len(prompt) + 100  # Réserver pour le pied de contexte

        for doc in documents:
            texte = doc.get("texte_extrait") or doc.get("texte") or ""
            if not texte.strip():
                continue

            header = f"\n--- Document : {doc['nom']} ---\n"
            available = MAX_CONTEXT_CHARS - total_chars - len(header)

            if available <= 0:
                log.warning("Contexte plein — document ignoré", document=doc["nom"])
                break

            if len(texte) > available:
                texte = texte[:available] + "\n[... tronqué ...]"
                log.warning(
                    "Document tronqué",
                    document=doc["nom"],
                    chars_originaux=len(doc.get("texte_extrait") or ""),
                    chars_gardes=available,
                )

            parts.append(header + texte)
            total_chars += len(header) + len(texte)

        context = "\n".join(parts)
        return f"{context}\n\n--- Instruction ---\n{prompt}"

    async def _charger_textes(self, document_ids: list[str]) -> list[dict]:
        """Charge les textes extraits depuis la DB."""
        import uuid as _uuid

        from sqlalchemy import select

        from database import AsyncSessionLocal
        from models.document import Document

        doc_uuids = []
        for doc_id in document_ids:
            try:
                doc_uuids.append(_uuid.UUID(doc_id))
            except ValueError:
                log.warning("UUID invalide ignoré", doc_id=doc_id)

        if not doc_uuids:
            return []

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Document.nom, Document.texte_extrait)
                .where(Document.id.in_(doc_uuids))
            )
            rows = result.fetchall()

        return [{"nom": row[0], "texte_extrait": row[1] or ""} for row in rows]
