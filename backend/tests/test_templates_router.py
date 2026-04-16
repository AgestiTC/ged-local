"""
Tests d'intégration — routers/templates.py
============================================
Couvre la gestion des templates DOCX/PDF :
  GET    /templates          → liste des templates
  POST   /templates          → upload (DOCX détection champs, PDF accepté)
  GET    /templates/{id}     → détail + champs
  DELETE /templates/{id}     → suppression (fichier physique inclus)

Le stockage disque et la détection DOCX sont mockés pour l'isolation.
"""

import io
import uuid
from pathlib import Path
from unittest.mock import patch

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


async def _creer_template(
    db_session,
    nom="Contrat Type",
    description="Template de contrat",
    type_="docx",
    chemin="/storage/templates/contrat.docx",
    champs=None,
):
    """Crée et flush un template de test."""
    from models.template import Template

    t = Template(
        nom=nom,
        description=description,
        type=type_,
        chemin_fichier=chemin,
        champs=champs or [{"nom": "titre", "type": "texte", "description": None}],
    )
    db_session.add(t)
    await db_session.flush()
    return t


def _fake_upload(nom: str, contenu: bytes = b"contenu fictif") -> tuple:
    """Crée un tuple (nom, fichier, content-type) pour httpx multipart."""
    ext = Path(nom).suffix.lower()
    mime = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pdf": "application/pdf",
        ".txt": "text/plain",
    }.get(ext, "application/octet-stream")
    return (nom, io.BytesIO(contenu), mime)


# ─── GET /templates ───────────────────────────────────────────────────────────

class TestListTemplates:
    @pytest.mark.asyncio
    async def test_liste_vide(self, client):
        """Sans templates, retourne une liste vide."""
        async with client as c:
            resp = await c.get("/api/templates")

        assert resp.status_code == 200
        assert resp.json()["templates"] == []

    @pytest.mark.asyncio
    async def test_liste_avec_templates(self, client, db_session):
        """Retourne tous les templates enregistrés."""
        await _creer_template(db_session, nom="Contrat", type_="docx")
        await _creer_template(db_session, nom="Rapport", type_="pdf")

        async with client as c:
            resp = await c.get("/api/templates")

        data = resp.json()
        assert len(data["templates"]) == 2

    @pytest.mark.asyncio
    async def test_structure_reponse(self, client, db_session):
        """Chaque template a les champs requis (sans champs)."""
        await _creer_template(db_session)

        async with client as c:
            resp = await c.get("/api/templates")

        t = resp.json()["templates"][0]
        assert {"id", "nom", "description", "type", "created_at"}.issubset(t.keys())
        # La liste ne doit PAS exposer les champs (détail uniquement)
        assert "champs" not in t

    @pytest.mark.asyncio
    async def test_ordre_alphabetique(self, client, db_session):
        """Les templates sont retournés triés par nom."""
        await _creer_template(db_session, nom="Zèbre")
        await _creer_template(db_session, nom="Alpha")
        await _creer_template(db_session, nom="Milieu")

        async with client as c:
            resp = await c.get("/api/templates")

        noms = [t["nom"] for t in resp.json()["templates"]]
        assert noms == sorted(noms)


# ─── POST /templates ──────────────────────────────────────────────────────────

