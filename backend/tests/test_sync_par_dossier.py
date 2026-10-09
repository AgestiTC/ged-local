"""
Tests — surveillance automatique DOSSIER PAR DOSSIER
===================================================
Avant : la synchro automatique était tout ou rien pour une source. « Toutes les heures » sur le
NAS relançait 18 synchros, dont la plupart sur des dossiers qui ne bougent jamais (09/10/2026).
Chaque dossier a désormais sa fréquence : réglage propre, sinon celle de la source ; 0 = jamais.
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from models.document import Document
from models.source import Source
from services.job_worker import cle_dossier, dossiers_dus, intervalle_dossier

MAINTENANT = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
SCOPES = [{"partage": "home", "chemin": "/[02-données]"},
          {"partage": "home", "chemin": "/[03-W]"},
          {"partage": "Scan", "chemin": "/Non classé"}]


def _il_y_a(minutes: int) -> datetime:
    return MAINTENANT - timedelta(minutes=minutes)


def _cles(scopes: list[dict]) -> list[str]:
    return [cle_dossier(s["partage"], s["chemin"]) for s in scopes]


def test_la_cle_distingue_deux_dossiers_homonymes():
    assert cle_dossier("Scan", "/Non classé") != cle_dossier("Scans_Epson", "/Non classé")
    assert cle_dossier(None, "/") == "/"                       # source locale : un seul périmètre


def test_le_reglage_du_dossier_prime_sur_celui_de_la_source():
    reglages = {"home/[03-W]": 0, "Scan/Non classé": 1440}
    assert intervalle_dossier("home/[02-données]", 60, reglages) == 60      # suit la source
    assert intervalle_dossier("home/[03-W]", 60, reglages) == 0             # jamais
    assert intervalle_dossier("Scan/Non classé", 60, reglages) == 1440
    assert intervalle_dossier("home/[02-données]", None, {}) == 0           # source non surveillée


def test_seuls_les_dossiers_echus_sont_synchronises():
    reglages = {"home/[03-W]": 0, "Scan/Non classé": 1440}
    etats = {"home/[02-données]": (_il_y_a(61), False),       # 1 h écoulée → dû
             "home/[03-W]": (_il_y_a(5000), False),           # réglé sur « jamais »
             "Scan/Non classé": (_il_y_a(600), False)}        # 24 h pas encore écoulées
    assert _cles(dossiers_dus(SCOPES, 60, reglages, etats, MAINTENANT)) == ["home/[02-données]"]


def test_un_dossier_deja_en_cours_passe_son_tour():
    etats = {"home/[02-données]": (_il_y_a(600), True)}       # échu, mais sa synchro tourne encore
    dus = _cles(dossiers_dus(SCOPES, 60, {}, etats, MAINTENANT))
    assert "home/[02-données]" not in dus and "home/[03-W]" in dus     # jamais synchronisé → dû


def test_un_dossier_surveille_dans_une_source_qui_ne_l_est_pas():
    """Source sur « désactivée », un seul dossier coché : lui seul est synchronisé."""
    dus = dossiers_dus(SCOPES, None, {"Scan/Non classé": 60}, {}, MAINTENANT)
    assert _cles(dus) == ["Scan/Non classé"]


@pytest_asyncio.fixture
async def client(db_session):
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_regler_puis_revenir_au_reglage_de_la_source(client, db_session):
    src = Source(libelle="NAS", type="smb", hote="192.168.42.200", sync_intervalle_minutes=60)
    db_session.add(src)
    await db_session.flush()

    async with client as c:
        r = await c.patch(f"/api/sources/{src.id}/sync-dossiers", json={"cle": "home/[03-W]", "minutes": 0})
        assert r.status_code == 200 and src.sync_dossiers == {"home/[03-W]": 0}
        await c.patch(f"/api/sources/{src.id}/sync-dossiers", json={"cle": "Scan/Non classé", "minutes": 1440})
        assert src.sync_dossiers == {"home/[03-W]": 0, "Scan/Non classé": 1440}
        await c.patch(f"/api/sources/{src.id}/sync-dossiers", json={"cle": "home/[03-W]", "minutes": None})
        assert src.sync_dossiers == {"Scan/Non classé": 1440}
        refus = await c.patch(f"/api/sources/{src.id}/sync-dossiers", json={"cle": "home/x", "minutes": -5})
    assert refus.status_code == 422


@pytest.mark.asyncio
async def test_les_dossiers_surveilles_sont_donnes_en_chemins_d_arbre(client, db_session):
    """Le repère visuel des explorateurs compare ces chemins à ceux de leurs nœuds."""
    src = Source(libelle="NAS", type="smb", hote="192.168.42.200", sync_intervalle_minutes=60,
                 sync_dossiers={"home/[03-W]": 0})
    db_session.add(src)
    for dossier in ("home/[02-données]", "home/[03-W]"):
        db_session.add(Document(chemin=f"smb://192.168.42.200/{dossier}/a.pdf", nom="a.pdf", extension="pdf",
                                hash_sha256=f"h-{dossier}", taille_octets=1, statut="enriched"))
    await db_session.flush()

    async with client as c:
        dossiers = (await c.get("/api/sources/dossiers-surveilles")).json()["dossiers"]

    assert [(d["chemin"], d["minutes"]) for d in dossiers] == [("smb://192.168.42.200/home/[02-données]", 60)]
