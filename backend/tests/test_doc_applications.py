"""
Tests — plan « Recevoir la documentation des autres applications »
==================================================================
Étape 1 : règles de classement par emplacement (choix du préfixe, tags, classement fixe).
Étape 2 : versions — classement conservé, texte des versions remplacées archivé (5 au plus).
Étape 3 : en-tête des Markdown (appli / version / titre).
Étape 4 : regroupement par application pour la page « Documentation des applications ».
"""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from models import Base
from models.document import Document
from models.metadata import MetadonneeIA
from models.regle_classement import RegleClassement
from models.version import Version
from routers.doc_applications import regrouper
from services import front_matter, regles_classement
from services.extraction import ExtractionService, lire_archive

PREFIXE = "smb://192.168.42.200/Partage-Nas-Mato/[GED]/Docs-applications/"
CHEMIN_GUIDE = PREFIXE + "composeur-yealink/guide-composeur-yealink.md"


def _regle(prefixe=PREFIXE, classement="fixe", actif=True, **k):
    return RegleClassement(libelle=k.pop("libelle", "Docs des applications"), prefixe_chemin=prefixe,
                           categorie=k.pop("categorie", "Documentation"),
                           sous_categorie=k.pop("sous_categorie", "Applications"),
                           tags=k.pop("tags", ["doc-appli"]), tag_depuis_sous_dossier=k.pop("tag_depuis_sous_dossier", True),
                           classement=classement, actif=actif)


# ─── Étape 1 — fonctions pures ────────────────────────────────────────────────

class TestReglesPures:
    def test_prefixe_le_plus_long_gagne(self):
        large = _regle(prefixe="smb://192.168.42.200/Partage-Nas-Mato/", libelle="large")
        precis = _regle(libelle="précis")
        assert regles_classement.choisir_regle(CHEMIN_GUIDE, [large, precis]).libelle == "précis"

    def test_regle_inactive_ou_hors_prefixe_ignoree(self):
        assert regles_classement.choisir_regle(CHEMIN_GUIDE, [_regle(actif=False)]) is None
        assert regles_classement.choisir_regle("smb://autre/x.pdf", [_regle()]) is None
        assert regles_classement.choisir_regle(None, [_regle()]) is None

    def test_sous_dossier_et_tag(self):
        assert regles_classement.sous_dossier(CHEMIN_GUIDE, PREFIXE) == "composeur-yealink"
        assert regles_classement.sous_dossier(PREFIXE + "a-la-racine.md", PREFIXE) is None
        assert regles_classement.en_tag("Composeur Yéalink T54W") == "composeur-yealink-t54w"

    def test_tags_regle_ajoute_le_sous_dossier_sans_doublon(self):
        assert regles_classement.tags_regle(_regle(), CHEMIN_GUIDE) == ["doc-appli", "composeur-yealink"]
        r = _regle(tags=["composeur-yealink"])
        assert regles_classement.tags_regle(r, CHEMIN_GUIDE) == ["composeur-yealink"]
        r = _regle(tag_depuis_sous_dossier=False)
        assert regles_classement.tags_regle(r, CHEMIN_GUIDE) == ["doc-appli"]

    def test_classement_fixe_ignore_categorie_et_tags_de_l_ia(self):
        ia = {"categorie": "rapport", "sous_categorie": "test", "tags": ["ia1"]}
        out = regles_classement.classement_fixe(_regle(), CHEMIN_GUIDE, ia, "md")
        assert out == {"categorie": "Documentation", "sous_categorie": "Applications",
                       "tags": ["md", "doc-appli", "composeur-yealink"]}

    def test_classement_fixe_sans_categorie_reprend_celle_de_l_ia(self):
        out = regles_classement.classement_fixe(_regle(categorie=None, sous_categorie=None), CHEMIN_GUIDE,
                                                {"categorie": "rapport", "sous_categorie": "x"}, "")
        assert out["categorie"] == "rapport" and out["sous_categorie"] == "x"


# ─── Étape 3 — en-tête Markdown (pur) ─────────────────────────────────────────

class TestFrontMatter:
    def test_en_tete_lu_et_retire_du_corps(self):
        fm, corps = front_matter.lire("---\nappli: composeur-yealink\nversion: \"1.5.18\"\n"
                                      "titre: Guide du composeur\nautre: ignorée\n---\n\n# Titre\nTexte")
        assert fm == {"appli": "composeur-yealink", "version": "1.5.18", "titre": "Guide du composeur"}
        assert corps == "# Titre\nTexte"

    def test_sans_en_tete_texte_inchange(self):
        assert front_matter.lire("# Titre\nTexte") == (None, "# Titre\nTexte")
        assert front_matter.lire("") == (None, "")

    def test_en_tete_non_conforme_ignore_sans_erreur(self):
        texte = "---\nappli composeur\n---\nCorps"
        assert front_matter.lire(texte) == (None, texte)
        non_ferme = "---\nappli: x\nCorps sans fin d'en-tête"
        assert front_matter.lire(non_ferme) == (None, non_ferme)

    def test_bom_et_valeurs_bornees(self):
        fm, _ = front_matter.lire("﻿---\ntitre: " + "x" * 500 + "\n---\n")
        assert len(fm["titre"]) == 200


