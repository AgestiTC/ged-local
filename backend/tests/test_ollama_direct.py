"""
Tests — le téléchargement de modèles contourne la passerelle AIGUILLEUR
======================================================================
Depuis la bascule du 28/09/2026, `ollama_url` désigne la passerelle, qui NE relaie PAS
`/api/pull` (décision de conception : le téléchargement appartient à un updater dédié). Le
bouton « Mettre à jour » d'un modèle répondait donc 404, sans rien de plus explicite.

`ollama_direct_url` sert au SEUL pull. Son défaut est l'adresse d'environnement d'Ollama —
jamais la surcharge en base — pour qu'un pull reparte vers Ollama en direct sans aucun réglage.
"""

import httpx
import pytest

from config import get_settings
from services import ollama_service, runtime_config

PASSERELLE = "http://passerelle.test:21450"


@pytest.fixture
def config_propre():
    avant = dict(runtime_config._overrides)
    yield
    runtime_config._overrides.clear()
    runtime_config._overrides.update(avant)


def test_le_defaut_est_l_adresse_d_environnement_pas_la_passerelle(config_propre):
    runtime_config._overrides["ollama_url"] = PASSERELLE
    runtime_config._overrides.pop("ollama_direct_url", None)
    assert runtime_config.effective("ollama_url") == PASSERELLE
    assert runtime_config.effective("ollama_direct_url") == get_settings().ollama_url


def test_une_adresse_directe_saisie_l_emporte(config_propre):
    runtime_config._overrides["ollama_direct_url"] = "http://ollama.direct.test:11434"
    assert runtime_config.effective("ollama_direct_url") == "http://ollama.direct.test:11434"


@pytest.mark.asyncio
async def test_le_pull_vise_ollama_en_direct_meme_quand_l_inference_passe_par_la_passerelle(
        config_propre, monkeypatch):
    runtime_config._overrides["ollama_url"] = PASSERELLE
    runtime_config._overrides["ollama_direct_url"] = "http://ollama.direct.test:11434"
    vus: list[str] = []

    def repondre(requete: httpx.Request) -> httpx.Response:
        vus.append(str(requete.url))
        return httpx.Response(200, text='{"status":"success"}\n')

    vrai_client = httpx.AsyncClient

    def client_simule(*args, **kwargs):
        return vrai_client(*args, transport=httpx.MockTransport(repondre), **kwargs)

    monkeypatch.setattr(ollama_service.httpx, "AsyncClient", client_simule)
    service = ollama_service.OllamaService()
    assert service.base_url == PASSERELLE                   # l'inférence, elle, passe par la passerelle
    lignes = [ligne async for ligne in service.pull_stream("nomic-embed-text:latest")]

    assert vus == ["http://ollama.direct.test:11434/api/pull"]
    assert any("success" in ligne for ligne in lignes)


def test_nos_appels_se_nomment_aupres_de_la_passerelle(monkeypatch):
    monkeypatch.delenv("AI_PROJECT", raising=False)
    client = ollama_service.OllamaService(base_url="http://x.test")._get_client()
    assert client.headers["X-AI-Project"] == "ged-local"


def test_une_pile_de_test_se_nomme_autrement(monkeypatch):
    """Docker réécrit l'adresse source : sans nom distinct, le test se confond avec la prod."""
    monkeypatch.setenv("AI_PROJECT", "ged-local-verif")
    client = ollama_service.OllamaService(base_url="http://x.test")._get_client()
    assert client.headers["X-AI-Project"] == "ged-local-verif"
