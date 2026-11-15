"""
Règle de nommage des séries (Rangement, 15/11/2026) — `Series/<Titre>/S01/<épisodes>`.

Un pack téléchargé est VIDÉ dans sa saison (les fichiers gardent leur nom), un épisode égaré dans Films
rejoint sa série, ce qui est ambigu n'est pas touché, un doublon identique n'est pas renommé « _(2) ».
Données fictives, faux partage dans un dossier temporaire, dépôt en mémoire.
"""

from pathlib import Path

import pytest
from fakes.depot_memoire import DepotMemoire
from sqlalchemy import select

from models.plan_classement import PlanNoeud, PlanProposition
from services.rangement import deplacements, plan, series, service
from services.rangement.exclusions import Exclusions
from services.rangement.scan import Scanner


def _ecrire(p: Path, n: int = 10) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * n)


# --------------------------------------------------------------------------- #
# Lecture des noms (pur)                                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("nom", "attendu"), [
    ("Adolescence.S01.FRENCH.WEBRip.x264", ("Adolescence", 1)),
    ("Arcane.S02.MULTi.HDR.DV.1080p.WEB.H265-FW", ("Arcane", 2)),
    ("Outlander.Blood.of.My.Blood.S01E09.MULTi.HDR.2160p.WEB.H265-FW", ("Outlander Blood of My Blood", 1)),
    ("Young.Sherlock.2026.S01.MULTi.VFF.1080p.WEB.H265-TyHD", ("Young Sherlock 2026", 1)),
    ("Westworld.S01", ("Westworld", 1)),
    ("Breaking.Bad.S01E01.mkv", ("Breaking Bad", 1)),
    ("22.11.63.S01E03.FRENCH.mkv", ("22.11.63", 1)),          # le triple point est gardé
    ("Mr.Robot.S04E13-E14.mkv", ("Mr Robot", 4)),
    ("The_Office_S03E05.avi", ("The Office", 3)),
])
def test_lire_titre_et_saison(nom, attendu):
    ep = series.lire(nom)
    assert ep is not None and (ep.titre, ep.saison) == attendu


@pytest.mark.parametrize("nom", ["22.11.63", "Quantum.Leap.1989.iNTEGRALE.MULTi.1080p.WEB.H265-TyHD",
                                 "Livre 1", "Dark", "The Sinner [Integral 2017-2021]", "Season.S00"])
def test_un_nom_sans_saison_n_est_pas_un_episode(nom):
    assert series.lire(nom) is None


def test_le_triple_point_n_est_pas_touche():
    assert series.nettoyer_titre("22.11.63") == "22.11.63"
    assert series.nettoyer_titre("Stranger.Things") == "Stranger Things"


def test_dossier_de_saison_et_titre_existant():
    assert [series.saison_de_dossier(n) for n in ("S01", "S1", "Saison 2", "Season 03", "Livre 1", "1")] == \
        [1, 1, 2, 3, None, None]
    existants = {series.cle(n): n for n in ("STRANGER THINGS", "Rick et Morty", "L'amie prodigieuse")}
    assert series.dossier_serie("Stranger Things", existants) == "STRANGER THINGS"
    assert series.dossier_serie("L amie prodigieuse", existants) == "L'amie prodigieuse"
    assert series.dossier_serie("Nouvelle Serie", existants) == "Nouvelle Serie"


# --------------------------------------------------------------------------- #
# Plan : propositions                                                          #
# --------------------------------------------------------------------------- #
@pytest.fixture
def depot(monkeypatch) -> DepotMemoire:
    d = DepotMemoire()
    monkeypatch.setattr(service, "fabrique", lambda: d)
    return d


@pytest.fixture
async def media(tmp_path, depot):
    r = tmp_path / "media"
    _ecrire(r / "Films" / "Le Film (2020)" / "film.mkv", 500)
    _ecrire(r / "Films" / "Breaking.Bad.S01E01.mkv", 300)                               # épisode égaré
    # Un épisode en double : dans Films ET à la racine de Series (cas réel d'Outlander).
    for ou in ("Films", "Series"):
        _ecrire(r / ou / "Outlander.Blood.S01E09.FW" / "Outlander.Blood.S01E09.FW.mkv", 800)
        _ecrire(r / ou / "Outlander.Blood.S01E09.FW" / "Outlander.Blood.S01E09.FW.nfo", 7)
    _ecrire(r / "Series" / "Adolescence.S01.FRENCH" / "Adolescence.S01E01.mp4", 100)    # pack à la racine
    _ecrire(r / "Series" / "Adolescence.S01.FRENCH" / "Adolescence.S01E02.mp4", 100)
    _ecrire(r / "Series" / "Arcane" / "Arcane.S02.MULTi" / "Arcane.S02E01.mkv", 200)      # pack dans sa série
    _ecrire(r / "Series" / "Arcane" / "S01" / "Arcane.S01E01.mkv", 200)                   # déjà rangé
    _ecrire(r / "Series" / "Dark" / "Saison 2" / "Dark.S02E01.mkv", 150)                  # saison mal nommée
    _ecrire(r / "Series" / "22.11.63" / "1" / "ep1.mkv", 90)                              # ambigu : pas touché
    _ecrire(r / "Series" / "STRANGER THINGS" / "Stranger.Things.S05E01.mkv", 120)         # épisode isolé
    _ecrire(r / "Series" / "Stranger.Things.S04.VF" / "Stranger.Things.S04E01.mkv", 110)  # pack → titre existant
    emp = await depot.creer_emplacement("Médiathèque", str(r).replace("\\", "/"))
    await Scanner(depot, emp, Exclusions()).executer()
    return emp, r


