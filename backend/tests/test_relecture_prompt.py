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

    def test_prompt_rendu_en_objet_remis_en_texte(self):
        """Constat du 02/11/2026 : ministral-3 rend Rôle / Tâche / Règles / Barème en objet imbriqué."""
        r = rp.lire_reponse('{"prompt": {"Rôle": "Évalue les offres.", "Règles": ["Justifie chaque note.", '
                            '"Cite l\'offre."], "Barème": {"Tarif": {"1": "trop cher", "5": "dans le budget"}}}, '
                            '"remarques": ["Structuré"]}')
        assert r is not None and "{" not in r["prompt"]
        assert r["prompt"].splitlines() == [
            "Rôle : Évalue les offres.", "Règles :", "  - Justifie chaque note.", "  - Cite l'offre.",
            "Barème :", "  Tarif :", "    1 : trop cher", "    5 : dans le budget"]


class TestAppel:
    @pytest.mark.asyncio
    async def test_json_impose_et_second_essai(self):
        o = MagicMock()
        o.generate = AsyncMock(side_effect=['{"prompt": "coupé…', '{"prompt": "Rôle : x", "remarques": []}'])
        r = await rp.relire_prompt("x", "comparatif", "m", o)
        assert r == {"prompt": "Rôle : x", "remarques": []}
        assert o.generate.await_count == 2
        assert all(c.kwargs["format"] == "json" for c in o.generate.await_args_list)

    @pytest.mark.asyncio
    async def test_abandon_apres_deux_essais(self):
        o = _ollama("désolé")
        assert await rp.relire_prompt("x", None, "m", o) is None and o.generate.await_count == rp.ESSAIS

    def test_comparatif_sans_section_format_et_court(self):
        """02/11/2026 : la relecture rendait ~3 000 car. avec « Format attendu » ; le comparatif échouait."""
        consigne = rp.construire_consigne("x", "comparatif")
        assert "Format attendu" not in consigne and "AUCUNE section ni consigne de format" in consigne
        assert "1200 caractères au plus" in consigne

    def test_rapport_garde_la_section_format(self):
        consigne = rp.construire_consigne("x", "rapport_libre")
        assert "Format attendu" in consigne and "AUCUNE section" not in consigne

    def test_consigne_exige_une_chaine(self):
        assert "UNE SEULE CHAÎNE DE TEXTE" in rp.construire_consigne("x", "comparatif")


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


def test_mode_reference_consignes_de_fond_seulement():
    consigne = rp.construire_consigne("vérifie les pénalités", "reference")
    assert "document de référence" in consigne and "pas de structure ni de mise en forme" in consigne
