"""
Recherche hybride unique et fusion RRF (plan prompts + RAG, étape B1). Documents fictifs.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services import fusion_recherche as F


def doc(i):
    return SimpleNamespace(id=f"doc-{i}")


def liste(*ids_scores):
    return [(doc(i), None, s) for i, s in ids_scores]


def ids(resultats):
    return [d.id.removeprefix("doc-") for d, _, _ in resultats]


class TestPonderee:
    def test_identique_a_l_ancienne_fusion(self):
        texte = liste(("a", 0.2), ("b", 0.1))
        sens = liste(("b", 0.9), ("c", 0.45))
        r = {d.id: s for d, _, s in F.ponderee(texte, sens)}
        assert r == pytest.approx({"doc-a": 0.4, "doc-b": 0.2 + 0.6, "doc-c": 0.3})


class TestRRF:
    def test_seul_le_rang_compte(self):
        # Mêmes rangs, scores d'échelles très différentes : même résultat.
        a = F.rrf([(liste(("a", 0.1), ("b", 0.05)), 1.0), (liste(("b", 0.9), ("a", 0.8)), 1.0)])
        b = F.rrf([(liste(("a", 900), ("b", 1)), 1.0), (liste(("b", 0.0001), ("a", 0.00001)), 1.0)])
        assert [(d.id, round(s, 6)) for d, _, s in a] == [(d.id, round(s, 6)) for d, _, s in b]

    def test_present_dans_deux_listes_passe_devant(self):
        r = F.rrf([(liste(("seul", 1), ("deux", 1)), 1.0), (liste(("deux", 1)), 1.0)])
        assert ids(r) == ["deux", "seul"]

    def test_score_entre_0_et_1_premier_partout_vaut_1(self):
        r = F.rrf([(liste(("a", 1)), 1.0), (liste(("a", 1)), 0.5)])
        assert r[0][2] == pytest.approx(1.0)
        assert all(0 < s <= 1 for _, _, s in F.rrf([(liste(("a", 1), ("b", 1)), 1.0), (liste(("c", 1)), 1.0)]))

    def test_doublon_dans_une_liste_compte_une_fois(self):
        r = F.rrf([(liste(("a", 1), ("a", 1), ("b", 1)), 1.0)])
        assert ids(r) == ["a", "b"] and r[0][2] == pytest.approx(1.0)

    def test_listes_vides(self):
        assert F.rrf([([], 1.0), ([], 1.0)]) == []


class TestRechercheHybride:
    """Orchestration : quels signaux, quelle fusion, quelles preuves lexicales pour le gate."""

    @pytest.fixture
    def signaux(self):
        return {
            "_recherche_fulltext": AsyncMock(return_value=liste(("t", 0.1))),
            "_recherche_semantique": AsyncMock(return_value=liste(("s", 0.8), ("t", 0.7))),
            "_recherche_nom": AsyncMock(return_value=liste(("n", 0.6))),
            "_recherche_meta_ou": AsyncMock(return_value=liste(("m", 0.05))),
            "_cosinus_pour": AsyncMock(return_value={"doc-n": 0.66, "doc-m": 0.5}),
        }

    async def _lancer(self, signaux, **kw):
        from routers import search
        with patch.multiple(search, **signaux):
            return await search.recherche_hybride("question fictive", db=None, **kw)

    @pytest.mark.asyncio
    async def test_rrf_utilise_les_quatre_signaux(self, signaux):
        h = await self._lancer(signaux, fusion="rrf")
        assert set(ids(h.candidats)) == {"t", "s", "n", "m"}
        assert ids(h.candidats)[0] == "t"                       # texte + sens : en tête
        # Le nom de fichier vaut preuve lexicale ; le « au moins un mot » des métadonnées, non.
        assert h.ids_texte == {"doc-t", "doc-n"}
        assert h.cos_abs == {"doc-s": 0.8, "doc-t": 0.7, "doc-n": 0.66, "doc-m": 0.5}

    @pytest.mark.asyncio
    async def test_ponderee_ne_lance_pas_les_signaux_d_appoint(self, signaux):
        h = await self._lancer(signaux, fusion="ponderee")
        signaux["_recherche_nom"].assert_not_awaited()
        signaux["_recherche_meta_ou"].assert_not_awaited()
        assert set(ids(h.candidats)) == {"t", "s"}

    @pytest.mark.asyncio
    async def test_appoint_borne(self, signaux):
        from routers import search
        await self._lancer(signaux, fusion="rrf", limit=200)
        assert signaux["_recherche_nom"].await_args.kwargs["limit"] == search.LIMITE_APPOINT
        assert signaux["_recherche_fulltext"].await_args.kwargs["limit"] == 200

    @pytest.mark.asyncio
    async def test_sans_mesure_de_cosinus(self, signaux):
        h = await self._lancer(signaux, fusion="rrf", mesurer_cosinus=False)
        signaux["_cosinus_pour"].assert_not_awaited()
        assert "doc-n" not in h.cos_abs

    @pytest.mark.asyncio
    async def test_mode_texte(self, signaux):
        h = await self._lancer(signaux, type="text")
        signaux["_recherche_semantique"].assert_not_awaited()
        assert ids(h.candidats) == ["t"] and h.moteur_semantique == "non_utilise"

    def test_rrf_par_defaut(self):
        from routers import search
        assert search.FUSION_DEFAUT == F.RRF


@pytest.mark.asyncio
async def test_signaux_d_appoint_muets_hors_postgres():
    """pg_trgm et tsquery n'existent pas sous SQLite : les deux signaux rendent [] sans erreur."""
    from routers import search
    db = SimpleNamespace(bind=SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    assert await search._recherche_nom("x", db) == []
    assert await search._recherche_meta_ou("x", db) == []
