"""
Tests d'intégration — routers/documents.py
===========================================
Couvre les endpoints CRUD du router documents :
  GET    /documents              → liste paginée + filtres
  GET    /documents/stats        → statistiques globales
  GET    /documents/{id}         → détail + métadonnées IA
  GET    /documents/{id}/text    → texte extrait brut
  PATCH  /documents/{id}/metadata → mise à jour tags/catégorie
  GET    /documents/{id}/versions → historique versions
  DELETE /documents/{id}         → suppression
"""

import uuid
from datetime import datetime, timezone

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


async def _creer_document(db_session, **kwargs):
    """Crée et flush un document de test. Retourne l'instance Document."""
    from models.document import Document
    defaults = dict(
        nom="test.pdf",
        chemin="/documents/test.pdf",
        extension="pdf",
        hash_sha256="abc123" + "0" * 58,
        taille_octets=50_000,
        statut="enriched",
        source="upload",
        texte_extrait="Texte de test du document.",
    )
    defaults.update(kwargs)
    doc = Document(**defaults)
    db_session.add(doc)
    await db_session.flush()
    return doc


async def _creer_meta(db_session, document_id, **kwargs):
    """Crée et flush des métadonnées IA pour un document."""
    from models.metadata import MetadonneeIA
    defaults = dict(
        document_id=document_id,
        categorie="rapport",
        sous_categorie="annuel",
        tags=["annuel", "2025"],
        resume="Résumé du document de test.",
        langue="fr",
        entites={"personnes": ["Alice"], "dates": ["2025-01-01"], "lieux": [], "organisations": []},
        mots_cles=["test", "docflow"],
        niveau_confidentialite="normal",
        modele_utilise="mistral:latest",
    )
    defaults.update(kwargs)
    meta = MetadonneeIA(**defaults)
    db_session.add(meta)
    await db_session.flush()
    return meta


# ─── GET /documents ───────────────────────────────────────────────────────────

