"""
Tests — chat GED : la recherche par MOTS-CLÉS de la question passe avant les signaux qa_service
==============================================================================================
Cas réel (09/11/2026, v1.160.0) : « Quel est la licence d'athlétisme de Thomas ? » ramenait des
fiches de paie — `qa_service.recuperer` ne cherche qu'avec des signaux (« Thomas » + un type de
pièce, « fiche de paie » par défaut), jamais avec les mots de la question. La page GED, elle,
trouvait la bonne attestation en tête avec « licence athlétisme thomas ».

Données FICTIVES uniquement ; recherche, qa_service et Ollama mockés.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from routers import generate as gen


@pytest_asyncio.fixture
async def client():
    from main import app
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _isole():
    async def _resoudre(demande=None, usage="rapport"):
        return demande or "llama3.1:latest"
    with patch("routers.generate._resoudre_modele", new=AsyncMock(side_effect=_resoudre)):
        yield


class _OllamaFactice:
    recus: list = []

    async def chat_stream(self, messages, model=None, think=False):
        type(self).recus = messages
        yield "ok"


INTENT = {"intent": "autre", "personnes": ["Thomas"], "organisations": [],
          "type_piece": [], "periode": {}}
ATTESTATION = {"id": "22222222-2222-2222-2222-222222222222", "nom": "attestation-fictive.pdf",
               "texte": "Jean Exemple est licencié FFA, n° 0000000", "meta_texte": ""}
PAIE = {"id": "33333333-3333-3333-3333-333333333333", "nom": "fiche-paie-fictive.pdf",
        "texte": "Bulletin de salaire de Jean Exemple", "meta_texte": ""}


class TestRequeteMotsCles:
    @pytest.mark.parametrize("question, attendu", [
        ("Quel est la licence d'athlétisme de Thomas ?", "licence athlétisme thomas"),
        ("Quelle est la date de fin de mon contrat ?", "date fin contrat"),
        ("Peux-tu me donner le numéro de licence de Jean Exemple ?", "numéro licence jean exemple"),
        ("Où est mon attestation d'assurance ?", "attestation assurance"),
    ])
    def test_garde_les_mots_utiles(self, question, attendu):
        assert gen._requete_mots_cles(question) == attendu

    def test_question_sans_mot_utile(self):
        assert gen._requete_mots_cles("Qu'est-ce que c'est ?") == ""

    def test_borne(self):
        assert len(gen._requete_mots_cles("licence " * 200 + "a b c d e f")) <= 200


class TestPrioriteMotsCles:
    @pytest.mark.asyncio
    async def test_resultats_pertinents_remplacent_les_signaux(self, client):
        recuperer = AsyncMock(return_value=[PAIE])
        with patch("services.qa_service.comprendre", AsyncMock(return_value=INTENT)), \
             patch("services.qa_service.recuperer", recuperer), \
             patch("routers.generate._recherche_mots_cles", AsyncMock(return_value=[ATTESTATION])) as rmc, \
             patch("routers.generate.OllamaService", _OllamaFactice):
            r = await client.post("/api/generate/chat", json={
                "messages": [{"role": "user", "content": "Quel est la licence d'athlétisme de Thomas ?"}],
                "ged_mode": "auto"})
        assert r.status_code == 200
        assert rmc.await_args.args[0] == "Quel est la licence d'athlétisme de Thomas ?"
        recuperer.assert_not_awaited()          # pas de fiches de paie en renfort
        systeme = _OllamaFactice.recus[0]["content"]
        assert "attestation-fictive.pdf" in systeme and "fiche-paie-fictive.pdf" not in systeme
        assert "attestation-fictive.pdf" in r.headers["X-Ged-Sources"]

    @pytest.mark.asyncio
    async def test_repli_sur_les_signaux_si_rien_de_pertinent(self, client):
        recuperer = AsyncMock(return_value=[PAIE])
        with patch("services.qa_service.comprendre", AsyncMock(return_value=INTENT)), \
             patch("services.qa_service.recuperer", recuperer), \
             patch("routers.generate._recherche_mots_cles", AsyncMock(return_value=[])), \
             patch("routers.generate.OllamaService", _OllamaFactice):
            r = await client.post("/api/generate/chat", json={
                "messages": [{"role": "user", "content": "Combien gagne Thomas ?"}],
                "ged_mode": "toujours"})
        assert r.status_code == 200
        recuperer.assert_awaited_once()
        assert "fiche-paie-fictive.pdf" in r.headers["X-Ged-Sources"]

    @pytest.mark.asyncio
    async def test_echec_recherche_mots_cles_ne_casse_pas(self, client):
        recuperer = AsyncMock(return_value=[PAIE])
        with patch("services.qa_service.comprendre", AsyncMock(return_value=INTENT)), \
             patch("services.qa_service.recuperer", recuperer), \
             patch("routers.search.search", AsyncMock(side_effect=RuntimeError("panne"))), \
             patch("routers.generate.OllamaService", _OllamaFactice):
            r = await client.post("/api/generate/chat", json={
                "messages": [{"role": "user", "content": "Quel est la licence de Thomas ?"}],
                "ged_mode": "toujours"})
        assert r.status_code == 200
        recuperer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auto_non_documentaire_ne_cherche_pas(self, client):
        vide = {"intent": "autre", "personnes": [], "organisations": [], "type_piece": [], "periode": {}}
        rmc = AsyncMock(return_value=[ATTESTATION])
        with patch("services.qa_service.comprendre", AsyncMock(return_value=vide)), \
             patch("routers.generate._recherche_mots_cles", rmc), \
             patch("routers.generate.OllamaService", _OllamaFactice):
            r = await client.post("/api/generate/chat", json={
                "messages": [{"role": "user", "content": "Que penses-tu de Paris ?"}],
                "ged_mode": "auto"})
        assert r.headers["X-Ged-Utilise"] == "0"
        rmc.assert_not_awaited()
