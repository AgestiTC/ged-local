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

Le score ci-dessus est RELATIF au lot (normalisé par le meilleur) → chaque résultat est en
plus marqué `pertinent` / `etiquette` par le gate ABSOLU de `services/pertinence.py`, seul
capable de dire « aucun document ne répond vraiment à cette requête ».
"""

from collections import OrderedDict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from logger import get_logger
from models.document import Document
from models.metadata import MetadonneeIA
from services import pertinence
from services.ollama_service import OllamaService
from utils.vectors import matryoshka_prefix

log = get_logger(__name__)
settings = get_settings()
router = APIRouter()

# Embeddings de requêtes déjà calculés (clé : modèle + requête). Déterministe à modèle fixe.
_EMBED_CACHE: OrderedDict[tuple[str, str], list[float]] = OrderedDict()
_EMBED_CACHE_MAX = 128
# Indicateur GLOBAL « Ollama lent pour l'embedding » (GPU pris par la vision, cold-load…). Une
# recherche embarque la requête DEUX fois (sémantique + gate) → sans ça 2×15 s = 30 s = timeout
# navigateur. Dès qu'un embed de requête échoue, on note l'instant : pendant ~20 s, TOUTES les
# recherches basculent immédiatement sur le TEXTE (pas de nouvel embed) → réactif. S'auto-répare
# passé le TTL (on retente, Ollama peut s'être libéré).
_EMBED_STATE: dict[str, float] = {"last_fail": 0.0}
_EMBED_FAIL_TTL = 20.0


# Catégories larges de type de fichier (pour regrouper/filtrer les résultats côté UI).
_TYPES_GROUPES: dict[str, set[str]] = {
    "PDF": {"pdf"},
    "Document": {"doc", "docx", "odt", "rtf", "txt", "md"},
    "Tableur": {"xls", "xlsx", "ods", "csv"},
    "Présentation": {"ppt", "pptx", "pps", "ppsx", "odp"},
    "Image": {"jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff", "svg", "ico",
              "heic", "heif", "avif", "raw", "cr2", "nef", "arw", "dng", "psd"},
    "Audio": {"mp3", "wav", "flac", "aac", "ogg", "wma", "m4a", "opus", "aiff"},
    "Vidéo": {"mp4", "avi", "mkv", "mov", "wmv", "flv", "webm", "m4v", "mpg", "mpeg"},
    "Archive": {"zip", "rar", "7z", "tar", "gz"},
}
_EXT_VERS_GROUPE: dict[str, str] = {ext: grp for grp, exts in _TYPES_GROUPES.items() for ext in exts}


def _type_groupe(extension: str | None) -> str:
    """Catégorie large d'un fichier depuis son extension (PDF, Document, Image, Audio…)."""
    return _EXT_VERS_GROUPE.get((extension or "").lstrip(".").lower(), "Autre")


def _doc_resultat(doc: Document, meta: MetadonneeIA | None, score: float) -> dict:
    """Sérialise un résultat de recherche."""
    from services.file_access import chemin_affichage
    res = {
        "id": str(doc.id),
        "nom": doc.nom,
        "extension": doc.extension,
        "type_groupe": _type_groupe(doc.extension),
        "taille_octets": doc.taille_octets,
        "statut": doc.statut,
        "chemin_copie": chemin_affichage(doc.chemin or ""),  # UNC pour « copier le chemin »
        "score": round(score, 4),
        "date_import": doc.date_import.isoformat() if doc.date_import else None,
        "metadonnees_ia": {
            "categorie": meta.categorie if meta else None,
            "tags": meta.tags or [] if meta else [],
            "resume": meta.resume if meta else None,
            "langue": meta.langue if meta else None,
        },
    }
    # Document issu du wiki → lien BookStack (carte spécifique côté front : « Ouvrir dans le wiki »).
    if (doc.chemin or "").startswith("wiki://"):
        from services.runtime_config import effective
        base = (effective("bookstack_url") or "").rstrip("/")
        pid = doc.chemin.replace("wiki://", "")
        res["wiki_url"] = f"{base}/link/{pid}" if base else None
    return res


