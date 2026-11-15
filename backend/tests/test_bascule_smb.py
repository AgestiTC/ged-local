"""
Bascule des emplacements « disque monté » vers SMB (étape 8 du plan Rangement sur Sources SMB).

L'emplacement garde son identifiant, donc ce qu'il sait (entrées, empreintes, instantanés) ; seul un
`prefixe` recentre l'inventaire sur un sous-dossier (cas « Home-TOM » déclaré sur `/mnt/rangement`).
Juge de paix : après la bascule, un scan par SMB du même arbre n'ajoute ni ne retire rien.
Données fictives, aucun réseau.
"""

from pathlib import Path

import pytest
from fakes.depot_memoire import DepotMemoire
from test_emplacement_smb import FauxPartage, _sources
from test_scan_smb import _ecrire, _nas_depuis, _source, _vus

from outils import rangement_smb
from services.rangement import bascule_smb, emplacement_smb
from services.rangement.erreurs import InventaireRefus
from services.rangement.exclusions import Exclusions
from services.rangement.scan import Scanner, exclusions_de

HOTE = "192.0.2.20"   # celui des Sources de test_emplacement_smb


@pytest.fixture(autouse=True)
def faux_smb(monkeypatch):
    FauxPartage.panne = False
    FauxPartage.ouvertures = []
    monkeypatch.setattr(FauxPartage, "dossiers", {"/Tom", "/Tom/Photos", "/media"})
    monkeypatch.setattr(emplacement_smb, "SessionSmb", FauxPartage)


@pytest.fixture
def monte(tmp_path: Path) -> Path:
    """`/mnt/rangement` fictif : tout le contenu est sous `homes-Tom/` (comme en prod)."""
    r = tmp_path / "rangement"
    _ecrire(r / "homes-Tom" / "Photos" / "2024" / "vacances.jpg", 100)
    _ecrire(r / "homes-Tom" / "homes-Tom" / "piege.txt", 7)   # même nom que le préfixe, un cran plus bas
    _ecrire(r / "homes-Tom" / "lisez-moi.txt", 2)
    # Dossier de l'UTILISATEUR au nom en « @ » : un cran sous la racine avant la bascule, À la racine
    # après. Cas réel du 15/11/2026 (528 Go comptés « disparus » par le premier scan de contrôle).
    _ecrire(r / "homes-Tom" / "@@@-trier URGENT" / "gros.mkv", 30)
    return r


async def _scanne(depot, racine: Path):
    emp = await depot.creer_emplacement("Home-TOM", str(racine))
    r = await Scanner(depot, emp, Exclusions()).executer()
    assert r.statut == "termine"
    return emp


async def test_a_blanc_rien_ne_change(db_session, monte):
    depot = DepotMemoire()
    ranger, _ = await _sources(db_session)
    emp = await _scanne(depot, monte)
    avant = {k: dict(v) for k, v in depot.entrees.items()}
    b = await bascule_smb.basculer(db_session, depot, emp.id, str(ranger.id), "homes", "/Tom", prefixe="homes-Tom")
    assert not b.applique and b.apres == f"smb://{HOTE}/homes/Tom" and b.avant == str(monte)
    assert (await depot.emplacement(emp.id)).source == "serveur" and depot.entrees == avant


async def test_bascule_simple_garde_tout(db_session, monte):
    depot = DepotMemoire()
    ranger, _ = await _sources(db_session)
    emp = await _scanne(depot, monte / "homes-Tom")
    avant = {k[1]: dict(v) for k, v in depot.entrees.items()}
    b = await bascule_smb.basculer(db_session, depot, emp.id, str(ranger.id), "homes", "/Tom", appliquer=True)
    assert b.applique and (b.entrees_gardees, b.entrees_retirees) == (len(avant), 0)
    e = await depot.emplacement(emp.id)
    assert (e.id, e.source, e.partage, e.sous_dossier, e.source_id) == (emp.id, "smb", "homes", "/Tom", str(ranger.id))
    assert e.racine == f"smb://{HOTE}/homes/Tom"
    assert {k[1]: v for k, v in depot.entrees.items()} == avant


