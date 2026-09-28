"""
Tests — constats MOYENS de l'audit du 28/09/2026 (docs/rapport-audit-2026-09.md)
==============================================================================
M1 traversée de chemin · M6 texte non rapatrié par la recherche · M7 purge par lots ·
M8 plafond d'upload · M9 sonde de liens bornée · M12 embedding vide.
(M4 — CHECK rejoués au démarrage — touche le catalogue Postgres : vérifié sur Postgres réel.)
"""

import hashlib
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from utils.file_utils import sous_chemin


@pytest_asyncio.fixture
async def client(db_session):
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


# ─── M1 : un `..` ne sort plus du dossier d'une source ────────────────────────────────

def test_sous_chemin_reste_dans_la_source(tmp_path):
    (tmp_path / "clientA" / "factures").mkdir(parents=True)
    base = tmp_path / "clientA"
    assert sous_chemin(base, "/") == base
    assert sous_chemin(base, "") == base
    assert sous_chemin(base, "/factures") == base / "factures"
    assert sous_chemin(base, "factures/../factures") == base / "factures"


@pytest.mark.parametrize("chemin", ["../", "../../etc", "/../clientB", "factures/../../clientB"])
def test_sous_chemin_refuse_de_sortir(tmp_path, chemin):
    (tmp_path / "clientA").mkdir()
    with pytest.raises(ValueError, match="hors du dossier"):
        sous_chemin(tmp_path / "clientA", chemin)


def test_sous_chemin_garde_la_forme_d_origine(tmp_path):
    """Les documents sont repérés par leur chemin : sa forme ne doit pas changer."""
    base = tmp_path / "docs"
    base.mkdir()
    assert str(sous_chemin(str(base), "/a")) == str(base / "a")


# ─── M6 : la route de recherche ne rapatrie pas le texte ──────────────────────────────

@pytest.mark.asyncio
async def test_la_recherche_ne_rapatrie_pas_le_texte(client):
    texte, sens = AsyncMock(return_value=[]), AsyncMock(return_value=[])
    async with client as c:
        with patch("routers.search._recherche_fulltext", texte), \
             patch("routers.search._recherche_semantique", sens):
            await c.get("/api/search", params={"q": "facture"})
    assert texte.await_args.kwargs["charger_texte"] is False
    assert sens.await_args.kwargs["charger_texte"] is False


# ─── M7 : purge des doublons — même plan, calculé par lots ────────────────────────────

@pytest.mark.asyncio
async def test_purge_des_doublons_trouve_les_groupes(client, db_session):
    from models.document import Document

    h = hashlib.sha256(b"x").hexdigest()
    db_session.add_all([
        Document(id=uuid.uuid4(), chemin=f"/d/copie{i}.pdf", nom=f"copie{i}.pdf", extension="pdf",
                 hash_sha256=h, statut="enriched", texte_extrait="t" * 1000)
        for i in range(3)
    ] + [
        Document(id=uuid.uuid4(), chemin="/d/seul.pdf", nom="seul.pdf", extension="pdf",
                 hash_sha256=hashlib.sha256(b"y").hexdigest(), statut="enriched"),
    ])
    await db_session.flush()
    async with client as c:
        r = (await c.post("/api/documents/purge-duplicates", params={"dry_run": "true"})).json()
    hash_groupes = [g for g in r["apercu"] if g.get("type") == "hash"]
    assert r["nb_groupes"] == 1
    assert len(hash_groupes) == 1 and len(hash_groupes[0]["supprimer"]) == 2


# ─── M8 : un fichier trop gros est arrêté, et le partiel supprimé ─────────────────────

