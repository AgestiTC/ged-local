"""
Tests d'intégration — routers/dossiers.py
=========================================
Couvre le CRUD des dossiers thématiques et de leurs ressources, la résolution
par slug, et l'**idempotence du seed** (le point le plus facile à casser :
réinstaller un seed ne doit jamais dupliquer les ressources).
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


DOSSIER_VALIDE = {
    "titre": "Veille RGPD",
    "description": "Sources sur la protection des données",
}

RESSOURCE_VALIDE = {
    "titre": "Guide du sous-traitant",
    "auteur": "CNIL",
    "type": "rapport",
    "url": "https://www.cnil.fr/",
    "langue": "fr",
    "groupe": "Officiel",
    "note": "Le cadre de référence des obligations du sous-traitant.",
    "tags": ["rgpd", "cnil"],
}


# ─── Métadonnées ──────────────────────────────────────────────────────────────

class TestTypes:
    @pytest.mark.asyncio
    async def test_types_et_seeds_exposes(self, client):
        """Le front a besoin des types reconnus et des seeds installables."""
        async with client as c:
            resp = await c.get("/api/dossiers/types")
        assert resp.status_code == 200
        data = resp.json()
        assert "podcast" in data["types"]
        assert "livre" in data["types"]
        assert any(s["cle"] == "devenir-parent" for s in data["seeds"])

    @pytest.mark.asyncio
    async def test_types_avant_route_dynamique(self, client):
        """/dossiers/types ne doit pas être capté par /dossiers/{ref} (ordre des routes)."""
        async with client as c:
            resp = await c.get("/api/dossiers/types")
        assert resp.status_code == 200
        assert "types" in resp.json()


# ─── Dossiers ─────────────────────────────────────────────────────────────────

class TestCreateDossier:
    @pytest.mark.asyncio
    async def test_creation_reussie(self, client):
        async with client as c:
            resp = await c.post("/api/dossiers", json=DOSSIER_VALIDE)
        assert resp.status_code == 201
        data = resp.json()
        assert data["titre"] == "Veille RGPD"
        assert data["origine"] == "manuel"
        uuid.UUID(data["id"])

    @pytest.mark.asyncio
    async def test_slug_derive_du_titre(self, client):
        """Sans slug fourni, il est dérivé du titre : accents retirés, espaces → tirets."""
        async with client as c:
            resp = await c.post("/api/dossiers", json={"titre": "Congé de paternité 2026"})
        assert resp.json()["slug"] == "conge-de-paternite-2026"

    @pytest.mark.asyncio
    async def test_titre_vide_rejete(self, client):
        async with client as c:
            resp = await c.post("/api/dossiers", json={"titre": ""})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_slug_duplique_rejete(self, client):
        """Deux dossiers ne peuvent pas partager le même slug → 409."""
        async with client as c:
            await c.post("/api/dossiers", json=DOSSIER_VALIDE)
            resp = await c.post("/api/dossiers", json=DOSSIER_VALIDE)
        assert resp.status_code == 409


class TestReadDossier:
    @pytest.mark.asyncio
    async def test_detail_par_slug(self, client):
        """Un dossier est adressable par son slug autant que par son UUID."""
        async with client as c:
            cree = (await c.post("/api/dossiers", json=DOSSIER_VALIDE)).json()
            par_slug = await c.get(f"/api/dossiers/{cree['slug']}")
            par_id = await c.get(f"/api/dossiers/{cree['id']}")
        assert par_slug.status_code == 200
        assert par_id.status_code == 200
        assert par_slug.json()["id"] == par_id.json()["id"]

    @pytest.mark.asyncio
    async def test_dossier_inexistant(self, client):
        async with client as c:
            resp = await c.get(f"/api/dossiers/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_liste_compte_les_ressources(self, client):
        async with client as c:
            cree = (await c.post("/api/dossiers", json=DOSSIER_VALIDE)).json()
            await c.post(f"/api/dossiers/{cree['id']}/ressources", json=RESSOURCE_VALIDE)
            liste = (await c.get("/api/dossiers")).json()

        notre = next(d for d in liste["dossiers"] if d["id"] == cree["id"])
        assert notre["nb_ressources"] == 1


class TestUpdateDeleteDossier:
    @pytest.mark.asyncio
    async def test_modification_partielle(self, client):
        async with client as c:
            cree = (await c.post("/api/dossiers", json=DOSSIER_VALIDE)).json()
            resp = await c.patch(f"/api/dossiers/{cree['id']}", json={"description": "Mise à jour"})
        data = resp.json()
        assert data["description"] == "Mise à jour"
        assert data["titre"] == "Veille RGPD"   # champ non fourni → inchangé

    @pytest.mark.asyncio
    async def test_suppression_emporte_les_ressources(self, client):
        """Supprimer un dossier supprime ses ressources (pas d'orphelines)."""
        async with client as c:
            cree = (await c.post("/api/dossiers", json=DOSSIER_VALIDE)).json()
            ress = (await c.post(f"/api/dossiers/{cree['id']}/ressources",
                                 json=RESSOURCE_VALIDE)).json()
            suppr = await c.delete(f"/api/dossiers/{cree['id']}")
            orpheline = await c.patch(f"/api/dossiers/ressources/{ress['id']}", json={"favori": True})

        assert suppr.status_code == 200
        assert orpheline.status_code == 404


# ─── Ressources ───────────────────────────────────────────────────────────────

class TestRessources:
    @pytest.mark.asyncio
    async def test_ajout_reussi(self, client):
        async with client as c:
            cree = (await c.post("/api/dossiers", json=DOSSIER_VALIDE)).json()
            resp = await c.post(f"/api/dossiers/{cree['id']}/ressources", json=RESSOURCE_VALIDE)
        assert resp.status_code == 201
        data = resp.json()
        assert data["titre"] == "Guide du sous-traitant"
        assert data["tags"] == ["rgpd", "cnil"]
        assert data["active"] is True

    @pytest.mark.asyncio
    async def test_champs_optionnels(self, client):
        """Seul le titre est requis ; les défauts s'appliquent."""
        async with client as c:
            cree = (await c.post("/api/dossiers", json=DOSSIER_VALIDE)).json()
            resp = await c.post(f"/api/dossiers/{cree['id']}/ressources",
                                json={"titre": "Note de veille"})
        data = resp.json()
        assert data["type"] == "article"
        assert data["langue"] == "fr"
        assert data["tags"] == []

    @pytest.mark.asyncio
    async def test_groupes_dans_l_ordre_d_insertion(self, client):
        """L'ordre des groupes suit les positions, pas l'alphabet (il porte une progression)."""
        async with client as c:
            cree = (await c.post("/api/dossiers", json=DOSSIER_VALIDE)).json()
            for groupe in ("Zéro — à lire en premier", "Approfondir"):
                await c.post(f"/api/dossiers/{cree['id']}/ressources",
                             json={"titre": f"Ressource {groupe}", "groupe": groupe})
            detail = (await c.get(f"/api/dossiers/{cree['id']}")).json()

        assert detail["groupes"] == ["Zéro — à lire en premier", "Approfondir"]

    @pytest.mark.asyncio
    async def test_modification(self, client):
        async with client as c:
            cree = (await c.post("/api/dossiers", json=DOSSIER_VALIDE)).json()
            ress = (await c.post(f"/api/dossiers/{cree['id']}/ressources",
                                 json=RESSOURCE_VALIDE)).json()
            resp = await c.patch(f"/api/dossiers/ressources/{ress['id']}",
                                 json={"favori": True, "active": False})
        data = resp.json()
        assert data["favori"] is True
        assert data["active"] is False
        assert data["titre"] == "Guide du sous-traitant"

    @pytest.mark.asyncio
    async def test_ressource_inactive_hors_comptage(self, client):
        """Une ressource archivée reste consultable mais ne compte plus."""
        async with client as c:
            cree = (await c.post("/api/dossiers", json=DOSSIER_VALIDE)).json()
            ress = (await c.post(f"/api/dossiers/{cree['id']}/ressources",
                                 json=RESSOURCE_VALIDE)).json()
            await c.patch(f"/api/dossiers/ressources/{ress['id']}", json={"active": False})
            detail = (await c.get(f"/api/dossiers/{cree['id']}")).json()

        assert detail["nb_ressources"] == 0
        assert len(detail["ressources"]) == 1

    @pytest.mark.asyncio
    async def test_suppression(self, client):
        async with client as c:
            cree = (await c.post("/api/dossiers", json=DOSSIER_VALIDE)).json()
            ress = (await c.post(f"/api/dossiers/{cree['id']}/ressources",
                                 json=RESSOURCE_VALIDE)).json()
            resp = await c.delete(f"/api/dossiers/ressources/{ress['id']}")
            detail = (await c.get(f"/api/dossiers/{cree['id']}")).json()

        assert resp.status_code == 200
        assert detail["ressources"] == []

    @pytest.mark.asyncio
    async def test_id_invalide(self, client):
        async with client as c:
            resp = await c.delete("/api/dossiers/ressources/pas-un-uuid")
        assert resp.status_code == 400


# ─── Seeds ────────────────────────────────────────────────────────────────────

class TestSeed:
    @pytest.mark.asyncio
    async def test_installation(self, client):
        async with client as c:
            resp = await c.post("/api/dossiers/seed/devenir-parent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cree"] is True
        assert data["ajoutees"] > 50
        assert data["slug"] == "devenir-parent"

    @pytest.mark.asyncio
    async def test_reinstallation_idempotente(self, client):
        """Rejouer le seed ne duplique rien — c'est tout l'intérêt de la clé URL/titre."""
        async with client as c:
            premier = (await c.post("/api/dossiers/seed/devenir-parent")).json()
            second = (await c.post("/api/dossiers/seed/devenir-parent")).json()
            detail = (await c.get("/api/dossiers/devenir-parent")).json()

        assert second["cree"] is False
        assert second["ajoutees"] == 0
        assert second["ignorees"] == premier["ajoutees"]
        assert len(detail["ressources"]) == premier["ajoutees"]

    @pytest.mark.asyncio
    async def test_contenu_installe(self, client):
        """Le dossier livré couvre bien les six familles de sources annoncées."""
        async with client as c:
            await c.post("/api/dossiers/seed/devenir-parent")
            detail = (await c.get("/api/dossiers/devenir-parent")).json()

        types = {r["type"] for r in detail["ressources"]}
        assert {"podcast", "chaine", "documentaire", "livre", "etude", "prompt"} <= types
        assert any(r["langue"] == "en" for r in detail["ressources"])
        assert any(r["favori"] for r in detail["ressources"])

    @pytest.mark.asyncio
    async def test_seed_inconnu(self, client):
        async with client as c:
            resp = await c.post("/api/dossiers/seed/inexistant")
        assert resp.status_code == 404

# ─── Champ `contenu` (texte long intégral) ────────────────────────────────────

class TestContenu:
    @pytest.mark.asyncio
    async def test_absent_par_defaut(self, client):
        """Une ressource ordinaire pointe vers un contenu : elle n'en porte pas."""
        async with client as c:
            cree = (await c.post("/api/dossiers", json=DOSSIER_VALIDE)).json()
            resp = await c.post(f"/api/dossiers/{cree['id']}/ressources", json=RESSOURCE_VALIDE)
        assert resp.json()["contenu"] is None

    @pytest.mark.asyncio
    async def test_aller_retour_texte_long(self, client):
        """Le texte long survit intact aux sauts de ligne et aux accents."""
        # Jointure explicite : les sauts de ligne comptent, autant qu'ils se voient.
        texte = chr(10).join([
            "Ligne 1 — accentuée",
            "",
            "Ligne 3 : « guillemets » et l'apostrophe.",
        ])
        async with client as c:
            cree = (await c.post("/api/dossiers", json=DOSSIER_VALIDE)).json()
            ress = (await c.post(f"/api/dossiers/{cree['id']}/ressources",
                                 json={**RESSOURCE_VALIDE, "contenu": texte})).json()
            detail = (await c.get(f"/api/dossiers/{cree['id']}")).json()

        assert ress["contenu"] == texte
        assert detail["ressources"][0]["contenu"] == texte

    @pytest.mark.asyncio
    async def test_effacable(self, client):
        """Mettre `contenu` à null retire le texte sans toucher au reste."""
        async with client as c:
            cree = (await c.post("/api/dossiers", json=DOSSIER_VALIDE)).json()
            ress = (await c.post(f"/api/dossiers/{cree['id']}/ressources",
                                 json={**RESSOURCE_VALIDE, "contenu": "texte"})).json()
            resp = await c.patch(f"/api/dossiers/ressources/{ress['id']}", json={"contenu": None})
        data = resp.json()
        assert data["contenu"] is None
        assert data["titre"] == "Guide du sous-traitant"

    @pytest.mark.asyncio
    async def test_prompts_du_seed_portent_leur_texte(self, client):
        """Les prompts livrés doivent être copiables tels quels : texte intégral en base."""
        async with client as c:
            await c.post("/api/dossiers/seed/devenir-parent")
            detail = (await c.get("/api/dossiers/devenir-parent")).json()

        prompts = [r for r in detail["ressources"] if r["type"] == "prompt"]
        assert len(prompts) >= 4
        assert all(r["contenu"] for r in prompts), "un prompt sans texte intégral est inutilisable"

        principal = next(r for r in prompts if "principal" in r["titre"].lower())
        # La clause anti-invention est la raison d'être du prompt : elle ne doit pas sauter.
        assert "N'invente aucun titre" in principal["contenu"]
        assert "CATÉGORIES ATTENDUES" in principal["contenu"]
