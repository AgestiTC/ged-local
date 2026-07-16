"""
Tests — services/pertinence.py + le gate exposé par GET /api/search
===================================================================
Les cas de `TestGate` rejouent la calibration du 02/07/2026 consignée dans
docs/plan-recherche-pertinence-seuil.md §3.3 : ce sont les 8 requêtes témoins mesurées
sur le corpus réel. Si un seuil bouge, ces tests disent lesquelles basculent.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import ASGITransport, AsyncClient

from services import pertinence

HAUT = pertinence.SEUIL_HAUT_DEFAUT   # 0.72
BAS = pertinence.SEUIL_BAS_DEFAUT     # 0.65 (corpus NAS)

# Seuils de la calibration ORIGINALE (02/07, corpus dev ~520 docs) : la table témoin ci-dessous
# a été mesurée avec ces valeurs, on les fige donc explicitement pour tester la LOGIQUE du gate,
# indépendamment du défaut déployé (qui a bougé après re-calibration NAS, cf. pertinence.py).
HAUT_CAL, BAS_CAL = 0.72, 0.60


class TestGate:
    @pytest.mark.parametrize(
        "libelle, cosinus, match_texte, attendu",
        [
            # Requêtes SANS réponse dans le corpus : cosinus parfois élevé, mais 0 match lexical.
            ("dossier de mariage", 0.657, False, False),
            ("documents nécessaires mariage", 0.627, False, False),
            ("recette tarte aux pommes", 0.511, False, False),
            # Requêtes AVEC réponse : le match lexical corrobore un cosinus moyen.
            ("contrat de location immobilière", 0.618, True, True),
            ("liste des adhérents du club", 0.686, True, True),
            ("manuel utilisation windows", 0.754, True, True),
            ("facture", 0.830, True, True),
            ("attestation assurance", 0.933, True, True),
        ],
    )
    def test_requetes_temoins_de_la_calibration(self, libelle, cosinus, match_texte, attendu):
        pertinent, _ = pertinence.evaluer(cosinus, match_texte, HAUT_CAL, BAS_CAL)
        assert pertinent is attendu, f"« {libelle} » mal classé"

    def test_cosinus_haut_seul_suffit(self):
        """Au-dessus du seuil haut, le sens suffit — même sans les mots."""
        assert pertinence.evaluer(0.80, False, HAUT, BAS) == (True, pertinence.ELEVEE)

    def test_cosinus_moyen_sans_lexical_est_rejete(self):
        """Le cœur du gate : un faux positif sémantique sans match lexical tombe."""
        assert pertinence.evaluer(0.65, False, HAUT, BAS) == (False, pertinence.FAIBLE)

    def test_cosinus_moyen_avec_lexical_passe(self):
        assert pertinence.evaluer(0.65, True, HAUT, BAS) == (True, pertinence.MOYENNE)

    def test_cosinus_sous_le_seuil_bas_reste_rejete_malgre_le_lexical(self):
        assert pertinence.evaluer(0.40, True, HAUT, BAS) == (False, pertinence.FAIBLE)

    def test_sans_mesure_semantique_le_lexical_fait_foi(self):
        """Mode texte pur / document hors du top sémantique : un match = pertinent."""
        assert pertinence.evaluer(None, True, HAUT, BAS) == (True, pertinence.MOYENNE)
        assert pertinence.evaluer(None, False, HAUT, BAS) == (False, pertinence.FAIBLE)


class TestSeuils:
    def test_defauts_de_calibration(self):
        with patch("services.runtime_config.effective", return_value=""):
            assert pertinence.seuils() == (HAUT, BAS)

    def test_surcharge_depuis_la_config(self):
        with patch("services.runtime_config.effective", side_effect=lambda c: {
            "search_cos_haut": "0.9", "search_cos_bas": "0.5",
        }[c]):
            assert pertinence.seuils() == (0.9, 0.5)

    @pytest.mark.parametrize("valeur", ["abc", "", "0", "-0.5", "1.5"])
    def test_valeur_invalide_retombe_sur_le_defaut(self, valeur):
        """Un seuil hors [0,1] ou illisible désactiverait le gate en silence → on l'ignore."""
        with patch("services.runtime_config.effective", return_value=valeur):
            assert pertinence.seuils() == (HAUT, BAS)


# ─── Le gate vu de l'endpoint ────────────────────────────────────────────────

@pytest_asyncio.fixture
async def client(db_session):
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


def _doc(doc_id: str, cosinus: float):
    """(Document, MetadonneeIA, score) fictif — le score porte le cosinus en sémantique."""
    doc = MagicMock()
    doc.id = doc_id
    doc.nom = f"{doc_id}.pdf"
    doc.extension = "pdf"
    doc.taille_octets = 1000
    doc.statut = "enriched"
    doc.chemin = "/docs/x.pdf"
    doc.date_import = None
    meta = MagicMock()
    meta.categorie = "facture"
    meta.tags = []
    meta.resume = ""
    meta.langue = "fr"
    return (doc, meta, cosinus)


