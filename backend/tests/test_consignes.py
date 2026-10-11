"""Consignes de base versionnées (11/10/2026) : garde-fous, versions, retour à l'origine."""

import pytest

TEXTE = "## 🎯 En bref\n" + "Consigne de test fictive. " * 12


@pytest.mark.asyncio
async def test_versions_et_retour_origine(client):
    assert (await client.get("/api/consignes/reference_analyse")).json() == {
        "cle": "reference_analyse", "active": None, "versions": []}      # rien en base = l'origine du code

    v1 = await client.post("/api/consignes/reference_analyse", json={"texte": TEXTE, "commentaire": "essai"})
    assert v1.status_code == 201 and v1.json()["version"] == 1
    v2 = await client.post("/api/consignes/reference_analyse", json={"texte": None})
    assert v2.json() == {**v2.json(), "version": 2, "origine": True, "texte": None}

    r = (await client.get("/api/consignes/reference_analyse")).json()
    assert r["active"]["version"] == 2 and r["active"]["origine"]
    assert [v["version"] for v in r["versions"]] == [2, 1]               # rien d'écrasé
    assert r["versions"][1]["texte"] == TEXTE.strip()


@pytest.mark.asyncio
async def test_garde_fous(client):
    trop_court = await client.post("/api/consignes/reference_corrigee", json={"texte": "   court   "})
    assert trop_court.status_code == 400 and "rétablissez la consigne d'origine" in trop_court.json()["detail"]
    assert (await client.post("/api/consignes/inconnue", json={"texte": TEXTE})).status_code == 404
    assert (await client.get("/api/consignes/reference_corrigee")).json()["versions"] == []
