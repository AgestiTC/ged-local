"""
Fichiers remplis de zéros (relevé du 19/11/2026) : signalés en erreur, sans appel à Tika.
=========================================================================================
Fichiers fictifs écrits dans `tmp_path` uniquement.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base
from models.document import Document
from models.job import Job
from services.extraction import ExtractionService, fichier_entierement_nul, message_fichier_nul


@pytest_asyncio.fixture
async def mem_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})
    with patch("models.embedding.HALFVEC", lambda dim: None):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def tika():
    t = MagicMock()
    t.extract_metadata = AsyncMock(return_value=[{"X-TIKA:content": "Texte fictif.",
                                                  "Content-Type": "application/pdf"}])
    return t


@pytest.fixture
def nul(tmp_path):
    f = tmp_path / "facture-fictive.pdf"
    f.write_bytes(b"\x00" * 4096)
    return f


class TestDetection:
    def test_que_des_zeros(self, nul):
        assert fichier_entierement_nul(nul)

    def test_fichier_de_taille_zero_n_est_pas_signale(self, tmp_path):
        f = tmp_path / "vide.txt"
        f.write_bytes(b"")
        assert not fichier_entierement_nul(f)

    def test_texte_utf16_n_est_pas_signale(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_bytes("Notes fictives".encode("utf-16-le"))
        assert not fichier_entierement_nul(f)

    def test_un_seul_octet_non_nul_apres_le_premier_bloc(self, tmp_path):
        f = tmp_path / "presque.bin"
        f.write_bytes(b"\x00" * (3 << 20) + b"x")
        assert not fichier_entierement_nul(f)

    def test_message_lisible(self):
        m = message_fichier_nul(1234567)
        assert "que des zéros" in m and "1 234 567 octets" in m and "Restaurez" in m


class TestPipeline:
    @pytest.mark.asyncio
    async def test_indexation_signale_en_erreur_sans_tika_ni_ia(self, tika, mem_db, nul):
        service = ExtractionService(tika, MagicMock(), MagicMock())
        await service.process_file(nul, source="upload", db=mem_db)

        doc = (await mem_db.execute(select(Document))).scalar_one()
        assert doc.statut == "error" and "que des zéros" in doc.erreur
        assert "4 096 octets" in doc.erreur
        tika.extract_metadata.assert_not_awaited()
        assert (await mem_db.execute(select(Job))).scalars().all() == []

    @pytest.mark.asyncio
    async def test_fichier_sain_inchange(self, tika, mem_db, tmp_path):
        f = tmp_path / "sain.pdf"
        f.write_bytes(b"%PDF-1.4 contenu fictif")
        await ExtractionService(tika, MagicMock(), MagicMock()).process_file(f, source="upload", db=mem_db)
        doc = (await mem_db.execute(select(Document))).scalar_one()
        assert doc.statut != "error" and doc.erreur is None
        tika.extract_metadata.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_relecture_d_un_document_existant(self, tika, mem_db, nul):
        # Cas du stock : document déjà « extracted » sans texte, relu par `ia_contenu`.
        doc = Document(chemin=str(nul), nom=nul.name, extension="pdf", hash_sha256="x" * 64,
                       statut="extracted", texte_extrait="")
        mem_db.add(doc)
        await mem_db.flush()

        a_du_texte = await ExtractionService(tika, MagicMock(), MagicMock()).extraire_contenu(doc, nul, mem_db)

        assert a_du_texte is False
        assert doc.statut == "error" and "que des zéros" in doc.erreur
        assert doc.taille_octets == 4096
        tika.extract_metadata.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fichier_restaure_redevient_normal(self, tika, mem_db, nul):
        doc = Document(chemin=str(nul), nom=nul.name, extension="pdf", hash_sha256="x" * 64,
                       statut="error", erreur=message_fichier_nul(4096))
        mem_db.add(doc)
        await mem_db.flush()
        nul.write_bytes(b"%PDF-1.4 contenu restaure fictif")

        a_du_texte = await ExtractionService(tika, MagicMock(), MagicMock()).extraire_contenu(doc, nul, mem_db)

        assert a_du_texte is True
        assert doc.statut == "extracted" and doc.erreur is None
