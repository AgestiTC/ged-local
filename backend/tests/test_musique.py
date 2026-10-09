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
    # `charge` = mémoire prise par les modèles d'Ollama (`/api/ps`) : c'est elle qui décide, pas
    # `/system_stats` de ComfyUI, faux sous Windows (il ne voit pas les autres processus).
    etat = {"charge": 0, "rendu": "success"}
    appels: list[tuple[str, str, dict | None]] = []

    def repondre(r: httpx.Request) -> httpx.Response:
        corps = json.loads(r.content) if r.content else None
        appels.append((r.method, r.url.path, corps))
        if r.url.path == "/system_stats":
            return httpx.Response(200, json={"devices": [{"vram_free": 15 * GIO, "vram_total": 16 * GIO}]})
        if r.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "ministral-3:14b", "size_vram": etat["charge"]}]
                                                 if etat["charge"] else []})
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
    monkeypatch.setitem(runtime_config._overrides, "ollama_url", "http://passerelle:21450")
    monkeypatch.setattr(musique_jobs, "ATTENTE_CARTE_PAS_S", 0)
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
async def test_carte_occupee_on_attend_puis_on_renonce_sans_rien_lancer(comfy, monkeypatch):
    """ministral-3 (JARVIS, 9 Gio) chargé : 16 - 2 - 9 = 5 Gio libres < 8 → attente, puis abandon."""
    comfy.etat["charge"] = 9 * GIO
    monkeypatch.setattr(musique_jobs, "ATTENTE_CARTE_MAX_S", 0)
    with pytest.raises(musique_jobs.MusiqueIndisponible, match="Carte occupée"):
        await musique_jobs.handler_musique(_ctx(style="jazz"))
    assert "/prompt" not in [p for _, p, _ in comfy.appels]        # ni rendu, ni déchargement d'autrui


@pytest.mark.asyncio
async def test_la_carte_se_libere_pendant_l_attente(comfy):
    """JARVIS décharge son modèle : le morceau part dès que la place est faite."""
    comfy.etat["charge"] = 9 * GIO
    vus = []

    async def report(_p, message=""):
        vus.append(message)
        if "attente" in message:
            comfy.etat["charge"] = 0                             # JARVIS a fini
    ctx = _ctx(style="jazz")
    ctx.report = report
    r = await musique_jobs.handler_musique(ctx)
    assert r["fichier"] == "job-1.mp3" and any("ministral-3:14b" in m for m in vus)


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


@pytest.mark.asyncio
async def test_le_depassement_autorise_lance_quand_meme_et_vide_comfyui(comfy):
    """« Autoriser le dépassement » : pour ce morceau seulement, le seuil est ignoré."""
    comfy.etat["charge"] = 12 * GIO
    r = await musique_jobs.handler_musique(_ctx(style="jazz", forcer=True))
    assert r["fichier"] == "job-1.mp3"
    assert any(p == "/prompt" for _, p, _ in comfy.appels) and any(p == "/free" for _, p, _ in comfy.appels)



@pytest.mark.asyncio
async def test_preparer_garde_les_paroles_si_l_ia_les_reecrit(monkeypatch):
    """L'IA ne doit qu'AJOUTER des balises : si elle change un mot, on garde le texte d'origine."""
    class FausseIA:
        async def generate(self, *_a, **_k):
            return ('{"tags": "french slam, spoken word, deep male voice, piano", "bpm": 82, '
                    '"keyscale": "A minor", "paroles": "[Verse]\\nPetit escargot qui court"}')

    monkeypatch.setattr("services.ollama_service.OllamaService", lambda: FausseIA())
    r = (await musique_jobs.preparer_style("à la façon de Grand Corps Malade",
                                                "Petit escargot porte sur son dos", "fr"))
    assert (r["bpm"], r["keyscale"]) == (82, "A minor") and "slam" in r["tags"]
    assert r["paroles"] == "Petit escargot porte sur son dos"


@pytest.mark.asyncio
async def test_preparer_accepte_des_balises_ajoutees(monkeypatch):
    class FausseIA:
        async def generate(self, *_a, **_k):
            return ('{"tags": "musette, accordion", "bpm": 500, "keyscale": "do majeur", '
                    '"paroles": "[Verse]\\nPetit escargot\\n[Chorus]\\nporte sur son dos"}')

    monkeypatch.setattr("services.ollama_service.OllamaService", lambda: FausseIA())
    r = (await musique_jobs.preparer_style("musette", "Petit escargot\nporte sur son dos", "fr"))
    assert r["paroles"].startswith("[Verse]") and (r["bpm"], r["keyscale"]) == (300, "C major")
