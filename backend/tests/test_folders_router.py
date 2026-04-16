"""
Tests d'intégration — routers/folders.py
==========================================
Couvre la gestion des dossiers surveillés :
  GET    /folders              → liste
  POST   /folders              → ajout (vérifie existence sur disque — mocké)
  PUT    /folders/{id}         → modification
  DELETE /folders/{id}         → suppression (avec/sans docs)
  POST   /folders/{id}/scan    → scan forcé
  GET    /folders/browse       → navigation filesystem
"""

import uuid
from unittest.mock import MagicMock, patch

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


async def _creer_dossier(db_session, chemin="/documents/test", nom_affichage="Test", actif=True):
    """Crée et flush un dossier surveillé. Retourne l'instance."""
    from models.folder import DossierSurveille
    d = DossierSurveille(
        chemin=chemin,
        nom_affichage=nom_affichage,
        actif=actif,
        recursive=True,
        intervalle_scan_secondes=300,
    )
    db_session.add(d)
    await db_session.flush()
    return d


# ─── GET /folders ─────────────────────────────────────────────────────────────

class TestListFolders:
    @pytest.mark.asyncio
    async def test_liste_vide(self, client):
        """Sans dossiers, retourne une liste vide."""
        async with client as c:
            resp = await c.get("/api/folders")
        assert resp.status_code == 200
        assert resp.json()["dossiers"] == []

    @pytest.mark.asyncio
    async def test_liste_avec_dossiers(self, client, db_session):
        """Retourne tous les dossiers enregistrés."""
        await _creer_dossier(db_session, "/docs/rapports", "Rapports")
        await _creer_dossier(db_session, "/docs/factures", "Factures")

        async with client as c:
            resp = await c.get("/api/folders")
        data = resp.json()
        assert len(data["dossiers"]) == 2

    @pytest.mark.asyncio
    async def test_structure_reponse(self, client, db_session):
        """Chaque dossier a les champs requis."""
        await _creer_dossier(db_session)

        async with client as c:
            resp = await c.get("/api/folders")
        dossier = resp.json()["dossiers"][0]
        assert {"id", "chemin", "nom_affichage", "actif", "recursive"}.issubset(dossier.keys())


# ─── POST /folders ─────────────────────────────────────────────────────────────

class TestAddFolder:
    @pytest.mark.asyncio
    async def test_ajout_dossier_existant(self, client):
        """Un dossier qui existe sur le disque est ajouté avec succès."""
        with patch("routers.folders.Path") as mock_path_cls:
            mock_p = MagicMock()
            mock_p.exists.return_value = True
            mock_p.is_dir.return_value = True
            mock_p.resolve.return_value = mock_p
            mock_p.__str__ = lambda self: "/documents/test_ajout"
            mock_p.name = "test_ajout"
            mock_path_cls.return_value = mock_p

            async with client as c:
                resp = await c.post("/api/folders", json={
                    "chemin": "/documents/test_ajout",
                })

        assert resp.status_code == 200
        data = resp.json()
        assert "id" in data
        assert data["scan"] == "lancé en arrière-plan"

    @pytest.mark.asyncio
    async def test_dossier_inexistant_rejete(self, client):
        """Un chemin qui n'existe pas sur le disque → 422."""
        with patch("routers.folders.Path") as mock_path_cls:
            mock_p = MagicMock()
            mock_p.exists.return_value = False
            mock_p.is_dir.return_value = False
            mock_path_cls.return_value = mock_p

            async with client as c:
                resp = await c.post("/api/folders", json={
                    "chemin": "/dossier/qui/nexiste/pas",
                })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_doublon_rejete(self, client, db_session):
        """Un chemin déjà surveillé → 409 Conflict."""
        await _creer_dossier(db_session, chemin="/documents/existant")

        with patch("routers.folders.Path") as mock_path_cls:
            mock_p = MagicMock()
            mock_p.exists.return_value = True
            mock_p.is_dir.return_value = True
            mock_p.resolve.return_value = mock_p
            mock_p.__str__ = lambda self: "/documents/existant"
            mock_path_cls.return_value = mock_p

            async with client as c:
                resp = await c.post("/api/folders", json={"chemin": "/documents/existant"})
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_nom_affichage_personnalise(self, client):
        """Le nom_affichage personnalisé est bien enregistré."""
        with patch("routers.folders.Path") as mock_path_cls:
            mock_p = MagicMock()
            mock_p.exists.return_value = True
            mock_p.is_dir.return_value = True
            mock_p.resolve.return_value = mock_p
            mock_p.__str__ = lambda self: "/documents/perso"
            mock_p.name = "perso"
            mock_path_cls.return_value = mock_p

            async with client as c:
                resp = await c.post("/api/folders", json={
                    "chemin": "/documents/perso",
                    "nom_affichage": "Mes Documents Importants",
                })

        assert resp.status_code == 200
        assert resp.json()["nom_affichage"] == "Mes Documents Importants"


