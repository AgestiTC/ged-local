"""
Tests d'intégration — routers/upload.py
=========================================
Couvre l'upload de fichiers :
  POST /upload       → un ou plusieurs fichiers (PDF, DOCX, XLSX…)
  POST /upload/zip   → archive ZIP spécifique

Le stockage disque et les background tasks sont mockés.
"""

import io
from pathlib import Path
from unittest.mock import AsyncMock, patch

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


def _fake_file(nom: str, contenu: bytes = b"contenu test") -> tuple:
    """Crée un tuple (nom, fichier, content-type) pour httpx multipart."""
    ext = Path(nom).suffix.lower()
    mime = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".zip": "application/zip",
        ".txt": "text/plain",
        ".jpg": "image/jpeg",
    }.get(ext, "application/octet-stream")
    return (nom, io.BytesIO(contenu), mime)


# ─── POST /upload ─────────────────────────────────────────────────────────────

class TestUploadFiles:
    @pytest.mark.asyncio
    async def test_upload_pdf_accepte(self, client, tmp_path):
        """Un PDF valide est accepté et un job est créé."""
        with patch("routers.upload._sauvegarder_fichier", new_callable=AsyncMock) as mock_save, \
             patch("routers.upload.settings") as mock_settings:
            mock_settings.storage_uploads = str(tmp_path)
            mock_save.return_value = tmp_path / "rapport.pdf"

            async with client as c:
                resp = await c.post(
                    "/api/upload",
                    files={"files": _fake_file("rapport.pdf")},
                )

        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        assert len(jobs) == 1
        assert jobs[0]["statut"] == "en_attente"
        assert "job_id" in jobs[0]

    @pytest.mark.asyncio
    async def test_upload_docx_accepte(self, client, tmp_path):
        """Un DOCX est également accepté."""
        with patch("routers.upload._sauvegarder_fichier", new_callable=AsyncMock) as mock_save, \
             patch("routers.upload.settings") as mock_settings:
            mock_settings.storage_uploads = str(tmp_path)
            mock_save.return_value = tmp_path / "contrat.docx"

            async with client as c:
                resp = await c.post(
                    "/api/upload",
                    files={"files": _fake_file("contrat.docx")},
                )

        assert resp.status_code == 200
        assert resp.json()["jobs"][0]["statut"] == "en_attente"

    @pytest.mark.asyncio
    async def test_upload_xlsx_accepte(self, client, tmp_path):
        """Un XLSX est accepté."""
        with patch("routers.upload._sauvegarder_fichier", new_callable=AsyncMock) as mock_save, \
             patch("routers.upload.settings") as mock_settings:
            mock_settings.storage_uploads = str(tmp_path)
            mock_save.return_value = tmp_path / "tableau.xlsx"

            async with client as c:
                resp = await c.post(
                    "/api/upload",
                    files={"files": _fake_file("tableau.xlsx")},
                )

        assert resp.status_code == 200
        assert resp.json()["jobs"][0]["statut"] == "en_attente"

    @pytest.mark.asyncio
    async def test_extension_txt_rejetee(self, client, tmp_path):
        """Un fichier .txt est rejeté (extension non supportée)."""
        with patch("routers.upload.settings") as mock_settings:
            mock_settings.storage_uploads = str(tmp_path)

            async with client as c:
                resp = await c.post(
                    "/api/upload",
                    files={"files": _fake_file("notes.txt")},
                )

        assert resp.status_code == 200
        job = resp.json()["jobs"][0]
        assert job["statut"] == "rejeté"
        assert "raison" in job

    @pytest.mark.asyncio
    async def test_extension_jpg_rejetee(self, client, tmp_path):
        """Un fichier .jpg est rejeté."""
        with patch("routers.upload.settings") as mock_settings:
            mock_settings.storage_uploads = str(tmp_path)

            async with client as c:
                resp = await c.post(
                    "/api/upload",
                    files={"files": _fake_file("photo.jpg")},
                )

        job = resp.json()["jobs"][0]
        assert job["statut"] == "rejeté"

    @pytest.mark.asyncio
    async def test_upload_multi_fichiers(self, client, tmp_path):
        """Plusieurs fichiers peuvent être uploadés en une seule requête."""
        with patch("routers.upload._sauvegarder_fichier", new_callable=AsyncMock) as mock_save, \
             patch("routers.upload.settings") as mock_settings:
            mock_settings.storage_uploads = str(tmp_path)
            mock_save.side_effect = [
                tmp_path / "doc1.pdf",
                tmp_path / "doc2.docx",
            ]

            async with client as c:
                resp = await c.post(
                    "/api/upload",
                    files=[
                        ("files", _fake_file("doc1.pdf")),
                        ("files", _fake_file("doc2.docx")),
                    ],
                )

        assert resp.status_code == 200
        jobs = resp.json()["jobs"]
        assert len(jobs) == 2
        assert all(j["statut"] == "en_attente" for j in jobs)

    @pytest.mark.asyncio
    async def test_melange_acceptes_et_rejetes(self, client, tmp_path):
        """Un mélange de fichiers valides et invalides retourne les deux statuts."""
        with patch("routers.upload._sauvegarder_fichier", new_callable=AsyncMock) as mock_save, \
             patch("routers.upload.settings") as mock_settings:
            mock_settings.storage_uploads = str(tmp_path)
            mock_save.return_value = tmp_path / "doc.pdf"

            async with client as c:
                resp = await c.post(
                    "/api/upload",
                    files=[
                        ("files", _fake_file("doc.pdf")),
                        ("files", _fake_file("image.jpg")),
                    ],
                )

        jobs = resp.json()["jobs"]
        assert len(jobs) == 2
        statuts = {j["fichier"]: j["statut"] for j in jobs}
        assert statuts["doc.pdf"] == "en_attente"
        assert statuts["image.jpg"] == "rejeté"

    @pytest.mark.asyncio
    async def test_job_cree_en_db(self, client, db_session, tmp_path):
        """Un job d'extraction est bien créé dans la DB après upload."""
        from sqlalchemy import select
        from models.job import Job

        with patch("routers.upload._sauvegarder_fichier", new_callable=AsyncMock) as mock_save, \
             patch("routers.upload.settings") as mock_settings:
            mock_settings.storage_uploads = str(tmp_path)
            mock_save.return_value = tmp_path / "doc.pdf"

            async with client as c:
                resp = await c.post(
                    "/api/upload",
                    files={"files": _fake_file("doc.pdf")},
                )

        job_id = resp.json()["jobs"][0]["job_id"]

        # Vérifier que le job existe en DB
        result = await db_session.execute(select(Job))
        jobs_db = result.scalars().all()
        ids_db = [str(j.id) for j in jobs_db]
        assert job_id in ids_db

    @pytest.mark.asyncio
    async def test_job_statut_pending(self, client, db_session, tmp_path):
        """Le job est créé en statut 'pending' (la background task n'a pas encore tourné)."""
        from sqlalchemy import select
        from models.job import Job

        with patch("routers.upload._sauvegarder_fichier", new_callable=AsyncMock) as mock_save, \
             patch("routers.upload.settings") as mock_settings:
            mock_settings.storage_uploads = str(tmp_path)
            mock_save.return_value = tmp_path / "doc.pdf"

            async with client as c:
                await c.post(
                    "/api/upload",
                    files={"files": _fake_file("doc.pdf")},
                )

        result = await db_session.execute(select(Job))
        job = result.scalars().first()
        assert job is not None
        assert job.statut == "pending"
        assert job.type == "extraction"