async def test_le_prefixe_devient_la_racine(db_session, monte):
    depot = DepotMemoire()
    ranger, _ = await _sources(db_session)
    emp = await _scanne(depot, monte)
    ids = {k[1]: v["id"] for k, v in depot.entrees.items()}
    b = await bascule_smb.basculer(db_session, depot, emp.id, str(ranger.id), "homes", "/Tom",
                                   prefixe="/homes-Tom/", appliquer=True)
    assert b.entrees_retirees == 1   # l'entrée « homes-Tom » elle-même : elle devient la racine
    chemins = {k[1]: (v["parent"], v["id"]) for k, v in depot.entrees.items()}
    assert chemins == {
        "Photos": ("", ids["homes-Tom/Photos"]),
        "Photos/2024": ("Photos", ids["homes-Tom/Photos/2024"]),
        "Photos/2024/vacances.jpg": ("Photos/2024", ids["homes-Tom/Photos/2024/vacances.jpg"]),
        "homes-Tom": ("", ids["homes-Tom/homes-Tom"]),
        "homes-Tom/piege.txt": ("homes-Tom", ids["homes-Tom/homes-Tom/piege.txt"]),
        "lisez-moi.txt": ("", ids["homes-Tom/lisez-moi.txt"]),
        "@@@-trier URGENT": ("", ids["homes-Tom/@@@-trier URGENT"]),
        "@@@-trier URGENT/gros.mkv": ("@@@-trier URGENT", ids["homes-Tom/@@@-trier URGENT/gros.mkv"]),
    }
    inst = {(li["chemin"], li["profondeur"]) for li in depot.instantanes}
    assert ("", 0) in inst and ("Photos", 1) in inst and ("Photos/2024", 2) in inst
    assert not any(c.startswith("homes-Tom/Photos") for c, _ in inst)


async def test_apres_la_bascule_le_scan_smb_n_ajoute_ni_ne_retire_rien(db_session, monte):
    depot = DepotMemoire()
    ranger, _ = await _sources(db_session)
    emp = await _scanne(depot, monte)
    await bascule_smb.basculer(db_session, depot, emp.id, str(ranger.id), "homes", "/Tom",
                               prefixe="homes-Tom", appliquer=True)
    avant = _vus(depot)
    e = await depot.emplacement(emp.id)
    nas = _nas_depuis(monte / "homes-Tom")
    exclusions = await exclusions_de(depot, e, Exclusions())   # celles du vrai scan (worker)
    r = await Scanner(depot, e, exclusions, source=_source(nas, e, exclusions)).executer()
    assert r.statut == "termine", r.message
    assert (r.compteurs.nb_ajouts, r.compteurs.nb_disparus, r.compteurs.nb_erreurs) == (0, 0, 0)
    assert "@@@-trier URGENT/gros.mkv" in _vus(depot)
    assert _vus(depot) == avant


@pytest.mark.parametrize(("kw", "code"), [
    ({"prefixe": "../x"}, "prefixe_invalide"),
    ({"prefixe": "inconnu"}, "prefixe_inconnu"),
    ({"sous_dossier": "/Absent"}, "dossier_introuvable"),
    ({"partage": "a/b"}, "partage_invalide"),
])
async def test_refus_sans_rien_ecrire(db_session, monte, kw, code):
    depot = DepotMemoire()
    ranger, _ = await _sources(db_session)
    emp = await _scanne(depot, monte)
    avant = {k: dict(v) for k, v in depot.entrees.items()}
    args = {"partage": "homes", "sous_dossier": "/Tom", "prefixe": "homes-Tom"} | kw
    with pytest.raises(InventaireRefus) as exc:
        await bascule_smb.basculer(db_session, depot, emp.id, str(ranger.id), args["partage"], args["sous_dossier"],
                                   prefixe=args["prefixe"], appliquer=True)
    assert exc.value.code == code
    assert (await depot.emplacement(emp.id)).source == "serveur" and depot.entrees == avant


