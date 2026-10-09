"""
Tests — le texte renvoyé par Tika 4 est lu, et le texte « dormant » est rattrapé
==============================================================================
`apache/tika:latest-full` est passé en 4.0.0 : `/rmeta` range désormais le texte sous
`tk:content` (avant : `X-TIKA:content`). Le pipeline ne lisait que l'ancienne clé → documents
« extraits » à vide, jamais analysés par l'IA (457 en prod, 09/10/2026) — alors que leur texte
était bien là, rangé dans `tika_metadata`.
"""

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from models.document import Document
from models.job import Job
from services.extraction import ExtractionService, _contenu_tika

TEXTE = "RELEVES D'IDENTITE BANCAIRE — titulaire du compte, IBAN, BIC."


@pytest.fixture(autouse=True)
def _ia_hors_ligne():
    with patch("services.runtime_config.model_candidates", new=AsyncMock(return_value=["test-model"])):
        yield


def _doc(nom: str, **champs) -> Document:
    return Document(chemin=f"smb://nas/partage/{nom}", nom=nom, extension="pdf",
                    hash_sha256=f"hash-{nom}", taille_octets=10, statut="extracted", **champs)


@pytest.mark.parametrize("cle", ["X-TIKA:content", "tk:content"])
def test_le_texte_est_lu_sous_les_deux_cles(cle):
    metadata = {cle: f"\n\n\n{TEXTE}", "Content-Type": "application/pdf"}
    assert _contenu_tika(metadata).strip() == TEXTE
    assert metadata == {"Content-Type": "application/pdf"}      # retiré : pas de texte en double


def test_sans_contenu_le_texte_est_vide():
    assert _contenu_tika({"Content-Type": "image/jpeg"}) == ""
    assert _contenu_tika({"tk:content": "\n\n \n"}) == ""


@pytest.mark.asyncio
async def test_un_fichier_extrait_par_tika_4_est_analyse(db_session, mock_tika, mock_ollama,
                                                        mock_embedding_service, tmp_path):
    mock_tika.extract_metadata = AsyncMock(
        side_effect=lambda *_a, **_k: [{"tk:content": TEXTE, "Content-Type": "application/pdf"}])
    fichier = tmp_path / "C03_RIB.pdf"
    fichier.write_bytes(b"%PDF-1.4 contenu")

    service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
    await service.process_file(fichier, source="watch", db=db_session)

    doc = (await db_session.execute(select(Document))).scalar_one()
    assert doc.texte_extrait == TEXTE and doc.statut == "enriched"
    assert "tk:content" not in doc.tika_metadata
    mock_embedding_service.embed_document.assert_awaited_once()


@pytest.mark.asyncio
async def test_le_texte_dormant_est_repris_puis_analyse(db_session, mock_tika, mock_ollama,
                                                       mock_embedding_service):
    doc = _doc("C03_RIB.pdf", texte_extrait="", tika_metadata={"tk:content": TEXTE, "dc:format": "application/pdf"})
    db_session.add(doc)
    await db_session.flush()

    service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
    assert await service.reprendre_contenu_stocke(doc, db_session) is True

    assert doc.texte_extrait == TEXTE and doc.statut == "enriched"
    assert doc.tika_metadata == {"dc:format": "application/pdf"}
    mock_tika.extract_metadata.assert_not_awaited()             # ni NAS ni Tika sollicités
    mock_embedding_service.embed_document.assert_awaited_once()


@pytest.mark.asyncio
async def test_rien_a_reprendre_ne_touche_a_rien(db_session, mock_tika, mock_ollama, mock_embedding_service):
    deja = _doc("deja.pdf", texte_extrait="texte déjà là", tika_metadata={"tk:content": TEXTE})
    image = _doc("photo.pdf", texte_extrait="", tika_metadata={"Content-Type": "image/jpeg"})
    db_session.add_all([deja, image])
    await db_session.flush()

    service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
    assert await service.reprendre_contenu_stocke(deja, db_session) is None
    assert await service.reprendre_contenu_stocke(image, db_session) is None
    assert deja.texte_extrait == "texte déjà là"
    mock_ollama.generate.assert_not_awaited()


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
async def test_le_rattrapage_ne_vise_que_le_texte_dormant(client, db_session):
    db_session.add_all([
        _doc("dormant-1.pdf", texte_extrait="", tika_metadata={"tk:content": TEXTE}),
        _doc("dormant-2.pdf", texte_extrait=None, tika_metadata={"X-TIKA:content": TEXTE}),
        _doc("sain.pdf", texte_extrait="du texte", tika_metadata={"tk:content": TEXTE}),
        _doc("photo.pdf", texte_extrait="", tika_metadata={"Content-Type": "image/jpeg"}),
        _doc("sans-meta.pdf", texte_extrait="", tika_metadata=None),
    ])
    await db_session.flush()

    async with client as c:
        assert (await c.get("/api/documents/maintenance/texte-dormant")).json() == {"a_reprendre": 2}
        premier = (await c.post("/api/documents/maintenance/reprise-texte")).json()
        second = (await c.post("/api/documents/maintenance/reprise-texte")).json()

    assert premier["enqueued"] == 2 and second["enqueued"] == 0      # un second clic ne double rien
    jobs = (await db_session.execute(select(Job))).scalars().all()
    assert {j.type for j in jobs} == {"reprise_texte"}
    assert sorted(j.parametres["cible"] for j in jobs) == ["dormant-1.pdf", "dormant-2.pdf"]
