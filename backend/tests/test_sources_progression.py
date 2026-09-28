"""
Tests — la barre de progression d'indexation d'une source se lit EN BASE
======================================================================
Audit du 28/09/2026, H3 : la route lisait un dict du process API, alors que l'indexation tourne
dans le process worker. Selon le process qui répondait, la barre restait figée sur
« énumération 0/0 » jusqu'au redémarrage, ou n'affichait rien. Et deux jobs d'une même source
partageaient un compteur (« 40047/34290 »).

Désormais la route lit la table `jobs` : ce que le worker y écrit (`resultat` = phase, total,
fait) est vu par n'importe quel process — ce que ces tests vérifient en vidant le dict.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from models.job import Job
from routers import sources as sources_mod

SRC = str(uuid.uuid4())
AUTRE = str(uuid.uuid4())


@pytest_asyncio.fixture
async def client(db_session):
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    sources_mod._progression.clear()      # ce que voit un process API : RIEN du worker
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


def _job(source_id: str, statut: str, resultat: dict | None = None, type_: str = "indexation"):
    return Job(type=type_, statut=statut, parametres={"source_id": source_id}, resultat=resultat)


async def _progression(c, sid=SRC) -> dict:
    return (await c.get(f"/api/sources/{sid}/progression")).json()


@pytest.mark.asyncio
async def test_sans_job_actif_aucune_barre(client, db_session):
    db_session.add(_job(SRC, "completed", {"total": 10, "indexes": 10}))
    await db_session.flush()
    async with client as c:
        p = await _progression(c)
    assert p["en_cours"] is False and p["phase"] == "aucune"


@pytest.mark.asyncio
async def test_job_en_file_affiche_l_attente(client, db_session):
    """Avant : « énumération 0/0 » posé par le process API, figé jusqu'au redémarrage."""
    db_session.add(_job(SRC, "pending"))
    await db_session.flush()
    async with client as c:
        p = await _progression(c)
    assert p["en_cours"] is True and p["phase"] == "attente"


@pytest.mark.asyncio
async def test_le_process_api_voit_ce_que_le_worker_ecrit(client, db_session):
    """Le dict est vide (autre process) : la progression vient de `jobs.resultat`."""
    db_session.add(_job(SRC, "running", {"phase": "indexation", "total": 200, "fait": 50}))
    await db_session.flush()
    async with client as c:
        p = await _progression(c)
    assert (p["phase"], p["total"], p["fait"], p["pct"]) == ("indexation", 200, 50, 25)


@pytest.mark.asyncio
async def test_enumeration_en_cours(client, db_session):
    db_session.add(_job(SRC, "running", {"phase": "enumeration", "total": 0, "fait": 0}))
    await db_session.flush()
    async with client as c:
        p = await _progression(c)
    assert p["en_cours"] is True and p["phase"] == "enumeration"


@pytest.mark.asyncio
async def test_plusieurs_jobs_d_une_source_s_additionnent_sans_depasser(client, db_session):
    """Avant : un compteur PAR SOURCE partagé → « 40047/34290 », plus de 100 %."""
    db_session.add_all([
        _job(SRC, "running", {"phase": "indexation", "total": 100, "fait": 40}),
        _job(SRC, "running", {"phase": "indexation", "total": 50, "fait": 50}),
        _job(SRC, "pending"),
    ])
    await db_session.flush()
    async with client as c:
        p = await _progression(c)
    assert (p["total"], p["fait"], p["pct"], p["nb_jobs"]) == (150, 90, 60, 3)
    assert p["fait"] <= p["total"]


@pytest.mark.asyncio
async def test_les_jobs_d_une_autre_source_ou_d_un_autre_type_ne_comptent_pas(client, db_session):
    db_session.add_all([
        _job(AUTRE, "running", {"phase": "indexation", "total": 10, "fait": 1}),
        _job(SRC, "running", {"phase": "indexation", "total": 10, "fait": 1}, type_="sync_source"),
    ])
    await db_session.flush()
    async with client as c:
        p = await _progression(c)
    assert p["en_cours"] is False
