"""
Tests — « Créer une vidéo ! » (Wan 2.2 dans ComfyUI, carte VIDE exigée)
=======================================================================
Règles de la session AIGUILLEUR (09/10/2026) : endormir Voxtral, attendre qu'aucun modèle d'Ollama
ne soit chargé sans décharger personne, pas de dépassement, /free après chaque rendu ; dictée par le
proxy Voxtral avec un nom de fichier UNIQUE (le proxy met en cache sur nom + taille).
"""
import json
from types import SimpleNamespace

import httpx
import pytest

from services import runtime_config, video_jobs

GIO = 2**30


@pytest.fixture
def pcgame(monkeypatch, tmp_path):
    """ComfyUI + passerelle + proxy Voxtral simulés ; `etat` les règle, `appels` garde la trace."""
    etat = {"charge": 0, "voxtral_dort": False, "rendu": "success"}
    appels: list[tuple[str, str]] = []

    def repondre(r: httpx.Request) -> httpx.Response:
        appels.append((r.method, r.url.path))
        chemin = r.url.path
        if chemin == "/system_stats":
            return httpx.Response(200, json={"devices": [{}]})
        if chemin == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": "llama3.1:latest", "size_vram": etat["charge"]}]
                                             if etat["charge"] else []})
        if chemin == "/voxtral/sleep":
            etat["voxtral_dort"] = True
            return httpx.Response(200, json={"sleeping": True})
        if chemin == "/voxtral/state":
            return httpx.Response(200, json={"sleeping": etat["voxtral_dort"], "busy": 0})
        if chemin == "/upload/image":
            return httpx.Response(200, json={"name": "matotheque_job-1.png"})
        if chemin == "/prompt":
            etat["graphe"] = json.loads(r.content)["prompt"]
            return httpx.Response(200, json={"prompt_id": "v1"})
        if chemin == "/history/v1":
            return httpx.Response(200, json={"v1": {
                "status": {"completed": True, "status_str": etat["rendu"], "messages": [["e", {}]]},
                "outputs": {"58": {"images": [{"filename": "v.mp4", "subfolder": "video", "type": "output"}]}}}})
        if chemin == "/view":
            return httpx.Response(200, content=b"MP4-video")
        if chemin == "/v1/audio/transcriptions":
            etat.setdefault("noms", []).append(r.content.split(b'filename="')[1].split(b'"')[0].decode())
            return httpx.Response(200, json={"text": "Le chat tourne la tête."})
        return httpx.Response(200, json={})

    vrai = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: vrai(transport=httpx.MockTransport(repondre), **kw))
    for cle, val in (("comfyui_url", "http://pc-game:18188"), ("ollama_url", "http://passerelle:21450"),
                     ("voxtral_proxy_url", "http://pc-game:8012")):
        monkeypatch.setitem(runtime_config._overrides, cle, val)
    monkeypatch.setattr(video_jobs.settings, "storage_exports", str(tmp_path))
    monkeypatch.setattr(video_jobs, "SUIVI_S", 0)
    monkeypatch.setattr(video_jobs, "ATTENTE_CARTE_PAS_S", 0)
    source = tmp_path / "dessin.png"
    source.write_bytes(b"PNG")
    return SimpleNamespace(etat=etat, appels=appels, dossier=tmp_path, source=source)


def _ctx(**params):
    async def report(*_a, **_k):
        return None
    return SimpleNamespace(job_id="job-1", parametres=params, cancelled=False, report=report)


def test_format_natif_selon_l_orientation():
    assert video_jobs.format_natif(3000, 2000) == (1280, 704)
    assert video_jobs.format_natif(2000, 3000) == (704, 1280)


@pytest.mark.asyncio
async def test_une_video_est_rendue_carte_vide_puis_comfyui_est_vide(pcgame):
    r = await video_jobs.handler_video(_ctx(image=str(pcgame.source), largeur=2000, hauteur=3000,
                                            prompt="The cat turns its head. " + video_jobs.FIN_PROMPT))
    assert r["fichier"] == "job-1.mp4" and (r["largeur"], r["hauteur"]) == (704, 1280)
    assert (pcgame.dossier / "video" / "job-1.mp4").read_bytes() == b"MP4-video"
    assert ("POST", "/voxtral/sleep") in pcgame.appels and ("POST", "/free") in pcgame.appels
    g = pcgame.etat["graphe"]
    assert g["56"]["inputs"]["image"] == "matotheque_job-1.png" and g["55"]["inputs"]["length"] == 121


@pytest.mark.asyncio
async def test_un_modele_charge_fait_attendre_sans_rien_decharger(pcgame, monkeypatch):
    pcgame.etat["charge"] = 6 * GIO
    monkeypatch.setattr(video_jobs, "ATTENTE_CARTE_MAX_S", 0)
    with pytest.raises(video_jobs.MusiqueIndisponible, match="llama3.1"):
        await video_jobs.handler_video(_ctx(image=str(pcgame.source), prompt="x"))
    assert ("POST", "/prompt") not in pcgame.appels


@pytest.mark.asyncio
async def test_un_rendu_en_erreur_vide_quand_meme_comfyui(pcgame):
    pcgame.etat["rendu"] = "error"
    with pytest.raises(RuntimeError, match="rendu en erreur"):
        await video_jobs.handler_video(_ctx(image=str(pcgame.source), prompt="x"))
    assert ("POST", "/free") in pcgame.appels


@pytest.mark.asyncio
async def test_la_dictee_suit_le_proxy_qui_repond_pas_la_configuration(pcgame, monkeypatch):
    """Coupure du 8012 (bascule netsh annoncée par AIGUILLEUR) : le micro doit s'effacer."""
    assert (await video_jobs.etat_carte())["dictee"] is True

    async def coupe():
        return None
    monkeypatch.setattr(video_jobs, "etat_voxtral", coupe)
    etat = await video_jobs.etat_carte()
    assert etat["dictee"] is False and etat["joignable"] is True


@pytest.mark.asyncio
async def test_la_dictee_reste_possible_comfyui_eteint(pcgame, monkeypatch):
    monkeypatch.setitem(runtime_config._overrides, "comfyui_url", "")
    etat = await video_jobs.etat_carte()
    assert etat["dictee"] is True and etat["joignable"] is False


@pytest.mark.asyncio
async def test_chaque_dictee_porte_un_nom_unique(pcgame):
    """Le proxy met en cache sur (nom, taille) : deux dictées de même taille ne doivent pas se confondre."""
    t1 = await video_jobs.transcrire_dictee(b"abc", "audio/webm")
    await video_jobs.transcrire_dictee(b"xyz", "audio/webm")
    noms = pcgame.etat["noms"]
    assert t1 == "Le chat tourne la tête." and len(set(noms)) == 2 and all(n.startswith("dictee_") for n in noms)


@pytest.mark.asyncio
async def test_le_prompt_de_mouvement_finit_par_la_consigne_de_style(monkeypatch):
    vus = {}

    class FausseIA:
        async def generate(self, *_a, **k):
            vus.update(k)
            return "The cat slowly turns its head and wags its tail."

    monkeypatch.setattr("services.ollama_service.OllamaService", lambda: FausseIA())
    p = await video_jobs.preparer_mouvement("Le chat tourne la tête et remue la queue")
    assert p.endswith(video_jobs.FIN_PROMPT) and vus["keep_alive"] == 0