async def _recherche_fulltext(q: str, db: AsyncSession, limit: int = 20) -> list[tuple]:
    """
    Recherche full-text PostgreSQL via ts_vector.
    Retourne une liste de (Document, MetadonneeIA|None, score).
    """
    # Classement full-text sur les colonnes tsvector STOCKÉES : `d.tsv` (texte extrait + nom) ET
    # `m.tsv` (métadonnées IA : résumé, tags, mots-clés, catégorie). On matche sur l'UNE OU l'AUTRE
    # → un document sans texte (image cataloguée) reste trouvable par son résumé/tags. `ts_rank` sur
    # colonnes stockées = pas de recalcul → rapide (index GIN idx_documents_tsv / idx_meta_tsv).
    stmt = text("""
        SELECT d.id, GREATEST(
                   ts_rank(d.tsv, plainto_tsquery('french', :q)),
                   ts_rank(COALESCE(m.tsv, ''::tsvector), plainto_tsquery('french', :q))
               ) AS score
        FROM documents d
        LEFT JOIN metadonnees_ia m ON m.document_id = d.id
        WHERE d.tsv @@ plainto_tsquery('french', :q)
           OR m.tsv @@ plainto_tsquery('french', :q)
        ORDER BY score DESC
        LIMIT :limit
    """)
    try:
        rows = (await db.execute(stmt, {"q": q, "limit": limit})).fetchall()
    except Exception as e:
        # `tsv` pas encore créée (déploiement avant migration) → repli : recalcul à la volée (lent).
        log.warning("Colonne tsv indisponible — repli full-text sur l'expression", erreur=str(e) or type(e).__name__)
        await db.rollback()
        stmt_expr = text("""
            SELECT d.id,
                   ts_rank(to_tsvector('french', coalesce(d.texte_extrait,'') || ' ' || coalesce(d.nom,'')),
                           plainto_tsquery('french', :q)) AS score
            FROM documents d
            WHERE to_tsvector('french', coalesce(d.texte_extrait,'') || ' ' || coalesce(d.nom,''))
                  @@ plainto_tsquery('french', :q)
            ORDER BY score DESC LIMIT :limit
        """)
        rows = (await db.execute(stmt_expr, {"q": q, "limit": limit})).fetchall()

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


async def _embed_query(q: str) -> list[float] | None:
    """
    Embedding de la requête — via l'usage « embeddings » configuré (cohérent avec
    l'indexation) ; à défaut, le modèle d'embedding par défaut. None si Ollama échoue.

    Mémoïsé : une recherche embarque la même requête deux fois (top sémantique, puis mesure
    des candidats trouvés lexicalement) et l'assistant rejoue les mêmes libellés — sans cache
    on paierait un appel Ollama à chaque fois, sur le chemin critique de la recherche.
    """
    import asyncio
    import time

    from services import runtime_config

    modele = runtime_config.usage_model("embeddings") or ""
    cle = (modele, q)
    if cle in _EMBED_CACHE:
        _EMBED_CACHE.move_to_end(cle)
        return _EMBED_CACHE[cle]

    # Ollama récemment lent (< 20 s) → repli texte immédiat, pour TOUTES les requêtes (pas juste la
    # 2ᵉ passe) → aucune recherche ne paie 15 s pendant une lenteur (vision en cours).
    if (time.monotonic() - _EMBED_STATE["last_fail"]) < _EMBED_FAIL_TTL:
        return None

    try:
        # Timeout COURT (fail-fast) : si Ollama est lent à embarquer la requête (GPU pris par la
        # vision, cold-load…), on abandonne le sémantique et on retombe sur le TEXTE (instantané)
        # AVANT le timeout de 30 s du navigateur → l'utilisateur a toujours des résultats.
        #
        # `asyncio.wait_for` borne le temps MURAL TOTAL : `embed()` porte un `@retry(3 tentatives)`
        # (voulu à l'indexation) qui, sur timeout, rejouerait 3×15 s ≈ 45 s > 30 s navigateur. On
        # coupe donc l'ensemble (retries compris) à 10 s, quoi que fasse tenacity.
        embedding = await asyncio.wait_for(
            OllamaService().embed(q, model=modele or None, timeout=8.0),
            timeout=10.0,
        )
    except Exception as e:
        log.warning("Embedding requête échoué (repli texte)", erreur=str(e) or type(e).__name__)
        _EMBED_STATE["last_fail"] = time.monotonic()
        return None
    if not embedding:
        _EMBED_STATE["last_fail"] = time.monotonic()
        return None

    _EMBED_CACHE[cle] = embedding
    if len(_EMBED_CACHE) > _EMBED_CACHE_MAX:
        _EMBED_CACHE.popitem(last=False)
    return embedding