class TestListDocuments:
    @pytest.mark.asyncio
    async def test_liste_vide_par_defaut(self, client):
        """Sans documents en DB, retourne une liste vide."""
        async with client as c:
            resp = await c.get("/api/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["documents"] == []
        assert data["page"] == 1

    @pytest.mark.asyncio
    async def test_liste_avec_documents(self, client, db_session):
        """Avec des documents en DB, la liste est remplie."""
        await _creer_document(db_session, nom="doc1.pdf", hash_sha256="aaa" + "0" * 61)
        await _creer_document(db_session, nom="doc2.pdf", hash_sha256="bbb" + "0" * 61)

        async with client as c:
            resp = await c.get("/api/documents")
        data = resp.json()
        assert data["total"] == 2
        assert len(data["documents"]) == 2

    @pytest.mark.asyncio
    async def test_filtre_par_statut(self, client, db_session):
        """Le filtre statut=pending ne retourne que les documents en attente."""
        await _creer_document(db_session, nom="enrichi.pdf", statut="enriched", hash_sha256="aaa" + "0" * 61)
        await _creer_document(db_session, nom="pending.pdf", statut="pending", hash_sha256="bbb" + "0" * 61)

        async with client as c:
            resp = await c.get("/api/documents", params={"statut": "pending"})
        data = resp.json()
        assert data["total"] == 1
        assert data["documents"][0]["nom"] == "pending.pdf"

    @pytest.mark.asyncio
    async def test_filtre_par_extension(self, client, db_session):
        """Le filtre extension retourne uniquement les documents de ce type."""
        await _creer_document(db_session, nom="doc.pdf", extension="pdf", hash_sha256="aaa" + "0" * 61)
        await _creer_document(db_session, nom="doc.docx", extension="docx", hash_sha256="bbb" + "0" * 61)

        async with client as c:
            resp = await c.get("/api/documents", params={"extension": "docx"})
        data = resp.json()
        assert data["total"] == 1
        assert data["documents"][0]["extension"] == "docx"

    @pytest.mark.asyncio
    async def test_filtre_par_nom(self, client, db_session):
        """Le filtre q=... fait une recherche partielle sur le nom."""
        await _creer_document(db_session, nom="rapport_annuel.pdf", hash_sha256="aaa" + "0" * 61)
        await _creer_document(db_session, nom="facture_mars.pdf", hash_sha256="bbb" + "0" * 61)

        async with client as c:
            resp = await c.get("/api/documents", params={"q": "rapport"})
        data = resp.json()
        assert data["total"] == 1
        assert "rapport" in data["documents"][0]["nom"]

    @pytest.mark.asyncio
    async def test_pagination_page_size(self, client, db_session):
        """La pagination page_size limite correctement le nombre de résultats."""
        for i in range(5):
            await _creer_document(db_session, nom=f"doc_{i}.pdf", hash_sha256=f"hash{i:064d}")

        async with client as c:
            resp = await c.get("/api/documents", params={"page_size": 3})
        data = resp.json()
        assert len(data["documents"]) == 3
        assert data["pages"] == 2
        assert data["total"] == 5

    @pytest.mark.asyncio
    async def test_structure_reponse(self, client, db_session):
        """Chaque document retourné a les champs attendus."""
        await _creer_document(db_session)

        async with client as c:
            resp = await c.get("/api/documents")
        doc = resp.json()["documents"][0]
        champs_requis = {"id", "nom", "chemin", "extension", "taille_octets", "statut", "source", "hash_sha256"}
        assert champs_requis.issubset(doc.keys())


# ─── GET /documents/stats ─────────────────────────────────────────────────────

class TestDocumentStats:
    @pytest.mark.asyncio
    async def test_stats_base_vide(self, client):
        """Sans documents, les stats retournent des zéros."""
        async with client as c:
            resp = await c.get("/api/documents/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_documents"] == 0
        assert data["taille_totale_octets"] == 0

    @pytest.mark.asyncio
    async def test_stats_avec_documents(self, client, db_session):
        """Les stats agrègent correctement le total et la taille."""
        await _creer_document(db_session, taille_octets=1000, statut="enriched", hash_sha256="aaa" + "0" * 61)
        await _creer_document(db_session, taille_octets=2000, statut="pending", hash_sha256="bbb" + "0" * 61)

        async with client as c:
            resp = await c.get("/api/documents/stats")
        data = resp.json()
        assert data["total_documents"] == 2
        assert data["taille_totale_octets"] == 3000
        assert "par_statut" in data
        assert "categories" in data

    @pytest.mark.asyncio
    async def test_stats_endpoint_avant_id(self, client):
        """
        /documents/stats NE doit PAS être confondu avec /documents/{id}.
        L'endpoint stats doit retourner 200, pas 400/404.
        """
        async with client as c:
            resp = await c.get("/api/documents/stats")
        # Pas de 400 "ID de document invalide"
        assert resp.status_code == 200
        assert "total_documents" in resp.json()


# ─── GET /documents/{id} ─────────────────────────────────────────────────────

class TestGetDocument:
    @pytest.mark.asyncio
    async def test_document_existant(self, client, db_session):
        """Un document existant est retourné avec ses champs."""
        doc = await _creer_document(db_session, nom="rapport.pdf")

        async with client as c:
            resp = await c.get(f"/api/documents/{doc.id}")
        assert resp.status_code == 200
        assert resp.json()["nom"] == "rapport.pdf"

    @pytest.mark.asyncio
    async def test_document_avec_metadonnees(self, client, db_session):
        """Si des métadonnées IA existent, elles sont incluses dans la réponse."""
        doc = await _creer_document(db_session)
        await _creer_meta(db_session, document_id=doc.id)

        async with client as c:
            resp = await c.get(f"/api/documents/{doc.id}")
        data = resp.json()
        assert data["metadonnees_ia"] is not None
        assert data["metadonnees_ia"]["categorie"] == "rapport"
        assert "annuel" in data["metadonnees_ia"]["tags"]

    @pytest.mark.asyncio
    async def test_document_sans_metadonnees(self, client, db_session):
        """Sans métadonnées, le champ metadonnees_ia est null."""
        doc = await _creer_document(db_session)

        async with client as c:
            resp = await c.get(f"/api/documents/{doc.id}")
        assert resp.json()["metadonnees_ia"] is None

    @pytest.mark.asyncio
    async def test_document_inexistant(self, client):
        """Un UUID inexistant retourne 404."""
        async with client as c:
            resp = await c.get(f"/api/documents/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_id_invalide(self, client):
        """Un ID non-UUID retourne 400."""
        async with client as c:
            resp = await c.get("/api/documents/pas-un-uuid")
        assert resp.status_code == 400


# ─── GET /documents/{id}/text ─────────────────────────────────────────────────

class TestGetDocumentText:
    @pytest.mark.asyncio
    async def test_texte_extrait(self, client, db_session):
        """Retourne le texte extrait avec le nombre de caractères."""
        doc = await _creer_document(db_session, texte_extrait="Voici le contenu du document.")

        async with client as c:
            resp = await c.get(f"/api/documents/{doc.id}/text")
        assert resp.status_code == 200
        data = resp.json()
        assert data["texte"] == "Voici le contenu du document."
        assert data["nb_caracteres"] == len("Voici le contenu du document.")
        assert data["document_id"] == str(doc.id)

    @pytest.mark.asyncio
    async def test_texte_vide(self, client, db_session):
        """Un document sans texte retourne une chaîne vide (pas d'erreur)."""
        doc = await _creer_document(db_session, texte_extrait=None)

        async with client as c:
            resp = await c.get(f"/api/documents/{doc.id}/text")
        assert resp.status_code == 200
        assert resp.json()["texte"] == ""
        assert resp.json()["nb_caracteres"] == 0

    @pytest.mark.asyncio
    async def test_document_inexistant(self, client):
        """Document introuvable → 404."""
        async with client as c:
            resp = await c.get(f"/api/documents/{uuid.uuid4()}/text")
        assert resp.status_code == 404


# ─── PATCH /documents/{id}/metadata ──────────────────────────────────────────

class TestPatchMetadata:
    @pytest.mark.asyncio
    async def test_mise_a_jour_tags(self, client, db_session):
        """PATCH /metadata met à jour les tags correctement."""
        doc = await _creer_document(db_session)
        await _creer_meta(db_session, document_id=doc.id, tags=["ancien"])

        async with client as c:
            resp = await c.patch(f"/api/documents/{doc.id}/metadata", json={
                "tags": ["nouveau", "test"],
            })
        assert resp.status_code == 200
        assert resp.json()["tags"] == ["nouveau", "test"]

    @pytest.mark.asyncio
    async def test_mise_a_jour_categorie(self, client, db_session):
        """PATCH /metadata met à jour la catégorie."""
        doc = await _creer_document(db_session)
        await _creer_meta(db_session, document_id=doc.id, categorie="rapport")

        async with client as c:
            resp = await c.patch(f"/api/documents/{doc.id}/metadata", json={
                "categorie": "facture",
            })
        assert resp.status_code == 200
        assert resp.json()["categorie"] == "facture"

    @pytest.mark.asyncio
    async def test_mise_a_jour_resume(self, client, db_session):
        """PATCH /metadata met à jour le résumé."""
        doc = await _creer_document(db_session)
        await _creer_meta(db_session, document_id=doc.id, resume="Ancien résumé")

        async with client as c:
            resp = await c.patch(f"/api/documents/{doc.id}/metadata", json={
                "resume": "Nouveau résumé mis à jour",
            })
        assert resp.status_code == 200
        assert resp.json()["resume"] == "Nouveau résumé mis à jour"

    @pytest.mark.asyncio
    async def test_sans_metadonnees_existantes(self, client, db_session):
        """Sans métadonnées IA, le PATCH retourne 404."""
        doc = await _creer_document(db_session)

        async with client as c:
            resp = await c.patch(f"/api/documents/{doc.id}/metadata", json={"tags": ["test"]})
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_champs_non_fournis_non_modifies(self, client, db_session):
        """Un champ absent du PATCH ne doit pas être écrasé."""
        doc = await _creer_document(db_session)
        await _creer_meta(db_session, document_id=doc.id, categorie="rapport", tags=["tag1"])

        async with client as c:
            # PATCH seulement les tags
            resp = await c.patch(f"/api/documents/{doc.id}/metadata", json={
                "tags": ["nouveau_tag"],
            })
        data = resp.json()
        # La catégorie ne doit pas avoir changé
        assert data["categorie"] == "rapport"
        assert data["tags"] == ["nouveau_tag"]


# ─── GET /documents/{id}/versions ────────────────────────────────────────────

class TestGetVersions:
    @pytest.mark.asyncio
    async def test_sans_versions(self, client, db_session):
        """Un nouveau document n'a pas de versions."""
        doc = await _creer_document(db_session)

        async with client as c:
            resp = await c.get(f"/api/documents/{doc.id}/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"] == str(doc.id)
        assert data["versions"] == []

    @pytest.mark.asyncio
    async def test_avec_versions(self, client, db_session):
        """Les versions sont retournées dans l'ordre décroissant."""
        from models.version import Version
        doc = await _creer_document(db_session)
        v1 = Version(document_id=doc.id, numero_version=1, hash_sha256="hash1", taille_octets=1000)
        v2 = Version(document_id=doc.id, numero_version=2, hash_sha256="hash2", taille_octets=1200)
        db_session.add_all([v1, v2])
        await db_session.flush()

        async with client as c:
            resp = await c.get(f"/api/documents/{doc.id}/versions")
        data = resp.json()
        assert len(data["versions"]) == 2
        # Ordre décroissant (v2 d'abord)
        assert data["versions"][0]["numero_version"] == 2

    @pytest.mark.asyncio
    async def test_document_inexistant(self, client):
        """Document introuvable → 404."""
        async with client as c:
            resp = await c.get(f"/api/documents/{uuid.uuid4()}/versions")
        assert resp.status_code == 404


# ─── DELETE /documents/{id} ───────────────────────────────────────────────────

class TestDeleteDocument:
    @pytest.mark.asyncio
    async def test_suppression_reussie(self, client, db_session):
        """Un document existant est supprimé avec confirmation."""
        doc = await _creer_document(db_session, nom="a_supprimer.pdf")

        async with client as c:
            resp = await c.delete(f"/api/documents/{doc.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert str(doc.id) in data["document_id"]
        assert "a_supprimer" in data["message"]

    @pytest.mark.asyncio
    async def test_document_absent_apres_suppression(self, client, db_session):
        """Après suppression, GET retourne 404."""
        doc = await _creer_document(db_session)

        async with client as c:
            await c.delete(f"/api/documents/{doc.id}")
            resp = await c.get(f"/api/documents/{doc.id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_suppression_document_inexistant(self, client):
        """Supprimer un document inexistant → 404."""
        async with client as c:
            resp = await c.delete(f"/api/documents/{uuid.uuid4()}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_id_invalide(self, client):
        """ID non-UUID → 400."""
        async with client as c:
            resp = await c.delete("/api/documents/pas-un-uuid")
        assert resp.status_code == 400
