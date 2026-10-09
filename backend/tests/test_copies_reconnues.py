"""
Tests — les copies de fichiers ne sont plus recomptées à chaque synchro
======================================================================
09/10/2026 : un fichier dont le contenu était déjà indexé ailleurs était reconnu puis sauté SANS
que son emplacement soit enregistré. Chaque synchro le redécouvrait, le retéléchargeait et le
recomptait « nouveau » (6 692 fichiers toutes les heures). Et dès qu'un contenu existait en deux
fiches, la recherche par empreinte plantait (53 échecs par passage).

Plan : docs/plan-copies-reconnues.md.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from models.document import Document
from models.metadata import MetadonneeIA
from services import sync_service
from services.extraction import TEXTE_MAX, ExtractionService, _contenu_tika
from utils.hash_utils import compute_sha256

CONTENU = b"%PDF-1.4 attestation de regularite fiscale"


@pytest.fixture(autouse=True)
def _ia_hors_ligne():
    with patch("services.runtime_config.model_candidates", new=AsyncMock(return_value=["test-model"])):
        yield


@pytest.fixture
def fichier(tmp_path):
    f = tmp_path / "attestation.pdf"
    f.write_bytes(CONTENU)
    return f


@pytest.fixture
def service(mock_tika, mock_ollama, mock_embedding_service):
    return ExtractionService(mock_tika, mock_ollama, mock_embedding_service)


async def _indexe(db, chemin: str, fichier, *, statut="enriched", categorie="attestation", doublon_de=None) -> Document:
    """Une fiche déjà en base portant le contenu de `fichier`."""
    doc = Document(chemin=chemin, nom=chemin.rsplit("/", 1)[-1], extension="pdf",
                   hash_sha256=compute_sha256(fichier), taille_octets=len(CONTENU), statut=statut,
                   texte_extrait="Attestation de régularité fiscale.", tika_metadata={"dc:format": "pdf"},
                   antivirus="sain", doublon_de=doublon_de)
    db.add(doc)
    await db.flush()
    if categorie:
        db.add(MetadonneeIA(document_id=doc.id, categorie=categorie, tags=["fiscal"], resume="Une attestation."))
        await db.flush()
    return doc


async def _fiches(db) -> list[Document]:
    return list((await db.execute(select(Document).order_by(Document.chemin))).scalars().all())


@pytest.mark.asyncio
async def test_une_copie_est_enregistree_sans_tika_ni_ia(db_session, service, fichier, mock_tika,
                                                        mock_ollama, mock_embedding_service):
    original = await _indexe(db_session, "smb://nas/home/A/attestation.pdf", fichier)
    mtime = datetime(2026, 9, 1, tzinfo=timezone.utc)

    doc_id = await service.process_file(fichier, source="watch", db=db_session,
                                        chemin_logique="smb://nas/home/B/copie.pdf", mtime_fichier=mtime)

    copie = await db_session.get(Document, uuid.UUID(doc_id))
    assert copie.id != original.id and copie.doublon_de == original.id
    assert (copie.chemin, copie.nom, copie.statut) == ("smb://nas/home/B/copie.pdf", "copie.pdf", "enriched")
    assert copie.texte_extrait == original.texte_extrait
    meta = (await db_session.execute(select(MetadonneeIA).where(MetadonneeIA.document_id == copie.id))).scalar_one()
    assert (meta.categorie, meta.tags, meta.resume) == ("attestation", ["fiscal"], "Une attestation.")
    mock_tika.extract_metadata.assert_not_awaited()
    mock_ollama.generate.assert_not_awaited()
    mock_embedding_service.embed_document.assert_not_awaited()      # la recherche garde l'original seul


@pytest.mark.asyncio
async def test_un_contenu_deja_en_deux_fiches_ne_fait_plus_planter(db_session, service, fichier):
    """Avant : `scalar_one_or_none` → « Multiple rows were found », 53 échecs par synchro."""
    original = await _indexe(db_session, "smb://nas/home/A/attestation.pdf", fichier)
    await _indexe(db_session, "smb://nas/home/B/copie.pdf", fichier, doublon_de=original.id)

    doc_id = await service.process_file(fichier, source="watch", db=db_session,
                                        chemin_logique="smb://nas/home/C/encore.pdf")

    fiches = await _fiches(db_session)
    assert len(fiches) == 3
    assert next(f for f in fiches if str(f.id) == doc_id).doublon_de == original.id      # jamais une copie de copie


@pytest.mark.asyncio
async def test_le_meme_emplacement_n_est_pas_copie_une_seconde_fois(db_session, service, fichier):
    """C'est ce qui arrête le recomptage : à la synchro suivante, plus rien n'est créé."""
    await _indexe(db_session, "smb://nas/home/A/attestation.pdf", fichier)
    premier = await service.process_file(fichier, source="watch", db=db_session,
                                         chemin_logique="smb://nas/home/B/copie.pdf")
    second = await service.process_file(fichier, source="watch", db=db_session,
                                        chemin_logique="smb://nas/home/B/copie.pdf")
    assert premier == second and len(await _fiches(db_session)) == 2


@pytest.mark.asyncio
async def test_un_depot_manuel_garde_son_dedoublonnage(db_session, service, fichier):
    original = await _indexe(db_session, "smb://nas/home/A/attestation.pdf", fichier)
    doc_id = await service.process_file(fichier, source="upload", db=db_session)
    assert doc_id == str(original.id) and len(await _fiches(db_session)) == 1


@pytest.mark.asyncio
async def test_on_ne_copie_pas_un_echec(db_session, service, fichier, mock_tika):
    """Seule une fiche en erreur porte ce contenu : le fichier est traité normalement."""
    await _indexe(db_session, "smb://nas/home/A/attestation.pdf", fichier, statut="error", categorie=None)

    doc_id = await service.process_file(fichier, source="watch", db=db_session,
                                        chemin_logique="smb://nas/home/B/copie.pdf")

    nouveau = next(f for f in await _fiches(db_session) if str(f.id) == doc_id)
    assert nouveau.doublon_de is None and nouveau.statut == "enriched"
    mock_tika.extract_metadata.assert_awaited_once()


def test_un_texte_geant_est_tronque_et_le_dit():
    """1,8 Mo de texte faisait déborder la colonne tsvector : le document n'était jamais indexé."""
    metadata = {"tk:content": "A1B2 " * 400_000}                    # 2 000 000 caractères
    texte = _contenu_tika(metadata)
    assert len(texte) == TEXTE_MAX
    assert metadata["matotheque:texte_tronque"] == {"longueur_origine": 2_000_000, "conserve": TEXTE_MAX}


