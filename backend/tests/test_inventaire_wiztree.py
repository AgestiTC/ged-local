"""
Inventaire — import d'un export CSV de WizTree : lecture, prudence, ré-import, validation.

Porté de rangement (`tests/test_wiztree.py`). `tests/donnees/wiztree-exemple.csv` reprend un export
RÉEL de WizTree 4.33 (BOM, ligne d'information et en-tête traduits, nom avec virgule, dossier vide),
racine renommée C:\\Essai. Les écrans (formulaire d'import) viendront à l'étape 7.
"""

from datetime import timezone
from pathlib import Path

import pytest
from fakes.depot_memoire import DepotMemoire

from services.rangement import agent, wiztree
from services.rangement.erreurs import InventaireRefus

EXEMPLE = Path(__file__).parent / "donnees" / "wiztree-exemple.csv"
LIGNES = EXEMPLE.read_bytes().decode("utf-8-sig").splitlines()


@pytest.fixture
def nas(tmp_path) -> Path:
    r = tmp_path / "nas"
    r.mkdir()
    return r


@pytest.fixture
def depot() -> DepotMemoire:
    return DepotMemoire()


def _export(nas: Path, lignes: list[str], nom: str = "export.csv") -> Path:
    p = nas / nom
    p.write_bytes(("\ufeff" + "\r\n".join(lignes) + "\r\n").encode("utf-8"))
    return p


async def _importer(depot, chemin: Path, nas: Path, nom_pc: str = "PC-SALON", libelle: str = ""):
    resume = await wiztree.importer(depot, nom_pc, libelle, str(chemin), str(nas))
    return await depot.emplacement(resume["emplacement_id"])


def _presents(depot, emp_id: int) -> set[str]:
    return {e["chemin"] for e in depot.entrees.values()
            if e["emplacement_id"] == emp_id and e["disparu_scan_id"] is None}


# --------------------------------------------------------------------------- #
# Lecture                                                                      #
# --------------------------------------------------------------------------- #
def test_lecture_de_l_export_reel():
    assert wiztree.racine_du_fichier(str(EXEMPLE)) == "C:\\Essai"
    lots = []
    bilan = wiztree.lire(str(EXEMPLE), "C:\\Essai", timezone.utc, lots.extend)
    par_dossier = {d.chemin: sorted(e.nom for e in d.enfants) for d in lots}
    assert par_dossier[""] == ["Docs", "Photos", "Vide", "racine.txt"]
    assert par_dossier["Docs"] == ["facture, EDF.pdf"]          # virgule dans le nom
    assert par_dossier["Photos/Été 2024"] == ["plage.jpg"]      # accents
    assert par_dossier["Vide"] == []                            # dossier vide : listé, pas « illisible »
    assert (bilan.dossiers, bilan.fichiers) == (4, 3)


@pytest.mark.parametrize("texte", ["2026/10/14 23:26:00", "2026-10-14 23:26:00", "14/10/2026 23:26:00",
                                   "2026/10/14 23:26"])
def test_formats_de_date(texte):
    attendu = wiztree.date_en_secondes("2026/10/14 23:26:00", timezone.utc)
    assert wiztree.date_en_secondes(texte, timezone.utc) == attendu


def test_date_inconnue_refusee():
    with pytest.raises(wiztree.ImportRefuse):
        wiztree.date_en_secondes("hier soir", timezone.utc)


def test_racine_d_un_disque_entier(nas):
    p = _export(nas, [*LIGNES[:2], '"D:\\",10,10,2026/10/14 23:26:00,0,1,0',
                      '"D:\\a.txt",10,10,2026/10/14 23:26:00,32,0,0'])
    assert wiztree.racine_du_fichier(str(p)) == "D:\\"
    lots = []
    wiztree.lire(str(p), "D:\\", timezone.utc, lots.extend)
    assert [e.nom for d in lots for e in d.enfants] == ["a.txt"]


# --------------------------------------------------------------------------- #
# Import complet                                                               #
# --------------------------------------------------------------------------- #
async def test_import_complet(depot, nas):
    emp = await _importer(depot, _export(nas, LIGNES), nas)
    assert (emp.source, emp.racine, emp.libelle) == ("import", "C:\\Essai", "PC-SALON — C:\\Essai")
    scan = await depot.dernier_scan(emp.id)
    assert scan["statut"] == "termine" and scan["declencheur"] == "import"
    assert scan["nb_fichiers"] == 3 and scan["volume_octets"] == 154212
    assert (await depot.dossier(emp.id, "Photos")).totaux == (150000, 1, 1)
    poste = await depot.poste(emp.poste_id)
    assert poste.nom == "PC-SALON" and poste.dernier_contact is None and poste.jeton_id is None
    assert not depot.envoi_dossiers   # l'envoi est effacé une fois traité


async def test_libelle_choisi(depot, nas):
    emp = await _importer(depot, _export(nas, LIGNES), nas, libelle="Disque du salon")
    assert emp.libelle == "Disque du salon"


async def test_reimport_sans_changement_n_ecrit_rien(depot, nas):
    chemin = _export(nas, LIGNES)
    emp = await _importer(depot, chemin, nas)
    avant = depot.ecritures_entrees
    emp2 = await _importer(depot, chemin, nas)
    assert emp2.id == emp.id and depot.ecritures_entrees == avant


