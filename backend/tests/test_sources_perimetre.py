"""
Tests — synchroniser / indexer UN dossier depuis l'arbre des documents
=====================================================================
`POST /api/sources/perimetre` reçoit le chemin d'un dossier tel que l'arbre « Parcourir »
l'affiche, retrouve la source qui y donne accès et enfile UN job — au lieu de relancer toute la
source (18 jobs sur le NAS, 09/10/2026) pour un besoin ponctuel.
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from models.job import Job
from models.source import Source


@pytest_asyncio.fixture
async def client(db_session):
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    db_session.add(Source(libelle="NAS-MATO", type="smb", hote="192.168.42.200"))
    db_session.add(Source(libelle="Local", type="local", chemin_base="/app/documents"))
    await db_session.flush()
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


async def _jobs(db_session) -> list[Job]:
    return list((await db_session.execute(select(Job))).scalars().all())


@pytest.mark.asyncio
async def test_synchro_d_un_sous_dossier_smb(client, db_session):
    async with client as c:
        r = await c.post("/api/sources/perimetre",
                         json={"chemin": "smb://192.168.42.200/home/[02-données]/Factures", "action": "sync"})
    assert r.status_code == 200 and r.json()["deja_en_cours"] is False
    (job,) = await _jobs(db_session)
    assert job.type == "sync_source" and job.statut == "pending"
    assert job.parametres["partage"] == "home"
    assert job.parametres["chemin"] == "/[02-données]/Factures"


@pytest.mark.asyncio
async def test_indexation_d_un_partage_entier(client, db_session):
    async with client as c:
        r = await c.post("/api/sources/perimetre",
                         json={"chemin": "smb://192.168.42.200/Scan", "action": "index"})
    assert r.status_code == 200
    (job,) = await _jobs(db_session)
    assert job.type == "indexation"
    assert (job.parametres["partage"], job.parametres["chemin"], job.parametres["recursive"]) == ("Scan", "/", True)


@pytest.mark.asyncio
async def test_dossier_d_une_source_locale(client, db_session):
    async with client as c:
        r = await c.post("/api/sources/perimetre",
                         json={"chemin": "/app/documents/clients/A", "action": "sync"})
    assert r.status_code == 200
    (job,) = await _jobs(db_session)
    assert job.parametres["partage"] is None and job.parametres["chemin"] == "/clients/A"


@pytest.mark.asyncio
async def test_un_second_clic_ne_double_pas_le_travail(client, db_session):
    corps = {"chemin": "smb://192.168.42.200/home/[03-W]", "action": "sync"}
    async with client as c:
        premier = (await c.post("/api/sources/perimetre", json=corps)).json()
        second = (await c.post("/api/sources/perimetre", json=corps)).json()
    assert second["deja_en_cours"] is True and second["job_id"] == premier["job_id"]
    assert len(await _jobs(db_session)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("chemin", [
    "smb://192.168.42.200",                       # toute la source : justement ce qu'on veut éviter
    "smb://10.0.0.9/partage/x",                   # hôte sans source
    "smb://192.168.42.200/home/../autre",         # sortie du périmètre
    "/app",                                       # au-dessus de la source locale
    "/app/documents/../../etc",
    "gdrive://a1618c1a-3e14-4953-b3e6-445e428f65c1/Dossier",
])
async def test_perimetres_refuses(client, db_session, chemin):
    async with client as c:
        r = await c.post("/api/sources/perimetre", json={"chemin": chemin, "action": "sync"})
    assert r.status_code == 422, r.text
    assert await _jobs(db_session) == []


@pytest.mark.asyncio
async def test_action_inconnue_refusee(client, db_session):
    async with client as c:
        r = await c.post("/api/sources/perimetre",
                         json={"chemin": "smb://192.168.42.200/home", "action": "purge"})
    assert r.status_code == 422
