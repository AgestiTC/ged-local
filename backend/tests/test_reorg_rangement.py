"""Réorganisation : l'application physique et son annulation sont RETIRÉES (étape 10 du plan rangement).

Ranger des fichiers passe désormais par le seul exécutant du Rangement (services/rangement/deplacements.py),
par lots annulables, depuis Rangement › Plan de classement. Le plan virtuel et sa simulation restent.
"""

import pytest


@pytest.mark.asyncio
async def test_appliquer_et_annuler_n_existent_plus(client):
    for chemin in ("/api/organize/apply", "/api/organize/undo"):
        assert (await client.post(chemin)).status_code in (404, 405), chemin
    plan = (await client.get("/api/organize/plan")).json()
    assert plan["application_physique"] is False and plan["peut_annuler"] is False


@pytest.mark.asyncio
async def test_la_simulation_reste(client):
    assert (await client.post("/api/organize/apply/dry-run")).status_code == 200
