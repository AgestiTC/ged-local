"""
Tests — audit du 28/09/2026, H6 (scans qui gelaient l'API) et H7 (Synology)
==========================================================================
"""

import asyncio
import time

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from services.connectors import synology


# ─── H6 : un scan de doublons ne gèle plus l'API ──────────────────────────────────────

@pytest.mark.asyncio
async def test_l_api_repond_pendant_un_scan_de_doublons_lent(monkeypatch, tmp_path):
    """
    Le scan est synchrone (parcours + empreintes). Appelé tel quel dans la route, il bloquait
    l'event loop : aucune autre requête n'avançait avant sa fin. En thread, l'API reste vive.
    """
    from main import app
    from routers import duplicates
    from services import duplicate_service

    # Un dossier qui EXISTE, quel que soit le poste : sinon la route répond 503 (M3).
    monkeypatch.setattr(duplicates.settings, "documents_root", str(tmp_path))

    def scan_lent(root, dirname):
        time.sleep(1.0)
        return []

    monkeypatch.setattr(duplicate_service, "find_duplicates", scan_lent)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        scan = asyncio.create_task(c.get("/api/duplicates"))
        await asyncio.sleep(0.05)                       # le scan a démarré
        t0 = time.perf_counter()
        r = await c.get("/api/version")
        attente = time.perf_counter() - t0
        assert r.status_code == 200
        assert attente < 0.5, f"l'API a attendu {attente:.2f} s la fin du scan"
        assert (await scan).status_code == 200


@pytest.mark.asyncio
async def test_dossier_des_documents_absent_n_est_pas_un_aucun_doublon(monkeypatch, tmp_path):
    """Avant : liste vide → « Aucun doublon trouvé 🎉 » pour un scan qui n'avait rien vu (M3)."""
    from main import app
    from routers import duplicates

    monkeypatch.setattr(duplicates.settings, "documents_root", str(tmp_path / "demonte"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/duplicates")
    assert r.status_code == 503
    assert "introuvable" in r.json()["detail"]


@pytest.mark.asyncio
async def test_un_refus_d_extension_dit_lesquelles_sont_acceptees(db_session):
    """« Extension refusée » sans alternative : deux allers-retours perdus pendant la mesure E5."""
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/upload", files=[("files", ("notes.md", b"# test", "text/markdown"))])
    finally:
        app.dependency_overrides.clear()
    rejet = next(x for x in r.json()["jobs"] if x.get("statut") == "rejeté")
    assert "acceptées" in rejet["raison"] and "docx" in rejet["raison"]


# ─── H7 : Synology — certificat vérifié hors LAN, mot de passe hors de l'URL ──────────

@pytest.mark.parametrize("url, verifie", [
    ("https://192.168.1.20:5001", False),           # LAN : auto-signé toléré
    ("https://10.0.0.5:5001", False),
    ("https://172.20.0.2:5001", False),
    ("https://127.0.0.1:5001", False),
    ("https://nas.local:5001", False),
    ("https://monnas.synology.me:5001", True),       # DDNS public : vérifié
    ("https://monnas.direct.quickconnect.to:5001", True),
    ("https://81.250.10.20:5001", True),             # IP publique (relais) : vérifié
])
def test_politique_de_certificat(url, verifie, monkeypatch):
    monkeypatch.delenv("SYNOLOGY_TLS_NON_VERIFIE", raising=False)
    assert synology._verifier_tls(url) is verifie


def test_echappatoire_explicite(monkeypatch):
    monkeypatch.setenv("SYNOLOGY_TLS_NON_VERIFIE", "1")
    assert synology._verifier_tls("https://monnas.synology.me:5001") is False


@pytest.mark.asyncio
async def test_le_mot_de_passe_ne_passe_plus_par_l_url(monkeypatch):
    vues: list[httpx.Request] = []

    def repondre(requete: httpx.Request) -> httpx.Response:
        vues.append(requete)
        return httpx.Response(200, json={"success": True, "data": {"sid": "SID42"}})

    vrai = httpx.AsyncClient
    monkeypatch.setattr(synology.httpx, "AsyncClient",
                        lambda *a, **k: vrai(*a, transport=httpx.MockTransport(repondre), **k))
    sid = await synology._login("https://192.168.1.20:5001", "admin", "S3cr3t!")

    assert sid == "SID42"
    requete = vues[0]
    assert requete.method == "POST"
    assert "S3cr3t" not in str(requete.url)
    assert b"passwd=S3cr3t%21" in requete.content


@pytest.mark.asyncio
async def test_un_certificat_refuse_le_dit_clairement(monkeypatch):
    def refuser(requete):
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

    vrai = httpx.AsyncClient
    monkeypatch.setattr(synology.httpx, "AsyncClient",
                        lambda *a, **k: vrai(*a, transport=httpx.MockTransport(refuser), **k))
    with pytest.raises(synology.SynologyError, match="Certificat TLS non vérifiable"):
        await synology._login("https://monnas.synology.me:5001", "admin", "x")