class TestUploadTemplate:
    @pytest.mark.asyncio
    async def test_upload_docx_accepte(self, client, tmp_path):
        """Un DOCX est accepté et un template est créé (statut 201)."""
        with patch("routers.templates.settings") as mock_settings, \
             patch("routers.templates._detecter_champs_docx", return_value=[]) as _:
            mock_settings.storage_templates = str(tmp_path)

            async with client as c:
                resp = await c.post(
                    "/api/templates",
                    files={"file": _fake_upload("modele_contrat.docx")},
                )

        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["type"] == "docx"

    @pytest.mark.asyncio
    async def test_upload_pdf_accepte(self, client, tmp_path):
        """Un PDF est accepté (pas de détection de champs)."""
        with patch("routers.templates.settings") as mock_settings:
            mock_settings.storage_templates = str(tmp_path)

            async with client as c:
                resp = await c.post(
                    "/api/templates",
                    files={"file": _fake_upload("rapport.pdf")},
                )

        assert resp.status_code == 201
        assert resp.json()["type"] == "pdf"
        assert resp.json()["nb_champs"] == 0  # Pas de détection pour les PDF

    @pytest.mark.asyncio
    async def test_extension_non_supportee(self, client, tmp_path):
        """Un fichier .txt est rejeté → 400."""
        with patch("routers.templates.settings") as mock_settings:
            mock_settings.storage_templates = str(tmp_path)

            async with client as c:
                resp = await c.post(
                    "/api/templates",
                    files={"file": _fake_upload("notes.txt")},
                )

        assert resp.status_code == 400
        assert "non supportée" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_champs_docx_detectes(self, client, tmp_path):
        """Les champs {{ nom }} du DOCX sont détectés et retournés."""
        champs_faux = [
            {"nom": "titre", "type": "texte", "description": None},
            {"nom": "date", "type": "texte", "description": None},
            {"nom": "signataire", "type": "texte", "description": None},
        ]

        with patch("routers.templates.settings") as mock_settings, \
             patch("routers.templates._detecter_champs_docx", return_value=champs_faux):
            mock_settings.storage_templates = str(tmp_path)

            async with client as c:
                resp = await c.post(
                    "/api/templates",
                    files={"file": _fake_upload("contrat.docx")},
                )

        assert resp.status_code == 201
        data = resp.json()
        assert data["nb_champs"] == 3
        assert len(data["champs"]) == 3
        noms = [c["nom"] for c in data["champs"]]
        assert "titre" in noms
        assert "date" in noms
        assert "signataire" in noms

    @pytest.mark.asyncio
    async def test_nom_affichage_genere(self, client, tmp_path):
        """Le nom d'affichage est généré depuis le nom de fichier (title case)."""
        with patch("routers.templates.settings") as mock_settings, \
             patch("routers.templates._detecter_champs_docx", return_value=[]):
            mock_settings.storage_templates = str(tmp_path)

            async with client as c:
                resp = await c.post(
                    "/api/templates",
                    files={"file": _fake_upload("contrat_type_2024.docx")},
                )

        assert resp.status_code == 201
        # "contrat_type_2024" → "Contrat Type 2024"
        assert resp.json()["nom"] == "Contrat Type 2024"

    @pytest.mark.asyncio
    async def test_template_cree_en_db(self, client, db_session, tmp_path):
        """Après upload, le template est bien persisté en DB."""
        from sqlalchemy import select
        from models.template import Template

        with patch("routers.templates.settings") as mock_settings, \
             patch("routers.templates._detecter_champs_docx", return_value=[]):
            mock_settings.storage_templates = str(tmp_path)

            async with client as c:
                resp = await c.post(
                    "/api/templates",
                    files={"file": _fake_upload("doc.docx")},
                )

        template_id = resp.json()["id"]
        result = await db_session.execute(select(Template))
        templates_db = result.scalars().all()
        ids_db = [str(t.id) for t in templates_db]
        assert template_id in ids_db


# ─── GET /templates/{id} ──────────────────────────────────────────────────────

