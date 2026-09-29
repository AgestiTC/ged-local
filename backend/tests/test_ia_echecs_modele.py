"""
Tests — appels IA en échec, par modèle (services/ia_echecs.py, table ia_echecs)
==============================================================================
Un modèle qui répond 400/404, qui expire ou qui rend une réponse vide était absorbé par le repli
« même famille » sans que rien ne le dise. Désormais chaque échec laisse une ligne en base, et
la page Journaux les agrège par modèle.
"""

from unittest.mock import patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from models.ia_echec import IAEchec
from services import ia_echecs
from services.ollama_service import OllamaService


@pytest.fixture
def base_de_test(test_engine):
    """`noter()` ouvre sa propre session : on la fait pointer sur la base de test."""
    with patch("database.AsyncSessionLocal", async_sessionmaker(test_engine, expire_on_commit=False)):
        yield


def _requete() -> httpx.Request:
    return httpx.Request("POST", "http://ia.test/api/generate")


@pytest.mark.parametrize("exc, attendu", [
    (httpx.HTTPStatusError("x", request=_requete(), response=httpx.Response(404, request=_requete())), ("http", 404)),
    (httpx.ReadTimeout("lent"), ("delai", None)),
    (httpx.ConnectError("refusé"), ("connexion", None)),
    (ValueError("autre"), ("autre", None)),
])
def test_classement_des_erreurs(exc, attendu):
    assert ia_echecs.classer(exc) == attendu


async def _compter(db_session) -> int:
    return (await db_session.execute(select(func.count()).select_from(IAEchec))).scalar_one()


@pytest.mark.asyncio
async def test_noter_puis_resumer_par_modele(base_de_test, db_session):
    err = httpx.HTTPStatusError("x", request=_requete(),
                                response=httpx.Response(400, text="keep_alive invalide", request=_requete()))
    for _ in range(3):
        await ia_echecs.noter("llama3.1:latest", "generate", err, base_url="http://passerelle")
    await ia_echecs.noter("llama3.1:latest", "enrichissement", nature="inexploitable", message="sans catégorie")
    await ia_echecs.noter("qwen3-embedding:8b", "embed", nature="vide", message="vecteur vide renvoyé")

    r = await ia_echecs.resume(db_session, 24)
    assert r["total"] == 5
    premier = r["modeles"][0]
    assert premier["modele"] == "llama3.1:latest" and premier["total"] == 4
    assert premier["natures"][0] == {"nature": "http", "code_http": 400, "nombre": 3}
    assert premier["dernier_message"] == "sans catégorie"
    assert r["modeles"][1]["natures"] == [{"nature": "vide", "code_http": None, "nombre": 1}]


@pytest.mark.asyncio
async def test_noter_ne_leve_jamais():
    """Base indisponible : le témoin se tait, l'appel IA garde son comportement."""
    class SessionCassee:
        def __call__(self):
            raise RuntimeError("base indisponible")
    with patch("database.AsyncSessionLocal", SessionCassee()):
        await ia_echecs.noter("m", "generate", ValueError("x"))   # ne lève pas


def _ollama_qui_repond(monkeypatch, reponse: httpx.Response):
    vrai_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: vrai_client(transport=httpx.MockTransport(lambda _r: reponse), **kw))
    return OllamaService(base_url="http://ia.test")


@pytest.mark.asyncio
async def test_une_generation_en_erreur_est_notee_et_toujours_levee(base_de_test, db_session, monkeypatch):
    from tenacity import RetryError, stop_after_attempt
    monkeypatch.setattr(OllamaService.generate.retry, "stop", stop_after_attempt(1))  # sans attente
    svc = _ollama_qui_repond(monkeypatch, httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(RetryError) as err:
        await svc.generate("bonjour", model="absent:latest")
    assert isinstance(err.value.last_attempt.exception(), httpx.HTTPStatusError)   # l'erreur d'origine
    ligne = (await db_session.execute(select(IAEchec))).scalar_one()
    assert (ligne.modele, ligne.operation, ligne.nature, ligne.code_http) == ("absent:latest", "generate", "http", 404)
    assert "model not found" in ligne.message and ligne.base_url == "http://ia.test"


@pytest.mark.asyncio
async def test_un_vecteur_vide_est_note(base_de_test, db_session, monkeypatch):
    svc = _ollama_qui_repond(monkeypatch, httpx.Response(200, json={"embedding": []}))
    assert await OllamaService.embed.__wrapped__(svc, "texte", model="emb:latest") == []
    ligne = (await db_session.execute(select(IAEchec))).scalar_one()
    assert (ligne.modele, ligne.operation, ligne.nature) == ("emb:latest", "embed", "vide")


@pytest.mark.asyncio
async def test_un_appel_reussi_ne_note_rien(base_de_test, db_session, monkeypatch):
    svc = _ollama_qui_repond(monkeypatch, httpx.Response(200, json={"response": "OK"}))
    assert await OllamaService.generate.__wrapped__(svc, "bonjour", model="llama3.1:latest") == "OK"
    assert await _compter(db_session) == 0


@pytest.mark.asyncio
async def test_route_echecs_par_modele(base_de_test, db_session):
    from database import get_db
    from main import app

    await ia_echecs.noter("llama3.1:latest", "generate", httpx.ReadTimeout("lent"))

    async def override_get_db():
        yield db_session
    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = (await c.get("/api/system/ia/echecs", params={"heures": 24})).json()
            refus = await c.get("/api/system/ia/echecs", params={"heures": 0})
    finally:
        app.dependency_overrides.clear()
    assert r["total"] == 1 and r["modeles"][0]["natures"][0]["nature"] == "delai"
    assert refus.status_code == 422
