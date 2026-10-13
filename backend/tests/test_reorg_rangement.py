"""Réorganisation : déplacement physique confié à l'application « Rangement » (13/10/2026)."""

from unittest.mock import patch

import pytest

from routers import organize


@pytest.mark.asyncio
async def test_apply_refuse_par_defaut(client):
    r = await client.post("/api/organize/apply")
    assert r.status_code == 409 and "Rangement" in r.json()["detail"]
    plan = (await client.get("/api/organize/plan")).json()
    assert plan["application_physique"] is False


@pytest.mark.asyncio
async def test_apply_reactivable(client):
    with patch.object(organize, "application_physique_active", return_value=True):
        r = await client.post("/api/organize/apply")
    assert r.status_code == 200 and r.json()["statut"] == "pending"


@pytest.mark.asyncio
async def test_simulation_et_annulation_restent(client):
    assert (await client.post("/api/organize/apply/dry-run")).status_code == 200
    assert (await client.post("/api/organize/undo")).status_code == 404   # rien à annuler, mais la route répond
