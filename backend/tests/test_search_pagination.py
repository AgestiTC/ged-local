"""
Tests d'intégration — routers/search.py — Pagination (offset / has_more)
=========================================================================
Vérifie que l'endpoint GET /search supporte correctement le paramètre
offset et retourne has_more, offset, limit dans la réponse.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client(db_session):
    """Client HTTP de test avec DB mockée."""
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


# Résultats fictifs pour mocker _recherche_fulltext
def _make_mock_docs(n: int):
    """Crée n documents fictifs avec leurs métadonnées pour simuler la recherche."""
    from unittest.mock import MagicMock
    results = []
    for i in range(n):
        doc = MagicMock()
        doc.id = f"doc-{i:03d}"
        doc.nom = f"document_{i:03d}.pdf"
        doc.extension = "pdf"
        doc.taille_octets = 100_000 + i * 1000
        doc.statut = "enriched"
        doc.date_import = None

        meta = MagicMock()
        meta.categorie = "rapport"
        meta.tags = ["test"]
        meta.resume = f"Résumé document {i}"
        meta.langue = "fr"

        results.append((doc, meta, 1.0 - i * 0.01))  # scores décroissants
    return results


class TestSearchPagination:
    @pytest.mark.asyncio
    async def test_retourne_champs_pagination(self, client):
        """La réponse doit contenir has_more, offset, limit."""
        mock_results = _make_mock_docs(5)

        async with client as c:
            with patch("routers.search._recherche_fulltext", AsyncMock(return_value=mock_results)), \
                 patch("routers.search._recherche_semantique", AsyncMock(return_value=[])):
                resp = await c.get("/api/search", params={"q": "test", "type": "text"})

        assert resp.status_code == 200
        data = resp.json()
        assert "has_more" in data
        assert "offset" in data
        assert "limit" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_has_more_false_si_moins_que_limit(self, client):
        """Si total < limit, has_more doit être False."""
        mock_results = _make_mock_docs(5)

        async with client as c:
            with patch("routers.search._recherche_fulltext", AsyncMock(return_value=mock_results)), \
                 patch("routers.search._recherche_semantique", AsyncMock(return_value=[])):
                resp = await c.get("/api/search", params={"q": "test", "type": "text", "limit": 20})

        data = resp.json()
        assert data["has_more"] is False
        assert len(data["resultats"]) == 5

    @pytest.mark.asyncio
    async def test_has_more_true_si_plus_de_resultats(self, client):
        """Si total > limit, has_more doit être True."""
        mock_results = _make_mock_docs(30)  # 30 résultats, limit = 20

        async with client as c:
            with patch("routers.search._recherche_fulltext", AsyncMock(return_value=mock_results)), \
                 patch("routers.search._recherche_semantique", AsyncMock(return_value=[])):
                resp = await c.get("/api/search", params={"q": "test", "type": "text", "limit": 20})

        data = resp.json()
        assert data["has_more"] is True
        assert data["total"] == 30
        assert len(data["resultats"]) == 20

    @pytest.mark.asyncio
    async def test_offset_decale_les_resultats(self, client):
        """Avec offset=20, les 20 premiers résultats doivent être sautés."""
        mock_results = _make_mock_docs(30)

        async with client as c:
            # Page 1 : offset=0
            with patch("routers.search._recherche_fulltext", AsyncMock(return_value=mock_results)), \
                 patch("routers.search._recherche_semantique", AsyncMock(return_value=[])):
                resp1 = await c.get("/api/search", params={"q": "test", "type": "text", "limit": 20, "offset": 0})

            # Page 2 : offset=20
            with patch("routers.search._recherche_fulltext", AsyncMock(return_value=mock_results)), \
                 patch("routers.search._recherche_semantique", AsyncMock(return_value=[])):
                resp2 = await c.get("/api/search", params={"q": "test", "type": "text", "limit": 20, "offset": 20})

        data1 = resp1.json()
        data2 = resp2.json()

        # Les IDs ne doivent pas se chevaucher
        ids1 = {r["id"] for r in data1["resultats"]}
        ids2 = {r["id"] for r in data2["resultats"]}
        assert ids1.isdisjoint(ids2), "Les pages ne doivent pas avoir de résultats en commun"

        # Page 2 doit avoir les 10 restants (30 - 20 = 10)
        assert len(data2["resultats"]) == 10
        assert data2["has_more"] is False

    @pytest.mark.asyncio
    async def test_offset_invalide_rejete(self, client):
        """Un offset négatif doit être rejeté (422 Pydantic)."""
        async with client as c:
            resp = await c.get("/api/search", params={"q": "test", "offset": -1})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_offset_par_defaut_est_zero(self, client):
        """Sans offset, la réponse doit avoir offset=0."""
        mock_results = _make_mock_docs(3)

        async with client as c:
            with patch("routers.search._recherche_fulltext", AsyncMock(return_value=mock_results)), \
                 patch("routers.search._recherche_semantique", AsyncMock(return_value=[])):
                resp = await c.get("/api/search", params={"q": "test", "type": "text"})

        assert resp.json()["offset"] == 0

    @pytest.mark.asyncio
    async def test_total_reste_stable_entre_pages(self, client):
        """Le total doit être identique sur toutes les pages."""
        mock_results = _make_mock_docs(25)

        async with client as c:
            with patch("routers.search._recherche_fulltext", AsyncMock(return_value=mock_results)), \
                 patch("routers.search._recherche_semantique", AsyncMock(return_value=[])):
                resp1 = await c.get("/api/search", params={"q": "test", "type": "text", "limit": 20, "offset": 0})

            with patch("routers.search._recherche_fulltext", AsyncMock(return_value=mock_results)), \
                 patch("routers.search._recherche_semantique", AsyncMock(return_value=[])):
                resp2 = await c.get("/api/search", params={"q": "test", "type": "text", "limit": 20, "offset": 20})

        assert resp1.json()["total"] == resp2.json()["total"] == 25


class TestSearchFiltersWithPagination:
    @pytest.mark.asyncio
    async def test_filtre_categorie_puis_pagine(self, client):
        """Le filtre par catégorie s'applique avant la pagination."""
        from unittest.mock import MagicMock

        def make_doc_with_cat(i, cat):
            doc = MagicMock()
            doc.id = f"doc-{i}"
            doc.nom = f"doc_{i}.pdf"
            doc.extension = "pdf"
            doc.taille_octets = 50_000
            doc.statut = "enriched"
            doc.date_import = None
            meta = MagicMock()
            meta.categorie = cat
            meta.tags = []
            meta.resume = ""
            meta.langue = "fr"
            return (doc, meta, 0.9 - i * 0.01)

        # 15 rapports + 10 factures = 25 docs
        mock_results = [make_doc_with_cat(i, "rapport") for i in range(15)] + \
                       [make_doc_with_cat(15 + i, "facture") for i in range(10)]

        async with client as c:
            with patch("routers.search._recherche_fulltext", AsyncMock(return_value=mock_results)), \
                 patch("routers.search._recherche_semantique", AsyncMock(return_value=[])):
                resp = await c.get("/api/search", params={
                    "q": "test", "type": "text",
                    "categorie": "rapport",
                    "limit": 10, "offset": 0,
                })

        data = resp.json()
        # Seulement les 15 rapports sont dans le total filtré
        assert data["total"] == 15
        # Page 1 = 10 résultats
        assert len(data["resultats"]) == 10
        assert data["has_more"] is True
        # Tous les résultats sont des rapports
        for r in data["resultats"]:
            assert r["metadonnees_ia"]["categorie"] == "rapport"
