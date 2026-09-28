"""
Tests — la recherche ne rend plus un résultat incomplet qui a l'air complet
=========================================================================
Deux défauts relevés par l'audit du 28/09/2026 (docs/rapport-audit-2026-09.md, H1 et H2) :

- **H1** — les filtres catégorie / extension étaient appliqués en Python APRÈS la limite de
  200 candidats : tout document de la catégorie classé au-delà disparaissait sans signal. Ils
  descendent maintenant dans chaque requête SQL, avant la limite.
- **H2** — un Ollama occupé ou arrêté rendait « 0 résultat » en recherche sémantique, lu « ce
  document n'existe pas ». La réponse dit désormais si le moteur a tourné, et le mode
  sémantique retombe sur le texte en le disant.

Le SQL lui-même (tsvector, pgvector) ne tourne pas sous SQLite : il est vérifié sur Postgres
réel à la livraison. Ici : la construction du filtre, et le contrat de la route.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from routers import search as search_mod


def _doc(doc_id: str, score: float, categorie: str | None = "facture", extension: str = "pdf"):
    doc = MagicMock()
    doc.id = doc_id
    doc.nom = f"{doc_id}.{extension}"
    doc.extension = extension
    doc.taille_octets = 1000
    doc.statut = "enriched"
    doc.chemin = f"/docs/{doc_id}.{extension}"
    doc.date_import = None
    meta = MagicMock()
    meta.categorie = categorie
    meta.tags = []
    meta.resume = ""
    meta.langue = "fr"
    return (doc, meta, score)


@pytest_asyncio.fixture
async def client(db_session):
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    search_mod._EMBED_CACHE.clear()
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()
    search_mod._EMBED_CACHE.clear()


# ─── H1 : le filtre est dans la requête, pas après ─────────────────────────────────────

class TestFiltreSql:
    def test_sans_filtre_rien_n_est_ajoute(self):
        assert search_mod._filtre_sql("d.id", None, None) == ("", {})
        assert search_mod._filtre_sql("d.id", "", "") == ("", {})

    def test_extension_normalisee_et_liee_en_parametre(self):
        sql, params = search_mod._filtre_sql("d.id", None, ".PDF")
        assert sql.startswith(" AND d.id IN (SELECT fd.id FROM documents fd")
        assert "fd.extension = :f_ext" in sql
        assert params == {"f_ext": "pdf"}

    def test_categorie_jointe_aux_metadonnees_sans_casse(self):
        sql, params = search_mod._filtre_sql("e.document_id", "Facture", None)
        assert "JOIN metadonnees_ia fm ON fm.document_id = fd.id" in sql
        assert "lower(fm.categorie) = lower(:f_cat)" in sql
        assert sql.startswith(" AND e.document_id IN")
        assert params == {"f_cat": "Facture"}

    def test_la_valeur_n_est_jamais_dans_le_sql(self):
        """Une catégorie saisie ne doit pas pouvoir écrire du SQL : elle passe en paramètre."""
        sql, _ = search_mod._filtre_sql("d.id", "x'); DROP TABLE documents; --", "pdf")
        assert "DROP" not in sql


@pytest.mark.asyncio
async def test_les_filtres_descendent_dans_les_deux_recherches(client):
    """Les deux branches reçoivent le filtre — plus aucun tri après coup sur un lot tronqué."""
    texte = AsyncMock(return_value=[])
    sens = AsyncMock(return_value=[])
    async with client as c:
        with patch("routers.search._recherche_fulltext", texte), \
             patch("routers.search._recherche_semantique", sens):
            await c.get("/api/search", params={"q": "facture", "categorie": "Impôts",
                                               "extension": "pdf"})
    for appel in (texte, sens):
        assert appel.await_args.kwargs["categorie"] == "Impôts"
        assert appel.await_args.kwargs["extension"] == "pdf"


@pytest.mark.asyncio
async def test_les_resultats_filtres_en_sql_ne_sont_pas_refiltres(client):
    """
    La route fait confiance au SQL : un résultat renvoyé par une recherche filtrée n'est pas
    rejeté une seconde fois (l'ancien filtre Python comparait `meta.categorie`, absente d'un
    document sans métadonnées IA).
    """
    async with client as c:
        with patch("routers.search._recherche_fulltext",
                   AsyncMock(return_value=[_doc("a", 0.9, categorie=None)])), \
             patch("routers.search._recherche_semantique", AsyncMock(return_value=[])):
            r = (await c.get("/api/search", params={"q": "facture", "type": "text",
                                                    "extension": "pdf"})).json()
    assert [x["id"] for x in r["resultats"]] == ["a"]


# ─── H2 : un moteur sémantique muet se dit ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_moteur_indisponible_est_signale_en_hybride(client):
    async with client as c:
        with patch("routers.search._recherche_fulltext", AsyncMock(return_value=[_doc("t", 0.5)])), \
             patch("routers.search._recherche_semantique", AsyncMock(return_value=[])):
            r = (await c.get("/api/search", params={"q": "facture"})).json()
    assert r["moteur_semantique"] == "indisponible"
    assert r["repli_texte"] is False                    # l'hybride montre déjà le texte
    assert [x["id"] for x in r["resultats"]] == ["t"]


@pytest.mark.asyncio
async def test_mode_semantique_sans_moteur_retombe_sur_le_texte_et_le_dit(client):
    """Avant : « 0 résultat », lu « ce document n'existe pas »."""
    async with client as c:
        with patch("routers.search._recherche_fulltext", AsyncMock(return_value=[_doc("t", 0.5)])), \
             patch("routers.search._recherche_semantique", AsyncMock(return_value=[])):
            r = (await c.get("/api/search", params={"q": "facture", "type": "semantic"})).json()
    assert r["moteur_semantique"] == "indisponible" and r["repli_texte"] is True
    assert [x["id"] for x in r["resultats"]] == ["t"]
    assert r["resultats"][0]["pertinent"] is True       # le match texte fait foi, comme en mode texte


@pytest.mark.asyncio
async def test_moteur_qui_a_tourne_sans_rien_trouver_n_est_pas_indisponible(client):
    """Embedding calculé (en cache), aucun voisin : c'est un vrai « rien trouvé »."""
    from services import runtime_config
    search_mod._EMBED_CACHE[(runtime_config.usage_model("embeddings") or "", "facture")] = [0.1]
    async with client as c:
        with patch("routers.search._recherche_fulltext", AsyncMock(return_value=[])), \
             patch("routers.search._recherche_semantique", AsyncMock(return_value=[])):
            r = (await c.get("/api/search", params={"q": "facture", "type": "semantic"})).json()
    assert r["moteur_semantique"] == "ok" and r["repli_texte"] is False
    assert r["total"] == 0


@pytest.mark.asyncio
async def test_moteur_ok_quand_il_rend_des_resultats(client):
    async with client as c:
        with patch("routers.search._recherche_fulltext", AsyncMock(return_value=[])), \
             patch("routers.search._recherche_semantique", AsyncMock(return_value=[_doc("s", 0.9)])):
            r = (await c.get("/api/search", params={"q": "facture"})).json()
    assert r["moteur_semantique"] == "ok"


@pytest.mark.asyncio
async def test_mode_texte_n_utilise_pas_le_moteur(client):
    async with client as c:
        with patch("routers.search._recherche_fulltext", AsyncMock(return_value=[])), \
             patch("routers.search._recherche_semantique", AsyncMock(return_value=[])):
            r = (await c.get("/api/search", params={"q": "facture", "type": "text"})).json()
    assert r["moteur_semantique"] == "non_utilise" and r["repli_texte"] is False
