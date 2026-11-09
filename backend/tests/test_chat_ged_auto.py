"""
Tests — chat libre : mode GED « auto | toujours | jamais » (POST /api/generate/chat)
====================================================================================
Données FICTIVES uniquement. qa_service et Ollama sont mockés : aucun réseau, aucune base.

Contrat :
  - « jamais »   → aucun appel à qa_service ;
  - « toujours » → comprendre + recuperer systématiques ;
  - « auto »     → pré-détection bon marché (sans LLM) ; question manifestement générale → aucun
                   appel ; question documentaire → comprendre, puis recuperer si l'intention porte
                   sur des documents ;
  - en-têtes `X-Ged-Utilise: 1|0` et `X-Ged-Sources` (JSON puis percent-encoding).
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import unquote

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
    # Recherche par mots-clés neutralisée : ces tests portent sur le repli qa_service (couvert
    # à part dans test_chat_ged_mots_cles.py).
    with patch("routers.generate._resoudre_modele", new=AsyncMock(side_effect=_resoudre)), \
         patch("routers.generate._recherche_mots_cles", new=AsyncMock(return_value=[])):
        yield


INTENT_LICENCE = {"intent": "autre", "personnes": ["Thomas"], "organisations": [],
                  "type_piece": ["licence"], "periode": {}}
INTENT_VIDE = {"intent": "autre", "personnes": [], "organisations": [], "type_piece": [], "periode": {}}
CANDIDATS = [{"id": "11111111-1111-1111-1111-111111111111", "nom": "licence-fictive-é.pdf",
              "texte": "Licence FFA n° 0000000 — Jean Exemple", "meta_texte": ""}]


class _OllamaFactice:
    """Remplace OllamaService : mémorise les messages reçus."""
    recus: list = []

    async def chat_stream(self, messages, model=None, think=False):
        type(self).recus = messages
        yield "ok"


def _qa(intent):
    qa = MagicMock()
    qa.comprendre = AsyncMock(return_value=intent)
    qa.recuperer = AsyncMock(return_value=CANDIDATS)
    return qa


def _poster(client, question, **extra):
    corps = {"messages": [{"role": "user", "content": question}], **extra}
    return client.post("/api/generate/chat", json=corps)


def _sources(resp):
    return json.loads(unquote(resp.headers["X-Ged-Sources"]))


class TestPreDetection:
    @pytest.mark.parametrize("q", [
        "Écris un mail de relance",
        "Rédige un mail poli pour reporter un rendez-vous à la semaine prochaine.",
        "Résume ce texte en 3 points : bonjour à tous",
        "Explique-moi la photosynthèse simplement",
    ])
    def test_question_generale_non_documentaire(self, q):
        assert gen._question_peut_etre_documentaire(q) is False

    @pytest.mark.parametrize("q", [
        "Quel est la licence d'athlétisme de Thomas ?",
        "Où est mon contrat de travail ?",
        "Donne-moi le numéro de la facture EDF",
        "Que sait-on sur Jean Dupont ?",
        "Retrouve l'attestation de Marie",
    ])
    def test_question_documentaire(self, q):
        assert gen._question_peut_etre_documentaire(q) is True

    def test_majuscule_de_debut_de_phrase_ignoree(self):
        assert gen._question_peut_etre_documentaire("Bonjour. Écris un mail") is False


class TestModeGed:
    def test_defaut_auto(self):
        assert gen._mode_ged(gen.ChatRequest(messages=[{"role": "user", "content": "x"}])) == "auto"

    def test_use_ged_true_toujours(self):
        r = gen.ChatRequest(messages=[{"role": "user", "content": "x"}], use_ged=True)
        assert gen._mode_ged(r) == "toujours"

    def test_use_ged_false_explicite_jamais(self):
        r = gen.ChatRequest(messages=[{"role": "user", "content": "x"}], use_ged=False)
        assert gen._mode_ged(r) == "jamais"

    def test_ged_mode_prioritaire(self):
        r = gen.ChatRequest(messages=[{"role": "user", "content": "x"}], use_ged=True, ged_mode="jamais")
        assert gen._mode_ged(r) == "jamais"

    def test_ged_mode_invalide_refuse(self):
        with pytest.raises(Exception):
            gen.ChatRequest(messages=[{"role": "user", "content": "x"}], ged_mode="peut-etre")


class TestChatHttp:
    @pytest.mark.asyncio
    async def test_auto_question_licence_injecte_et_signale(self, client):
        qa = _qa(INTENT_LICENCE)
        with patch("services.qa_service.comprendre", qa.comprendre), \
             patch("services.qa_service.recuperer", qa.recuperer), \
             patch("routers.generate.OllamaService", _OllamaFactice):
            async with client as c:
                resp = await _poster(c, "Quel est la licence d'athlétisme de Thomas ?", ged_mode="auto")
        assert resp.status_code == 200
        qa.comprendre.assert_awaited_once()
        qa.recuperer.assert_awaited_once()
        assert resp.headers["X-Ged-Utilise"] == "1"
        assert _sources(resp) == [{"id": CANDIDATS[0]["id"], "nom": "licence-fictive-é.pdf"}]
        assert resp.headers["X-Ged-Sources"].isascii()
        systeme = _OllamaFactice.recus[0]
        assert systeme["role"] == "system" and "licence-fictive-é.pdf" in systeme["content"]

    @pytest.mark.asyncio
    async def test_auto_question_generale_aucun_appel(self, client):
        qa = _qa(INTENT_LICENCE)
        with patch("services.qa_service.comprendre", qa.comprendre), \
             patch("services.qa_service.recuperer", qa.recuperer), \
             patch("routers.generate.OllamaService", _OllamaFactice):
            async with client as c:
                resp = await _poster(c, "Écris un mail de relance", ged_mode="auto")
        qa.comprendre.assert_not_awaited()
        qa.recuperer.assert_not_awaited()
        assert resp.headers["X-Ged-Utilise"] == "0"
        assert _sources(resp) == []
        assert _OllamaFactice.recus[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_auto_sans_ged_mode_est_auto(self, client):
        qa = _qa(INTENT_LICENCE)
        with patch("services.qa_service.comprendre", qa.comprendre), \
             patch("services.qa_service.recuperer", qa.recuperer), \
             patch("routers.generate.OllamaService", _OllamaFactice):
            async with client as c:
                await _poster(c, "Écris un mail de relance")
        qa.comprendre.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_auto_intention_non_documentaire_pas_de_recuperation(self, client):
        """Pré-détection positive (nom propre) mais le LLM n'y voit aucun signal documentaire."""
        qa = _qa(INTENT_VIDE)
        with patch("services.qa_service.comprendre", qa.comprendre), \
             patch("services.qa_service.recuperer", qa.recuperer), \
             patch("routers.generate.OllamaService", _OllamaFactice):
            async with client as c:
                resp = await _poster(c, "Que penses-tu de Paris ?", ged_mode="auto")
        qa.comprendre.assert_awaited_once()
        qa.recuperer.assert_not_awaited()
        assert resp.headers["X-Ged-Utilise"] == "0"

    @pytest.mark.asyncio
    async def test_jamais_aucun_appel_qa(self, client):
        qa = _qa(INTENT_LICENCE)
        with patch("services.qa_service.comprendre", qa.comprendre), \
             patch("services.qa_service.recuperer", qa.recuperer), \
             patch("routers.generate.OllamaService", _OllamaFactice):
            async with client as c:
                resp = await _poster(c, "Quel est la licence de Thomas ?", ged_mode="jamais")
        qa.comprendre.assert_not_awaited()
        qa.recuperer.assert_not_awaited()
        assert resp.headers["X-Ged-Utilise"] == "0"

    @pytest.mark.asyncio
    async def test_use_ged_false_ancien_client_jamais(self, client):
        qa = _qa(INTENT_LICENCE)
        with patch("services.qa_service.comprendre", qa.comprendre), \
             patch("services.qa_service.recuperer", qa.recuperer), \
             patch("routers.generate.OllamaService", _OllamaFactice):
            async with client as c:
                await _poster(c, "Quel est la licence de Thomas ?", use_ged=False)
        qa.comprendre.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_toujours_force_meme_question_generale(self, client):
        qa = _qa(INTENT_LICENCE)
        with patch("services.qa_service.comprendre", qa.comprendre), \
             patch("services.qa_service.recuperer", qa.recuperer), \
             patch("routers.generate.OllamaService", _OllamaFactice):
            async with client as c:
                resp = await _poster(c, "écris un mail de relance", ged_mode="toujours")
        qa.comprendre.assert_awaited_once()
        qa.recuperer.assert_awaited_once()
        assert resp.headers["X-Ged-Utilise"] == "1"

    @pytest.mark.asyncio
    async def test_toujours_recuperation_en_echec_ne_casse_pas(self, client):
        qa = _qa(INTENT_LICENCE)
        qa.recuperer = AsyncMock(side_effect=RuntimeError("base HS"))
        with patch("services.qa_service.comprendre", qa.comprendre), \
             patch("services.qa_service.recuperer", qa.recuperer), \
             patch("routers.generate.OllamaService", _OllamaFactice):
            async with client as c:
                resp = await _poster(c, "licence de Thomas", ged_mode="toujours")
        assert resp.status_code == 200
        assert resp.headers["X-Ged-Utilise"] == "0"