async def _calcul(db, depot, emp):
    await plan.charger_modele_media(db, depot, emp)
    await plan.calculer(db, depot, emp, ia=None)
    return {p.chemin: p for p in (await db.execute(select(PlanProposition))).scalars().all()}


async def test_la_rubrique_series_prend_la_regle(db_session, depot, media):
    emp, _ = media
    await plan.charger_modele_media(db_session, depot, emp)
    n = (await db_session.execute(select(PlanNoeud).where(PlanNoeud.chemin == "Series"))).scalar_one()
    assert n.gabarit == series.GABARIT


async def test_propositions_des_series(db_session, depot, media):
    emp, _ = media
    props = await _calcul(db_session, depot, emp)
    att = {
        "Series/Adolescence.S01.FRENCH": ("Series/Adolescence/S01", True, "proposee"),
        "Series/Arcane/Arcane.S02.MULTi": ("Series/Arcane/S02", True, "proposee"),
        "Series/Arcane/S01": ("Series/Arcane/S01", True, "en_place"),
        "Series/Dark/Saison 2": ("Series/Dark/S02", True, "proposee"),
        "Series/STRANGER THINGS/Stranger.Things.S05E01.mkv": ("Series/STRANGER THINGS/S05", False, "proposee"),
        "Series/Stranger.Things.S04.VF": ("Series/STRANGER THINGS/S04", True, "proposee"),
        "Series/Outlander.Blood.S01E09.FW": ("Series/Outlander Blood/S01", True, "proposee"),
        "Films/Outlander.Blood.S01E09.FW": ("Series/Outlander Blood/S01", True, "proposee"),
        "Films/Breaking.Bad.S01E01.mkv": ("Series/Breaking Bad/S01", False, "proposee"),
    }
    for chemin, (dest, contenu, statut) in att.items():
        p = props[chemin]
        assert (p.destination, p.contenu, p.statut) == (dest, contenu, statut), chemin
    # Ambigu : ni le dossier « 22.11.63 », ni son « 1 » ne sont proposés.
    assert not any(c.startswith("Series/22.11.63") for c in props)
    # Les dossiers de série eux-mêmes ne sont plus des candidats.
    assert "Series/Arcane" not in props and "Series/Dark" not in props


async def test_ranger_puis_annuler_un_pack(db_session, depot, media):
    emp, r = media
    props = await _calcul(db_session, depot, emp)
    ids = []
    for chemin in ("Series/Adolescence.S01.FRENCH", "Films/Outlander.Blood.S01E09.FW",
                   "Series/Outlander.Blood.S01E09.FW", "Films/Breaking.Bad.S01E01.mkv"):
        await plan.decider(db_session, props[chemin], "validee", "tclement")
        ids.append(props[chemin].id)
    ops = await deplacements.apercu(db_session, depot, emp, ids)
    sources = sorted(o["source"] for o in ops)
    # Le pack donne une opération par épisode ; les deux Outlander identiques n'en donnent qu'UNE paire
    # (le second est un doublon : il reste où il est, jamais renommé « _(2) »).
    assert not any(o["renomme"] for o in ops)
    assert sum("Outlander" in s for s in sources) == 2
    assert "Series/Adolescence.S01.FRENCH/Adolescence.S01E01.mp4" in sources

    lot = await deplacements.creer_lot(db_session, depot, emp, "séries", "tclement", ids)
    lot = await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    assert lot.statut == "range", lot.message
    assert (r / "Series" / "Adolescence" / "S01" / "Adolescence.S01E01.mp4").is_file()
    assert (r / "Series" / "Adolescence" / "S01" / "Adolescence.S01E02.mp4").is_file()
    assert (r / "Series" / "Breaking Bad" / "S01" / "Breaking.Bad.S01E01.mkv").is_file()
    assert (r / "Series" / "Outlander Blood" / "S01" / "Outlander.Blood.S01E09.FW.mkv").is_file()
    assert not list((r / "Series" / "Adolescence.S01.FRENCH").iterdir())      # le pack reste, vide

    lot = await deplacements.annuler(db_session, lot, "tclement", emp)
    assert lot.statut == "annule", lot.message
    assert (r / "Series" / "Adolescence.S01.FRENCH" / "Adolescence.S01E01.mp4").is_file()
    assert (r / "Films" / "Breaking.Bad.S01E01.mkv").is_file()
    assert not list((r / "Series" / "Adolescence" / "S01").iterdir())
