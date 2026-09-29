"""
Tests — voyant d'Ollama lu chez la passerelle AIGUILLEUR (`aiguilleur_url` → `/status`)
=====================================================================================
Les quatre règles du contrat `/status`, chacune née d'une erreur réelle chez un client :
lire `etat` et jamais `disponible` · mot inconnu → gris · `perime` → gris · échec → gris.
Gris = 'inconnu' : ce n'est pas l'IA qui est en panne, c'est la passerelle ou le réseau.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from routers import system
from services import runtime_config

URL = "http://aiguilleur.test:21450"


@pytest.fixture(autouse=True)
def _propre(monkeypatch):
    system._cache_aiguilleur.clear()
    monkeypatch.delitem(runtime_config._overrides, "aiguilleur_url", raising=False)
    yield
    system._cache_aiguilleur.clear()


def _status(corps):
    return patch("routers.system._lire_status_aiguilleur", AsyncMock(return_value=corps))


@pytest.mark.asyncio
@pytest.mark.parametrize("corps, attendu", [
    ({"etat": "disponible", "disponible": True, "perime": False}, "ok"),
    ({"etat": "indisponible", "disponible": False, "perime": False}, "down"),
    ({"etat": "inconnu", "disponible": None, "perime": False}, "inconnu"),
    # Règle 1 : `disponible` n'est jamais lu — seul `etat` compte.
    ({"etat": "indisponible", "disponible": True, "perime": False}, "down"),
    # Règle 2 : un mot d'une version future ne fait pas basculer au rouge.
    ({"etat": "degrade", "perime": False}, "inconnu"),
    ({}, "inconnu"),
    # Règle 3 : périmé vaut inconnu, quel que soit le reste.
    ({"etat": "disponible", "disponible": True, "perime": True}, "inconnu"),
    # Règle 4 : pas de réponse exploitable → gris, pas rouge.
    (None, "inconnu"),
])
async def test_les_quatre_regles_du_contrat(corps, attendu):
    with _status(corps):
        etat, _ = await system._etat_aiguilleur(URL)
    assert etat == attendu


@pytest.mark.asyncio
async def test_le_libelle_de_la_passerelle_est_repris_tel_quel():
    with _status({"etat": "disponible", "libelle": "IA disponible", "perime": False}):
        assert await system._etat_aiguilleur(URL) == ("ok", "IA disponible")


@pytest.mark.asyncio
async def test_une_passerelle_muette_est_annoncee_comme_telle():
    with _status(None):
        _, libelle = await system._etat_aiguilleur(URL)
    assert "injoignable" in libelle


@pytest.mark.asyncio
async def test_cache_de_dix_secondes():
    """Sa sonde ne tourne que toutes les 20 s : la redemander plus souvent n'apprend rien."""
    lecture = AsyncMock(return_value={"etat": "disponible", "perime": False})
    with patch("routers.system._lire_status_aiguilleur", lecture):
        await system._etat_aiguilleur(URL)
        await system._etat_aiguilleur(URL)
    assert lecture.await_count == 1


@pytest.mark.asyncio
async def test_lecture_http_avec_en_tete_et_json_invalide(monkeypatch):
    recues: list[httpx.Request] = []
    reponses = iter([httpx.Response(200, json={"etat": "disponible"}),
                     httpx.Response(200, text="<html>pas du json</html>"),
                     httpx.Response(404)])

    def repondre(requete: httpx.Request) -> httpx.Response:
        recues.append(requete)
        return next(reponses)

    vrai_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: vrai_client(transport=httpx.MockTransport(repondre), **kw))
    assert await system._lire_status_aiguilleur(URL + "/") == {"etat": "disponible"}
    assert await system._lire_status_aiguilleur(URL) is None      # JSON invalide
    assert await system._lire_status_aiguilleur(URL) is None      # 404
    assert recues[0].url.path == "/status"
    assert recues[0].headers["X-AI-Project"]


# ─── Branchement du voyant ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sans_reglage_le_voyant_sonde_ollama_lui_meme():
    sonde = AsyncMock(return_value="ok")
    with patch("routers.system._etat_service", sonde), _status({"etat": "indisponible"}) as lecture:
        r = await system._sonde_ollama("http://ollama.test:11434")
    assert r == {"etat": "ok", "source": "ollama"}
    lecture.assert_not_awaited()


@pytest.mark.asyncio
async def test_avec_reglage_le_voyant_lit_la_passerelle_sans_toucher_ollama(monkeypatch):
    monkeypatch.setitem(runtime_config._overrides, "aiguilleur_url", URL)
    sonde = AsyncMock(return_value="ok")
    with patch("routers.system._etat_service", sonde), \
         _status({"etat": "indisponible", "libelle": "IA indisponible", "perime": False}):
        r = await system._sonde_ollama("http://ollama.test:11434")
    assert r == {"etat": "down", "source": "aiguilleur", "libelle": "IA indisponible"}
    sonde.assert_not_awaited()


@pytest.mark.asyncio
async def test_bouton_tester_la_passerelle():
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        vide = (await c.post("/api/system/test/aiguilleur", json={})).json()
        with _status({"etat": "indisponible", "libelle": "IA indisponible"}):
            joignable = (await c.post("/api/system/test/aiguilleur", json={"aiguilleur_url": URL})).json()
        with _status(None):
            muette = (await c.post("/api/system/test/aiguilleur", json={"aiguilleur_url": URL})).json()

    assert vide["ok"] is False and "aucune adresse" in vide["erreur"]
    # Joignable qui annonce Ollama éteint = réglage CORRECT : le test porte sur la passerelle.
    assert joignable["ok"] is True and joignable["libelle"] == "IA indisponible"
    assert muette["ok"] is False