# ─── PUT /folders/{id} ────────────────────────────────────────────────────────

class TestUpdateFolder:
    @pytest.mark.asyncio
    async def test_modification_actif(self, client, db_session):
        """On peut désactiver un dossier via PUT."""
        dossier = await _creer_dossier(db_session, actif=True)

        async with client as c:
            resp = await c.put(f"/api/folders/{dossier.id}", json={"actif": False})
        assert resp.status_code == 200
        assert resp.json()["actif"] is False

    @pytest.mark.asyncio
    async def test_modification_nom_affichage(self, client, db_session):
        """On peut renommer un dossier."""
        dossier = await _creer_dossier(db_session, nom_affichage="Ancien Nom")

        async with client as c:
            resp = await c.put(f"/api/folders/{dossier.id}", json={"nom_affichage": "Nouveau Nom"})
        assert resp.status_code == 200
        assert resp.json()["nom_affichage"] == "Nouveau Nom"

    @pytest.mark.asyncio
    async def test_modification_partielle(self, client, db_session):
        """Un champ non fourni dans PUT reste inchangé."""
        dossier = await _creer_dossier(db_session, nom_affichage="Nom Original", actif=True)

        async with client as c:
            resp = await c.put(f"/api/folders/{dossier.id}", json={"recursive": False})
        data = resp.json()
        assert data["nom_affichage"] == "Nom Original"
        assert data["actif"] is True
        assert data["recursive"] is False

    @pytest.mark.asyncio
    async def test_modification_intervalle_minimum(self, client, db_session):
        """L'intervalle de scan doit être ≥ 30 secondes."""
        dossier = await _creer_dossier(db_session)

        async with client as c:
            resp = await c.put(f"/api/folders/{dossier.id}", json={"intervalle_scan_secondes": 10})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_dossier_inexistant(self, client):
        """PUT sur un ID inexistant → 404."""
        async with client as c:
            resp = await c.put(f"/api/folders/{uuid.uuid4()}", json={"actif": False})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_id_invalide(self, client):
        """ID non-UUID → 400."""
        async with client as c:
            resp = await c.put("/api/folders/pas-un-uuid", json={"actif": False})
        assert resp.status_code == 400


# ─── DELETE /folders/{id} ─────────────────────────────────────────────────────

