"""
Retrouver le flux d'un podcast, et reconnaître ce qui n'en est pas un.

Ce fichier existe à cause d'un bug réel : `flux_url` de « La Matrescence » valait
`https://www.deezer.com/search/La%20Matrescence...` — une page de recherche, pas un flux. La
lecture des épisodes échouait donc en disant « format illisible », ce qui envoie chercher un
problème de réseau là où il n'y a qu'un mauvais champ. Le garde-fou testé ici nomme la
plateforme AVANT que l'utilisateur ne se demande pourquoi rien ne marche.

La recherche elle-même sort sur Internet : elle est testée sur une réponse enregistrée, pas
en appelant l'annuaire — un test ne doit pas dépendre d'un service tiers.
"""

import json

import httpx
import pytest

from services import podcast_index


class TestRessembleAUnePage:
    @pytest.mark.parametrize("url", [
        "https://www.deezer.com/search/La%20Matrescence",     # le cas vécu
        "https://open.spotify.com/show/3e0LTZ7BxfTpeClgtgKOwc",
        "https://podcasts.apple.com/fr/podcast/le-podcast-des-paternelles/id1234",
        "https://www.youtube.com/@unechaine",
    ])
    def test_les_pages_d_ecoute_sont_signalees(self, url):
        assert podcast_index.ressemble_a_une_page(url) is not None

    @pytest.mark.parametrize("url", [
        "https://feeds.acast.com/public/shows/la-matrescence",
        "https://www.arteradio.com/rss/un_podcast_a_soi.xml",
        "https://anchor.fm/s/1234/podcast/rss",
        "",
    ])
    def test_un_vrai_flux_passe(self, url):
        assert podcast_index.ressemble_a_une_page(url) is None

    def test_la_casse_ne_trompe_pas(self):
        assert podcast_index.ressemble_a_une_page("HTTPS://OPEN.SPOTIFY.COM/show/x") == "open.spotify.com"


class TestChercher:
    @pytest.fixture
    def reponse_annuaire(self):
        """Réponse type de l'annuaire, réduite aux champs qu'on lit."""
        return {
            "resultCount": 3,
            "results": [
                {"collectionName": "La Matrescence", "artistName": "Clémentine Sarlat",
                 "feedUrl": "https://feeds.acast.com/public/shows/la-matrescence",
                 "trackCount": 210, "artworkUrl100": "https://img/1.jpg",
                 "primaryGenreName": "Kids & Family"},
                # Sans `feedUrl` : présent dans l'annuaire mais inutilisable ici.
                {"collectionName": "Matrescence — bonus", "artistName": "X", "trackCount": 4},
                {"collectionName": "Bliss Stories", "artistName": "Clémentine Galey",
                 "feedUrl": "https://feeds.audiomeans.fr/bliss", "trackCount": 300},
            ],
        }

    async def _chercher_avec(self, monkeypatch, corps: str, statut: int = 200, **kw):
        def faux_get(self, url, **_):
            # L'annuaire répond en text/javascript : c'est justement le piège que le service
            # contourne en décodant `resp.text` plutôt qu'en appelant `resp.json()`.
            return httpx.Response(statut, text=corps,
                                  headers={"content-type": "text/javascript; charset=utf-8"},
                                  request=httpx.Request("GET", url))
        monkeypatch.setattr(httpx.AsyncClient, "get", faux_get)
        return await podcast_index.chercher(**kw)

    @pytest.mark.asyncio
    async def test_ne_rend_que_les_resultats_porteurs_d_un_flux(self, monkeypatch, reponse_annuaire):
        r = await self._chercher_avec(monkeypatch, json.dumps(reponse_annuaire), titre="Matrescence")
        assert [c["feed_url"] for c in r] == [
            "https://feeds.acast.com/public/shows/la-matrescence",
            "https://feeds.audiomeans.fr/bliss",
        ]
        assert r[0]["auteur"] == "Clémentine Sarlat" and r[0]["nb_episodes"] == 210

    @pytest.mark.asyncio
    async def test_plusieurs_candidats_sont_rendus_sans_choisir(self, monkeypatch, reponse_annuaire):
        """
        On ne garde PAS le premier : « Le Nid » ou « Père » désignent plusieurs émissions, et
        trancher à la place de l'utilisateur mettrait le mauvais flux dans sa fiche en silence.
        """
        r = await self._chercher_avec(monkeypatch, json.dumps(reponse_annuaire), titre="Matrescence")
        assert len(r) > 1

    @pytest.mark.asyncio
    async def test_aucun_resultat_rend_une_liste_vide(self, monkeypatch):
        r = await self._chercher_avec(monkeypatch, '{"resultCount":0,"results":[]}', titre="Zzz")
        assert r == []

    @pytest.mark.asyncio
    async def test_titre_vide_ne_sort_pas_sur_le_reseau(self, monkeypatch):
        """Un terme vide ramènerait n'importe quoi : autant ne pas faire l'appel du tout."""
        def interdit(*_a, **_k):
            raise AssertionError("aucune requête ne doit partir sans terme de recherche")
        monkeypatch.setattr(httpx.AsyncClient, "get", interdit)
        assert await podcast_index.chercher("", None) == []