# ─── Corrections de relecture + étape 2 (consigne anti-invention) ─────────────

def _avec_qa(qa):
    return (patch("services.qa_service.comprendre", qa.comprendre),
            patch("services.qa_service.recuperer", qa.recuperer),
            patch("routers.generate.OllamaService", _OllamaFactice))


def _systemes():
    return [m for m in _OllamaFactice.recus if m["role"] == "system"]


class TestEntetesBornes:
    def test_taille_encodee_bornee(self):
        nom = ("é" * 40) + ("漢" * 80)       # 120 caractères accentués + CJK
        ctx = gen.ContexteGed("x", [{"id": str(i), "nom": nom} for i in range(5)])
        valeur = gen._entetes_ged(ctx)["X-Ged-Sources"]
        assert len(valeur) < 4000 and valeur.isascii()
        assert len(json.loads(unquote(valeur))) >= 1

    def test_nom_avec_guillemet_virgule_pourcent_aller_retour(self):
        nom = 'a"b,c%d é.pdf'
        ctx = gen.ContexteGed("x", [{"id": "1", "nom": nom}])
        assert json.loads(unquote(gen._entetes_ged(ctx)["X-Ged-Sources"])) == [{"id": "1", "nom": nom}]


class TestChatRobustesse:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["auto", "toujours"])
    async def test_comprendre_leve(self, client, mode):
        qa = _qa(INTENT_LICENCE)
        qa.comprendre = AsyncMock(side_effect=RuntimeError("LLM HS"))
        p1, p2, p3 = _avec_qa(qa)
        with p1, p2, p3:
            async with client as c:
                resp = await _poster(c, "licence de Thomas", ged_mode=mode)
        assert resp.status_code == 200
        assert resp.headers["X-Ged-Utilise"] == "0"
        assert _systemes() == []

    @pytest.mark.asyncio
    async def test_use_ged_true_est_toujours(self, client):
        qa = _qa(INTENT_LICENCE)
        p1, p2, p3 = _avec_qa(qa)
        with p1, p2, p3:
            async with client as c:
                resp = await _poster(c, "écris un mail", use_ged=True)
        qa.comprendre.assert_awaited_once()
        assert resp.headers["X-Ged-Utilise"] == "1"

    @pytest.mark.asyncio
    async def test_seul_dernier_message_user_analyse_et_tronque(self, client):
        qa = _qa(INTENT_LICENCE)
        p1, p2, p3 = _avec_qa(qa)
        corps = {"ged_mode": "toujours", "messages": [
            {"role": "user", "content": "premiere question"},
            {"role": "assistant", "content": "reponse"},
            {"role": "user", "content": "licence de Thomas " + "x" * 800},
        ]}
        with p1, p2, p3:
            async with client as c:
                await c.post("/api/generate/chat", json=corps)
        analysee = qa.comprendre.await_args.args[0]
        assert analysee.startswith("licence de Thomas") and len(analysee) == 500

    @pytest.mark.asyncio
    async def test_licence_minuscules_auto(self, client):
        qa = _qa(INTENT_LICENCE)
        p1, p2, p3 = _avec_qa(qa)
        with p1, p2, p3:
            async with client as c:
                resp = await _poster(c, "licence de thomas", ged_mode="auto")
        qa.recuperer.assert_awaited_once()
        assert resp.headers["X-Ged-Utilise"] == "1"

    @pytest.mark.asyncio
    async def test_paris_aucun_message_systeme(self, client):
        qa = _qa(INTENT_VIDE)
        p1, p2, p3 = _avec_qa(qa)
        with p1, p2, p3:
            async with client as c:
                await _poster(c, "Que penses-tu de Paris ?", ged_mode="auto")
        assert _systemes() == []


