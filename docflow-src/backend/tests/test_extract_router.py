"""
Tests d'intégration — routers/extract.py
==========================================
Couvre la gestion des jobs d'extraction :
  GET  /extract/status/{job_id}    → statut d'un job
  POST /extract/{document_id}      → relance extraction
  GET  /extract/jobs               → liste des jobs récents
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


async def _creer_job(db_session, type_="extraction", statut="pending", doc_id=None, erreur=None):
    """Crée et flush un job de test."""
    from models.job import Job
    job = Job(
        type=type_,
        statut=statut,
        document_id=doc_id,
        parametres={"fichier": "/test/doc.pdf"},
        erreur=erreur,
    )
    db_session.add(job)
    await db_session.flush()
    return job


async def _creer_document(db_session, chemin="/docs/test.pdf", statut="enriched"):
    """Crée et flush un document de test."""
    from models.document import Document
    doc = Document(
        nom="test.pdf",
        chemin=chemin,
        extension="pdf",
        hash_sha256="abc" + "0" * 61,
        taille_octets=10000,
        statut=statut,
        source="upload",
    )
    db_session.add(doc)
    await db_session.flush()
    return doc


# ─── GET /extract/status/{job_id} ────────────────────────────────────────────

class TestGetJobStatus:
    @pytest.mark.asyncio
    async def test_statut_job_pending(self, client, db_session):
        """Un job en attente retourne statut='pending'."""
        job = await _creer_job(db_session, statut="pending")

        async with client as c:
            resp = await c.get(f"/api/extract/status/{job.id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["statut"] == "pending"
        assert data["id"] == str(job.id)
        assert data["type"] == "extraction"

    @pytest.mark.asyncio
    async def test_statut_job_completed(self, client, db_session):
        """Un job terminé retourne statut='completed'."""
        job = await _creer_job(db_session, statut="completed")

        async with client as c:
            resp = await c.get(f"/api/extract/status/{job.id}")

        assert resp.json()["statut"] == "completed"

    @pytest.mark.asyncio
    async def test_statut_job_failed(self, client, db_session):
        """Un job en erreur retourne statut='failed' avec le message d'erreur."""
        job = await _creer_job(db_session, statut="failed", erreur="Tika inaccessible")

        async with client as c:
            resp = await c.get(f"/api/extract/status/{job.id}")

        data = resp.json()
        assert data["statut"] == "failed"
        assert data["erreur"] == "Tika inaccessible"

    @pytest.mark.asyncio
    async def test_structure_reponse(self, client, db_session):
        """La réponse a tous les champs attendus."""
        job = await _creer_job(db_session)

        async with client as c:
            resp = await c.get(f"/api/extract/status/{job.id}")

        data = resp.json()
        champs = {"id", "type", "statut", "document_id", "parametres", "resultat", "erreur", "created_at"}
        assert champs.issubset(data.keys())

    @pytest.mark.asyncio
    async def test_job_inexistant(self, client):
        """Un job_id inconnu → 404."""
        async with client as c:
            resp = await c.get(f"/api/extract/status/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_id_invalide(self, client):
        """Un job_id non-UUID → 400."""
        async with client as c:
            resp = await c.get("/api/extract/status/pas-un-uuid")
        assert resp.status_code == 400


# ─── POST /extract/{document_id} ─────────────────────────────────────────────

class TestRelancerExtraction:
    @pytest.mark.asyncio
    async def test_relance_document_existant(self, client, db_session, tmp_path):
        """Relancer l'extraction d'un document existant crée un nouveau job."""
        chemin = tmp_path / "doc.pdf"
        chemin.write_bytes(b"contenu pdf")

        doc = await _creer_document(db_session, chemin=str(chemin), statut="error")

        async with client as c:
            resp = await c.post(f"/api/extract/{doc.id}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"] == str(doc.id)
        assert "job_id" in data
        assert data["statut"] == "en_attente"

    @pytest.mark.asyncio
    async def test_relance_remet_statut_pending(self, client, db_session, tmp_path):
        """Après relance, le document repasse en statut 'pending'."""
        from sqlalchemy import select
        from models.document import Document

        chemin = tmp_path / "doc2.pdf"
        chemin.write_bytes(b"pdf")
        doc = await _creer_document(db_session, chemin=str(chemin), statut="error")

        async with client as c:
            await c.post(f"/api/extract/{doc.id}")

        result = await db_session.execute(select(Document).where(Document.id == doc.id))
        doc_apres = result.scalar_one()
        assert doc_apres.statut == "pending"

    @pytest.mark.asyncio
    async def test_relance_fichier_source_manquant(self, client, db_session):
        """Si le fichier source n'existe plus sur le disque → 422."""
        doc = await _creer_document(
            db_session,
            chemin="/fichier/qui/nexiste/pas.pdf",
            statut="error",
        )

        async with client as c:
            resp = await c.post(f"/api/extract/{doc.id}")

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_relance_document_inexistant(self, client):
        """Document inconnu → 404."""
        async with client as c:
            resp = await c.post(f"/api/extract/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_relance_id_invalide(self, client):
        """ID non-UUID → 400."""
        async with client as c:
            resp = await c.post("/api/extract/pas-un-uuid")
        assert resp.status_code == 400


# ─── GET /extract/jobs ────────────────────────────────────────────────────────

class TestListJobs:
    @pytest.mark.asyncio
    async def test_liste_vide(self, client):
        """Sans jobs, retourne une liste vide."""
        async with client as c:
            resp = await c.get("/api/extract/jobs")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        assert resp.json()["jobs"] == []

    @pytest.mark.asyncio
    async def test_liste_avec_jobs(self, client, db_session):
        """Retourne tous les jobs enregistrés."""
        await _creer_job(db_session, statut="completed")
        await _creer_job(db_session, statut="pending")

        async with client as c:
            resp = await c.get("/api/extract/jobs")

        data = resp.json()
        assert data["total"] == 2
        assert len(data["jobs"]) == 2

    @pytest.mark.asyncio
    async def test_filtre_par_statut(self, client, db_session):
        """Filtre statut=completed ne retourne que les jobs terminés."""
        await _creer_job(db_session, statut="completed")
        await _creer_job(db_session, statut="pending")
        await _creer_job(db_session, statut="failed")

        async with client as c:
            resp = await c.get("/api/extract/jobs", params={"statut": "completed"})

        data = resp.json()
        assert data["total"] == 1
        assert data["jobs"][0]["statut"] == "completed"

    @pytest.mark.asyncio
    async def test_filtre_par_type(self, client, db_session):
        """Filtre type=rapport ne retourne que les jobs de rapport."""
        await _creer_job(db_session, type_="extraction")
        await _creer_job(db_session, type_="rapport")
        await _creer_job(db_session, type_="rapport")

        async with client as c:
            resp = await c.get("/api/extract/jobs", params={"type": "rapport"})

        data = resp.json()
        assert data["total"] == 2
        assert all(j["type"] == "rapport" for j in data["jobs"])

    @pytest.mark.asyncio
    async def test_limite_resultats(self, client, db_session):
        """Le paramètre limit borne le nombre de résultats retournés."""
        for _ in range(5):
            await _creer_job(db_session)

        async with client as c:
            resp = await c.get("/api/extract/jobs", params={"limit": 3})

        assert len(resp.json()["jobs"]) == 3

    @pytest.mark.asyncio
    async def test_structure_job(self, client, db_session):
        """Chaque job a les champs requis."""
        await _creer_job(db_session)

        async with client as c:
            resp = await c.get("/api/extract/jobs")

        job = resp.json()["jobs"][0]
        assert {"id", "type", "statut", "document_id", "erreur", "created_at"}.issubset(job.keys())

    @pytest.mark.asyncio
    async def test_ordre_decroissant(self, client, db_session):
        """Les jobs sont retournés du plus récent au plus ancien."""
        import asyncio
        job1 = await _creer_job(db_session, statut="completed")
        await asyncio.sleep(0.01)
        job2 = await _creer_job(db_session, statut="pending")

        async with client as c:
            resp = await c.get("/api/extract/jobs")

        jobs = resp.json()["jobs"]
        # Le plus récent (job2) doit être en premier
        assert jobs[0]["id"] == str(job2.id)
        assert jobs[1]["id"] == str(job1.id)