def test_un_long_rapport_n_est_pas_touche():
    metadata = {"tk:content": "mot " * 100_000}                     # 400 000 caractères
    assert len(_contenu_tika(metadata)) == 400_000
    assert "matotheque:texte_tronque" not in metadata


@pytest.mark.asyncio
async def test_le_recap_de_synchro_distingue_copies_et_nouveautes():
    src = SimpleNamespace(type="local", chemin_base="/data", libelle="Test")
    distants = {f"/d{i}.pdf": {"chemin": f"/d{i}.pdf", "rel": f"/d{i}.pdf", "taille": 1, "mtime": None}
                for i in range(10)}

    async def traiter(service, src, partage, secret, entree, taille_max):
        return entree["chemin"] not in ("/d0.pdf", "/d1.pdf")        # 8 copies, 2 vraies nouveautés

    with patch.object(sync_service, "_lister_local", AsyncMock(return_value=distants)), \
         patch.object(sync_service, "_lister_index", AsyncMock(return_value={})), \
         patch.object(sync_service, "_appliquer_deplacements", AsyncMock(return_value=0)), \
         patch.object(sync_service, "_marquer_absents", AsyncMock(return_value=0)), \
         patch.object(sync_service, "_reactiver", AsyncMock(return_value=0)), \
         patch.object(sync_service, "_traiter_fichier", side_effect=traiter), \
         patch("routers.sources._extraction_service", return_value=object()):
        recap = await sync_service.synchroniser(src, None, "/", None)

    assert (recap["nouveaux"], recap["copies"], recap["traites"], recap["echecs"]) == (2, 8, 10, 0)
