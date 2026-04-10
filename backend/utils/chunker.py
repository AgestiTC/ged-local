"""
Utilitaire Chunker — Découpage de texte en chunks
===================================================
Découpe un texte long en chunks avec overlap pour les embeddings.

Stratégie :
  - Chunk de ~500 tokens (≈ 2000 caractères)
  - Overlap de ~50 tokens (≈ 200 caractères) entre chunks consécutifs
  - Respect des limites de phrases si possible

Note : On utilise une approximation caractères/tokens (1 token ≈ 4 chars)
pour éviter de charger un tokenizer lourd. Adapter si besoin.
"""

from config import get_settings

settings = get_settings()

# Approximation : 1 token ≈ 4 caractères
CHARS_PER_TOKEN = 4


def chunk_text(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[str]:
    """
    Découpe un texte en chunks avec overlap.

    Args:
        text: Texte à découper
        chunk_size: Taille en tokens (défaut : settings.chunk_size)
        chunk_overlap: Overlap en tokens (défaut : settings.chunk_overlap)

    Returns:
        Liste de chunks (strings)
    """
    chunk_size = chunk_size or settings.chunk_size
    chunk_overlap = chunk_overlap or settings.chunk_overlap

    chunk_chars = chunk_size * CHARS_PER_TOKEN
    overlap_chars = chunk_overlap * CHARS_PER_TOKEN

    if len(text) <= chunk_chars:
        return [text.strip()] if text.strip() else []

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_chars

        # Essayer de couper à la limite d'une phrase ou d'un paragraphe
        if end < len(text):
            # Chercher le dernier point/newline dans les 200 derniers chars
            cutpoint = text.rfind("\n\n", end - 200, end)
            if cutpoint == -1:
                cutpoint = text.rfind(". ", end - 200, end)
            if cutpoint != -1:
                end = cutpoint + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # Avancer avec overlap
        start = end - overlap_chars
        if start >= len(text):
            break

    return chunks
