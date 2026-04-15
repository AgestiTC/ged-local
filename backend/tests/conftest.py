"""
Fixtures pytest partagées — DocFlow AI Backend
===============================================
Fournit une DB de test en mémoire (SQLite async) et des mocks
pour les services externes (Tika, Ollama).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Patch pgvector.sqlalchemy.Vector → Text pour SQLite (pgvector n'existe pas en SQLite)
# Doit être importé avant tout modèle SQLAlchemy qui utilise Vector
from sqlalchemy import Text
import pgvector.sqlalchemy as _pgvec
_pgvec.Vector = lambda dim=None: Text()  # type: ignore[assignment]

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# DB de test en mémoire — évite de toucher PostgreSQL
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Boucle asyncio partagée pour toute la session de tests."""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """Moteur SQLite en mémoire pour les tests."""
    # SQLite n'a pas pgvector — on patch les types vector pour les tests
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
    )

    # Créer les tables (en mockant pgvector)
    from models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine):
    """Session de DB de test."""
    session_factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    async with session_factory() as session:
        yield session


@pytest.fixture
def mock_tika():
    """Mock du service Tika."""
    tika = MagicMock()
    tika.extract_metadata = AsyncMock(return_value=[{
        "X-TIKA:content": "Contenu test du document. Ceci est un texte d'exemple pour les tests.",
        "Content-Type": "application/pdf",
        "dc:title": "Document Test",
        "resourceName": "test.pdf",
    }])
    tika.extract_text = AsyncMock(return_value="Contenu test du document.")
    tika.check_health = AsyncMock(return_value=True)
    return tika


@pytest.fixture
def mock_ollama():
    """Mock du service Ollama."""
    ollama = MagicMock()
    ollama.generate = AsyncMock(return_value='''{
        "categorie": "rapport",
        "sous_categorie": "test",
        "tags": ["test", "unitaire", "docflow"],
        "resume": "Document de test pour les tests unitaires DocFlow AI.",
        "langue": "fr",
        "entites": {"personnes": [], "dates": [], "lieux": [], "organisations": []},
        "mots_cles": ["test", "docflow"],
        "niveau_confidentialite": "normal"
    }''')
    ollama.generate_stream = AsyncMock(return_value=iter(["Rapport ", "généré ", "avec succès."]))
    ollama.embed = AsyncMock(return_value=[0.1] * 10)  # Vecteur court pour les tests
    ollama.check_health = AsyncMock(return_value=True)
    return ollama


@pytest.fixture
def mock_embedding_service(mock_ollama):
    """Mock du service Embeddings."""
    from services.embedding_service import EmbeddingService
    service = EmbeddingService(mock_ollama)
    service.embed_document = AsyncMock(return_value=2)  # 2 chunks générés
    return service


@pytest_asyncio.fixture
async def test_app(db_session):
    """App FastAPI de test avec DB mockée."""
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(test_app):
    """Client HTTP de test."""
    async with AsyncClient(
        transport=ASGITransport(app=test_app),
        base_url="http://test",
    ) as c:
        yield c
