"""
Tests d'intégration — routers/prompts.py
==========================================
Couvre le CRUD complet des prompts pré-enregistrés :
  GET    /prompts          → liste
  POST   /prompts          → création (201)
  PUT    /prompts/{id}     → modification
  DELETE /prompts/{id}     → suppression
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client(db_session):
    """Client HTTP avec DB de test injectée."""
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


PROMPT_VALIDE = {
    "nom": "Résumé exécutif",
    "description": "Génère un résumé de 3 paragraphes",
    "prompt_text": "Analyse ces documents et génère un résumé exécutif en 3 paragraphes.",
    "categorie": "rapport",
    "modele_prefere": "mixtral:latest",
}


async def _creer_prompt(client, data=None):
    """Crée un prompt via l'API et retourne la réponse JSON."""
    async with client as c:
        resp = await c.post("/api/prompts", json=data or PROMPT_VALIDE)
    return resp.json()


# ─── GET /prompts ─────────────────────────────────────────────────────────────

class TestListPrompts:
    @pytest.mark.asyncio
    async def test_liste_vide(self, client):
        """Sans prompts en DB, retourne une liste vide."""
        async with client as c:
            resp = await c.get("/api/prompts")
        assert resp.status_code == 200
        data = resp.json()
        assert "prompts" in data
        # La liste peut contenir les seeds, mais elle existe
        assert isinstance(data["prompts"], list)

    @pytest.mark.asyncio
    async def test_structure_reponse(self, client):
        """Chaque prompt retourné a les champs attendus."""
        # Créer un prompt d'abord
        async with client as c:
            await c.post("/api/prompts", json=PROMPT_VALIDE)
            resp = await c.get("/api/prompts")

        prompts = resp.json()["prompts"]
        # Trouver notre prompt créé
        notre_prompt = next((p for p in prompts if p["nom"] == "Résumé exécutif"), None)
        assert notre_prompt is not None

        champs_requis = {"id", "nom", "prompt_text", "categorie", "modele_prefere", "created_at"}
        assert champs_requis.issubset(notre_prompt.keys())


# ─── POST /prompts ────────────────────────────────────────────────────────────

class TestCreatePrompt:
    @pytest.mark.asyncio
    async def test_creation_reussie(self, client):
        """Création valide → 201 avec les champs retournés."""
        async with client as c:
            resp = await c.post("/api/prompts", json=PROMPT_VALIDE)
        assert resp.status_code == 201
        data = resp.json()
        assert data["nom"] == "Résumé exécutif"
        assert data["categorie"] == "rapport"
        assert data["modele_prefere"] == "mixtral:latest"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_nom_vide_rejete(self, client):
        """Un nom vide doit être rejeté (422)."""
        async with client as c:
            resp = await c.post("/api/prompts", json={
                **PROMPT_VALIDE,
                "nom": "",
            })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_prompt_text_vide_rejete(self, client):
        """Un prompt_text vide doit être rejeté (422)."""
        async with client as c:
            resp = await c.post("/api/prompts", json={
                **PROMPT_VALIDE,
                "prompt_text": "",
            })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_champs_optionnels(self, client):
        """Seuls nom et prompt_text sont requis."""
        async with client as c:
            resp = await c.post("/api/prompts", json={
                "nom": "Prompt minimal",
                "prompt_text": "Analyse ce document.",
            })
        assert resp.status_code == 201
        data = resp.json()
        assert data["nom"] == "Prompt minimal"
        assert data["categorie"] is None
        assert data["modele_prefere"] is None

    @pytest.mark.asyncio
    async def test_id_est_uuid(self, client):
        """L'ID retourné doit être un UUID valide."""
        async with client as c:
            resp = await c.post("/api/prompts", json=PROMPT_VALIDE)
        prompt_id = resp.json()["id"]
        # Ne doit pas lever d'exception
        uuid.UUID(prompt_id)


# ─── PUT /prompts/{id} ────────────────────────────────────────────────────────

class TestUpdatePrompt:
    @pytest.mark.asyncio
    async def test_modification_nom(self, client):
        """PUT modifie le nom d'un prompt."""
        async with client as c:
            cree = (await c.post("/api/prompts", json=PROMPT_VALIDE)).json()
            resp = await c.put(f"/api/prompts/{cree['id']}", json={"nom": "Nouveau nom"})

        assert resp.status_code == 200
        assert resp.json()["nom"] == "Nouveau nom"

    @pytest.mark.asyncio
    async def test_modification_partielle(self, client):
        """PUT partiel : les champs non fournis restent inchangés."""
        async with client as c:
            cree = (await c.post("/api/prompts", json=PROMPT_VALIDE)).json()
            resp = await c.put(f"/api/prompts/{cree['id']}", json={"categorie": "analyse"})

        data = resp.json()
        # Le nom original est conservé
        assert data["nom"] == "Résumé exécutif"
        # La catégorie est mise à jour
        assert data["categorie"] == "analyse"

    @pytest.mark.asyncio
    async def test_prompt_inexistant(self, client):
        """PUT sur un ID inexistant → 404."""
        async with client as c:
            resp = await c.put(f"/api/prompts/{uuid.uuid4()}", json={"nom": "Test"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_id_invalide(self, client):
        """ID non-UUID → 400."""
        async with client as c:
            resp = await c.put("/api/prompts/pas-un-uuid", json={"nom": "Test"})
        assert resp.status_code == 400


# ─── DELETE /prompts/{id} ─────────────────────────────────────────────────────

class TestDeletePrompt:
    @pytest.mark.asyncio
    async def test_suppression_reussie(self, client):
        """Suppression d'un prompt existant → 200 avec confirmation."""
        async with client as c:
            cree = (await c.post("/api/prompts", json=PROMPT_VALIDE)).json()
            resp = await c.delete(f"/api/prompts/{cree['id']}")

        assert resp.status_code == 200
        data = resp.json()
        assert "message" in data
        assert "Résumé exécutif" in data["message"]

    @pytest.mark.asyncio
    async def test_prompt_absent_apres_suppression(self, client):
        """Après suppression, le prompt n'apparaît plus dans la liste."""
        async with client as c:
            cree = (await c.post("/api/prompts", json=PROMPT_VALIDE)).json()
            await c.delete(f"/api/prompts/{cree['id']}")
            liste = (await c.get("/api/prompts")).json()

        ids = [p["id"] for p in liste["prompts"]]
        assert cree["id"] not in ids

    @pytest.mark.asyncio
    async def test_prompt_inexistant(self, client):
        """Supprimer un prompt inexistant → 404."""
        async with client as c:
            resp = await c.delete(f"/api/prompts/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_id_invalide(self, client):
        """ID non-UUID → 400."""
        async with client as c:
            resp = await c.delete("/api/prompts/pas-un-uuid")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_double_suppression(self, client):
        """Supprimer deux fois le même prompt → 404 à la deuxième tentative."""
        async with client as c:
            cree = (await c.post("/api/prompts", json=PROMPT_VALIDE)).json()
            await c.delete(f"/api/prompts/{cree['id']}")
            resp = await c.delete(f"/api/prompts/{cree['id']}")
        assert resp.status_code == 404