async def _cosinus_pour(q: str, doc_ids: list[str], db: AsyncSession) -> dict[str, float]:
    """
    Similarité cosinus de la requête pour des documents PRÉCIS.

    Le gate de pertinence en a besoin : la recherche sémantique ne renvoie que son top N
    global, or sur un gros corpus un document trouvé lexicalement en est souvent absent. Sans
    sa mesure, on ne saurait pas s'il est vraiment proche du SENS de la requête, et le laisser
    passer sur le seul match de mots fait remonter du hors-sujet (mesuré sur les 56 k docs du
    NAS : « dossier de mariage » matche des thèses, des guides du locataire…).
    """
    if not doc_ids:
        return {}
    embedding = await _embed_query(q)
    if not embedding:
        return {}

    vecteur_str = "[" + ",".join(str(v) for v in embedding) + "]"
    stmt = text("""
        SELECT
            e.document_id,
            MAX(1 - (e.embedding <=> CAST(:embedding AS vector))) AS score
        FROM embeddings e
        WHERE e.embedding IS NOT NULL
          AND e.document_id = ANY(CAST(:ids AS uuid[]))
        GROUP BY e.document_id
    """)
    result = await db.execute(stmt, {"embedding": vecteur_str, "ids": doc_ids})
    return {str(row[0]): float(row[1]) for row in result.fetchall()}


