"""
Fixtures pytest partagées — DocFlow AI Backend
===============================================
Fournit une DB de test en mémoire (SQLite async) et des mocks
pour les services externes (Tika, Ollama).
"""

import asyncio
import uuid as _uuid
from unittest.mock import AsyncMock, MagicMock

import pgvector.sqlalchemy as _pgvec
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, Text
from sqlalchemy.dialects import postgresql as _pg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.types import CHAR, TypeDecorator


class _GUID(TypeDecorator):
    """UUID multi-dialecte pour les tests SQLite.

    Le type `postgresql.UUID` n'existe pas sous SQLite ; un simple `Text()` ne suffit
    pas car SQLite ne sait pas **binder** un objet `uuid.UUID` (« type 'UUID' is not
    supported »), or les modèles génèrent des UUID via `default=uuid.uuid4`. Ce
    décorateur stocke en `CHAR(36)` et convertit `uuid.UUID ↔ str` au bind/lecture,
    en rendant des `uuid.UUID` (comme le fait `UUID(as_uuid=True)` en production).
    """

    impl = CHAR(36)
    cache_ok = True

    def __init__(self, as_uuid: bool = True, **_kw):
        self.as_uuid = as_uuid
        super().__init__()

    def process_bind_param(self, value, dialect):
        return None if value is None else str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if self.as_uuid and not isinstance(value, _uuid.UUID):
            return _uuid.UUID(str(value))
        return value


# Patch des types PostgreSQL → types SQLite-compatibles
# Doit être fait AVANT tout import de modèle SQLAlchemy
_pgvec.Vector = lambda dim=None: Text()   # pgvector → Text
_pg.JSONB = JSON                          # type: ignore[assignment]
_pg.UUID = lambda as_uuid=True, **kw: _GUID(as_uuid=as_uuid)  # type: ignore[assignment]
_pg.ARRAY = lambda item_type, **kw: JSON()  # type: ignore[assignment]

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
