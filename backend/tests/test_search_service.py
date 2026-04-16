"""
Tests unitaires — services/search_service.py
=============================================
Teste la fusion des scores, la normalisation, et les utilitaires de recherche.
"""

import pytest
from services.search_service import SearchService, POIDS_FULLTEXT, POIDS_SEMANTIQUE


class TestFusionScores:
    """Tests de la logique de fusion sans DB."""

    def _make_service(self):
        mock_ollama = type("MockOllama", (), {})()
        return SearchService(mock_ollama)

    def test_fusion_scores_ponderation(self):
        service = self._make_service()
        scores_text = {"doc1": 1.0, "doc2": 0.5}
        scores_sem = {"doc1": 0.8, "doc3": 1.0}

        fusionnes = service._fusionner(scores_text, scores_sem)

        # doc1 : 0.4 × 1.0 + 0.6 × 0.8 = 0.88
        assert abs(fusionnes["doc1"] - (POIDS_FULLTEXT * 1.0 + POIDS_SEMANTIQUE * 0.8)) < 1e-9

        # doc2 : 0.4 × 0.5 + 0.6 × 0.0 = 0.20
        assert abs(fusionnes["doc2"] - (POIDS_FULLTEXT * 0.5)) < 1e-9

        # doc3 : 0.4 × 0.0 + 0.6 × 1.0 = 0.60
        assert abs(fusionnes["doc3"] - POIDS_SEMANTIQUE) < 1e-9

    def test_fusion_tous_ids_presents(self):
        service = self._make_service()
        scores_text = {"a": 0.9, "b": 0.5}
        scores_sem = {"b": 0.7, "c": 1.0}

        fusionnes = service._fusionner(scores_text, scores_sem)
        assert set(fusionnes.keys()) == {"a", "b", "c"}

    def test_fusion_scores_vides(self):
        service = self._make_service()
        assert service._fusionner({}, {}) == {}

    def test_fusion_un_seul_index(self):
        service = self._make_service()
        scores_text = {"doc1": 0.8}
        fusionnes = service._fusionner(scores_text, {})
        assert abs(fusionnes["doc1"] - POIDS_FULLTEXT * 0.8) < 1e-9

    def test_poids_somment_a_1(self):
        assert abs(POIDS_FULLTEXT + POIDS_SEMANTIQUE - 1.0) < 1e-9


class TestSearchService:
    """Tests avec mock DB."""

    @pytest.mark.asyncio
    async def test_search_query_vide_retourne_vide(self):
        from unittest.mock import MagicMock
        ollama = MagicMock()
        db = MagicMock()
        service = SearchService(ollama)
        result = await service.search("", db)
        assert result == []

    @pytest.mark.asyncio
    async def test_search_query_espaces_retourne_vide(self):
        from unittest.mock import MagicMock
        ollama = MagicMock()
        db = MagicMock()
        service = SearchService(ollama)
        result = await service.search("   ", db)
        assert result == []

    @pytest.mark.asyncio
    async def test_search_semantic_fallback_si_embed_echoue(self):
        """En cas d'erreur d'embeddings, on doit tomber en fallback full-text."""
        from unittest.mock import AsyncMock, MagicMock, patch

        ollama = MagicMock()
        ollama.embed = AsyncMock(side_effect=RuntimeError("Ollama timeout"))

        db = MagicMock()

        service = SearchService(ollama)

        # Patcher _recherche_fulltext pour ne pas toucher la DB
        with patch.object(service, "_recherche_fulltext", AsyncMock(return_value={"doc1": 0.9})), \
             patch.object(service, "_charger_resultats", AsyncMock(return_value=[])):
            result = await service.search("contrat", db, search_type="hybrid")

        # Ne doit pas lever d'exception — fallback silencieux
        assert isinstance(result, list)
