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
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,          # Log SQL en mode debug
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,           # Vérifier la connexion avant chaque utilisation
)

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


async def close_db() -> None:
    """Ferme le pool de connexions proprement à l'arrêt."""
    await engine.dispose()