class TestGetTemplate:
    @pytest.mark.asyncio
    async def test_get_template_existant(self, client, db_session):
        """Retourne le détail du template avec ses champs."""
        champs = [
            {"nom": "titre", "type": "texte", "description": None},
            {"nom": "auteur", "type": "texte", "description": None},
        ]
        t = await _creer_template(db_session, champs=champs)

        async with client as c:
            resp = await c.get(f"/api/templates/{t.id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(t.id)
        assert data["nom"] == t.nom
        assert "champs" in data
        assert len(data["champs"]) == 2

    @pytest.mark.asyncio
    async def test_structure_champs(self, client, db_session):
        """Chaque champ a un nom, un type et une description."""
        champs = [{"nom": "titre", "type": "texte", "description": "Titre du document"}]
        t = await _creer_template(db_session, champs=champs)

        async with client as c:
            resp = await c.get(f"/api/templates/{t.id}")

        champ = resp.json()["champs"][0]
        assert "nom" in champ
        assert "type" in champ
        assert "description" in champ

    @pytest.mark.asyncio
    async def test_template_inexistant(self, client):
        """Template inconnu → 404."""
        async with client as c:
            resp = await c.get(f"/api/templates/{uuid.uuid4()}")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_id_invalide(self, client):
        """ID non-UUID → 400."""
        async with client as c:
            resp = await c.get("/api/templates/pas-un-uuid")

        assert resp.status_code == 400


# ─── DELETE /templates/{id} ───────────────────────────────────────────────────

class TestDeleteTemplate:
    @pytest.mark.asyncio
    async def test_suppression_reussie(self, client, db_session, tmp_path):
        """Suppression d'un template existant → 200 avec message."""
        # Créer un fichier physique pour éviter l'erreur FileNotFoundError
        fichier = tmp_path / "contrat.docx"
        fichier.write_bytes(b"contenu docx")

        t = await _creer_template(db_session, nom="Contrat", chemin=str(fichier))

        async with client as c:
            resp = await c.delete(f"/api/templates/{t.id}")

        assert resp.status_code == 200
        data = resp.json()
        assert "Contrat" in data["message"]
        assert data["id"] == str(t.id)

    @pytest.mark.asyncio
    async def test_absent_apres_suppression(self, client, db_session, tmp_path):
        """Après suppression, le template n'apparaît plus dans la liste."""
        fichier = tmp_path / "rapport.docx"
        fichier.write_bytes(b"rapport")
        t = await _creer_template(db_session, chemin=str(fichier))
        template_id = str(t.id)

        async with client as c:
            await c.delete(f"/api/templates/{template_id}")
            liste = (await c.get("/api/templates")).json()

        ids = [tpl["id"] for tpl in liste["templates"]]
        assert template_id not in ids

    @pytest.mark.asyncio
    async def test_fichier_physique_supprime(self, client, db_session, tmp_path):
        """Le fichier physique est supprimé du disque avec le template."""
        fichier = tmp_path / "supprime.docx"
        fichier.write_bytes(b"contenu")
        assert fichier.exists()

        t = await _creer_template(db_session, chemin=str(fichier))

        async with client as c:
            await c.delete(f"/api/templates/{t.id}")

        assert not fichier.exists()

    @pytest.mark.asyncio
    async def test_suppression_fichier_manquant_ok(self, client, db_session):
        """Si le fichier physique n'existe plus, la suppression DB réussit quand même."""
        t = await _creer_template(
            db_session,
            chemin="/fichier/qui/nexiste/pas.docx",
        )

        async with client as c:
            resp = await c.delete(f"/api/templates/{t.id}")

        # La suppression en DB doit réussir même sans le fichier physique
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_inexistant(self, client):
        """Supprimer un template inconnu → 404."""
        async with client as c:
            resp = await c.delete(f"/api/templates/{uuid.uuid4()}")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_id_invalide(self, client):
        """ID non-UUID → 400."""
        async with client as c:
            resp = await c.delete("/api/templates/pas-un-uuid")

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_double_suppression(self, client, db_session, tmp_path):
        """Supprimer deux fois le même template → 404 à la seconde tentative."""
        fichier = tmp_path / "double.docx"
        fichier.write_bytes(b"x")
        t = await _creer_template(db_session, chemin=str(fichier))

        async with client as c:
            await c.delete(f"/api/templates/{t.id}")
            resp2 = await c.delete(f"/api/templates/{t.id}")

        assert resp2.status_code == 404