async def _recherche_semantique(q: str, db: AsyncSession, limit: int = 20) -> list[tuple]:
    """
    Recherche sémantique via cosine similarity sur les embeddings pgvector.
    Retourne une liste de (Document, MetadonneeIA|None, score).
    """
    query_embedding = await _embed_query(q)
    if not query_embedding:
        return []

    # ── 1ᵉ passe ANN (E7) : préfixe Matryoshka 1024-d indexé HNSW → ~4 ms au lieu de scanner tous
    # les vecteurs 4096-d (non indexables par pgvector, plafond 2000 dims). Repli sur le scan complet
    # si la colonne 1024-d/l'index n'est pas prête. NB : CAST(:x AS vector) (le `::` casse le parseur).
    qsmall = matryoshka_prefix(query_embedding)
    scores: dict = {}
    if qsmall is not None:
        qs = "[" + ",".join(str(v) for v in qsmall) + "]"
        try:
            await db.execute(text("SET LOCAL hnsw.ef_search = 200"))
            rows = (await db.execute(text("""
                SELECT document_id, (embedding_small <=> CAST(:qs AS vector)) AS dist
                FROM embeddings
                WHERE embedding_small IS NOT NULL
                ORDER BY dist
                LIMIT :probe
            """), {"qs": qs, "probe": 400})).fetchall()
            for did, dist in rows:
                sim = 1.0 - float(dist)
                if sim > scores.get(did, -2.0):
                    scores[did] = sim
        except Exception as e:
            log.warning("ANN 1024-d indisponible — repli scan complet", erreur=str(e) or type(e).__name__)
            await db.rollback()
            scores = {}

    if not scores:
        # Repli : scan complet des vecteurs 4096 (correct mais lent — colonne 1024-d pas encore prête).
        vecteur_str = "[" + ",".join(str(v) for v in query_embedding) + "]"
        rows = (await db.execute(text("""
            SELECT e.document_id, MAX(1 - (e.embedding <=> CAST(:embedding AS vector))) AS score
            FROM embeddings e
            WHERE e.embedding IS NOT NULL
            GROUP BY e.document_id
            ORDER BY score DESC
            LIMIT :limit
        """), {"embedding": vecteur_str, "limit": limit})).fetchall()
        scores = {row[0]: float(row[1]) for row in rows}

    if not scores:
        return []

    doc_ids = sorted(scores, key=scores.get, reverse=True)[:limit]
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
    inclure_non_pertinents: bool = Query(
        default=False,
        description="Marquer tous les résultats pertinents (neutralise le gate de pertinence)",
    ),
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

    if type == "semantic":
        # En sémantique pur le lexical ne participe PAS au classement, mais il reste le
        # discriminant du gate (une requête sans réponse ne matche aucun mot) → on le
        # récupère quand même pour ne pas rendre ce mode arbitrairement plus strict.
        resultats_text = await _recherche_fulltext(q, db, limit=fetch_limit)

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

    # Pertinence ABSOLUE (cosinus brut) — indépendante de la normalisation /max, qui met
    # toujours le top à ~100 % même quand le lot entier est hors-sujet. Sert au gate et aux
    # TRANCHES de pertinence côté GED. Absente d'un document = pas de mesure sémantique
    # (mode texte, ou document hors du top sémantique) → le front retombe sur le score.
    cos_abs = {str(d.id): s for d, m, s in resultats_sem}
    ids_texte = {str(d.id) for d, m, s in resultats_text}

    # Candidats trouvés lexicalement mais absents du top sémantique : on MESURE leur cosinus
    # au lieu de les accepter sur le seul match de mots. Sur un gros corpus ce match est un
    # signal faible (« dossier » et « mariage » se croisent dans quantité de documents sans
    # rapport) — c'est précisément ce qui rendait les résultats non pertinents.
    if type != "text" and resultats_sem:
        manquants = [str(d.id) for d, m, s in resultats_candidats if str(d.id) not in cos_abs]
        cos_abs.update(await _cosinus_pour(q, manquants, db))

    # Gate appliqué à TOUS les candidats (pas seulement à la page) : `nb_pertinents` doit
    # répondre « aucun document pertinent » pour la recherche entière, pas pour la page 1.
    # On ne retire rien — les non-pertinents restent marqués dans la réponse, ce qui rend
    # « Afficher quand même » instantané côté front, sans second appel.
    haut, bas = pertinence.seuils()
    gate: dict[str, tuple[bool, str]] = {}
    for d, m, s in resultats_candidats:
        doc_id = str(d.id)
        pertinent, etiquette = pertinence.evaluer(
            cos_abs.get(doc_id), doc_id in ids_texte, haut, bas
        )
        gate[doc_id] = (True, etiquette) if inclure_non_pertinents else (pertinent, etiquette)
    nb_pertinents = sum(1 for pertinent, _ in gate.values() if pertinent)

    # Les pertinents D'ABORD, à score égal l'ordre habituel. Le classement reste le score
    # hybride, mais celui-ci est relatif et mêle lexical et sémantique : un faux positif bien
    # « écrit » peut devancer un vrai résultat. Mesuré sur le corpus NAS (56 k docs) : pour
    # « dossier de mariage », les 15 premiers étaient tous non pertinents alors que 34 l'étaient
    # plus bas — sans ce tri, la page 1 filtrée serait vide et la pagination inexploitable.
    resultats_candidats = sorted(
        resultats_candidats, key=lambda t: (not gate[str(t[0].id)][0], -t[2])
    )

    total_filtre = len(resultats_candidats)
    resultats_finaux = resultats_candidats[offset:offset + limit]

    return {
        "query": q,
        "type": type,
        "total": total_filtre,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total_filtre,
        "nb_pertinents": nb_pertinents,
        "nb_masques": total_filtre - nb_pertinents,
        "seuils": {"haut": haut, "bas": bas},
        "resultats": [
            {
                **_doc_resultat(d, m, s),
                "pertinence": (
                    round(cos_abs[str(d.id)] * 100) if str(d.id) in cos_abs else None
                ),
                "pertinent": gate[str(d.id)][0],
                "etiquette": gate[str(d.id)][1],
            }
            for d, m, s in resultats_finaux
        ],
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
        LIMIT 2000
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
