"""En-tête X-AI-Usage : l'usage déclaré à la passerelle (plan lots IA, étape 1).

Aucun appel réseau : httpx est bouchonné par un transport factice.
"""
import asyncio
import contextvars

import httpx
import pytest

from services.ollama_service import OllamaService, entetes_projet, usage_ia


def test_usage_par_defaut_jamais_vide():
    assert contextvars.copy_context().run(entetes_projet)["X-AI-Usage"] == "autre"


def test_usage_pose_puis_restaure():
    def scenario():
        avant = entetes_projet()["X-AI-Usage"]
        with usage_ia("vision"):
            dedans = entetes_projet()["X-AI-Usage"]
        return avant, dedans, entetes_projet()["X-AI-Usage"]

    assert contextvars.copy_context().run(scenario) == ("autre", "vision", "autre")


def test_usage_restaure_meme_sur_exception():
    def scenario():
        with pytest.raises(RuntimeError):
            with usage_ia("rapport"):
                raise RuntimeError("boum")
        return entetes_projet()["X-AI-Usage"]

    assert contextvars.copy_context().run(scenario) == "autre"


def test_usage_vide_ou_none_retombe_sur_autre():
    def scenario():
        with usage_ia(""):
            a = entetes_projet()["X-AI-Usage"]
        with usage_ia(None):  # type: ignore[arg-type]
            b = entetes_projet()["X-AI-Usage"]
        return a, b

    assert contextvars.copy_context().run(scenario) == ("autre", "autre")


@pytest.mark.asyncio
async def test_usage_ne_deborde_pas_sur_une_autre_tache():
    vu = {}

    async def lire(cle):
        await asyncio.sleep(0)
        vu[cle] = entetes_projet()["X-AI-Usage"]

    async def tache_enrichissement():
        with usage_ia("enrichissement"):
            vu["propre"] = entetes_projet()["X-AI-Usage"]
            await lire("fille")          # tâche créée DANS le bloc : hérite, c'est voulu

    # Tâche indépendante créée hors du `with` : ne doit rien voir.
    t_dehors = asyncio.create_task(lire("dehors"))
    await tache_enrichissement()
    await t_dehors
    assert vu["propre"] == "enrichissement"
    assert vu["dehors"] == "autre"
    assert entetes_projet()["X-AI-Usage"] == "autre"


def _service_bouchonne(vus: list[dict]) -> OllamaService:
    def handler(request: httpx.Request) -> httpx.Response:
        vus.append(dict(request.headers))
        if request.url.path == "/api/embeddings":
            return httpx.Response(200, json={"embedding": [0.1, 0.2]})
        return httpx.Response(200, json={"response": "ok", "done": True})

    svc = OllamaService(base_url="http://ollama.test")
    transport = httpx.MockTransport(handler)
    vrai = httpx.AsyncClient
    svc._get_client = lambda: vrai(base_url=svc.base_url, transport=transport,  # type: ignore[method-assign]
                                   headers=entetes_projet())
    return svc


@pytest.mark.asyncio
async def test_embed_porte_usage_embeddings_sans_deborder():
    vus: list[dict] = []
    svc = _service_bouchonne(vus)
    assert await svc.embed("texte fictif", model="m") == [0.1, 0.2]
    assert vus[0]["x-ai-usage"] == "embeddings"
    assert entetes_projet()["X-AI-Usage"] == "autre"    # restauré après l'appel