@pytest.mark.asyncio
async def test_upload_au_dela_du_plafond_refuse_sans_rien_laisser(client, tmp_path, monkeypatch):
    from routers import upload
    from services import runtime_config

    monkeypatch.setattr(upload.settings, "storage_uploads", str(tmp_path))
    monkeypatch.setitem(runtime_config._overrides, "index_taille_max_mo", "1")
    gros = b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 10)
    async with client as c:
        r = (await c.post("/api/upload", files=[("files", ("gros.pdf", gros, "application/pdf"))])).json()
    ligne = r["jobs"][0]
    assert ligne["statut"] == "erreur" and "trop volumineux" in ligne["raison"]
    assert not list(tmp_path.iterdir()), "le fichier partiel doit être supprimé"


# ─── M9 : « Vérifier les liens » ne sonde pas les services internes ───────────────────

@pytest.mark.parametrize("url, refuse", [
    ("https://nas.maison.fr", False),
    ("http://192.168.42.83:3003", False),          # un service du LAN : c'est l'usage
    ("http://localhost:8000", True),
    ("http://127.0.0.1:5432", True),
    ("http://169.254.169.254/latest/meta-data", True),
    ("http://postgres:5432", True),                # conteneur voisin
    ("file:///etc/passwd", True),
    ("ftp://nas.maison.fr", True),
])
def test_sonde_de_liens_bornee(url, refuse):
    from routers.system import _cible_interdite
    assert (_cible_interdite(url) is not None) is refuse


# ─── Constats BAS : chemin SMB, sélecteur de dossiers ─────────────────────────────────

@pytest.mark.parametrize("brut, attendu", [
    ("/", "/"), ("", "/"), (None, "/"),
    ("/Compta/2026", "/Compta/2026"),
    ("Compta\\2026", "/Compta/2026"),            # séparateurs Windows
    ("/Compta/../RH", "/RH"),
    ("/../../etc", "/etc"),                      # ne remonte JAMAIS au-dessus du partage
    ("/a/./b//c/", "/a/b/c"),
])
def test_chemin_smb_normalise_et_borne_au_partage(brut, attendu):
    from utils.file_utils import chemin_partage
    assert chemin_partage(brut) == attendu


@pytest.mark.parametrize("chemin, systeme", [
    ("/etc", True), ("/etc/ssl", True), ("/proc/1", True), ("/root", True),
    ("/app/documents", False), ("/mnt/nas", False), ("/etcetera", False),
])
def test_dossiers_systeme(chemin, systeme):
    from utils.file_utils import dossier_systeme
    assert dossier_systeme(chemin) is systeme


@pytest.mark.asyncio
async def test_le_selecteur_de_dossiers_ne_liste_pas_le_systeme(client):
    async with client as c:
        r = await c.get("/api/folders/browse", params={"path": "/etc"})
    assert r.status_code == 403


# ─── M12 : un embedding vide est une erreur, pas un NULL silencieux ───────────────────

@pytest.mark.asyncio
async def test_embedding_vide_leve_au_lieu_de_stocker_null(db_session):
    from services.embedding_service import EmbeddingService

    ollama = MagicMock()
    ollama.embed = AsyncMock(return_value=[])
    service = EmbeddingService(ollama)
    with pytest.raises(RuntimeError, match="Embedding vide"):
        await service.embed_document(str(uuid.uuid4()), "un texte à vectoriser", db_session)
    assert ollama.embed.await_count == 2          # le principal, puis le modèle de repli


@pytest.mark.asyncio
async def test_embedding_vide_rattrape_par_le_modele_de_repli():
    from services.embedding_service import EmbeddingService

    ollama = MagicMock()
    ollama.embed = AsyncMock(side_effect=[[], [0.1] * 8])
    db = MagicMock()                     # SQLite ne stocke pas de vecteur : session simulée
    db.flush = AsyncMock()
    n = await EmbeddingService(ollama).embed_document(str(uuid.uuid4()), "texte", db)
    assert n == 1
    stocke = db.add.call_args.args[0]
    assert stocke.embedding == [0.1] * 8, "c'est le vecteur du repli qui est stocké, pas un NULL"
