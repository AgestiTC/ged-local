"""
Inventaire — la vue « carte » d'un dossier (sous-dossiers triés, types, plus gros fichiers,
évolution), lue dans le dépôt en mémoire. Porté de rangement (`tests/test_carte_lecture.py`) ; la mise
en forme française (« 3,2 To ») reviendra à l'écran React (étape 7), elle n'est pas portée ici.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fakes.depot_memoire import DepotMemoire

from services.rangement.carte import famille, vue_dossier
from services.rangement.exclusions import Exclusions
from services.rangement.scan import Scanner

MAINTENANT = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("ext,attendu", [
    ("jpg", "Photos"), ("HEIC", "Photos"), ("mkv", "Vidéos"), ("mp3", "Audio"),
    ("pdf", "Documents"), ("7z", "Archives"), ("exe", "Logiciels"), ("xyz", "Autres"), (None, "Autres"),
])
def test_famille(ext, attendu):
    assert famille(ext) == attendu


def _ecrire(p: Path, octets: int) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"a" * octets)


@pytest.fixture
async def scanne(tmp_path):
    r = tmp_path / "nas"
    _ecrire(r / "Photos" / "2024" / "vacances.jpg", 600)
    _ecrire(r / "Photos" / "2023" / "noel.jpg", 200)
    _ecrire(r / "Documents" / "avis.pdf", 150)
    _ecrire(r / "Documents" / "notes.txt", 50)
    _ecrire(r / "lisez-moi.txt", 0)
    depot = DepotMemoire()
    emp = await depot.creer_emplacement("NAS", str(r))
    await Scanner(depot, emp, Exclusions()).executer()
    return depot, emp, r


async def test_racine_triee_par_taille_avec_pourcentages(scanne):
    depot, emp, _ = scanne
    vue = await vue_dossier(depot, emp, "", MAINTENANT)
    assert [li.nom for li in vue.lignes] == ["Photos", "Documents", "lisez-moi.txt"]
    assert vue.taille == 1000 and vue.nb_fichiers == 5
    assert [li.pourcent for li in vue.lignes] == [80, 20, 0]
    assert vue.lignes[0].est_dossier and vue.lignes[0].chemin == "Photos"
    assert vue.lignes[0].nb_fichiers == 2


async def test_sous_dossier_et_fil_d_ariane(scanne):
    depot, emp, _ = scanne
    vue = await vue_dossier(depot, emp, "Photos/2024", MAINTENANT)
    assert [(e.libelle, e.chemin) for e in vue.fil] == [("NAS", ""), ("Photos", "Photos"),
                                                         ("2024", "Photos/2024")]
    assert [li.nom for li in vue.lignes] == ["vacances.jpg"] and vue.taille == 600


async def test_dossier_inconnu_ou_fichier(scanne):
    depot, emp, _ = scanne
    assert await vue_dossier(depot, emp, "Nexiste/pas", MAINTENANT) is None
    assert await vue_dossier(depot, emp, "lisez-moi.txt", MAINTENANT) is None


async def test_types_par_famille(scanne):
    depot, emp, _ = scanne
    vue = await vue_dossier(depot, emp, "", MAINTENANT)
    assert [(t.famille, t.octets, t.pourcent) for t in vue.types] == [("Photos", 800, 80), ("Documents", 200, 20)]
    docs = await vue_dossier(depot, emp, "Documents", MAINTENANT)
    assert [(t.famille, t.octets) for t in docs.types] == [("Documents", 200)]


async def test_plus_gros_fichiers(scanne):
    depot, emp, _ = scanne
    vue = await vue_dossier(depot, emp, "", MAINTENANT, nb_gros=2)
    assert [(g.chemin, g.taille) for g in vue.gros] == [("Photos/2024/vacances.jpg", 600),
                                                         ("Photos/2023/noel.jpg", 200)]


async def test_evolution_depuis_le_scan_precedent(scanne):
    depot, emp, racine = scanne
    _ecrire(racine / "Photos" / "2024" / "plage.jpg", 400)
    await Scanner(depot, emp, Exclusions()).executer()
    vue = await vue_dossier(depot, emp, "", MAINTENANT)
    assert next(li for li in vue.lignes if li.nom == "Photos").variation == 400
    assert next(li for li in vue.lignes if li.nom == "Documents").variation == 0
    assert [(c.chemin, c.variation) for c in vue.croissances][:2] == [("Photos", 400), ("Photos/2024", 400)]


async def test_sans_scan_precedent_pas_d_evolution(scanne):
    depot, emp, _ = scanne
    vue = await vue_dossier(depot, emp, "", MAINTENANT)
    assert all(li.variation is None for li in vue.lignes) and vue.croissances == []


async def test_limite_de_lignes(scanne):
    depot, emp, _ = scanne
    vue = await vue_dossier(depot, emp, "", MAINTENANT, limite=2)
    assert len(vue.lignes) == 2 and vue.reste == 1