class TestSearchPertinence:
    @pytest.mark.asyncio
    async def test_aucun_document_pertinent_quand_le_lexical_est_vide(self, client):
        """« dossier de mariage » : cosinus 0.657 mais 0 match → nb_pertinents = 0."""
        async with client as c:
            with patch("routers.search._recherche_fulltext", AsyncMock(return_value=[])), \
                 patch("routers.search._recherche_semantique",
                       AsyncMock(return_value=[_doc("a", 0.657), _doc("b", 0.62)])):
                resp = await c.get("/api/search", params={"q": "dossier de mariage"})

        data = resp.json()
        assert data["nb_pertinents"] == 0
        assert data["nb_masques"] == 2
        # Les résultats sont RENVOYÉS quand même (« Afficher quand même » sans re-fetch).
        assert len(data["resultats"]) == 2
        assert all(r["pertinent"] is False for r in data["resultats"])
        assert all(r["etiquette"] == "faible" for r in data["resultats"])

    @pytest.mark.asyncio
    async def test_match_lexical_rend_un_cosinus_moyen_pertinent(self, client):
        """Cosinus entre SEUIL_BAS et SEUIL_HAUT + match lexical → pertinent (étiquette moyenne)."""
        docs = [_doc("a", 0.68)]   # 0.65 <= 0.68 < 0.72
        async with client as c:
            with patch("routers.search._recherche_fulltext", AsyncMock(return_value=docs)), \
                 patch("routers.search._recherche_semantique", AsyncMock(return_value=docs)):
                resp = await c.get("/api/search", params={"q": "contrat de location"})

        data = resp.json()
        assert data["nb_pertinents"] == 1
        assert data["resultats"][0]["etiquette"] == "moyenne"

    @pytest.mark.asyncio
    async def test_cosinus_eleve_est_etiquete_elevee(self, client):
        async with client as c:
            with patch("routers.search._recherche_fulltext", AsyncMock(return_value=[])), \
                 patch("routers.search._recherche_semantique",
                       AsyncMock(return_value=[_doc("a", 0.933)])):
                resp = await c.get("/api/search", params={"q": "attestation assurance"})

        data = resp.json()
        assert data["nb_pertinents"] == 1
        assert data["resultats"][0]["etiquette"] == "elevee"
        assert data["resultats"][0]["pertinence"] == 93   # cosinus absolu, pas le % relatif

    @pytest.mark.asyncio
    async def test_inclure_non_pertinents_reproduit_le_comportement_historique(self, client):
        """Filet de sécurité : rien n'est masqué quand on neutralise le gate."""
        async with client as c:
            with patch("routers.search._recherche_fulltext", AsyncMock(return_value=[])), \
                 patch("routers.search._recherche_semantique",
                       AsyncMock(return_value=[_doc("a", 0.51)])):
                resp = await c.get("/api/search", params={
                    "q": "recette tarte", "inclure_non_pertinents": "true",
                })

        data = resp.json()
        assert data["nb_pertinents"] == 1
        assert data["nb_masques"] == 0
        assert data["resultats"][0]["pertinent"] is True

    @pytest.mark.asyncio
    async def test_mode_texte_est_permissif(self, client):
        """Sans mesure sémantique, un match lexical suffit — et `pertinence` reste absente."""
        async with client as c:
            with patch("routers.search._recherche_fulltext",
                       AsyncMock(return_value=[_doc("a", 0.9), _doc("b", 0.1)])), \
                 patch("routers.search._recherche_semantique", AsyncMock(return_value=[])):
                resp = await c.get("/api/search", params={"q": "facture", "type": "text"})

        data = resp.json()
        assert data["nb_pertinents"] == 2
        assert data["nb_masques"] == 0
        assert data["resultats"][0]["pertinence"] is None

    @pytest.mark.asyncio
    async def test_les_pertinents_remontent_en_page_1(self, client):
        """
        Le classement est le score hybride (relatif) : un faux positif peut devancer un vrai
        résultat. Constaté sur le corpus NAS (« dossier de mariage » : 15 premiers tous non
        pertinents, 34 pertinents enterrés plus bas) → page 1 filtrée vide. Les pertinents
        doivent donc passer devant.
        """
        # 25 non-pertinents (cosinus faible, aucun match lexical) devant 2 pertinents.
        docs = [_doc(f"faible{i}", 0.50) for i in range(25)] + [_doc("fort", 0.95)]
        async with client as c:
            with patch("routers.search._recherche_fulltext", AsyncMock(return_value=[])), \
                 patch("routers.search._recherche_semantique", AsyncMock(return_value=docs)):
                resp = await c.get("/api/search", params={"q": "facture", "limit": 20})

        data = resp.json()
        assert data["nb_pertinents"] == 1
        assert data["resultats"][0]["id"] == "fort", "le pertinent doit être en tête de page 1"
        assert any(r["pertinent"] for r in data["resultats"]), "page 1 ne doit pas être vide une fois filtrée"

    @pytest.mark.asyncio
    async def test_nb_pertinents_couvre_tous_les_candidats_pas_la_page(self, client):
        """Le compteur doit répondre pour la recherche entière, sinon la page 1 décide seule."""
        docs = [_doc(f"d{i}", 0.95) for i in range(30)]
        async with client as c:
            with patch("routers.search._recherche_fulltext", AsyncMock(return_value=[])), \
                 patch("routers.search._recherche_semantique", AsyncMock(return_value=docs)):
                resp = await c.get("/api/search", params={"q": "facture", "limit": 20})

        data = resp.json()
        assert len(data["resultats"]) == 20
        assert data["nb_pertinents"] == 30
