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
        # Garde-fou idempotent : autorise le statut 'catalogued' (médias catalogués sans
        # fetch). Met à jour la contrainte CHECK des bases existantes (créées via init-db.sql)
        # sans nécessiter de migration. Sans effet si la table vient d'être créée sans contrainte.
        try:
            await conn.execute(text("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_statut_check"))
            await conn.execute(text(
                "ALTER TABLE documents ADD CONSTRAINT documents_statut_check "
                "CHECK (statut IN ('pending','extracted','enriched','error','catalogued'))"
            ))
        except Exception:
            pass  # non bloquant : l'app démarre même si l'ALTER échoue

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


async def close_db() -> None:
    """Ferme le pool de connexions proprement à l'arrêt."""
    await engine.dispose()
