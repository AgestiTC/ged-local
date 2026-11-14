"""
Chemins `smb://hote/partage/rel` (étape 2 du plan Rangement sur Sources SMB, 14/11/2026).

Trois parseurs copiés vivaient dans le code (réorganisation, accès aux fichiers, scans), chacun avec
ses cas limites. Ils passent désormais par `services.smb_chemins` : les tests de CARACTÉRISATION
ci-dessous figent leurs sorties d'avant, cas limites compris, pour qu'aucun appelant ne change de
comportement. Données fictives.
"""

import pytest

from routers import organize
from services import file_access, scan_service, smb_chemins

# entrée → (organize.parse_smb, scan_service.parse_smb, file_access._parse_smb ou "ValueError")
CAS = {
    "smb://nas/Documents/Factures/2026": (("nas", "Documents", "/Factures/2026"),
                                          ("nas", "Documents", "/Factures/2026"),
                                          ("nas", "Documents", "/Factures/2026")),
    "smb://nas/Documents": (None, ("nas", "Documents", "/"), ("nas", "Documents", "/")),
    "smb://nas/Documents/": (("nas", "Documents", "/"), ("nas", "Documents", "/"), ("nas", "Documents", "/")),
    "smb://nas/Documents/a/": (("nas", "Documents", "/a/"), ("nas", "Documents", "/a"),
                               ("nas", "Documents", "/a/")),
    "smb://nas": (None, None, "ValueError"),
    "smb://nas/": (None, None, "ValueError"),
    "smb:///Documents/x": (("", "Documents", "/x"), None, "ValueError"),
    "smb://nas//x": (("nas", "", "/x"), None, "ValueError"),
}


@pytest.mark.parametrize("chemin", list(CAS))
def test_les_trois_parseurs_gardent_leur_comportement(chemin):
    attendu_org, attendu_scan, attendu_fa = CAS[chemin]
    assert organize.parse_smb(chemin) == attendu_org
    assert scan_service.parse_smb(chemin) == attendu_scan
    if attendu_fa == "ValueError":
        with pytest.raises(ValueError):
            file_access._parse_smb(chemin)
    else:
        assert file_access._parse_smb(chemin) == attendu_fa


@pytest.mark.parametrize("valeur", [None, "", "/app/documents/x", "SMB://nas/x/y"])
def test_ce_qui_n_est_pas_smb(valeur):
    assert organize.parse_smb(valeur) is None
    assert scan_service.parse_smb(valeur) is None


# --- Le module commun ----------------------------------------------------------------------------

def test_decouper_forme_canonique():
    c = smb_chemins.decouper("smb://nas/media/Films/2026/")
    assert c == ("nas", "media", "/Films/2026")
    assert (c.hote, c.partage, c.rel) == ("nas", "media", "/Films/2026")
    assert smb_chemins.decouper("smb://nas/media") == ("nas", "media", "/")
    assert smb_chemins.decouper("/mnt/media") is None


@pytest.mark.parametrize("hote,partage,rel,uri", [
    ("nas", "media", "/", "smb://nas/media"),
    ("nas", "media", "", "smb://nas/media"),
    ("nas", "homes", "/Tom/Photos", "smb://nas/homes/Tom/Photos"),
    ("nas", "homes", "Tom/Photos/", "smb://nas/homes/Tom/Photos"),
])
def test_aller_retour(hote, partage, rel, uri):
    assert smb_chemins.composer(hote, partage, rel) == uri
    assert smb_chemins.composer(*smb_chemins.decouper(uri)) == uri


@pytest.mark.parametrize("hote,partage", [("", "media"), ("nas", ""), ("n/as", "media"), ("nas", "me/dia")])
def test_composer_refuse_un_hote_ou_partage_invalide(hote, partage):
    with pytest.raises(ValueError):
        smb_chemins.composer(hote, partage, "/x")


@pytest.mark.parametrize("rel,attendu", [("", "/"), ("/", "/"), ("a/b", "/a/b"), ("/a//b/", "/a/b"),
                                         ("a\\b", "/a/b")])
def test_normaliser_rel(rel, attendu):
    assert smb_chemins.normaliser_rel(rel) == attendu


@pytest.mark.parametrize("rel", ["../x", "/a/../../b", "a/.."])
def test_normaliser_rel_refuse_la_remontee(rel):
    with pytest.raises(ValueError):
        smb_chemins.normaliser_rel(rel)
