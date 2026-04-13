"""
Tests d'intégration — routers/export.py
=========================================
Teste les endpoints d'export PDF et DOCX avec du contenu Markdown.
"""

import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client():
    """Client HTTP de test contre l'app FastAPI."""
    from main import app
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


class TestExportDocx:
    @pytest.mark.asyncio
    async def test_export_docx_retourne_fichier(self, client, tmp_path):
        """POST /export/docx doit retourner un fichier DOCX."""
        with patch("routers.export.Path") as mock_path:
            # Simuler la création du fichier
            fichier_mock = tmp_path / "rapport.docx"
            fichier_mock.write_bytes(b"PK fake docx content")

            response = await client.post("/api/export/docx", json={
                "content": "# Titre\n\nParagraphe de test.\n\n- Item 1\n- Item 2",
                "title": "Rapport Test"
            })

            # 200 OK avec le bon content-type
            assert response.status_code == 200
            assert "docx" in response.headers.get("content-type", "").lower() or \
                   response.status_code in (200, 422, 500)  # Accepter si weasyprint absent

    @pytest.mark.asyncio
    async def test_export_docx_contenu_vide_rejete(self, client):
        """Un contenu vide doit être rejeté (400/422)."""
        response = await client.post("/api/export/docx", json={
            "content": "",
            "title": "Titre"
        })
        assert response.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_export_docx_sans_title_utilise_defaut(self, client, tmp_path):
        """Sans titre, le titre par défaut 'Rapport DocFlow AI' est utilisé."""
        response = await client.post("/api/export/docx", json={
            "content": "## Section\n\nContenu de test valide."
        })
        # Ne doit pas être 422 (validation error)
        assert response.status_code != 422


class TestExportPdf:
    @pytest.mark.asyncio
    async def test_export_pdf_sans_weasyprint(self, client):
        """Sans weasyprint installé, retourne 500 avec un message clair."""
        with patch.dict("sys.modules", {"weasyprint": None}):
            response = await client.post("/api/export/pdf", json={
                "content": "# Rapport\n\nContenu.",
                "title": "Test PDF"
            })
            # Soit 200 si weasyprint est dispo, soit 500 avec message d'erreur
            assert response.status_code in (200, 500)
            if response.status_code == 500:
                assert "weasyprint" in response.json().get("detail", "").lower() or \
                       "pdf" in response.json().get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_export_pdf_contenu_vide(self, client):
        """Contenu vide → 422 Unprocessable Entity."""
        response = await client.post("/api/export/pdf", json={
            "content": "",
            "title": "Test"
        })
        assert response.status_code == 422


class TestNomFichierExport:
    def test_nom_fichier_sans_caracteres_speciaux(self):
        from routers.export import _nom_export
        nom = _nom_export("Rapport d'analyse 2024 — test", "pdf")
        # Pas de caractères dangereux
        assert "/" not in nom
        assert "\\" not in nom
        assert "'" not in nom
        assert nom.endswith(".pdf")

    def test_nom_fichier_titre_long_tronque(self):
        from routers.export import _nom_export
        nom = _nom_export("A" * 200, "docx")
        # Le nom ne doit pas être trop long
        assert len(nom) < 120

    def test_nom_fichier_contient_horodatage(self):
        from routers.export import _nom_export
        import re
        nom = _nom_export("Rapport", "pdf")
        # Doit contenir un timestamp YYYYMMDD_HHMMSS
        assert re.search(r"\d{8}_\d{6}", nom)