class TestRemoveFolder:
    @pytest.mark.asyncio
    async def test_suppression_reussie(self, client, db_session):
        """Suppression d'un dossier existant → 200 avec message."""
        dossier = await _creer_dossier(db_session, chemin="/docs/a_supprimer")

        async with client as c:
            resp = await c.delete(f"/api/folders/{dossier.id}")
        assert resp.status_code == 200
        assert "/docs/a_supprimer" in resp.json()["message"]
        assert resp.json()["documents_supprimes"] == 0

    @pytest.mark.asyncio
    async def test_absent_apres_suppression(self, client, db_session):
        """Après suppression, le dossier n'est plus dans la liste."""
        dossier = await _creer_dossier(db_session)
        dossier_id = str(dossier.id)

        async with client as c:
            await c.delete(f"/api/folders/{dossier_id}")
            liste = (await c.get("/api/folders")).json()

        ids = [d["id"] for d in liste["dossiers"]]
        assert dossier_id not in ids

    @pytest.mark.asyncio
    async def test_suppression_avec_documents(self, client, db_session):
        """supprimer_documents=true supprime aussi les docs indexés depuis ce dossier."""
        from models.document import Document
        dossier = await _creer_dossier(db_session, chemin="/docs/projet")

        # Créer des documents liés à ce dossier
        doc = Document(
            nom="rapport.pdf",
            chemin="/docs/projet/rapport.pdf",
            extension="pdf",
            hash_sha256="aaa" + "0" * 61,
            taille_octets=10000,
            statut="enriched",
            source="watch",
        )
        db_session.add(doc)
        await db_session.flush()

        async with client as c:
            resp = await c.delete(
                f"/api/folders/{dossier.id}",
                params={"supprimer_documents": True},
            )
        assert resp.status_code == 200
        assert resp.json()["documents_supprimes"] == 1

    @pytest.mark.asyncio
    async def test_dossier_inexistant(self, client):
        """Supprimer un dossier inexistant → 404."""
        async with client as c:
            resp = await c.delete(f"/api/folders/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_id_invalide(self, client):
        """ID non-UUID → 400."""
        async with client as c:
            resp = await c.delete("/api/folders/pas-un-uuid")
        assert resp.status_code == 400


# ─── POST /folders/{id}/scan ──────────────────────────────────────────────────

class TestForceScan:
    @pytest.mark.asyncio
    async def test_scan_force_dossier_actif(self, client, db_session):
        """Force scan d'un dossier actif → 200 avec message."""
        dossier = await _creer_dossier(db_session, actif=True)

        async with client as c:
            resp = await c.post(f"/api/folders/{dossier.id}/scan")
        assert resp.status_code == 200
        assert "scan" in resp.json()["message"].lower() or "lancé" in resp.json()["message"].lower()
        assert resp.json()["dossier_id"] == str(dossier.id)

    @pytest.mark.asyncio
    async def test_scan_force_dossier_inactif_rejete(self, client, db_session):
        """Force scan d'un dossier désactivé → 422."""
        dossier = await _creer_dossier(db_session, actif=False)

        async with client as c:
            resp = await c.post(f"/api/folders/{dossier.id}/scan")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_dossier_inexistant(self, client):
        """Scan d'un dossier inexistant → 404."""
        async with client as c:
            resp = await c.post(f"/api/folders/{uuid.uuid4()}/scan")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_id_invalide(self, client):
        """ID non-UUID → 400."""
        async with client as c:
            resp = await c.post("/api/folders/pas-un-uuid/scan")
        assert resp.status_code == 400


# ─── GET /folders/browse ──────────────────────────────────────────────────────

class TestBrowseFilesystem:
    @pytest.mark.asyncio
    async def test_browse_chemin_valide(self, client, tmp_path):
        """Browse d'un chemin valide retourne dossiers et fichiers."""
        # Créer une arborescence de test dans tmp_path
        sous_dossier = tmp_path / "sous_dossier"
        sous_dossier.mkdir()
        (tmp_path / "document.pdf").write_text("contenu")

        async with client as c:
            resp = await c.get("/api/folders/browse", params={"path": str(tmp_path)})

        assert resp.status_code == 200
        data = resp.json()
        assert data["chemin_actuel"] == str(tmp_path)
        assert isinstance(data["dossiers"], list)
        assert isinstance(data["fichiers"], list)

        # Le sous-dossier doit apparaître
        noms_dossiers = [d["nom"] for d in data["dossiers"]]
        assert "sous_dossier" in noms_dossiers

        # Le PDF doit apparaître dans les fichiers
        noms_fichiers = [f["nom"] for f in data["fichiers"]]
        assert "document.pdf" in noms_fichiers

    @pytest.mark.asyncio
    async def test_browse_chemin_inexistant(self, client):
        """Browse d'un chemin inexistant → 404."""
        async with client as c:
            resp = await c.get("/api/folders/browse", params={"path": "/chemin/qui/nexiste/pas"})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_browse_chemin_parent(self, client, tmp_path):
        """La réponse contient le chemin parent."""
        async with client as c:
            resp = await c.get("/api/folders/browse", params={"path": str(tmp_path)})

        data = resp.json()
        assert data["chemin_parent"] is not None
        assert data["chemin_parent"] == str(tmp_path.parent)

    @pytest.mark.asyncio
    async def test_browse_filtre_extensions(self, client, tmp_path):
        """Seuls les fichiers aux extensions supportées apparaissent."""
        (tmp_path / "doc.pdf").write_text("pdf")
        (tmp_path / "image.jpg").write_text("jpg")     # Non supporté
        (tmp_path / "script.py").write_text("python")  # Non supporté

        async with client as c:
            resp = await c.get("/api/folders/browse", params={"path": str(tmp_path)})

        noms = [f["nom"] for f in resp.json()["fichiers"]]
        assert "doc.pdf" in noms
        assert "image.jpg" not in noms
        assert "script.py" not in noms

    @pytest.mark.asyncio
    async def test_browse_retourne_taille_fichier(self, client, tmp_path):
        """Chaque fichier a un champ taille_octets."""
        (tmp_path / "doc.pdf").write_bytes(b"x" * 1024)

        async with client as c:
            resp = await c.get("/api/folders/browse", params={"path": str(tmp_path)})

        fichiers = resp.json()["fichiers"]
        assert len(fichiers) == 1
        assert fichiers[0]["taille_octets"] == 1024
