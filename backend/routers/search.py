"""
Router Search — GET /api/search
================================
Recherche hybride : full-text PostgreSQL + sémantique pgvector.

Endpoints :
  GET /search?q=...&type=hybrid    → recherche hybride (défaut)
  GET /search?q=...&type=text      → full-text uniquement
  GET /search?q=...&type=semantic  → sémantique uniquement
  GET /search/tags                 → liste tous les tags existants
  GET /search/categories           → liste toutes les catégories

Stratégie hybride :
  - Full-text : PostgreSQL ts_rank sur texte_extrait + nom
  - Sémantique : cosine similarity pgvector sur embeddings
  - Score hybride = 0.4 * score_text + 0.6 * score_semantique
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from logger import get_logger
from models.document import Document
from models.metadata import MetadonneeIA
from services.ollama_service import OllamaService

log = get_logger(__name__)
settings = get_settings()
router = APIRouter()


def _doc_resultat(doc: Document, meta: MetadonneeIA | None, score: float) -> dict:
    """Sérialise un résultat de recherche."""
    return {
        "id": str(doc.id),
        "nom": doc.nom,
        "extension": doc.extension,
        "taille_octets": doc.taille_octets,
        "statut": doc.statut,
        "score": round(score, 4),
        "date_import": doc.date_import.isoformat() if doc.date_import else None,
        "metadonnees_ia": {
            "categorie": meta.categorie if meta else None,
            "tags": meta.tags or [] if meta else [],
            "resume": meta.resume if meta else None,
            "langue": meta.langue if meta else None,
        },
    }


async def _recherche_fulltext(q: str, db: AsyncSession, limit: int = 20) -> list[tuple]:
    """
    Recherche full-text PostgreSQL via ts_vector.
    Retourne une liste de (Document, MetadonneeIA|None, score).
    """
    # Requête full-text sur texte_extrait + nom
    stmt = text("""
        SELECT
            d.id,
            ts_rank(
                to_tsvector('french', coalesce(d.texte_extrait, '') || ' ' || d.nom),
                plainto_tsquery('french', :q)
            ) AS score
        FROM documents d
        WHERE
            to_tsvector('french', coalesce(d.texte_extrait, '') || ' ' || d.nom)
            @@ plainto_tsquery('french', :q)
        ORDER BY score DESC
        LIMIT :limit
    """)

    result = await db.execute(stmt, {"q": q, "limit": limit})
    rows = result.fetchall()

    if not rows:
        return []

    doc_ids = [row[0] for row in rows]
    scores = {row[0]: float(row[1]) for row in rows}

    # Charger les documents + métadonnées
    docs_result = await db.execute(
        select(Document, MetadonneeIA)
        .outerjoin(MetadonneeIA, MetadonneeIA.document_id == Document.id)
        .where(Document.id.in_(doc_ids))
    )
    doc_rows = docs_result.all()

    resultats = [(doc, meta, scores.get(doc.id, 0.0)) for doc, meta in doc_rows]
    resultats.sort(key=lambda x: x[2], reverse=True)
    return resultats


async def _recherche_semantique(q: str, db: AsyncSession, limit: int = 20) -> list[tuple]:
    """
    Recherche sémantique via cosine similarity sur les embeddings pgvector.
    Retourne une liste de (Document, MetadonneeIA|None, score).
    """
    ollama = OllamaService()

    # Générer l'embedding de la requête
    try:
        query_embedding = await ollama.embed(q)
    except Exception as e:
        log.warning("Embedding requête échoué", erreur=str(e))
        return []

    if not query_embedding:
        return []

    # Formater le vecteur pour pgvector
    vecteur_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    stmt = text("""
        SELECT
            e.document_id,
            MAX(1 - (e.embedding <=> :embedding::vector)) AS score
        FROM embeddings e
        WHERE e.embedding IS NOT NULL
        GROUP BY e.document_id
        ORDER BY score DESC
        LIMIT :limit
    """)

    result = await db.execute(stmt, {"embedding": vecteur_str, "limit": limit})
    rows = result.fetchall()

    if not rows:
        return []

    doc_ids = [row[0] for row in rows]
    scores = {row[0]: float(row[1]) for row in rows}

    docs_result = await db.execute(
        select(Document, MetadonneeIA)
        .outerjoin(MetadonneeIA, MetadonneeIA.document_id == Document.id)
        .where(Document.id.in_(doc_ids))
    )
    doc_rows = docs_result.all()

    resultats = [(doc, meta, scores.get(doc.id, 0.0)) for doc, meta in doc_rows]
    resultats.sort(key=lambda x: x[2], reverse=True)
    return resultats


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1, description="Requête de recherche"),
    type: str = Query(default="hybrid", description="hybrid | text | semantic"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, description="Décalage pour la pagination"),
    categorie: str | None = Query(default=None, description="Filtrer par catégorie"),
    extension: str | None = Query(default=None, description="Filtrer par extension"),
    db: AsyncSession = Depends(get_db),
):
    """
    Recherche hybride full-text + sémantique dans les documents indexés.
    """
    if type not in ("hybrid", "text", "semantic"):
        raise HTTPException(status_code=400, detail="type doit être : hybrid, text ou semantic")

    resultats_text: list[tuple] = []
    resultats_sem: list[tuple] = []

    # Récupérer plus de résultats en amont pour permettre la pagination après filtrage
    fetch_limit = min(limit + offset + 50, 200)

    if type in ("hybrid", "text"):
        resultats_text = await _recherche_fulltext(q, db, limit=fetch_limit)

    if type in ("hybrid", "semantic"):
        resultats_sem = await _recherche_semantique(q, db, limit=fetch_limit)

    # Fusion des scores (hybride)
    if type == "hybrid":
        # Normaliser les scores text (max = 1)
        max_text = max((s for _, _, s in resultats_text), default=1.0) or 1.0
        max_sem = max((s for _, _, s in resultats_sem), default=1.0) or 1.0

        scores_fusionnes: dict = {}
        docs_index: dict = {}

        for doc, meta, score in resultats_text:
            doc_id = str(doc.id)
            score_norm = score / max_text
            scores_fusionnes[doc_id] = scores_fusionnes.get(doc_id, 0) + 0.4 * score_norm
            docs_index[doc_id] = (doc, meta)

        for doc, meta, score in resultats_sem:
            doc_id = str(doc.id)
            score_norm = score / max_sem
            scores_fusionnes[doc_id] = scores_fusionnes.get(doc_id, 0) + 0.6 * score_norm
            if doc_id not in docs_index:
                docs_index[doc_id] = (doc, meta)

        resultats_fusionnes = [
            (docs_index[doc_id][0], docs_index[doc_id][1], score)
            for doc_id, score in sorted(scores_fusionnes.items(), key=lambda x: x[1], reverse=True)
        ]
        resultats_candidats = resultats_fusionnes

    elif type == "text":
        resultats_candidats = resultats_text
    else:
        resultats_candidats = resultats_sem

    # Appliquer les filtres post-recherche avant pagination
    if categorie:
        resultats_candidats = [
            (d, m, s) for d, m, s in resultats_candidats
            if m and m.categorie and m.categorie.lower() == categorie.lower()
        ]
    if extension:
        ext = extension.lstrip(".").lower()
        resultats_candidats = [(d, m, s) for d, m, s in resultats_candidats if d.extension == ext]

    total_filtre = len(resultats_candidats)
    resultats_finaux = resultats_candidats[offset:offset + limit]

    return {
        "query": q,
        "type": type,
        "total": total_filtre,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total_filtre,
        "resultats": [_doc_resultat(d, m, s) for d, m, s in resultats_finaux],
    }


@router.get("/search/tags")
async def list_tags(db: AsyncSession = Depends(get_db)):
    """Retourne tous les tags existants avec leur fréquence."""
    stmt = text("""
        SELECT unnest(tags) AS tag, count(*) AS nb
        FROM metadonnees_ia
        WHERE tags IS NOT NULL AND array_length(tags, 1) > 0
        GROUP BY tag
        ORDER BY nb DESC, tag
        LIMIT 200
    """)
    result = await db.execute(stmt)
    rows = result.fetchall()

    return {
        "total": len(rows),
        "tags": [{"tag": row[0], "nb_documents": row[1]} for row in rows],
    }


@router.get("/search/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    """Retourne toutes les catégories existantes avec leur fréquence."""
    stmt = (
        select(MetadonneeIA.categorie, func.count().label("nb"))
        .where(MetadonneeIA.categorie.isnot(None))
        .group_by(MetadonneeIA.categorie)
        .order_by(func.count().desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    return {
        "total": len(rows),
        "categories": [{"categorie": row[0], "nb_documents": row[1]} for row in rows],
    }