# ─── Étape 4 — regroupement (pur) ─────────────────────────────────────────────

class TestRegroupement:
    def test_par_appli_avec_version_et_retard(self):
        maintenant = datetime(2026, 11, 16, tzinfo=timezone.utc)
        recent = SimpleNamespace(id="1", chemin=CHEMIN_GUIDE, nom="guide-composeur-yealink.md", statut="enriched",
                                 tika_metadata={"front_matter": {"titre": "Guide", "version": "1.5.18"}},
                                 date_modification_fichier=maintenant - timedelta(days=1), date_import=None)
        vieux = SimpleNamespace(id="2", chemin=PREFIXE + "vieille-appli/doc.pdf", nom="doc.pdf", statut="enriched",
                                tika_metadata=None, date_modification_fichier=maintenant - timedelta(days=200),
                                date_import=None)
        racine = SimpleNamespace(id="3", chemin=PREFIXE + "LISEZMOI.md", nom="LISEZMOI.md", statut="enriched",
                                 tika_metadata=None, date_modification_fichier=maintenant, date_import=None)
        applis = regrouper(_regle(), [recent, vieux, racine], {"1": 2}, maintenant)
        assert [a["appli"] for a in applis] == ["composeur-yealink", "vieille-appli"]
        yealink = applis[0]
        assert yealink["en_retard"] is False
        assert yealink["documents"][0] == {
            "id": "1", "nom": "guide-composeur-yealink.md", "titre": "Guide", "version": "1.5.18",
            "date_depot": (maintenant - timedelta(days=1)).isoformat(), "nb_versions": 3, "statut": "enriched"}
        assert applis[1]["en_retard"] is True


# ─── Intégration : pipeline d'extraction (SQLite en mémoire, Tika/Ollama simulés) ─

@pytest.fixture(autouse=True)
def _stub_model_candidates():
    with patch("services.runtime_config.model_candidates", new=AsyncMock(return_value=["test-model"])):
        yield


@pytest.fixture(autouse=True)
def _archives(tmp_path):
    with patch("services.extraction.settings.storage_versions", str(tmp_path / "versions")):
        yield


@pytest.fixture
def mock_tika():
    tika = MagicMock()
    tika.extract_metadata = AsyncMock(side_effect=lambda *_a, **_k: [{
        "X-TIKA:content": "Contenu extrait par Tika.", "Content-Type": "text/markdown"}])
    return tika


@pytest.fixture
def mock_ollama():
    ollama = MagicMock()
    ollama.generate = AsyncMock(return_value='{"categorie": "rapport", "sous_categorie": "test", '
                                             '"tags": ["ia1", "ia2"], "resume": "Résumé IA.", "langue": "fr", '
                                             '"entites": {}, "mots_cles": ["k"], "niveau_confidentialite": "normal"}')
    return ollama


@pytest.fixture
def mock_embeddings():
    e = MagicMock()
    e.embed_document = AsyncMock(return_value=1)
    return e


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


def _guide(tmp_path, version: str, corps: str = "Contenu du guide."):
    f = tmp_path / "guide-composeur-yealink.md"
    f.write_text(f"---\nappli: composeur-yealink\nversion: {version}\ntitre: Guide du composeur\n---\n"
                 f"# Guide\n{corps} (version {version})\n", encoding="utf-8")
    return f


async def _deposer(service, db, fichier, chemin=CHEMIN_GUIDE):
    return await service.process_file(fichier, source="watch", db=db, chemin_logique=chemin, differer_ia=False)


async def _fiche(db, doc_id) -> MetadonneeIA:
    return (await db.execute(select(MetadonneeIA).where(MetadonneeIA.document_id == uuid.UUID(doc_id)))).scalar_one()