async def test_reimport_avec_un_fichier_en_moins(depot, nas):
    emp = await _importer(depot, _export(nas, LIGNES), nas)
    await _importer(depot, _export(nas, [ligne for ligne in LIGNES if "racine.txt" not in ligne]), nas)
    assert "racine.txt" not in _presents(depot, emp.id)
    assert "Docs/facture, EDF.pdf" in _presents(depot, emp.id)


@pytest.mark.parametrize("mauvaise", [
    '"C:\\Essai\\x.txt",abc,0,2026/10/14 23:26:00,32,0,0',     # taille illisible
    '"C:\\Ailleurs\\x.txt",1,0,2026/10/14 23:26:00,32,0,0',    # hors de la racine
    '"C:\\Essai\\x.txt",1,0,hier,32,0,0',                       # date inconnue
    '"C:\\Essai\\x.txt",1',                                      # colonnes manquantes
])
async def test_ligne_abimee_refuse_tout_l_import(depot, nas, mauvaise):
    emp = await _importer(depot, _export(nas, LIGNES), nas)
    avant = _presents(depot, emp.id)
    await _importer(depot, _export(nas, [ligne for ligne in LIGNES if "racine.txt" not in ligne] + [mauvaise]), nas)
    scan = await depot.dernier_scan(emp.id)
    assert scan["statut"] == "echec" and "rien n'a changé" in scan["message"]
    assert _presents(depot, emp.id) == avant   # racine.txt n'a PAS disparu
    assert not depot.envoi_dossiers


async def test_nom_piege_ecarte_sans_rien_faire_disparaitre(depot, nas):
    emp = await _importer(depot, _export(nas, [*LIGNES, '"C:\\Essai\\..",1,0,2026/10/14 23:26:00,32,0,0']), nas)
    assert ".." not in _presents(depot, emp.id) and "racine.txt" in _presents(depot, emp.id)


async def test_jonction_ignoree(depot, nas):
    emp = await _importer(depot, _export(nas, [*LIGNES, '"C:\\Essai\\Lien\\",0,0,2026/10/14 23:26:00,1040,0,0']), nas)
    assert "Lien" not in _presents(depot, emp.id)


async def test_exclusions_appliquees(depot, nas):
    lignes = [*LIGNES, '"C:\\Essai\\@eaDir\\",0,0,2026/10/14 23:26:00,16,0,0',
              '"C:\\Essai\\@eaDir\\v.jpg",5,0,2026/10/14 23:26:00,32,0,0']
    emp = await _importer(depot, _export(nas, lignes), nas)
    assert not any("@eaDir" in c for c in _presents(depot, emp.id))


# --------------------------------------------------------------------------- #
# Validation de la demande (dans le worker, sur le disque)                     #
# --------------------------------------------------------------------------- #
async def test_fichier_hors_racine_autorisee(depot, nas, tmp_path):
    dehors = tmp_path / "dehors.csv"
    dehors.write_text("x", encoding="utf-8")
    with pytest.raises(InventaireRefus, match="sous"):
        await wiztree.preparer(depot, "PC", "", str(dehors), str(nas))


@pytest.mark.parametrize("nom", ["export.txt", "absent.csv"])
async def test_fichier_refuse(depot, nas, nom):
    if nom.endswith(".txt"):
        (nas / nom).write_text("x", encoding="utf-8")
    with pytest.raises(InventaireRefus):
        await wiztree.preparer(depot, "PC", "", str(nas / nom), str(nas))


async def test_pas_un_export_wiztree(depot, nas):
    p = nas / "autre.csv"
    p.write_text("a,b\n1,2\n3,4\n5,6\n7,8\n9,10\n11,12\n", encoding="utf-8")
    with pytest.raises(InventaireRefus, match="illisible"):
        await wiztree.preparer(depot, "PC", "", str(p), str(nas))


async def test_chemin_relatif_refuse(depot, nas):
    with pytest.raises(InventaireRefus):
        await wiztree.preparer(depot, "PC", "", "export.csv", str(nas))


async def test_import_qui_chevauche_un_autre_emplacement_du_meme_pc(depot, nas):
    poste = await agent.creer_poste_sans_jeton(depot, "PC-SALON")
    await agent.declarer_emplacement(depot, poste.id, "Tout C", "C:\\")
    with pytest.raises(InventaireRefus, match="Chevauche"):
        await wiztree.preparer(depot, "pc-salon", "", str(_export(nas, LIGNES)), str(nas))


async def test_fichier_illisible_aucun_poste_cree(depot, nas, monkeypatch):
    chemin = _export(nas, LIGNES)

    def refus(*_a, **_k):
        raise PermissionError("accès refusé")

    monkeypatch.setattr(wiztree, "racine_du_fichier", refus)
    with pytest.raises(InventaireRefus, match="illisible"):
        await wiztree.preparer(depot, "PC", "", str(chemin), str(nas))
    assert await depot.postes() == []


async def test_nom_de_poste_invalide(depot, nas):
    with pytest.raises(InventaireRefus):
        await wiztree.preparer(depot, "PC/../x", "", str(_export(nas, LIGNES)), str(nas))
    assert await depot.postes() == []