class TestConsigneAntiInvention:
    @pytest.mark.asyncio
    async def test_vide_et_documentaire_message_non_trouve(self, client):
        qa = _qa(INTENT_LICENCE)
        qa.recuperer = AsyncMock(return_value=[])
        p1, p2, p3 = _avec_qa(qa)
        with p1, p2, p3:
            async with client as c:
                resp = await _poster(c, "licence de Thomas", ged_mode="auto")
        sys_ = _systemes()
        assert len(sys_) == 1 and sys_[0]["content"] == gen.CONSIGNE_GED_VIDE
        assert "Je n'ai pas trouvé ce document dans la GED" in sys_[0]["content"]
        assert resp.headers["X-Ged-Utilise"] == "0"

    @pytest.mark.asyncio
    async def test_vide_documentaire_en_toujours(self, client):
        qa = _qa(INTENT_LICENCE)
        qa.recuperer = AsyncMock(return_value=[])
        p1, p2, p3 = _avec_qa(qa)
        with p1, p2, p3:
            async with client as c:
                await _poster(c, "licence de Thomas", ged_mode="toujours")
        assert _systemes()[0]["content"] == gen.CONSIGNE_GED_VIDE

    @pytest.mark.asyncio
    async def test_extraits_consigne_adaptee(self, client):
        qa = _qa(INTENT_LICENCE)
        p1, p2, p3 = _avec_qa(qa)
        with p1, p2, p3:
            await_ = client
            async with await_ as c:
                await _poster(c, "licence de Thomas", ged_mode="auto")
        contenu = _systemes()[0]["content"]
        assert contenu.startswith(gen.CONSIGNE_GED_EXTRAITS) and "licence-fictive-é.pdf" in contenu
        assert "ne figure PAS" in contenu

    @pytest.mark.asyncio
    async def test_intention_generale_aucun_message_systeme(self, client):
        qa = _qa(INTENT_VIDE)
        qa.recuperer = AsyncMock(return_value=[])
        p1, p2, p3 = _avec_qa(qa)
        with p1, p2, p3:
            async with client as c:
                await _poster(c, "écris un mail de relance", ged_mode="toujours")
        assert _systemes() == []
        qa.recuperer.assert_awaited_once()  # toujours récupère, mais rien à signaler