# ─── POST /upload/zip ─────────────────────────────────────────────────────────

class TestUploadZip:
    @pytest.mark.asyncio
    async def test_upload_zip_accepte(self, client, tmp_path):
        """Un ZIP valide est accepté et un job est créé."""
        with patch("routers.upload._sauvegarder_fichier", new_callable=AsyncMock) as mock_save, \
             patch("routers.upload.settings") as mock_settings:
            mock_settings.storage_uploads = str(tmp_path)
            mock_save.return_value = tmp_path / "archive.zip"

            async with client as c:
                resp = await c.post(
                    "/api/upload/zip",
                    files={"file": _fake_file("archive.zip")},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["statut"] == "en_attente"
        assert data["fichier"] == "archive.zip"

    @pytest.mark.asyncio
    async def test_upload_zip_non_zip_rejete(self, client, tmp_path):
        """Un fichier non-ZIP envoyé à /upload/zip → 400."""
        with patch("routers.upload.settings") as mock_settings:
            mock_settings.storage_uploads = str(tmp_path)

            async with client as c:
                resp = await c.post(
                    "/api/upload/zip",
                    files={"file": _fake_file("document.pdf")},
                )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_upload_zip_job_parametres(self, client, db_session, tmp_path):
        """Le job ZIP a bien le paramètre type='zip' dans ses paramètres."""
        from sqlalchemy import select
        from models.job import Job

        with patch("routers.upload._sauvegarder_fichier", new_callable=AsyncMock) as mock_save, \
             patch("routers.upload.settings") as mock_settings:
            mock_settings.storage_uploads = str(tmp_path)
            mock_save.return_value = tmp_path / "archive.zip"

            async with client as c:
                await c.post(
                    "/api/upload/zip",
                    files={"file": _fake_file("archive.zip")},
                )

        result = await db_session.execute(select(Job))
        job = result.scalars().first()
        assert job is not None
        assert job.parametres.get("type") == "zip"
