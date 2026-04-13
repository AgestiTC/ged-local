"""
Tests d'intégration — routers/generate.py
==========================================
Teste les endpoints de génération de rapports :
  GET  /generate/models     → proxy vers Ollama, fallback sur les défauts
  POST /generate/report     → création job + background task SSE
  GET  /generate/status/{job_id} → statut d'un job
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client(db_session):
    """Client HTTP de test avec DB mockée."""
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


# ─── GET /generate/models ─────────────────────────────────────────────────────

class TestListModels:
    @pytest.mark.asyncio
    async def test_retourne_modeles_ollama(self, client):
        """Quand Ollama répond, retourne la liste des modèles."""
        async with client as c:
            with patch("routers.generate.OllamaService") as mock_cls:
                instance = MagicMock()
                instance.list_models = AsyncMock(return_value=[
                    "mixtral:latest",
                    "mistral:latest",
                    "llama3.1:latest",
                ])
                mock_cls.return_value = instance

                resp = await c.get("/api/generate/models")

        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert len(data["models"]) == 3
        names = [m["name"] for m in data["models"]]
        assert "mixtral:latest" in names

    @pytest.mark.asyncio
    async def test_fallback_si_ollama_indisponible(self, client):
        """Si Ollama est inaccessible, retourne les modèles par défaut de la config."""
        async with client as c:
            with patch("routers.generate.OllamaService") as mock_cls:
                instance = MagicMock()
                instance.list_models = AsyncMock(side_effect=ConnectionError("Ollama down"))
                mock_cls.return_value = instance

                resp = await c.get("/api/generate/models")

        # Doit retourner 200 avec des modèles par défaut (pas d'erreur 500)
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert len(data["models"]) >= 1  # Au moins un modèle par défaut

    @pytest.mark.asyncio
    async def test_format_reponse(self, client):
        """Chaque modèle doit avoir un champ 'name'."""
        async with client as c:
            with patch("routers.generate.OllamaService") as mock_cls:
                instance = MagicMock()
                instance.list_models = AsyncMock(return_value=["mistral:latest"])
                mock_cls.return_value = instance

                resp = await c.get("/api/generate/models")

        for m in resp.json()["models"]:
            assert "name" in m
            assert isinstance(m["name"], str)


# ─── POST /generate/report ────────────────────────────────────────────────────

class TestGenerateReport:
    @pytest.mark.asyncio
    async def test_sans_documents_rejete(self, client):
        """Sans document_ids, doit retourner 400."""
        async with client as c:
            resp = await c.post("/api/generate/report", json={
                "document_ids": [],
                "prompt": "Résume ces documents.",
            })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_id_invalide_rejete(self, client):
        """Un document_id qui n'est pas un UUID valide → 400."""
        async with client as c:
            resp = await c.post("/api/generate/report", json={
                "document_ids": ["pas-un-uuid"],
                "prompt": "Résume.",
            })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_document_inexistant_rejete(self, client):
        """Un UUID valide mais qui n'existe pas en DB → 404."""
        async with client as c:
            resp = await c.post("/api/generate/report", json={
                "document_ids": [str(uuid.uuid4())],
                "prompt": "Résume.",
            })
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_prompt_vide_rejete(self, client):
        """Un prompt vide doit être rejeté par la validation Pydantic → 422."""
        async with client as c:
            resp = await c.post("/api/generate/report", json={
                "document_ids": [str(uuid.uuid4())],
                "prompt": "",
            })
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_rapport_avec_document_existant(self, client, db_session):
        """Avec un document existant, doit créer un job et retourner un job_id."""
        from models.document import Document

        # Créer un document de test dans la DB
        doc = Document(
            nom="rapport_test.pdf",
            chemin="/documents/rapport_test.pdf",
            extension="pdf",
            hash_sha256="abc123" + "0" * 58,
            taille_octets=12345,
            statut="enriched",
            source="upload",
            texte_extrait="Contenu du rapport de test pour la génération.",
        )
        db_session.add(doc)
        await db_session.flush()
        doc_id = str(doc.id)

        async with client as c:
            with patch("routers.generate.BackgroundTasks") as _:
                resp = await c.post("/api/generate/report", json={
                    "document_ids": [doc_id],
                    "prompt": "Génère un résumé de ce document.",
                    "model": "mistral:latest",
                })

        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert "stream_url" in data
        assert data["nb_documents"] == 1
        assert data["model"] == "mistral:latest"
        # L'URL de stream doit pointer vers le bon endpoint
        assert data["stream_url"].startswith("/api/generate/stream/")

    @pytest.mark.asyncio
    async def test_modele_defaut_utilise_si_absent(self, client, db_session):
        """Sans champ model, le modèle par défaut de la config est utilisé."""
        from models.document import Document

        doc = Document(
            nom="doc_sans_modele.pdf",
            chemin="/documents/doc_sans_modele.pdf",
            extension="pdf",
            hash_sha256="def456" + "0" * 58,
            taille_octets=5000,
            statut="enriched",
            source="upload",
            texte_extrait="Texte pour tester le modèle par défaut.",
        )
        db_session.add(doc)
        await db_session.flush()

        async with client as c:
            resp = await c.post("/api/generate/report", json={
                "document_ids": [str(doc.id)],
                "prompt": "Résume.",
                # model absent → doit prendre le défaut
            })

        assert resp.status_code == 200
        data = resp.json()
        # Le modèle retourné doit être une chaîne non vide
        assert isinstance(data.get("model"), str)
        assert len(data["model"]) > 0