@pytest.fixture
def requetes(monkeypatch):
    """Capture les en-têtes des requêtes RÉELLEMENT émises, en laissant le vrai `_get_client`
    en place : on n'injecte qu'un transport factice dans `httpx.AsyncClient`. C'est le câblage
    `headers=entetes_projet()` de la fabrique qui est exercé — un client mis en cache, ou des
    en-têtes calculés ailleurs, feraient rougir ces tests."""
    vus: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vus.append(dict(request.headers))
        return httpx.Response(200, content=b'{"response":"{}","done":true}\n')

    vrai = httpx.AsyncClient

    def fabrique(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return vrai(*a, **k)

    monkeypatch.setattr("services.ollama_service.httpx.AsyncClient", fabrique)
    return vus


def _candidats(monkeypatch):
    """Un seul modèle candidat, sans interroger ni la base ni Ollama."""
    from services import runtime_config

    async def un_modele(usage):
        return ["modele-fictif"]

    monkeypatch.setattr(runtime_config, "model_candidates", un_modele)


@pytest.mark.asyncio
async def test_vision_envoie_usage_vision_sur_la_requete(requetes, monkeypatch, tmp_path):
    from services.extraction import ExtractionService

    _candidats(monkeypatch)
    image = tmp_path / "scan-fictif.png"
    image.write_bytes(b"PNG fictif")
    svc = ExtractionService(None, OllamaService(base_url="http://ollama.test"), None)
    await svc._ocr_fallback(image, "png")
    assert requetes, "aucune requête émise : le test ne prouverait rien"
    assert {r["x-ai-usage"] for r in requetes} == {"vision"}
    assert entetes_projet()["X-AI-Usage"] == "autre"


@pytest.mark.asyncio
async def test_enrichissement_envoie_usage_enrichissement_sur_la_requete(requetes, monkeypatch):
    from types import SimpleNamespace

    from services import ia_echecs
    from services.extraction import ExtractionService

    _candidats(monkeypatch)

    async def rien(*a, **k):
        return None

    monkeypatch.setattr(ia_echecs, "noter", rien)
    svc = ExtractionService(None, OllamaService(base_url="http://ollama.test"), None)
    doc = SimpleNamespace(id="doc-fictif", nom="fictif.pdf", extension="pdf")
    # Réponse « {} » : sans catégorie, donc inexploitable → False, et la base n'est jamais touchée.
    assert await svc._enrich(doc, "texte fictif", None) is False
    assert requetes, "aucune requête émise : le test ne prouverait rien"
    assert {r["x-ai-usage"] for r in requetes} == {"enrichissement"}
    assert entetes_projet()["X-AI-Usage"] == "autre"


@pytest.mark.asyncio
async def test_rapport_envoie_usage_rapport_sur_la_requete(requetes, monkeypatch):
    from types import SimpleNamespace

    from services import rapport_jobs

    async def aucun_document(ids):
        return []

    async def rien(*a, **k):
        return None

    monkeypatch.setattr(rapport_jobs, "_charger_documents", aucun_document)
    monkeypatch.setattr(rapport_jobs, "_persister", rien)
    monkeypatch.setattr("routers.generate._archiver_rapport", rien)   # importé dans le handler

    ctx = SimpleNamespace(job_id="job-fictif", cancelled=False, report=rien,
                          parametres={"prompt": "consigne fictive", "model": "modele-fictif"})
    await rapport_jobs.handler_rapport(ctx)
    assert requetes, "aucune requête émise : le test ne prouverait rien"
    assert {r["x-ai-usage"] for r in requetes} == {"rapport"}
    assert entetes_projet()["X-AI-Usage"] == "autre"


@pytest.mark.asyncio
async def test_generate_hors_bloc_reste_sur_autre(requetes):
    await OllamaService(base_url="http://ollama.test").generate("consigne fictive", model="modele-fictif")
    assert {r["x-ai-usage"] for r in requetes} == {"autre"}


@pytest.mark.asyncio
async def test_deux_taches_concurrentes_gardent_chacune_leur_usage():
    depart, vu = asyncio.Event(), {}

    async def tache(usage):
        with usage_ia(usage):
            await depart.wait()                      # les deux blocs sont ouverts EN MÊME TEMPS
            vu[usage] = entetes_projet()["X-AI-Usage"]

    t1, t2 = asyncio.create_task(tache("vision")), asyncio.create_task(tache("rapport"))
    await asyncio.sleep(0)
    depart.set()
    await asyncio.gather(t1, t2)
    assert vu == {"vision": "vision", "rapport": "rapport"}
    assert entetes_projet()["X-AI-Usage"] == "autre"


def test_ai_project_nomme_le_projet(monkeypatch):
    monkeypatch.setenv("AI_PROJECT", "ged-local-verif")
    assert entetes_projet()["X-AI-Project"] == "ged-local-verif"
    monkeypatch.delenv("AI_PROJECT")
    assert entetes_projet()["X-AI-Project"] == "ged-local"


@pytest.mark.asyncio
async def test_chat_stream_porte_usage_chat_sans_deborder():
    vus: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        vus.append(dict(request.headers))
        return httpx.Response(200, content=b'{"message":{"content":"salut"},"done":true}\n')

    svc = OllamaService(base_url="http://ollama.test")
    transport = httpx.MockTransport(handler)
    svc._get_client = lambda: httpx.AsyncClient(base_url=svc.base_url, transport=transport,  # type: ignore[method-assign]
                                                headers=entetes_projet())
    morceaux = [c async for c in svc.chat_stream([{"role": "user", "content": "x"}], model="m")]
    assert morceaux == ["salut"]
    assert vus[0]["x-ai-usage"] == "chat"
    assert entetes_projet()["X-AI-Usage"] == "autre"
