"""
Inventaire (module Rangement, étape 4) — parcours, comparaison, instantané, exclusions, tournée de nuit.

Porté des tests de rangement (`tests/test_inventaire_scan.py`, `test_inventaire_exclusions.py`) sur le
dépôt en mémoire, qui compte chaque écriture : c'est ce qui vérifie la promesse centrale — **un
rescan sans changement n'écrit aucune ligne** — et que rien n'est marqué « disparu » sur un simple
doute (dossier illisible, partage démonté).
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fakes.depot_memoire import DepotMemoire

from services.rangement.depot import ScanEnCours
from services.rangement.exclusions import NOMS_VERROUILLES, Exclusions
from services.rangement.reglages import ReglagesInventaire
from services.rangement.scan import Scanner, dans_fenetre, planifier_et_scanner

NOM_LONG = "rapport-" + "x" * 140 + ".pdf"


def _ecrire(p: Path, octets: int = 10) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"a" * octets)
    return p


@pytest.fixture
def arbo(tmp_path: Path) -> Path:
    r = tmp_path / "nas"
    _ecrire(r / "Photos" / "2024" / "vacances.jpg", 100)
    _ecrire(r / "Photos" / "@eaDir" / "vacances.jpg" / "SYNOPHOTO_THUMB.jpg", 5)
    _ecrire(r / "Documents" / "Impôts été" / "avis.pdf", 40)
    _ecrire(r / "Documents" / NOM_LONG, 7)
    (r / "Documents" / "vide").mkdir(parents=True)
    _ecrire(r / "#recycle" / "ancien.txt", 3)
    _ecrire(r / "@appstore" / "paquet.spk", 3)
    _ecrire(r / "backup" / "pbs" / ".chunks" / "0001", 999)
    _ecrire(r / "lisez-moi.txt", 2)
    return r


@pytest.fixture
def depot() -> DepotMemoire:
    return DepotMemoire()


async def _scanner(depot: DepotMemoire, racine: Path, **kw) -> Scanner:
    emps = await depot.emplacements()
    emp = emps[0] if emps else await depot.creer_emplacement("NAS", str(racine))
    ex = kw.pop("exclusions", Exclusions.depuis_reglages(motifs="", chemins=str(racine / "backup" / "pbs")))
    return Scanner(depot, emp, ex, **kw)


async def _scan(depot: DepotMemoire, racine: Path, **kw):
    return await (await _scanner(depot, racine, **kw)).executer()


def _presents(depot: DepotMemoire) -> set[str]:
    return {e["chemin"] for e in depot.entrees.values() if e["disparu_scan_id"] is None}


# --------------------------------------------------------------------------- #
# Exclusions                                                                   #
# --------------------------------------------------------------------------- #
def _exclut(ex: Exclusions, nom: str, rel: str | None = None, abs_: str | None = None,
            profondeur: int = 1, dossier: bool = True) -> str | None:
    rel = rel or nom
    abs_ = abs_ or os.path.join(os.sep, "nas", *rel.split("/"))
    return ex.exclut(nom, rel, abs_, profondeur, dossier)


def test_noms_systeme_verrouilles_a_toute_profondeur():
    ex = Exclusions()
    for nom in ("@eaDir", "#recycle", "#snapshot", "DOUBLON-MATOTEQUE"):
        assert nom in NOMS_VERROUILLES
        assert _exclut(ex, nom, f"Photos/2024/{nom}", profondeur=3) == "système"


def test_dossier_arobase_exclu_seulement_a_la_racine():
    ex = Exclusions()
    assert _exclut(ex, "@appstore", profondeur=0) == "système"
    assert _exclut(ex, "@archives-2019", "Famille/@archives-2019", profondeur=2) is None
    assert _exclut(ex, "@note.txt", profondeur=0, dossier=False) is None


def test_datastore_pbs_exclu_avec_tout_son_contenu(tmp_path):
    pbs = tmp_path / "backup" / "pbs"
    ex = Exclusions.depuis_reglages(motifs="", chemins=str(pbs))
    assert _exclut(ex, "pbs", "backup/pbs", str(pbs)) == "sauvegarde"
    sous = pbs / ".chunks" / "0001"
    assert _exclut(ex, "0001", "backup/pbs/.chunks/0001", str(sous), profondeur=3) == "sauvegarde"
    voisin = tmp_path / "backup" / "pbs-notes"   # un voisin au nom proche n'est PAS exclu
    assert _exclut(ex, "pbs-notes", "backup/pbs-notes", str(voisin)) is None


def test_motifs_du_reglage_sur_le_nom_ou_le_chemin():
    ex = Exclusions.depuis_reglages(motifs="*.tmp, Thumbs.db\nTelechargements/cache*", chemins="")
    assert _exclut(ex, "a.tmp", "Docs/a.tmp", dossier=False) == "réglage"
    assert _exclut(ex, "Thumbs.db", "Photos/Thumbs.db", dossier=False) == "réglage"
    assert _exclut(ex, "cache-firefox", "Telechargements/cache-firefox") == "réglage"
    assert _exclut(ex, "rapport.pdf", "Docs/rapport.pdf", dossier=False) is None


def test_reglages_vides_et_verrous_inamovibles():
    ex = Exclusions.depuis_reglages(motifs=" , \n ,", chemins="  ")
    assert ex.motifs == () and ex.chemins_absolus == ()
    ex = Exclusions.depuis_reglages(motifs="!@eaDir", chemins="")
    assert _exclut(ex, "@eaDir", "Photos/@eaDir", profondeur=1) == "système"
    assert Exclusions().exclut("#Recycle", "#Recycle", "/nas/#Recycle", 0, True) == "système"


# --------------------------------------------------------------------------- #
# Premier scan                                                                 #
# --------------------------------------------------------------------------- #
async def test_premier_scan_inventorie_sans_les_exclusions(arbo, depot):
    res = await _scan(depot, arbo)
    assert res.statut == "termine"
    assert _presents(depot) == {
        "Photos", "Photos/2024", "Photos/2024/vacances.jpg",
        "Documents", "Documents/Impôts été", "Documents/Impôts été/avis.pdf",
        f"Documents/{NOM_LONG}", "Documents/vide",
        "backup", "lisez-moi.txt",
    }
    c = res.compteurs
    assert (c.nb_fichiers, c.volume_octets) == (4, 100 + 40 + 7 + 2)
    assert c.nb_dossiers == 6
    assert c.nb_ajouts == 10 and c.nb_modifs == 0 and c.nb_disparus == 0


async def test_ne_lit_jamais_le_contenu(arbo, depot, monkeypatch):
    def interdit(*a, **k):
        raise AssertionError("le parcours ne doit ouvrir aucun fichier")
    monkeypatch.setattr("builtins.open", interdit)
    assert (await _scan(depot, arbo)).statut == "termine"


# --------------------------------------------------------------------------- #
# Rescan                                                                       #
# --------------------------------------------------------------------------- #
async def test_rescan_sans_changement_n_ecrit_aucune_entree(arbo, depot):
    await _scan(depot, arbo)
    avant = depot.ecritures_entrees
    res = await _scan(depot, arbo)
    assert depot.ecritures_entrees == avant
    assert (res.compteurs.nb_ajouts, res.compteurs.nb_modifs, res.compteurs.nb_disparus) == (0, 0, 0)


async def test_fichier_modifie_est_detecte(arbo, depot):
    await _scan(depot, arbo)
    _ecrire(arbo / "lisez-moi.txt", 50)
    res = await _scan(depot, arbo)
    assert res.compteurs.nb_modifs == 1
    e = depot.entree(1, "lisez-moi.txt")
    assert e["taille"] == 50 and e["modifie_scan_id"] == res.scan_id


async def test_fichier_et_dossier_disparus_avec_leur_contenu(arbo, depot):
    await _scan(depot, arbo)
    (arbo / "lisez-moi.txt").unlink()
    (arbo / "Photos" / "2024" / "vacances.jpg").unlink()
    (arbo / "Photos" / "2024").rmdir()
    res = await _scan(depot, arbo)
    assert not ({"lisez-moi.txt", "Photos/2024", "Photos/2024/vacances.jpg"} & _presents(depot))
    assert res.compteurs.nb_disparus == 3
    # Rien n'est effacé : l'historique garde la trace.
    assert depot.entree(1, "Photos/2024/vacances.jpg")["disparu_scan_id"] == res.scan_id


async def test_un_fichier_qui_revient_reapparait(arbo, depot):
    await _scan(depot, arbo)
    contenu = (arbo / "lisez-moi.txt").read_bytes()
    (arbo / "lisez-moi.txt").unlink()
    await _scan(depot, arbo)
    (arbo / "lisez-moi.txt").write_bytes(contenu)
    await _scan(depot, arbo)
    assert "lisez-moi.txt" in _presents(depot)


async def test_changement_de_type_fichier_devient_dossier(arbo, depot):
    await _scan(depot, arbo)
    (arbo / "lisez-moi.txt").unlink()
    _ecrire(arbo / "lisez-moi.txt" / "dedans.txt", 1)
    await _scan(depot, arbo)
    assert depot.entree(1, "lisez-moi.txt")["est_dossier"] is True
    assert "lisez-moi.txt/dedans.txt" in _presents(depot)


# --------------------------------------------------------------------------- #
# Prudence : jamais « disparu » sur un doute                                   #
# --------------------------------------------------------------------------- #
def _scandir_refuse(cible: Path):
    vrai = os.scandir

    def scandir(chemin):
        if os.path.normpath(str(chemin)) == os.path.normpath(str(cible)):
            raise PermissionError("accès refusé")
        return vrai(chemin)
    return scandir


async def test_dossier_illisible_ne_fait_rien_disparaitre(arbo, depot, monkeypatch):
    await _scan(depot, arbo)
    monkeypatch.setattr("services.rangement.scan.os.scandir", _scandir_refuse(arbo / "Documents"))
    res = await _scan(depot, arbo)
    assert res.statut == "termine" and res.compteurs.nb_erreurs == 1
    assert "Documents/Impôts été/avis.pdf" in _presents(depot)


async def test_racine_vide_alors_que_l_inventaire_est_peuple_abandonne(arbo, depot, tmp_path):
    await _scan(depot, arbo)
    for enfant in list(arbo.iterdir()):
        enfant.rename(tmp_path / f"cache-{enfant.name}")
    res = await _scan(depot, arbo)
    assert res.statut == "echec" and "vide" in res.message
    assert "lisez-moi.txt" in _presents(depot)


async def test_racine_absente_echoue_proprement(tmp_path, depot):
    await depot.creer_emplacement("NAS", str(tmp_path / "absent"))
    assert (await _scan(depot, tmp_path / "absent")).statut == "echec"


@pytest.mark.skipif(os.name == "nt", reason="liens symboliques soumis à privilège sous Windows")
async def test_liens_symboliques_ignores(arbo, depot):
    os.symlink(arbo / "Photos", arbo / "raccourci")
    await _scan(depot, arbo)
    assert "raccourci" not in _presents(depot)


async def test_racine_devenue_lien_symbolique_refusee(arbo, depot, tmp_path, monkeypatch):
    emp = await depot.creer_emplacement("NAS", str(arbo))
    monkeypatch.setattr("services.rangement.scan.os.path.realpath", lambda p: str(tmp_path / "ailleurs"))
    res = await Scanner(depot, emp, Exclusions()).executer()
    assert res.statut == "echec" and "lien" in res.message


async def test_racine_hors_du_perimetre_autorise_refusee(arbo, depot, tmp_path):
    """L'API ne voit pas le NAS : c'est le worker qui confronte le chemin réel au périmètre."""
    autorise = tmp_path / "montage"
    autorise.mkdir()
    emp = await depot.creer_emplacement("NAS", str(arbo))
    res = await Scanner(depot, emp, Exclusions(), racine_autorisee=str(autorise)).executer()
    assert res.statut == "echec" and "racine autorisée" in res.message
    assert _presents(depot) == set()
    ok = await Scanner(depot, emp, Exclusions(), racine_autorisee=str(tmp_path)).executer()
    assert ok.statut == "termine"


class _EntreeFactice:
    """Entrée de `os.scandir` fabriquée : nom non encodable."""

    def __init__(self, nom: str, chemin: str) -> None:
        self.name, self.path = nom, chemin

    def is_symlink(self) -> bool:
        return False

    def is_dir(self, follow_symlinks: bool = True) -> bool:
        return False

    def is_file(self, follow_symlinks: bool = True) -> bool:
        return True

    def stat(self, follow_symlinks: bool = True):
        return os.stat(__file__)


class _Iterateur:
    def __init__(self, entrees, erreur_apres: int | None = None) -> None:
        self._entrees, self._erreur_apres = list(entrees), erreur_apres

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def __iter__(self):
        for i, e in enumerate(self._entrees):
            if self._erreur_apres is not None and i == self._erreur_apres:
                raise OSError("partage déconnecté")
            yield e


async def test_nom_non_utf8_ignore_et_compte(arbo, depot, monkeypatch):
    vrai = os.scandir
    cible = os.path.normpath(str(arbo / "Documents"))

    def scandir(chemin):
        if os.path.normpath(str(chemin)) == cible:
            mauvais = _EntreeFactice("caf\udce9.txt", os.path.join(cible, "cafe.txt"))
            return _Iterateur([*list(vrai(chemin)), mauvais])
        return vrai(chemin)

    monkeypatch.setattr("services.rangement.scan.os.scandir", scandir)
    res = await _scan(depot, arbo)
    assert res.statut == "termine" and res.compteurs.nb_erreurs == 1
    assert "partiels" in res.message
    assert not any("\udce9" in c for c in _presents(depot))


async def test_coupure_pendant_la_lecture_d_un_dossier(arbo, depot, monkeypatch):
    await _scan(depot, arbo)
    vrai = os.scandir
    cible = os.path.normpath(str(arbo / "Documents"))

    def scandir(chemin):
        if os.path.normpath(str(chemin)) == cible:
            return _Iterateur(list(vrai(chemin)), erreur_apres=1)
        return vrai(chemin)

    monkeypatch.setattr("services.rangement.scan.os.scandir", scandir)
    res = await _scan(depot, arbo)
    assert res.statut == "termine" and res.compteurs.nb_erreurs == 1
    assert f"Documents/{NOM_LONG}" in _presents(depot)   # tenu pour illisible : rien n'en disparaît


# --------------------------------------------------------------------------- #
# Instantané, pause, concurrence                                               #
# --------------------------------------------------------------------------- #
async def test_instantane_par_dossier_jusqu_a_la_profondeur_reglee(arbo, depot):
    res = await _scan(depot, arbo, profondeur_instantane=1)
    lignes = {li["chemin"]: li for li in depot.instantanes if li["scan_id"] == res.scan_id}
    assert set(lignes) == {"", "Photos", "Documents", "backup"}
    assert lignes[""]["taille_totale"] == 149 and lignes[""]["nb_fichiers"] == 4
    assert lignes["Photos"]["taille_totale"] == 100
    assert lignes["Documents"]["nb_fichiers"] == 2 and lignes["Documents"]["profondeur"] == 1


async def test_pause_entre_dossiers(arbo, depot):
    pauses: list[float] = []
    await _scan(depot, arbo, pause_s=0.05, sommeil=pauses.append)
    assert pauses and all(p == 0.05 for p in pauses)


async def test_deux_scans_simultanes_impossibles(arbo, depot):
    emp = await depot.creer_emplacement("NAS", str(arbo))
    await depot.ouvrir_scan(emp.id, "manuel")
    with pytest.raises(ScanEnCours):
        await depot.ouvrir_scan(emp.id, "nuit")


# --------------------------------------------------------------------------- #
# Totaux par dossier                                                           #
# --------------------------------------------------------------------------- #
def _totaux(depot: DepotMemoire, chemin: str) -> tuple[int, int, int]:
    e = depot.entree(1, chemin)
    return e["taille_totale"], e["nb_fichiers_total"], e["nb_dossiers_total"]


async def test_totaux_par_dossier(arbo, depot):
    await _scan(depot, arbo)
    assert _totaux(depot, "Documents") == (47, 2, 2)
    assert _totaux(depot, "Photos") == (100, 1, 1)
    assert _totaux(depot, "Documents/vide") == (0, 0, 0)
    assert depot.entree(1, "lisez-moi.txt")["taille_totale"] is None


async def test_totaux_remontent_quand_un_fichier_grossit(arbo, depot):
    await _scan(depot, arbo)
    _ecrire(arbo / "Photos" / "2024" / "vacances.jpg", 300)
    await _scan(depot, arbo)
    assert _totaux(depot, "Photos/2024")[0] == 300 and _totaux(depot, "Photos")[0] == 300


async def test_totaux_intacts_si_sous_dossier_illisible(arbo, depot, monkeypatch):
    await _scan(depot, arbo)
    monkeypatch.setattr("services.rangement.scan.os.scandir", _scandir_refuse(arbo / "Documents"))
    await _scan(depot, arbo)
    assert _totaux(depot, "Documents") == (47, 2, 2)   # pas d'écrasement par un total partiel


# --------------------------------------------------------------------------- #
# Tournée de nuit                                                              #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("heure,debut,fin,attendu", [
    (2, 1, 6, True), (0, 1, 6, False), (6, 1, 6, False),
    (23, 22, 6, True), (3, 22, 6, True), (12, 22, 6, False), (15, 0, 0, True),
])
def test_fenetre_horaire(heure, debut, fin, attendu):
    assert dans_fenetre(heure, debut, fin) is attendu


def _a(heure: int) -> datetime:
    # Dans le futur : le dépôt date la fin des scans de l'heure réelle, qui ne doit pas dépasser ces dates.
    return datetime(2099, 10, 14, heure, 0, tzinfo=timezone.utc)


def _reglages(arbo: Path, **kw) -> ReglagesInventaire:
    return ReglagesInventaire(exclusions=Exclusions.depuis_reglages("", str(arbo / "backup" / "pbs")),
                              racine_autorisee="", **kw)


async def test_tache_hors_fenetre_ne_scanne_pas(arbo, depot):
    await depot.creer_emplacement("NAS", str(arbo))
    assert await planifier_et_scanner(depot, _reglages(arbo), _a(14)) == []
    assert not depot.scans


async def test_tache_dans_la_fenetre_scanne_puis_respecte_le_delai(arbo, depot):
    await depot.creer_emplacement("NAS", str(arbo))
    premiers = await planifier_et_scanner(depot, _reglages(arbo), _a(2))
    assert [r.statut for r in premiers] == ["termine"]
    depot.scans[premiers[0].scan_id]["fin"] = _a(2)
    assert await planifier_et_scanner(depot, _reglages(arbo), _a(3)) == []           # trop récent
    assert len(await planifier_et_scanner(depot, _reglages(arbo), _a(2) + timedelta(days=1))) == 1


async def test_emplacement_inactif_ou_de_poste_jamais_scanne(arbo, depot):
    emp = await depot.creer_emplacement("NAS", str(arbo))
    await depot.activer_emplacement(emp.id, False)
    poste = await depot.creer_poste("PC")
    await depot.creer_emplacement("PC", "C:\\", source="import", poste_id=poste.id)
    assert await planifier_et_scanner(depot, _reglages(arbo), _a(2)) == []


async def test_un_echec_d_emplacement_n_arrete_pas_la_nuit(arbo, depot, tmp_path, monkeypatch):
    autre = tmp_path / "autre"
    (autre / "x").mkdir(parents=True)
    await depot.creer_emplacement("A", str(arbo))
    await depot.creer_emplacement("B", str(autre))
    vrai = DepotMemoire.enfants

    async def enfants_casse(self, emplacement_id, parent):
        if emplacement_id == 1:
            raise RuntimeError("base tombée")
        return await vrai(self, emplacement_id, parent)

    monkeypatch.setattr(DepotMemoire, "enfants", enfants_casse)
    res = await planifier_et_scanner(depot, _reglages(arbo), _a(2))
    assert [r.statut for r in res] == ["echec", "termine"]


async def test_instantanes_conserves_dans_la_limite(arbo, depot):
    await depot.creer_emplacement("NAS", str(arbo))
    r = _reglages(arbo, instantanes_gardes=2, delai_min_heures=0)
    for jour in range(4):
        await planifier_et_scanner(depot, r, _a(2) + timedelta(days=jour))
    assert {li["scan_id"] for li in depot.instantanes} == {3, 4}


async def test_scans_orphelins_interrompus(arbo, depot):
    emp = await depot.creer_emplacement("NAS", str(arbo))
    sid = await depot.ouvrir_scan(emp.id, "manuel")
    depot.scans[sid]["debut"] -= timedelta(hours=13)
    assert await depot.interrompre_scans_orphelins(age_heures=12) == 1
    assert depot.scans[sid]["statut"] == "interrompu"
    await depot.ouvrir_scan(emp.id, "manuel")   # n'est plus bloqué


async def test_arret_demande_entre_deux_dossiers(arbo, depot):
    """Le bouton « Annuler » d'une tâche : le scan s'arrête, clos « interrompu », sans disparition."""
    await _scan(depot, arbo)
    (arbo / "lisez-moi.txt").unlink()
    vus: list[int] = []

    def arret() -> bool:
        vus.append(1)
        return len(vus) > 2   # laisse passer la racine et un sous-dossier

    res = await _scan(depot, arbo, arret=arret)
    assert res.statut == "interrompu" and depot.scans[res.scan_id]["statut"] == "interrompu"
    assert "Documents/Impôts été/avis.pdf" in _presents(depot)


async def test_tournee_arretee_ne_passe_pas_a_l_emplacement_suivant(arbo, depot, tmp_path):
    autre = tmp_path / "autre"
    (autre / "x").mkdir(parents=True)
    await depot.creer_emplacement("A", str(arbo))
    await depot.creer_emplacement("B", str(autre))
    res = await planifier_et_scanner(depot, _reglages(arbo), _a(2), arret=lambda: True)
    assert res == [] and not depot.scans
