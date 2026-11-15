"""
Titre des épisodes (Rangement, 15/11/2026) — `Série - S01E01 - Titre.ext`, d'après Plex.

Noms (purs), client Plex (faux serveur httpx, aucun réseau), propositions sur un faux partage, puis
renommer et annuler par un lot. Données fictives.
"""

import json
from pathlib import Path

import httpx
import pytest
from fakes.depot_memoire import DepotMemoire
from sqlalchemy import select

from models.plan_classement import PlanProposition
from services.rangement import deplacements, plan, plex, service, titres_episodes as te
from services.rangement.exclusions import Exclusions
from services.rangement.scan import Scanner


# --------------------------------------------------------------------------- #
# Noms                                                                         #
# --------------------------------------------------------------------------- #
def test_nom_avec_et_sans_titre():
    c = te.Code(1, (1,))
    assert te.nom_episode("Westworld", c, ["Le Labyrinthe"], "mkv") == "Westworld - S01E01 - Le Labyrinthe.mkv"
    assert te.nom_episode("Westworld", c, ["Épisode 1"], "mkv") == "Westworld - S01E01.mkv"   # titre bouche-trou
    assert te.nom_episode("Westworld", c, [], "mkv") == "Westworld - S01E01.mkv"
    assert te.nom_episode("Mr. Robot", te.Code(4, (13, 14)), ["Un", "Deux"], "mkv") == \
        "Mr. Robot - S04E13-E14 - Un & Deux.mkv"


def test_caracteres_interdits_sur_smb():
    assert te.propre('Ma beuh, où elle est ?') == "Ma beuh, où elle est"
    assert te.propre("Star Trek: Picard") == "Star Trek - Picard"
    assert te.propre("A/B \\ C*") == "A-B - C"


def test_code_et_compagnons():
    assert te.code_de("Arcane.S02E03.MULTi.mkv") == te.Code(2, (3,))
    assert te.code_de("mr.robot.s04e13-e14.mkv") == te.Code(4, (13, 14))
    assert te.code_de("Livre 1.mkv") is None
    assert te.compagnons("X.mkv", ["X.mkv", "X.fr.srt", "X.nfo", "X.jpg", "Y.srt"]) == {"X.fr.srt": ".fr.srt", "X.nfo": ".nfo"}


def test_un_dossier_de_saison():
    fichiers = {"Dark.S01E01.WEB.mkv": 10, "Dark.S01E01.WEB.fr.srt": 1, "Dark.S01E02.WEB.mkv": 10,
                "Dark - S01E03 - Déjà là.mkv": 10, "Dark.S01E03.vieux.mkv": 10, "notes.txt": 1}
    index = {te.cle_chemin("Series/Dark/S01/Dark.S01E01.WEB.mkv"): [("Dark", 1, 1, "Secrets")],
             te.cle_chemin("Series/Dark/S01/Dark.S01E03.vieux.mkv"): [("Dark", 1, 3, "Déjà là")]}
    r, conflits = te.renommages_du_dossier("Series/Dark/S01", fichiers, "Dark", index)
    noms = {x.chemin.rsplit("/", 1)[1]: (x.nouveau, x.par) for x in r}
    assert noms == {
        "Dark.S01E01.WEB.mkv": ("Dark - S01E01 - Secrets.mkv", "plex"),
        "Dark.S01E01.WEB.fr.srt": ("Dark - S01E01 - Secrets.fr.srt", "plex"),   # le sous-titre suit
        "Dark.S01E02.WEB.mkv": ("Dark - S01E02.mkv", "regle"),                  # inconnu de Plex : nom propre
    }
    assert conflits == 1   # E03 : le nom voulu est déjà pris → ni écrasé ni suffixé
    # Inconnu de Plex mais déjà titré : le titre est gardé (cas réel de « The Gentlemen »).
    r, _ = te.renommages_du_dossier("Series/The Gentlemen/S01", {
        "The Gentlemen S01E01 - Raffinement et agressivité.mkv": 10}, "The Gentlemen", {})
    assert [x.nouveau for x in r] == ["The Gentlemen - S01E01 - Raffinement et agressivité.mkv"]


# --------------------------------------------------------------------------- #
# Client Plex (faux serveur)                                                   #
# --------------------------------------------------------------------------- #
def _faux_plex(jeton_ok="jeton-fictif"):
    def repondre(req: httpx.Request) -> httpx.Response:
        if req.headers.get("X-Plex-Token") != jeton_ok:
            return httpx.Response(401)
        if req.url.path == "/library/sections":
            return httpx.Response(200, json={"MediaContainer": {"Directory": [
                {"key": "2", "type": "show", "title": "Séries", "Location": [{"path": "/data/media/Series"}]},
                {"key": "1", "type": "movie", "title": "Films", "Location": [{"path": "/data/media/Films"}]}]}})
        if req.url.path == "/library/sections/2/all":
            assert req.url.params.get("type") == "4"
            return httpx.Response(200, json={"MediaContainer": {"Metadata": [
                {"grandparentTitle": "Westworld", "parentIndex": 1, "index": 1, "title": "Le Labyrinthe",
                 "Media": [{"Part": [{"file": "/data/media/Series/Westworld/S01/Westworld.S01E01.mkv"}]}]},
                {"grandparentTitle": "Westworld", "parentIndex": 1, "index": 2, "title": "Episode 2",
                 "Media": [{"Part": [{"file": "/data/media/Series/Westworld/S01/Westworld.S01E02.mkv"}]}]}]}})
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(repondre), base_url="http://plex.local:32400")


