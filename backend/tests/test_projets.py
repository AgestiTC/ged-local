"""
Tests — projets de la page Créer (brouillon, reprise, archive, corbeille, profils prévus)
========================================================================================
Plan : docs/plan-projets-creer.md (demande de Thomas, 09/10/2026).
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from models.projet import Projet


@pytest_asyncio.fixture
async def client(db_session):
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


async def _creer(c, titre="Comparatif MA26041", mode="comparatif", etat=None):
    r = await c.post("/api/projets", json={"titre": titre, "mode": mode, "etat": etat or {"version": 1}})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_creer_sauvegarder_et_reprendre(client):
    async with client as c:
        p = await _creer(c)
        etat = {"version": 1, "documents": ["a", "b"], "instructions": "Comparer les prix"}
        r = await c.patch(f"/api/projets/{p['id']}", json={"etat": etat, "version": p["updated_at"]})
        assert r.status_code == 200
        repris = (await c.get(f"/api/projets/{p['id']}")).json()
    assert repris["etat"] == etat and repris["mode"] == "comparatif"


@pytest.mark.asyncio
async def test_un_autre_onglet_ne_peut_pas_ecraser_en_silence(client):
    async with client as c:
        p = await _creer(c)
        premier = (await c.patch(f"/api/projets/{p['id']}", json={"etat": {"x": 1}, "version": p["updated_at"]})).json()
        perime = await c.patch(f"/api/projets/{p['id']}", json={"etat": {"x": 2}, "version": p["updated_at"]})
        assert perime.status_code == 409
        assert (await c.patch(f"/api/projets/{p['id']}", json={"etat": {"x": 2}, "version": premier["updated_at"]})).status_code == 200


@pytest.mark.asyncio
async def test_archiver_restaurer_et_corbeille(client):
    async with client as c:
        p = await _creer(c)
        await c.post(f"/api/projets/{p['id']}/archiver")
        assert (await c.get("/api/projets?statut=brouillon")).json()["projets"] == []
        assert [x["id"] for x in (await c.get("/api/projets?statut=archive")).json()["projets"]] == [p["id"]]
        await c.post(f"/api/projets/{p['id']}/restaurer")
        assert [x["id"] for x in (await c.get("/api/projets")).json()["projets"]] == [p["id"]]

        await c.delete(f"/api/projets/{p['id']}")
        assert (await c.get("/api/projets")).json()["projets"] == []
        assert [x["id"] for x in (await c.get("/api/projets?statut=corbeille")).json()["projets"]] == [p["id"]]
        await c.post(f"/api/projets/{p['id']}/restaurer")
        assert [x["id"] for x in (await c.get("/api/projets")).json()["projets"]] == [p["id"]]

        assert (await c.delete(f"/api/projets/{p['id']}?definitif=true")).json()["supprime"] == "definitif"
        assert (await c.get(f"/api/projets/{p['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_dupliquer_et_rattacher_des_resultats(client):
    async with client as c:
        p = await _creer(c, etat={"version": 1, "style": "slam"})
        for _ in range(2):           # rattacher deux fois le même résultat n'en crée qu'un
            await c.post(f"/api/projets/{p['id']}/resultats", json={"type": "morceau", "ref": "job-1", "libelle": "Slam"})
        detail = (await c.get(f"/api/projets/{p['id']}")).json()
        copie = (await c.post(f"/api/projets/{p['id']}/dupliquer")).json()
        copie_detail = (await c.get(f"/api/projets/{copie['id']}")).json()
    assert [r["ref"] for r in detail["resultats"]] == ["job-1"]
    assert copie["titre"].endswith("(copie)") and copie_detail["etat"] == {"version": 1, "style": "slam"}
    assert copie_detail["resultats"] == []                       # la copie repart sans résultats


@pytest.mark.asyncio
async def test_les_projets_d_un_autre_profil_sont_invisibles(client, db_session):
    """Profils PRÉVUS : un projet d'un autre propriétaire n'est ni listé, ni lisible, ni modifiable."""
    autre = Projet(titre="Projet de Sophie", mode="rapport_libre", etat={}, proprietaire="sophie")
    db_session.add(autre)
    await db_session.flush()
    async with client as c:
        assert (await c.get("/api/projets")).json()["projets"] == []
        assert (await c.get(f"/api/projets/{autre.id}")).status_code == 404
        assert (await c.delete(f"/api/projets/{autre.id}")).status_code == 404
