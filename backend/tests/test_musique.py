"""
Tests — « Créer une musique ! » (ComfyUI / ACE-Step sur PC-GAME)
================================================================
Règles posées avec la session AIGUILLEUR (09/10/2026) : ne jamais décharger les modèles des
autres — refuser si la carte n'a pas assez de mémoire libre ; et TOUJOURS appeler `/free` après un
rendu, sinon ACE-Step (~9 Gio) reste résident.
"""
import json
from types import SimpleNamespace

import httpx
import pytest

from services import musique_jobs, runtime_config

GIO = 2**30


@pytest.fixture
def comfy(monkeypatch, tmp_path):
    """ComfyUI simulé ; `etat` règle sa réponse, `appels` garde la trace."""
    etat = {"vram_libre": 12 * GIO, "rendu": "success"}
    appels: list[tuple[str, str, dict | None]] = []

    def repondre(r: httpx.Request) -> httpx.Response:
        corps = json.loads(r.content) if r.content else None
        appels.append((r.method, r.url.path, corps))
        if r.url.path == "/system_stats":
            return httpx.Response(200, json={"devices": [{"vram_free": etat["vram_libre"], "vram_total": 16 * GIO}]})
        if r.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "p1"})
        if r.url.path == "/history/p1":
            return httpx.Response(200, json={"p1": {
                "status": {"completed": True, "status_str": etat["rendu"], "messages": [["erreur", {}]]},
                "outputs": {"106": {"audio": [{"filename": "m.mp3", "subfolder": "audio", "type": "output"}]}}}})
        if r.url.path == "/view":
            return httpx.Response(200, content=b"ID3-morceau")
        return httpx.Response(200, json={})

    vrai = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: vrai(transport=httpx.MockTransport(repondre), **kw))
    monkeypatch.setitem(runtime_config._overrides, "comfyui_url", "http://pc-game:18188")
    monkeypatch.setattr(musique_jobs.settings, "storage_exports", str(tmp_path))
    monkeypatch.setattr(musique_jobs, "SUIVI_S", 0)
    return SimpleNamespace(etat=etat, appels=appels, dossier=tmp_path)


def _ctx(**params):
    async def report(*_a, **_k):
        return None
    return SimpleNamespace(job_id="job-1", parametres=params, cancelled=False, report=report)


def test_duree_et_graine_vont_aux_deux_endroits():
    g = musique_jobs.graphe("pop", "[Verse] la", 45, "fr", 120, 7, "audio/x")
    assert g["94"]["inputs"]["duration"] == g["98"]["inputs"]["seconds"] == 45
    assert g["94"]["inputs"]["seed"] == g["3"]["inputs"]["seed"] == 7
    assert g["106"]["inputs"]["filename_prefix"] == "audio/x"


def test_les_parametres_sont_bornes():
    p = musique_jobs.borner({"style": "rock", "duree": 5000, "bpm": 1})
    assert (p["duree"], p["bpm"], p["langue"]) == (musique_jobs.DUREE_MAX_S, 10, "fr")
    assert isinstance(p["graine"], int)


@pytest.mark.asyncio
async def test_un_morceau_est_rendu_puis_comfyui_est_vide(comfy):
    r = await musique_jobs.handler_musique(_ctx(style="chanson française, guitare", duree=30))
    assert r["fichier"] == "job-1.mp3"
    assert (comfy.dossier / "musique" / "job-1.mp3").read_bytes() == b"ID3-morceau"
    assert ("POST", "/free", {"unload_models": True, "free_memory": True}) in comfy.appels


@pytest.mark.asyncio
async def test_carte_occupee_on_refuse_sans_rien_lancer(comfy):
    comfy.etat["vram_libre"] = 3 * GIO
    with pytest.raises(musique_jobs.MusiqueIndisponible, match="Carte occupée"):
        await musique_jobs.handler_musique(_ctx(style="jazz"))
    assert [p for _, p, _ in comfy.appels] == ["/system_stats"]       # ni /prompt, ni déchargement d'autrui


@pytest.mark.asyncio
async def test_un_rendu_en_erreur_vide_quand_meme_comfyui(comfy):
    comfy.etat["rendu"] = "error"
    with pytest.raises(RuntimeError, match="rendu en erreur"):
        await musique_jobs.handler_musique(_ctx(style="jazz"))
    assert any(p == "/free" for _, p, _ in comfy.appels)


@pytest.mark.asyncio
async def test_non_configure(monkeypatch):
    monkeypatch.setitem(runtime_config._overrides, "comfyui_url", "")
    etat = await musique_jobs.etat_comfyui()
    assert etat["configure"] is False and etat["pret"] is False


@pytest.mark.asyncio
async def test_l_etat_dit_si_matotheque_occupe_la_carte(db_session, monkeypatch):
    """Carte pleine pendant un traitement de documents : la tuile doit pouvoir l'expliquer."""
    from httpx import ASGITransport, AsyncClient

    from database import get_db
    from main import app
    from models.job import Job

    monkeypatch.setitem(runtime_config._overrides, "comfyui_url", "")
    db_session.add_all([Job(type="enrich", statut="running"), Job(type="analyze", statut="running"),
                        Job(type="enrich", statut="pending"), Job(type="sync_source", statut="running")])
    await db_session.flush()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            etat = (await c.get("/api/musique/etat")).json()
    finally:
        app.dependency_overrides.clear()
    assert etat["taches_matotheque"] == 2                       # en cours ET sur la carte seulement
