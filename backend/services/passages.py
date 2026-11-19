"""
Passages d'un document les plus proches d'une question (plan prompts + RAG, étape B1).
=====================================================================================
Le chat de la GED envoyait au modèle les 1 500 PREMIERS caractères de chaque document trouvé :
la réponse d'un manuel de 400 000 caractères était rarement au début. On envoie désormais le
**passage indexé** (morceau de ~2 000 caractères, celui des embeddings) le plus proche de la
question — la même mesure que la recherche (préfixe Matryoshka 1024-d).

Lecture seule. Rend {} quand ce n'est pas possible (base sans pgvector, Ollama indisponible,
document sans vecteurs) : l'appelant garde alors le début du texte.
"""
from __future__ import annotations

from logger import get_logger

log = get_logger(__name__)


async def meilleurs_passages(question: str, doc_ids: list[str], par_document: int = 1) -> dict[str, list[tuple[int, str]]]:
    """
    {document_id: [(chunk_index, texte), …]} — les `par_document` passages les plus proches de la
    question, du plus proche au moins proche.
    """
    if not doc_ids or not (question or "").strip():
        return {}
    from sqlalchemy import text

    from database import AsyncSessionLocal
    from routers.search import _embed_query, _sur_postgres
    from utils.vectors import matryoshka_prefix

    try:
        async with AsyncSessionLocal() as db:
            if not _sur_postgres(db):
                return {}
            vecteur = matryoshka_prefix(await _embed_query(question[:4000]))
            if vecteur is None:
                return {}
            qs = "[" + ",".join(str(v) for v in vecteur) + "]"
            rows = (await db.execute(text("""
                SELECT did, chunk_index, chunk_text FROM (
                    SELECT CAST(document_id AS TEXT) AS did, chunk_index, chunk_text,
                           row_number() OVER (PARTITION BY document_id
                                              ORDER BY embedding_small <=> CAST(:qs AS vector)) AS rang
                    FROM embeddings
                    WHERE embedding_small IS NOT NULL AND document_id = ANY(CAST(:ids AS uuid[]))
                ) x
                WHERE rang <= :n
                ORDER BY did, rang
            """), {"qs": qs, "ids": list(doc_ids), "n": par_document})).fetchall()
    except Exception as e:  # noqa: BLE001 — le chat garde le début du texte
        log.warning("Passages proches indisponibles", erreur=str(e) or type(e).__name__)
        return {}
    passages: dict[str, list[tuple[int, str]]] = {}
    for did, idx, extrait in rows:
        if (extrait or "").strip():
            passages.setdefault(did, []).append((idx, extrait.strip()))
    return passages


def extrait_pour(texte: str, passages: list[tuple[int, str]] | None, taille: int) -> str:
    """
    Ce qu'on montre au modèle pour un document : le texte entier s'il tient dans `taille`, sinon
    ses passages proches (dans l'ordre du document, marqués « […] »), sinon son début.
    """
    texte = (texte or "").strip()
    if len(texte) <= taille or not passages:
        return texte[:taille]
    morceaux = [p for _, p in sorted(passages)]
    return "[…] " + "\n[…]\n".join(morceaux) + " […]"