class TestPipeline:
    @pytest.mark.asyncio
    async def test_regle_fixe_impose_categorie_et_tags(self, mock_tika, mock_ollama, mock_embeddings, mem_db, tmp_path):
        mem_db.add(_regle())
        await mem_db.flush()
        service = ExtractionService(mock_tika, mock_ollama, mock_embeddings)
        doc_id = await _deposer(service, mem_db, _guide(tmp_path, "1.5.17"))
        meta = await _fiche(mem_db, doc_id)
        assert (meta.categorie, meta.sous_categorie) == ("Documentation", "Applications")
        assert meta.tags == ["md", "doc-appli", "composeur-yealink"]
        assert meta.resume == "Résumé IA."              # l'IA garde le résumé

    @pytest.mark.asyncio
    async def test_hors_prefixe_comportement_inchange(self, mock_tika, mock_ollama, mock_embeddings, mem_db, tmp_path):
        mem_db.add(_regle())
        await mem_db.flush()
        service = ExtractionService(mock_tika, mock_ollama, mock_embeddings)
        doc_id = await _deposer(service, mem_db, _guide(tmp_path, "1"), chemin="smb://192.168.42.200/Autre/guide.md")
        meta = await _fiche(mem_db, doc_id)
        assert meta.categorie == "rapport"
        assert "ia1" in meta.tags and "doc-appli" not in meta.tags

    @pytest.mark.asyncio
    async def test_regle_ia_pose_puis_laisse_l_ia_classer(self, mock_tika, mock_ollama, mock_embeddings, mem_db, tmp_path):
        mem_db.add(_regle(classement="ia"))
        await mem_db.flush()
        service = ExtractionService(mock_tika, mock_ollama, mock_embeddings)
        doc_id = await _deposer(service, mem_db, _guide(tmp_path, "1"))
        meta = await _fiche(mem_db, doc_id)
        assert meta.categorie == "rapport"
        assert meta.tags[:3] == ["md", "doc-appli", "composeur-yealink"] and "ia1" in meta.tags

    @pytest.mark.asyncio
    async def test_en_tete_markdown(self, mock_tika, mock_ollama, mock_embeddings, mem_db, tmp_path):
        service = ExtractionService(mock_tika, mock_ollama, mock_embeddings)
        doc_id = await _deposer(service, mem_db, _guide(tmp_path, "1.5.18"))
        doc = await mem_db.get(Document, uuid.UUID(doc_id))
        assert doc.tika_metadata["front_matter"] == {"appli": "composeur-yealink", "version": "1.5.18",
                                                     "titre": "Guide du composeur"}
        assert doc.texte_extrait.startswith("# Guide") and "appli:" not in doc.texte_extrait
        assert "composeur-yealink" in (await _fiche(mem_db, doc_id)).tags

    @pytest.mark.asyncio
    async def test_trois_depots_meme_document_classement_garde_textes_relisibles(
            self, mock_tika, mock_ollama, mock_embeddings, mem_db, tmp_path):
        mem_db.add(_regle())
        await mem_db.flush()
        service = ExtractionService(mock_tika, mock_ollama, mock_embeddings)
        ids = {await _deposer(service, mem_db, _guide(tmp_path, v)) for v in ("1.5.16", "1.5.17", "1.5.18")}
        assert len(ids) == 1                                        # un seul document, pas trois
        doc_id = ids.pop()
        meta = await _fiche(mem_db, doc_id)
        assert meta.categorie == "Documentation" and meta.tags == ["md", "doc-appli", "composeur-yealink"]
        versions = (await mem_db.execute(select(Version).order_by(Version.numero_version))).scalars().all()
        assert [v.libelle for v in versions] == ["1.5.16", "1.5.17"]
        assert "version 1.5.16" in lire_archive(versions[0].chemin_archive)
        assert "version 1.5.17" in lire_archive(versions[1].chemin_archive)

    @pytest.mark.asyncio
    async def test_au_dela_de_cinq_archives_la_plus_ancienne_est_purgee(
            self, mock_tika, mock_ollama, mock_embeddings, mem_db, tmp_path):
        service = ExtractionService(mock_tika, mock_ollama, mock_embeddings)
        for n in range(7):
            await _deposer(service, mem_db, _guide(tmp_path, f"1.0.{n}"))
        versions = (await mem_db.execute(select(Version).order_by(Version.numero_version))).scalars().all()
        assert len(versions) == 6                                   # 7 dépôts = 6 versions remplacées
        assert versions[0].chemin_archive is None                   # la plus ancienne : texte purgé
        assert all(v.chemin_archive for v in versions[1:])          # les 5 plus récentes : gardées
        assert len(list((tmp_path / "versions").rglob("v*.txt"))) == 5

    def test_lire_archive_refuse_un_chemin_hors_du_dossier(self, tmp_path):
        dehors = tmp_path / "secret.txt"
        dehors.write_text("non", encoding="utf-8")
        assert lire_archive(str(dehors)) is None
        assert lire_archive(None) is None