# ─── GET /generate/status/{job_id} ───────────────────────────────────────────

class TestGenerationStatus:
    @pytest.mark.asyncio
    async def test_job_inexistant_retourne_404(self, client):
        """Un job_id inconnu doit retourner 404."""
        async with client as c:
            resp = await c.get(f"/api/generate/status/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_id_invalide_retourne_400(self, client):
        """Un job_id malformé → 400."""
        async with client as c:
            resp = await c.get("/api/generate/status/pas-un-uuid")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_statut_job_cree(self, client, db_session):
        """Après création d'un rapport, le statut du job est accessible."""
        from models.document import Document

        doc = Document(
            nom="doc_status.pdf",
            chemin="/documents/doc_status.pdf",
            extension="pdf",
            hash_sha256="ghi789" + "0" * 58,
            taille_octets=8000,
            statut="enriched",
            source="upload",
            texte_extrait="Contenu pour tester le statut du job.",
        )
        db_session.add(doc)
        await db_session.flush()

        async with client as c:
            # Créer le rapport
            resp_create = await c.post("/api/generate/report", json={
                "document_ids": [str(doc.id)],
                "prompt": "Résume ce document.",
            })
            assert resp_create.status_code == 200
            job_id = resp_create.json()["job_id"]

            # Vérifier le statut
            resp_status = await c.get(f"/api/generate/status/{job_id}")

        assert resp_status.status_code == 200
        data = resp_status.json()
        assert data["job_id"] == job_id
        assert "statut" in data
        assert data["statut"] in ("pending", "running", "completed", "failed")
        assert "nb_chars_generes" in data


# ─── Tests unitaires : construction du contexte ──────────────────────────────

class TestConstruireContexte:
    def test_contexte_simple(self):
        """Vérifie que le contexte inclut le texte du document et l'instruction."""
        from routers.generate import _construire_contexte
        from models.document import Document

        doc = Document(nom="test.pdf", texte_extrait="Contenu important du document.")
        contexte = _construire_contexte([doc], "Fais un résumé.")

        assert "test.pdf" in contexte
        assert "Contenu important du document." in contexte
        assert "Fais un résumé." in contexte

    def test_document_sans_texte_ignore(self):
        """Un document sans texte extrait est ignoré silencieusement."""
        from routers.generate import _construire_contexte
        from models.document import Document

        doc_vide = Document(nom="vide.pdf", texte_extrait=None)
        doc_contenu = Document(nom="rempli.pdf", texte_extrait="Du texte ici.")

        contexte = _construire_contexte([doc_vide, doc_contenu], "Résume.")

        assert "vide.pdf" not in contexte
        assert "rempli.pdf" in contexte
        assert "Du texte ici." in contexte

    def test_troncature_si_trop_long(self):
        """Un texte trop long doit être tronqué avec le marqueur [...] ."""
        from routers.generate import _construire_contexte
        from models.document import Document

        texte_long = "A" * 100_000
        doc = Document(nom="long.pdf", texte_extrait=texte_long)

        contexte = _construire_contexte([doc], "Résume.", max_chars=1000)

        assert "[... document tronqué ...]" in contexte
        assert len(contexte) < 1500  # Largement sous la limite

    def test_plusieurs_documents(self):
        """Plusieurs documents doivent tous apparaître dans le contexte."""
        from routers.generate import _construire_contexte
        from models.document import Document

        docs = [
            Document(nom="doc1.pdf", texte_extrait="Premier document."),
            Document(nom="doc2.pdf", texte_extrait="Deuxième document."),
            Document(nom="doc3.pdf", texte_extrait="Troisième document."),
        ]

        contexte = _construire_contexte(docs, "Analyse tout ça.")

        for doc in docs:
            assert doc.nom in contexte
            assert doc.texte_extrait in contexte
