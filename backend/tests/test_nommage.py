"""
Règles de nommage et fichiers mal nommés (Rangement, 16/11/2026). Données fictives, aucun réseau.
"""

import pytest
from fakes.depot_memoire import DepotMemoire

from services.rangement import nommage as nm
from services.rangement import service
from services.rangement.exclusions import Exclusions
from services.rangement.scan import Scanner

D = nm.regles_par_defaut()


def raisons(chemin, regles=D):
    return nm.raisons(chemin, regles)[1]


# --------------------------------------------------------------------------- #
# Catégories et raisons                                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("chemin, categorie", [
    ("Series/Arcane/S01/Arcane - S01E01.mkv", "episodes"),
    ("Telechargements/Dark.S01E02.WEB.mkv", "episodes"),          # code d'épisode hors rubrique
    ("Films/Barbie (2023).mkv", "films"),
    ("Films/Barbie/Extras/Making of.mkv", "autre"),               # bonus : pas un film
    ("Videos perso/Mariage.mp4", "autre"),
    ("Musique/Queen/A Night/01 - Death on Two Legs.flac", "musique"),
    ("Photos/2024/IMG_1234.jpg", "photos"),
    ("Films/Barbie/poster.jpg", None),                           # jaquette
    ("Series/Arcane/S01/Arcane - S01E01.fr.srt", None),           # sous-titre
    ("Films/@eaDir/Barbie.mkv", None),                           # vignettes du NAS
    ("Documents/Thumbs.db", None),
])
def test_categorie(chemin, categorie):
    assert nm.categorie_de(chemin) == categorie


def test_episodes():
    assert raisons("Series/Arcane/S01/Arcane - S01E01 - Bienvenue.mkv") == []
    assert raisons("Series/Arcane/S01/Arcane - S01E01.mkv") == []                       # titre facultatif
    assert raisons("Series/Mr Robot/S04/Mr Robot - S04E13-E14 - Fin.mkv") == []
    assert raisons("Series/Dark/S01/Dark.S01E01.WEB.MULTi.1080p.x264.mkv") == ["episode_format", "separateurs", "etiquettes"]
    assert raisons("Series/Livre/S01/Livre 1.mkv") == ["episode_format"]


def test_films_selon_le_format():
    assert raisons("Films/Barbie (2023).mkv") == []
    assert raisons("Films/Barbie.mkv") == ["film_annee"]
    sans_annee = {**D, "films": nm.Regle(True, "titre")}
    assert raisons("Films/Barbie.mkv", sans_annee) == []
    assert raisons("Films/22.11.63.mkv", sans_annee) == []        # chiffres : pas des séparateurs
    eteint = {**D, "films": nm.Regle(False, "titre_annee")}
    assert raisons("Films/Barbie.mkv", eteint) == []


def test_musique_et_photos():
    assert raisons("Musique/Queen/01 - Bohemian Rhapsody.flac") == []
    assert raisons("Musique/Queen/Bohemian Rhapsody.flac") == ["musique_piste"]
    artiste = {**D, "musique": nm.Regle(True, "artiste_titre")}
    assert raisons("Musique/Queen - Bohemian Rhapsody.flac", artiste) == []
    assert raisons("Photos/IMG_1234.jpg") == []                   # photos éteintes par défaut
    photos = {**D, "photos": nm.Regle(True, "date")}
    assert raisons("Photos/IMG_1234.jpg", photos) == ["photo_date"]
    assert raisons("Photos/2024-07-14 Feu.jpg", photos) == []


def test_defauts_communs():
    assert raisons("Documents/Facture (1).pdf") == ["copie"]
    assert raisons("Documents/Facture - Copie.pdf") == ["copie"]
    assert raisons("Documents/Copie de Facture.pdf") == ["copie"]
    assert raisons("Documents/rapport_final_v2.pdf") == []        # « _ » toléré hors vidéo et musique
    assert raisons("Documents/Facture  mars.pdf") == ["espaces"]
    assert raisons("Documents/" + "x" * 151 + ".pdf") == ["long"]
    assert raisons("Videos perso/Le_Bon_Film.mp4") == ["separateurs"]
    assert raisons("Documents/French course.pdf") == []           # « French » : étiquette des vidéos seulement
    sans = {**D, "defauts": nm.Regle(False, "standard")}
    assert raisons("Documents/Facture (1).pdf", sans) == []


