"""« Faire relire par l'IA » (11/10/2026) : consigne selon le mode, lecture tolérante, erreurs explicites."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import relecture_prompt as rp


def _ollama(reponse: str) -> MagicMock:
    o = MagicMock()
    o.generate = AsyncMock(return_value=reponse)
    return o


class TestConsigne:
    def test_mode_comparatif_interdit_titres_et_tableau(self):
        consigne = rp.construire_consigne("note les offres", "comparatif")
        assert "TABLEAU COMPARATIF" in consigne and "PAS demander" in consigne
        assert "<prompt>\nnote les offres\n</prompt>" in consigne

    def test_mode_inconnu_retombe_sur_le_rapport(self):
        assert rp._CONTEXTE_MODE["rapport_libre"] in rp.construire_consigne("x", "inexistant")

    def test_rien_inventer(self):
        assert "[à préciser" in rp.construire_consigne("x", None)


class TestLecture:
    def test_reponse_tolerante(self):
        r = rp.lire_reponse('```json\n{"prompt": "Rôle : analyste\nTâche : noter", '
                            '"remarques": ["- Barème à préciser", ""]}\n```')
        assert r == {"prompt": "Rôle : analyste\nTâche : noter", "remarques": ["Barème à préciser"]}

    @pytest.mark.parametrize("reponse", ["rien", "{}", '{"prompt": ""}', "{pas du json"])
    def test_inexploitable(self, reponse):
        assert rp.lire_reponse(reponse) is None


class TestRoute:
    @pytest.mark.asyncio
    async def test_proposition(self, client):
        o = _ollama('{"prompt": "Rôle : ingénieur", "remarques": ["Structuré"]}')
        with patch("services.ollama_service.OllamaService", return_value=o):
            r = await client.post("/api/prompts/relire", json={"texte": "tu es ingénieur", "mode": "comparatif",
                                                               "model": "m"})
        assert r.status_code == 200, r.text
        assert r.json()["prompt"] == "Rôle : ingénieur" and r.json()["model"] == "m"

    @pytest.mark.asyncio
    async def test_ollama_injoignable(self, client):
        o = MagicMock()
        o.generate = AsyncMock(side_effect=RuntimeError("connexion refusée"))
        with patch("services.ollama_service.OllamaService", return_value=o):
            r = await client.post("/api/prompts/relire", json={"texte": "x", "model": "m"})
        assert r.status_code == 503 and "Ollama" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_reponse_inexploitable(self, client):
        with patch("services.ollama_service.OllamaService", return_value=_ollama("désolé")):
            r = await client.post("/api/prompts/relire", json={"texte": "x", "model": "m"})
        assert r.status_code == 502
