"""
Scanner un emplacement par SMB (étape 4 du plan Rangement sur Sources SMB, 14/11/2026).

Un faux NAS en mémoire (aucun réseau), construit À PARTIR du même arbre que les tests du scan disque :
l'inventaire par SMB doit être le même que par le montage (noms, types, tailles). Puis la prudence :
un dossier refusé n'efface rien et n'arrête pas le scan ; un NAS coupé fait échouer le scan sans
rien marquer disparu. Données fictives.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fakes.depot_memoire import DepotMemoire
from smb.base import NotConnectedError
from smb.smb_structs import OperationFailure
from test_smb_session import FausseConnexion, FauxServeur

from services.rangement import emplacement_smb
from services.rangement.erreurs import InventaireRefus
from services.rangement.exclusions import Exclusions
from services.rangement.reglages import ReglagesInventaire
from services.rangement.scan import Scanner, exclusions_de, planifier_et_scanner, source_pour
from services.rangement.source_smb import SourceSmb
from services.smb_session import SessionSmb

HOTE = "192.0.2.40"


def _ecrire(p: Path, octets: int) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"a" * octets)


@pytest.fixture
def arbo(tmp_path: Path) -> Path:
    r = tmp_path / "Tom"
    _ecrire(r / "Photos" / "2024" / "vacances.jpg", 100)
    _ecrire(r / "Photos" / "@eaDir" / "vacances.jpg" / "SYNOPHOTO_THUMB.jpg", 5)
    _ecrire(r / "Documents" / "Impôts été" / "avis.pdf", 40)
    (r / "Documents" / "vide").mkdir(parents=True)
    _ecrire(r / "#recycle" / "ancien.txt", 3)
    _ecrire(r / "@appstore" / "paquet.spk", 3)
    _ecrire(r / "lisez-moi.txt", 2)
    return r


class NasFictif(FauxServeur):
    """Le faux serveur de `test_smb_session`, plus : des dossiers refusés, et un NAS éteint."""

    def __init__(self, arbre):
        super().__init__(arbre)
        self.refuses: set[str] = set()
        self.eteint = False
        self.fermetures = 0

    def connecter(self):
        if self.eteint:
            raise ConnectionError("NAS éteint")
        self.connexions += 1
        return ConnexionNas(self)


class ConnexionNas(FausseConnexion):
    def listPath(self, partage, chemin, **kw):
        if self.srv.eteint:
            raise NotConnectedError("coupure")
        if chemin in self.srv.refuses:
            raise OperationFailure("accès refusé", [])
        return super().listPath(partage, chemin, **kw)

    def close(self):
        self.srv.fermetures += 1
        super().close()


def _nas_depuis(racine: Path, prefixe: str = "/Tom") -> NasFictif:
    """Le même arbre que sur disque, vu par SMB sous `prefixe` dans le partage `homes`."""
    arbre: dict[str, bytes | None] = {prefixe: None}
    for p in sorted(racine.rglob("*")):
        chemin = prefixe + "/" + p.relative_to(racine).as_posix()
        arbre[chemin] = None if p.is_dir() else p.read_bytes()
    return NasFictif(arbre)


async def _emplacement(depot, sous_dossier="/Tom"):
    racine = f"smb://{HOTE}/homes" + ("" if sous_dossier == "/" else sous_dossier)
    return await depot.creer_emplacement("Tom", racine, source="smb", source_id="src-fictive",
                                         partage="homes", sous_dossier=sous_dossier)


def _source(nas, emp, exclusions=Exclusions()):
    return SourceSmb(SessionSmb(HOTE, "homes", "svc", "fictif", connecter=nas.connecter), emp, exclusions)


def _vus(depot) -> dict[str, tuple[bool, int]]:
    return {e["chemin"]: (e["est_dossier"], e["taille"]) for e in depot.entrees.values()
            if e["disparu_scan_id"] is None}


async def test_meme_inventaire_que_par_le_montage(arbo):
    disque, smb = DepotMemoire(), DepotMemoire()
    emp_disque = await disque.creer_emplacement("Tom", str(arbo))
    r1 = await Scanner(disque, emp_disque, Exclusions()).executer()
    emp = await _emplacement(smb)
    nas = _nas_depuis(arbo)
    r2 = await Scanner(smb, emp, Exclusions(), source=_source(nas, emp)).executer()
    assert (r1.statut, r2.statut) == ("termine", "termine")
    assert _vus(smb) == _vus(disque)
    assert "Photos/@eaDir" not in _vus(smb) and "#recycle" not in _vus(smb) and "@appstore" not in _vus(smb)
    c1, c2 = r1.compteurs, r2.compteurs
    assert (c2.nb_fichiers, c2.nb_dossiers, c2.volume_octets) == (c1.nb_fichiers, c1.nb_dossiers, c1.volume_octets)
    # UNE connexion pour tout le scan, refermée à la fin.
    assert nas.connexions == 1 and nas.fermetures == 1


async def test_rescan_sans_changement_n_ecrit_rien(arbo):
    depot = DepotMemoire()
    emp = await _emplacement(depot)
    nas = _nas_depuis(arbo)
    await Scanner(depot, emp, Exclusions(), source=_source(nas, emp)).executer()
    avant = depot.ecritures_entrees
    r = await Scanner(depot, emp, Exclusions(), source=_source(nas, emp)).executer()
    assert r.statut == "termine" and depot.ecritures_entrees == avant


async def test_un_dossier_refuse_n_arrete_rien_et_n_efface_rien(arbo):
    depot = DepotMemoire()
    emp = await _emplacement(depot)
    nas = _nas_depuis(arbo)
    await Scanner(depot, emp, Exclusions(), source=_source(nas, emp)).executer()
    nas.refuses.add("/Tom/Documents")          # le cas de homes/Tom/Rapport-PDF
    nas.arbre["/Tom/nouveau.txt"] = b"xyz"
    r = await Scanner(depot, emp, Exclusions(), source=_source(nas, emp)).executer()
    assert r.statut == "termine" and r.compteurs.nb_erreurs == 1
    vus = _vus(depot)
    assert "Documents/Impôts été/avis.pdf" in vus      # rien n'a disparu du dossier refusé
    assert "nouveau.txt" in vus                        # le reste du partage a bien été parcouru


async def test_nas_eteint_au_depart_echec_sans_disparus(arbo):
    depot = DepotMemoire()
    emp = await _emplacement(depot)
    nas = _nas_depuis(arbo)
    await Scanner(depot, emp, Exclusions(), source=_source(nas, emp)).executer()
    nas.eteint = True
    r = await Scanner(depot, emp, Exclusions(), source=_source(nas, emp)).executer()
    assert r.statut == "echec" and "injoignable" in r.message
    assert r.compteurs.nb_disparus == 0 and "lisez-moi.txt" in _vus(depot)


async def test_nas_coupe_pendant_le_scan_echec_sans_disparus(arbo):
    depot = DepotMemoire()
    emp = await _emplacement(depot)
    nas = _nas_depuis(arbo)
    await Scanner(depot, emp, Exclusions(), source=_source(nas, emp)).executer()
    avant = _vus(depot)

    source = _source(nas, emp)
    lister = source.lister
    appels = 0

    async def lister_puis_couper(relatif, profondeur, c):
        nonlocal appels
        appels += 1
        if appels == 2:
            nas.eteint = True     # coupure après la racine : la reconnexion échoue aussi
        return await lister(relatif, profondeur, c)

    source.lister = lister_puis_couper
    r = await Scanner(depot, emp, Exclusions(), source=source).executer()
    assert r.statut == "echec"
    assert r.compteurs.nb_disparus == 0 and _vus(depot) == avant


async def test_dossier_de_l_emplacement_introuvable(arbo):
    depot = DepotMemoire()
    emp = await _emplacement(depot, "/Absent")
    r = await Scanner(depot, emp, Exclusions(), source=_source(_nas_depuis(arbo), emp)).executer()
    assert r.statut == "echec" and "introuvable" in r.message


async def test_tout_le_partage(arbo):
    depot = DepotMemoire()
    emp = await _emplacement(depot, "/")
    r = await Scanner(depot, emp, Exclusions(), source=_source(_nas_depuis(arbo), emp)).executer()
    assert r.statut == "termine" and "Tom/Photos/2024/vacances.jpg" in _vus(depot)


async def test_un_emplacement_smb_dedans_est_saute(arbo):
    depot = DepotMemoire()
    parent = await _emplacement(depot, "/Tom")
    await _emplacement(depot, "/Tom/Photos")
    ex = await exclusions_de(depot, parent, Exclusions())
    r = await Scanner(depot, parent, ex, source=_source(_nas_depuis(arbo), parent, ex)).executer()
    assert r.statut == "termine"
    assert not any(c.startswith("Photos") for c in _vus(depot)) and "lisez-moi.txt" in _vus(depot)


async def test_source_retiree_du_rangement_echec_propre(monkeypatch):
    depot = DepotMemoire()
    emp = await _emplacement(depot)

    async def refus(_emp, ouvrir=None):
        raise InventaireRefus("Cette source sert à la GED.", code="source_pas_rangement")

    monkeypatch.setattr(emplacement_smb, "session_de", refus)
    source = await source_pour(emp, Exclusions())
    r = await Scanner(depot, emp, Exclusions(), source=source).executer()
    assert r.statut == "echec" and "GED" in r.message


async def test_la_tournee_de_nuit_scanne_aussi_les_emplacements_smb(arbo, monkeypatch):
    depot = DepotMemoire()
    await _emplacement(depot)
    nas = _nas_depuis(arbo)

    async def session(_emp, ouvrir=None):
        return SessionSmb(HOTE, "homes", "svc", "fictif", connecter=nas.connecter)

    monkeypatch.setattr(emplacement_smb, "session_de", session)
    reglages = ReglagesInventaire(exclusions=Exclusions(), racine_autorisee="")
    resultats = await planifier_et_scanner(depot, reglages, datetime(2099, 10, 14, 2, tzinfo=timezone.utc))
    assert [r.statut for r in resultats] == ["termine"]
    assert "Photos/2024/vacances.jpg" in _vus(depot)


async def test_le_scan_manuel_d_un_emplacement_smb_est_accepte(client, monkeypatch):
    from services.rangement import service

    depot = DepotMemoire()
    monkeypatch.setattr(service, "fabrique", lambda: depot)
    emp = await _emplacement(depot)
    r = await client.post(f"/api/inventaire/emplacements/{emp.id}/scan")
    assert r.status_code == 202, r.text