def test_bilan():
    b = nm.bilan([("Films/Barbie.mkv", 10), ("Films/Dune (2021).mkv", 20), ("Films/Barbie/poster.jpg", 1),
                  ("Series/Dark/S01/Dark.S01E01.mkv", 5), ("Documents/a (1).pdf", 2)], D)
    # « Dark.S01E01 » : un seul point entre lettres — il en faut deux pour parler de séparateurs.
    assert (b["fichiers"], b["analyses"], b["mal_nommes"], b["octets_mal_nommes"]) == (5, 4, 3, 17)
    assert [(c["code"], c["fichiers"], c["mal_nommes"]) for c in b["categories"]] == [
        ("episodes", 1, 1), ("films", 2, 1), ("autre", 1, 1)]
    assert {r["code"]: (r["nb"], r["exemples"]) for r in b["raisons"]} == {
        "episode_format": (1, ["Series/Dark/S01/Dark.S01E01.mkv"]),
        "film_annee": (1, ["Films/Barbie.mkv"]),
        "copie": (1, ["Documents/a (1).pdf"])}


def test_reglages_valides_et_tolerants():
    r = nm.valider({"films": {"actif": True, "format": "titre"}, "photos": {"actif": True}})
    assert r["films"] == nm.Regle(True, "titre") and r["photos"].actif and r["episodes"] == D["episodes"]
    with pytest.raises(ValueError, match="format inconnu"):
        nm.valider({"films": {"format": "n'importe quoi"}})
    with pytest.raises(ValueError, match="Catégorie inconnue"):
        nm.valider({"logiciels": {}})
    assert nm.depuis_json("pas du json") == D
    assert nm.depuis_json(nm.en_json(r)) == r


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #
@pytest.fixture
def depot(monkeypatch) -> DepotMemoire:
    d = DepotMemoire()
    monkeypatch.setattr(service, "fabrique", lambda: d)
    return d


def _ecrire(p, n=10):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * n)


async def test_routes_regles_et_statistiques(client, depot, tmp_path):
    r = tmp_path / "media"
    _ecrire(r / "Films" / "Barbie.mkv")
    _ecrire(r / "Films" / "Dune (2021).mkv")
    _ecrire(r / "Feuilletons" / "Dark" / "S01" / "Dark.S01E01.mkv")
    emp = await depot.creer_emplacement("Médiathèque", str(r).replace("\\", "/"))
    await Scanner(depot, emp, Exclusions()).executer()

    rep = await client.get(f"/api/inventaire/emplacements/{emp.id}/nommage")
    assert rep.status_code == 200
    b = rep.json()
    assert (b["fichiers"], b["mal_nommes"]) == (3, 2), b
    rep = await client.get(f"/api/inventaire/emplacements/{emp.id}/nommage", params={"chemin": "Films"})
    assert rep.json()["fichiers"] == 2

    regles = (await client.get("/api/inventaire/nommage/regles")).json()["regles"]
    assert [x["code"] for x in regles] == ["episodes", "films", "musique", "photos", "defauts"]
    rep = await client.put("/api/inventaire/nommage/regles", json={"films": {"actif": True, "format": "titre"}})
    assert rep.status_code == 200
    assert next(x for x in rep.json()["regles"] if x["code"] == "films")["format"] == "titre"
    assert (await client.get(f"/api/inventaire/emplacements/{emp.id}/nommage")).json()["mal_nommes"] == 1

    rep = await client.put("/api/inventaire/nommage/regles", json={"films": {"format": "inconnu"}})
    assert rep.status_code == 400
    assert (await client.get("/api/inventaire/emplacements/999999/nommage")).status_code == 404
    await client.put("/api/inventaire/nommage/regles", json={})   # remet les défauts (état partagé du cache)
