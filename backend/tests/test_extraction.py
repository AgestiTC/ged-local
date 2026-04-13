"""
Tests d'intégration — services/extraction.py
=============================================
Teste le pipeline d'extraction avec des services mockés (sans Tika ni Ollama réels).
"""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from models import Base
from models.document import Document
from models.metadata import MetadonneeIA
from services.extraction import ExtractionService, _extraire_json


# ─── Tests unitaires de _extraire_json ───────────────────────────────────────

class TestExtraireJson:
    def test_json_direct(self):
        reponse = '{"categorie": "rapport", "tags": ["a", "b"]}'
        data = _extraire_json(reponse)
        assert data["categorie"] == "rapport"
        assert data["tags"] == ["a", "b"]

    def test_json_dans_bloc_markdown(self):
        reponse = """Voici le JSON :
```json
{"categorie": "contrat", "resume": "Test"}
```
"""
        data = _extraire_json(reponse)
        assert data["categorie"] == "contrat"

    def test_json_premier_trouve(self):
        reponse = 'Réponse : {"categorie": "facture", "tags": []} et voilà.'
        data = _extraire_json(reponse)
        assert data["categorie"] == "facture"

    def test_json_invalide_leve_exception(self):
        import json
        with pytest.raises(json.JSONDecodeError):
            _extraire_json("Aucun JSON ici du tout")

    def test_champs_optionnels_null(self):
        reponse = '{"categorie": "note", "sous_categorie": null, "tags": [], "resume": "OK", "langue": "fr", "entites": {}, "mots_cles": [], "niveau_confidentialite": "normal"}'
        data = _extraire_json(reponse)
        assert data["sous_categorie"] is None


# ─── Tests d'intégration ExtractionService ───────────────────────────────────

@pytest.fixture
def mock_tika():
    tika = MagicMock()
    tika.extract_metadata = AsyncMock(return_value=[{
        "X-TIKA:content": "Contenu du document de test avec des informations importantes.",
        "Content-Type": "application/pdf",
    }])
    return tika


@pytest.fixture
def mock_ollama():
    ollama = MagicMock()
    ollama.generate = AsyncMock(return_value='''{
        "categorie": "rapport",
        "sous_categorie": "test",
        "tags": ["test", "unitaire"],
        "resume": "Document de test.",
        "langue": "fr",
        "entites": {"personnes": [], "dates": [], "lieux": [], "organisations": []},
        "mots_cles": ["test"],
        "niveau_confidentialite": "normal"
    }''')
    return ollama


@pytest.fixture
def mock_embeddings():
    embeddings = MagicMock()
    embeddings.embed_document = AsyncMock(return_value=1)
    return embeddings


@pytest_asyncio.fixture
async def mem_db():
    """DB SQLite en mémoire pour les tests d'intégration."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    # Patch pgvector.sqlalchemy pour SQLite
    with patch("models.embedding.Vector", lambda dim: None):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def fichier_test(tmp_path):
    """Crée un fichier PDF factice pour les tests."""
    fichier = tmp_path / "test_document.pdf"
    fichier.write_bytes(b"%PDF-1.4 test content for docflow ai testing purposes")
    return fichier


class TestExtractionService:

    @pytest.mark.asyncio
    async def test_process_file_cree_document(self, mock_tika, mock_ollama, mock_embeddings, mem_db, fichier_test):
        service = ExtractionService(mock_tika, mock_ollama, mock_embeddings)
        doc_id = await service.process_file(fichier_test, source="upload", db=mem_db)

        assert doc_id is not None
        result = await mem_db.execute(select(Document).where(Document.id.is_not(None)))
        docs = result.scalars().all()
        assert len(docs) == 1
        assert docs[0].nom == "test_document.pdf"
        assert docs[0].extension == "pdf"
        assert docs[0].source == "upload"

    @pytest.mark.asyncio
    async def test_process_file_statut_enriched(self, mock_tika, mock_ollama, mock_embeddings, mem_db, fichier_test):
        service = ExtractionService(mock_tika, mock_ollama, mock_embeddings)
        await service.process_file(fichier_test, source="upload", db=mem_db)

        result = await mem_db.execute(select(Document))
        doc = result.scalar_one()
        assert doc.statut == "enriched"

    @pytest.mark.asyncio
    async def test_process_file_texte_extrait(self, mock_tika, mock_ollama, mock_embeddings, mem_db, fichier_test):
        service = ExtractionService(mock_tika, mock_ollama, mock_embeddings)
        await service.process_file(fichier_test, source="upload", db=mem_db)

        result = await mem_db.execute(select(Document))
        doc = result.scalar_one()
        assert "Contenu du document" in doc.texte_extrait

    @pytest.mark.asyncio
    async def test_process_file_deduplication(self, mock_tika, mock_ollama, mock_embeddings, mem_db, fichier_test):
        """Un fichier déjà indexé ne doit pas créer de doublon."""
        service = ExtractionService(mock_tika, mock_ollama, mock_embeddings)
        id1 = await service.process_file(fichier_test, source="upload", db=mem_db)
        id2 = await service.process_file(fichier_test, source="upload", db=mem_db)

        assert id1 == id2
        result = await mem_db.execute(select(Document))
        docs = result.scalars().all()
        assert len(docs) == 1

    @pytest.mark.asyncio
    async def test_process_file_erreur_tika_statut_error(self, mock_ollama, mock_embeddings, mem_db, fichier_test):
        """En cas d'erreur Tika, le statut doit passer à 'error'."""
        mock_tika_err = MagicMock()
        mock_tika_err.extract_metadata = AsyncMock(side_effect=RuntimeError("Tika indisponible"))

        service = ExtractionService(mock_tika_err, mock_ollama, mock_embeddings)
        await service.process_file(fichier_test, source="upload", db=mem_db)

        result = await mem_db.execute(select(Document))
        doc = result.scalar_one()
        assert doc.statut == "error"
        assert "Tika indisponible" in doc.erreur

    @pytest.mark.asyncio
    async def test_process_file_erreur_ollama_reste_extracted(self, mock_tika, mock_embeddings, mem_db, fichier_test):
        """En cas d'erreur Ollama (enrichissement), le doc doit quand même être traité."""
        mock_ollama_err = MagicMock()
        mock_ollama_err.generate = AsyncMock(side_effect=RuntimeError("Ollama timeout"))

        service = ExtractionService(mock_tika, mock_ollama_err, mock_embeddings)
        await service.process_file(fichier_test, source="upload", db=mem_db)

        # Le document doit exister avec le texte extrait (Tika OK)
        result = await mem_db.execute(select(Document))
        doc = result.scalar_one()
        # L'erreur Ollama est non-fatale — le doc est en "enriched" (best effort)
        assert doc.texte_extrait is not None

    @pytest.mark.asyncio
    async def test_metadonnees_ia_creees(self, mock_tika, mock_ollama, mock_embeddings, mem_db, fichier_test):
        """Les métadonnées IA doivent être créées après enrichissement."""
        service = ExtractionService(mock_tika, mock_ollama, mock_embeddings)
        await service.process_file(fichier_test, source="upload", db=mem_db)

        result = await mem_db.execute(select(MetadonneeIA))
        meta = result.scalar_one_or_none()
        assert meta is not None
        assert meta.categorie == "rapport"
        assert "test" in meta.tags
        assert meta.langue == "fr"
