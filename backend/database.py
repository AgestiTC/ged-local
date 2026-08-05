"""
Moteur de base de données — DocFlow AI
=======================================
Moteur SQLAlchemy async + factory de sessions + dépendance FastAPI.

Usage dans un router :
    from database import get_db
    from sqlalchemy.ext.asyncio import AsyncSession

    @router.get("/exemple")
    async def exemple(db: AsyncSession = Depends(get_db)):
        ...
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import get_settings
from logger import get_logger

log = get_logger(__name__)

settings = get_settings()

# --- Moteur async ---
_is_sqlite = settings.database_url.startswith("sqlite")
_engine_kwargs: dict = {"echo": settings.debug}
if not _is_sqlite:
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20
    _engine_kwargs["pool_pre_ping"] = True  # Vérifier la connexion avant chaque utilisation

engine = create_async_engine(settings.database_url, **_engine_kwargs)

# --- Factory de sessions ---
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,       # Éviter les lazy-load après commit
    autoflush=False,
    autocommit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dépendance FastAPI — fournit une session DB async.
    La session est fermée automatiquement après la requête.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """
    Initialise la base de données au démarrage.
    Crée les extensions pgvector/pg_trgm puis les tables si elles n'existent pas.
    En production, les migrations Alembic prennent le relais (alembic upgrade head).
    """
    from models import Base  # Import ici pour éviter les imports circulaires
    from sqlalchemy import text

    async with engine.begin() as conn:
        # Extensions requises — doit précéder create_all (type vector utilisé dans embeddings)
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        # Crée toutes les tables définies dans les modèles
        await conn.run_sync(Base.metadata.create_all)
        # Garde-fou idempotent : autorise les statuts 'catalogued' (médias catalogués sans fetch)
        # et 'absent' (fichier disparu de la source, repéré par la synchro — jamais supprimé).
        # Met à jour la contrainte CHECK des bases existantes (créées via init-db.sql) sans
        # nécessiter de migration. Sans effet si la table vient d'être créée sans contrainte.
        try:
            await conn.execute(text("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_statut_check"))
            await conn.execute(text(
                "ALTER TABLE documents ADD CONSTRAINT documents_statut_check "
                "CHECK (statut IN ('pending','extracted','enriched','error','catalogued','absent'))"
            ))
        except Exception:
            pass  # non bloquant : l'app démarre même si l'ALTER échoue

        # Planification de la synchro (Phase 3) : colonnes ajoutées à chaud sur les bases
        # existantes — `create_all` ne fait que CREATE TABLE, jamais ALTER.
        for ddl in (
            "ALTER TABLE sources ADD COLUMN IF NOT EXISTS sync_intervalle_minutes INTEGER",
            "ALTER TABLE sources ADD COLUMN IF NOT EXISTS dernier_sync TIMESTAMPTZ",
            "ALTER TABLE sources ADD COLUMN IF NOT EXISTS dernier_sync_recap JSONB",
            # Annulation inter-process + compteur de reprises (Sprint N+1).
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS annulation_demandee BOOLEAN DEFAULT false",
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS reprises INTEGER DEFAULT 0",
            # Recherche sémantique accélérée (E7) : préfixe Matryoshka 1024-d indexable (HNSW).
            # Le backfill des lignes existantes + la création de l'index se font en tâche de fond
            # (cf. job_worker._matryoshka_scheduler) pour ne pas bloquer le démarrage.
            "ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS embedding_small vector(1024)",
        ):
            try:
                await conn.execute(text(ddl))
            except Exception:
                pass  # non bloquant

        # Garde-fou idempotent JOBS (file de tâches durable) : les types sont désormais
        # applicatifs et évolutifs → on retire le CHECK type ; on autorise le statut
        # 'cancelled' ; on ajoute les colonnes de progression (bases créées via init-db.sql).
        try:
            await conn.execute(text("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_type_check"))
            await conn.execute(text("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_statut_check"))
            await conn.execute(text(
                "ALTER TABLE jobs ADD CONSTRAINT jobs_statut_check "
                "CHECK (statut IN ('pending','running','completed','failed','cancelled'))"
            ))
            await conn.execute(text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress INTEGER DEFAULT 0"))
            await conn.execute(text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_message TEXT"))
        except Exception:
            pass  # non bloquant

    # Recherche full-text performante : un simple index GIN sur l'expression accélère le FILTRE
    # (`@@`), mais **pas** le classement — `ts_rank(to_tsvector(texte || nom), …)` RECALCULE le
    # tsvector sur le texte COMPLET de chaque document trouvé → ~30 s sur un terme fréquent (66 k docs).
    # Solution : colonne `tsv` **tsvector STOCKÉE** (générée) → `ts_rank(tsv, …)` sans recalcul (~20×).
    # 1ᵉ démarrage : la génération réécrit la table (~70 s) — le backend n'a pas de healthcheck, donc
    # pas de risque de kill ; ensuite `IF NOT EXISTS` est instantané. Transaction dédiée (robuste).
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "ALTER TABLE documents ADD COLUMN IF NOT EXISTS tsv tsvector "
                "GENERATED ALWAYS AS (to_tsvector('french', "
                "COALESCE(texte_extrait, '') || ' ' || COALESCE(nom, ''))) STORED"
            ))
        async with engine.begin() as conn:
            await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_documents_tsv ON documents USING gin(tsv)"))
            # L'index sur l'expression (idx_documents_fts_nom) devient redondant → on l'enlève pour
            # ne pas payer son coût d'écriture à chaque insertion (le tsvector est déjà stocké).
            await conn.execute(text("DROP INDEX IF EXISTS idx_documents_fts_nom"))
        async with engine.begin() as conn:
            await conn.execute(text("ANALYZE documents"))
    except Exception as e:
        log.warning("Colonne/index full-text (tsv) non créés au démarrage", erreur=str(e) or type(e).__name__)

    # Full-text sur les MÉTADONNÉES IA (résumé, tags, mots-clés, catégorie) : une image sans texte
    # extrait n'a « Fanny Jovignot » que dans son résumé/tags → invisible si l'on ne cherche que
    # `documents.tsv` (texte+nom). Colonne tsvector STOCKÉE sur `metadonnees_ia`, cherchée EN PLUS.
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "ALTER TABLE metadonnees_ia ADD COLUMN IF NOT EXISTS tsv tsvector "
                "GENERATED ALWAYS AS (to_tsvector('french', "
                "COALESCE(resume, '') || ' ' || "
                "COALESCE(array_to_string(tags, ' '), '') || ' ' || "
                "COALESCE(array_to_string(mots_cles, ' '), '') || ' ' || "
                "COALESCE(categorie, '') || ' ' || COALESCE(sous_categorie, ''))) STORED"
            ))
        async with engine.begin() as conn:
            await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_meta_tsv ON metadonnees_ia USING gin(tsv)"))
        async with engine.begin() as conn:
            await conn.execute(text("ANALYZE metadonnees_ia"))
    except Exception as e:
        log.warning("Colonne/index full-text métadonnées (meta.tsv) non créés", erreur=str(e) or type(e).__name__)


async def close_db() -> None:
    """Ferme le pool de connexions proprement à l'arrêt."""
    await engine.dispose()