async def test_la_source_de_la_ged_est_refusee(db_session, monte):
    depot = DepotMemoire()
    _, ged = await _sources(db_session)
    emp = await _scanne(depot, monte)
    with pytest.raises(InventaireRefus) as exc:
        await bascule_smb.basculer(db_session, depot, emp.id, str(ged.id), "homes", "/Tom", appliquer=True)
    assert exc.value.code == "source_pas_rangement"


async def test_deja_smb_ou_racine_prise(db_session, monte):
    depot = DepotMemoire()
    ranger, _ = await _sources(db_session)
    emp = await _scanne(depot, monte / "homes-Tom")
    await bascule_smb.basculer(db_session, depot, emp.id, str(ranger.id), "homes", "/Tom", appliquer=True)
    with pytest.raises(InventaireRefus) as exc:
        await bascule_smb.basculer(db_session, depot, emp.id, str(ranger.id), "homes", "/Tom", appliquer=True)
    assert exc.value.code == "pas_serveur"
    autre = await depot.creer_emplacement("Autre", str(monte))
    with pytest.raises(InventaireRefus) as exc:
        await bascule_smb.basculer(db_session, depot, autre.id, str(ranger.id), "homes", "/Tom", appliquer=True)
    assert exc.value.code == "doublon"


async def test_scan_en_cours_refuse(db_session, monte):
    depot = DepotMemoire()
    ranger, _ = await _sources(db_session)
    emp = await _scanne(depot, monte)
    await depot.ouvrir_scan(emp.id, "manuel")
    with pytest.raises(InventaireRefus) as exc:
        await bascule_smb.basculer(db_session, depot, emp.id, str(ranger.id), "homes", "/Tom", prefixe="homes-Tom")
    assert exc.value.code == "scan_en_cours"


async def test_la_commande(db_session, monte):
    depot = DepotMemoire()
    ranger, _ = await _sources(db_session)
    emp = await _scanne(depot, monte)
    liste = await rangement_smb.executer(["--liste"], db_session, depot)
    assert "Home-TOM" in liste and f"{ranger.id}" in liste and "[Rangement]" in liste
    base = ["--emplacement", str(emp.id), "--source", str(ranger.id), "--partage", "homes", "--dossier", "/Tom",
            "--prefixe", "homes-Tom"]
    sortie = await rangement_smb.executer(base, db_session, depot)
    assert "À BLANC" in sortie and (await depot.emplacement(emp.id)).source == "serveur"
    sortie = await rangement_smb.executer(base + ["--appliquer"], db_session, depot)
    assert "BASCULÉ" in sortie and (await depot.emplacement(emp.id)).source == "smb"
    refus = await rangement_smb.executer(base + ["--appliquer"], db_session, depot)
    assert refus.startswith("REFUS (pas_serveur)")
    assert "s3cr3t" not in liste + sortie + refus


def test_les_arobases_de_tete_ne_sont_systeme_qu_a_la_racine_d_un_partage():
    base = Exclusions()
    assert base.exclut("@appstore", "@appstore", "/mnt/x/@appstore", 0, True) == "système"
    assert base.pour_smb("/").exclut("@appstore", "@appstore", "smb://h/p/@appstore", 0, True) == "système"
    sous = base.pour_smb("/Tom")
    assert sous.exclut("@@@-trier URGENT", "@@@-trier URGENT", "smb://h/homes/Tom/@@@-trier URGENT", 0, True) is None
    assert sous.exclut("@eaDir", "@eaDir", "smb://h/homes/Tom/@eaDir", 0, True) == "système"   # verrouillé partout


def test_les_copies_smb_lisent_aussi_les_dossiers_en_arobase():
    from services.rangement.copies_smb import LecteurSmb
    from services.rangement.depot import Emplacement
    tom = Emplacement(1, "Tom", f"smb://{HOTE}/homes/Tom", source="smb", partage="homes", sous_dossier="/Tom")
    tout = Emplacement(2, "media", f"smb://{HOTE}/media", source="smb", partage="media", sous_dossier="/")
    assert not LecteurSmb(tom, Exclusions()).exclu("@@@-trier URGENT/gros.mkv")
    assert LecteurSmb(tout, Exclusions()).exclu("@appstore/paquet.spk")
