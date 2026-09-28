"""
Tests — un réglage enregistré est vu par TOUS les process, pas seulement celui du PUT
===================================================================================
Audit du 28/09/2026, H4. Le backend tourne en `uvicorn --workers 2` + un worker : trois copies
du cache `runtime_config._overrides`. Un réglage n'était visible que du process qui avait
traité l'enregistrement ; l'autre gardait l'ancienne valeur jusqu'au redémarrage.

Ici, « un autre process » = une valeur écrite directement en base, sans passer par le cache
du process courant — exactement ce que voit un process qui n'a pas reçu le PUT.
"""

import pytest

from models.config import Config
from services import runtime_config


@pytest.fixture
def cache_isole():
    avant, charge = dict(runtime_config._overrides), runtime_config._charge_le
    runtime_config._overrides.clear()
    yield
    runtime_config._overrides.clear()
    runtime_config._overrides.update(avant)
    runtime_config._charge_le = charge


@pytest.mark.asyncio
async def test_un_reglage_ecrit_par_un_autre_process_est_vu_apres_le_delai(db_session, cache_isole):
    await runtime_config.load(db_session)
    db_session.add(Config(cle="ollama_url", valeur="http://passerelle.test:21450"))
    await db_session.flush()

    # Cache encore frais : on ne relit pas (une lecture par requête serait du gaspillage).
    await runtime_config.rafraichir_si_perime(db_session)
    assert runtime_config.effective("ollama_url") != "http://passerelle.test:21450"

    # Délai écoulé : la première requête qui passe relit la table.
    runtime_config._charge_le -= runtime_config.FRAICHEUR_S + 0.1
    await runtime_config.rafraichir_si_perime(db_session)
    assert runtime_config.effective("ollama_url") == "http://passerelle.test:21450"


@pytest.mark.asyncio
async def test_un_reglage_retire_ailleurs_disparait_aussi(db_session, cache_isole):
    """Vider un champ dans un process doit le vider pour tous — sinon l'ancienne URL survit."""
    ligne = Config(cle="transcription_url", valeur="http://voxtral.test:8012")
    db_session.add(ligne)
    await db_session.flush()
    await runtime_config.load(db_session)
    assert runtime_config.effective("transcription_url") == "http://voxtral.test:8012"

    await db_session.delete(ligne)
    await db_session.flush()
    runtime_config._charge_le -= runtime_config.FRAICHEUR_S + 0.1
    await runtime_config.rafraichir_si_perime(db_session)
    assert runtime_config.effective("transcription_url") != "http://voxtral.test:8012"


@pytest.mark.asyncio
async def test_une_base_injoignable_garde_le_cache_sans_lever_ni_marteler(cache_isole, monkeypatch):
    """
    La fraîcheur du cache passe APRÈS la requête : une base injoignable ne fait rien tomber,
    garde l'ancien cache, et n'est retentée qu'après le délai — pas à chaque requête.
    """
    import database

    appels = 0

    def en_panne():
        nonlocal appels
        appels += 1
        raise RuntimeError("base injoignable")

    monkeypatch.setattr(database, "AsyncSessionLocal", en_panne)
    runtime_config._overrides["ollama_url"] = "http://ancienne.test:11434"
    runtime_config._charge_le = 0.0

    await runtime_config.rafraichir_si_perime()          # ne lève pas
    await runtime_config.rafraichir_si_perime()          # délai pas écoulé : pas de 2ᵉ essai
    assert appels == 1
    assert runtime_config.effective("ollama_url") == "http://ancienne.test:11434"


@pytest.mark.asyncio
async def test_le_middleware_relit_les_reglages_meme_sur_une_route_sans_base(cache_isole, monkeypatch):
    """GET /system/config n'ouvre pas de session : c'est pourtant là qu'on regarde un réglage."""
    from httpx import ASGITransport, AsyncClient

    from main import app

    relectures = 0

    async def relire(db=None):
        nonlocal relectures
        relectures += 1

    monkeypatch.setattr(runtime_config, "rafraichir_si_perime", relire)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.get("/api/system/config")
    assert relectures == 1
