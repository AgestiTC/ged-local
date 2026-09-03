"""
Tests — hiérarchie des dossiers thématiques (parent → sous-dossiers)
===================================================================
Couvre : création d'un sous-dossier, exclusion des enfants de la liste racine,
détail (fil d'Ariane parent + sous-dossiers), et le **seed hiérarchique « mon-bebe »**
(6 sous-dossiers d'âge, un prompt chacun, idempotent).
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


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
async def test_sous_dossier_cree_et_rattache(client):
    async with client as c:
        parent = (await c.post("/api/dossiers", json={"titre": "Mon sujet"})).json()
        enfant = (await c.post("/api/dossiers", json={"titre": "Sous-thème A", "parent": parent["slug"]})).json()
        assert enfant["parent_id"] == parent["id"]

        # La liste racine ne montre QUE le parent (pas l'enfant).
        racines = (await c.get("/api/dossiers")).json()["dossiers"]
        slugs = {d["slug"] for d in racines}
        assert parent["slug"] in slugs
        assert enfant["slug"] not in slugs
        p = next(d for d in racines if d["slug"] == parent["slug"])
        assert p["nb_sous_dossiers"] == 1


@pytest.mark.asyncio
async def test_detail_expose_parent_et_sous_dossiers(client):
    async with client as c:
        parent = (await c.post("/api/dossiers", json={"titre": "Racine"})).json()
        await c.post("/api/dossiers", json={"titre": "Enfant 1", "parent": parent["slug"]})

        det_parent = (await c.get(f"/api/dossiers/{parent['slug']}")).json()
        assert det_parent["parent"] is None
        assert len(det_parent["sous_dossiers"]) == 1
        assert det_parent["sous_dossiers"][0]["titre"] == "Enfant 1"

        enfant_slug = det_parent["sous_dossiers"][0]["slug"]
        det_enfant = (await c.get(f"/api/dossiers/{enfant_slug}")).json()
        assert det_enfant["parent"]["slug"] == parent["slug"]


@pytest.mark.asyncio
async def test_seed_mon_bebe_hierarchique_et_idempotent(client):
    async with client as c:
        r1 = (await c.post("/api/dossiers/seed/mon-bebe")).json()
        assert r1["cree"] is True
        assert len(r1["sous_dossiers"]) == 6           # 6 tranches d'âge
        assert all(s["ajoutees"] == 1 for s in r1["sous_dossiers"])   # un prompt chacun

        # Le parent « mon-bebe » est une racine avec 6 sous-dossiers.
        det = (await c.get("/api/dossiers/mon-bebe")).json()
        assert det["nb_sous_dossiers"] == 6
        # Chaque sous-dossier a un slug préfixé et une ressource de type prompt.
        sous0 = det["sous_dossiers"][0]
        detail_sous = (await c.get(f"/api/dossiers/{sous0['slug']}")).json()
        assert sous0["slug"].startswith("mon-bebe-")
        assert any(r["type"] == "prompt" and r["contenu"] for r in detail_sous["ressources"])

        # Ré-installer n'ajoute rien (idempotent).
        r2 = (await c.post("/api/dossiers/seed/mon-bebe")).json()
        assert r2["cree"] is False
        assert r2["ajoutees"] == 0


@pytest.mark.asyncio
async def test_suppression_parent_cascade_les_enfants(client):
    async with client as c:
        parent = (await c.post("/api/dossiers", json={"titre": "À supprimer"})).json()
        await c.post("/api/dossiers", json={"titre": "Enfant", "parent": parent["slug"]})
        msg = (await c.delete(f"/api/dossiers/{parent['slug']}")).json()["message"]
        assert "sous-dossier" in msg
        # L'enfant n'est plus accessible (cascade).
        assert (await c.get("/api/dossiers")).json()["dossiers"] == [] or \
            all(not d["slug"].startswith("a-supprimer") for d in (await c.get("/api/dossiers")).json()["dossiers"])