async def test_client_plex_lit_les_series():
    async with _faux_plex() as client:
        [b] = await plex.bibliotheques_series("http://plex.local:32400", "jeton-fictif", client=client)
    assert b.dossiers == ("/data/media/Series",) and len(b.episodes) == 2
    assert b.episodes[0].titre == "Le Labyrinthe" and (b.episodes[0].saison, b.episodes[0].episode) == (1, 1)
    assert plex.relatif(b.episodes[0].fichier, b.dossiers, {"series": "Series"}) == \
        "Series/Westworld/S01/Westworld.S01E01.mkv"


async def test_jeton_refuse_sans_le_divulguer():
    async with _faux_plex() as client:
        with pytest.raises(plex.PlexIndisponible) as exc:
            await plex.bibliotheques_series("http://plex.local:32400", "mauvais-jeton", client=client)
    assert "401" in str(exc.value) and "mauvais-jeton" not in str(exc.value)


# --------------------------------------------------------------------------- #
# Propositions, puis renommer et annuler                                       #
# --------------------------------------------------------------------------- #
def _ecrire(p: Path, n: int = 10) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * n)


@pytest.fixture
def depot(monkeypatch) -> DepotMemoire:
    d = DepotMemoire()
    monkeypatch.setattr(service, "fabrique", lambda: d)
    return d


async def test_proposer_renommer_puis_annuler(db_session, depot, tmp_path):
    r = tmp_path / "media"
    s01 = r / "Series" / "Westworld" / "S01"
    _ecrire(s01 / "Westworld.S01E01.mkv", 100)
    _ecrire(s01 / "Westworld.S01E01.fr.srt", 5)
    _ecrire(s01 / "Westworld.S01E02.mkv", 100)
    _ecrire(r / "Series" / "Arcane.S01.MULTi" / "Arcane.S01E01.mkv", 100)    # pack pas encore rangé : ignoré
    _ecrire(r / "Films" / "f" / "f.mkv", 1)
    emp = await depot.creer_emplacement("Médiathèque", str(r).replace("\\", "/"))
    await Scanner(depot, emp, Exclusions()).executer()
    await plan.charger_modele_media(db_session, depot, emp)
    async with _faux_plex() as client:
        biblios = await plex.bibliotheques_series("http://plex.local:32400", "jeton-fictif", client=client)

    bilan = await te.calculer(db_session, depot, emp, biblios)
    assert (bilan["proposees"], bilan["avec_titre"], bilan["sans_titre"]) == (3, 2, 1), bilan
    props = {p.chemin: p for p in (await db_session.execute(
        select(PlanProposition).where(PlanProposition.nouveau_nom.is_not(None)))).scalars().all()}
    assert props["Series/Westworld/S01/Westworld.S01E01.mkv"].nouveau_nom == "Westworld - S01E01 - Le Labyrinthe.mkv"
    assert props["Series/Westworld/S01/Westworld.S01E02.mkv"].nouveau_nom == "Westworld - S01E02.mkv"
    assert not any("Arcane" in c for c in props)

    # Le calcul du plan ne retire pas ces propositions (elles ne sont pas des « candidats »).
    await plan.calculer(db_session, depot, emp, ia=None)
    assert len((await db_session.execute(select(PlanProposition).where(
        PlanProposition.nouveau_nom.is_not(None)))).scalars().all()) == 3

    ids = [p.id for p in props.values()]
    for p in props.values():
        await plan.decider(db_session, p, "validee", "tclement")
    ops = await deplacements.apercu(db_session, depot, emp, ids)
    assert all(o["renommage"] and not o["renomme"] for o in ops) and len(ops) == 3
    lot = await deplacements.creer_lot(db_session, depot, emp, "titres", "tclement", ids)
    lot = await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    assert lot.statut == "range", lot.message
    assert sorted(p.name for p in s01.iterdir()) == [
        "Westworld - S01E01 - Le Labyrinthe.fr.srt", "Westworld - S01E01 - Le Labyrinthe.mkv", "Westworld - S01E02.mkv"]

    lot = await deplacements.annuler(db_session, lot, "tclement", emp)
    assert lot.statut == "annule", lot.message
    assert sorted(p.name for p in s01.iterdir()) == [
        "Westworld.S01E01.fr.srt", "Westworld.S01E01.mkv", "Westworld.S01E02.mkv"]

    # Recalcul : les décisions déjà prises (validées) sont gardées, rien n'est dupliqué.
    bilan = await te.calculer(db_session, depot, emp, biblios)
    assert bilan["gardees"] == 3 and bilan["proposees"] == 0, bilan


async def test_la_route_exige_plex_configure(client, db_session, depot, tmp_path):
    r = tmp_path / "media"
    _ecrire(r / "Films" / "f" / "f.mkv", 1)
    emp = await depot.creer_emplacement("Médiathèque", str(r).replace("\\", "/"))
    rep = await client.post(f"/api/inventaire/plan/titres/{emp.id}")
    assert rep.status_code == 400 and "Plex" in json.dumps(rep.json(), ensure_ascii=False)
