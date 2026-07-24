"""
Tests du parsing PROPFIND du connecteur WebDAV (`services.connectors.webdav.parse_propfind`).

`parse_propfind` est PURE (aucune I/O) : elle transforme la réponse XML `multistatus`
d'un serveur WebDAV en entrées {nom, dossier, taille, chemin}. C'est le point le plus
fragile du connecteur (namespaces, préfixe d'URL, encodage %XX) → couvert ici.
"""

from services.connectors.webdav import (
    WebDAVError, _base_path, _base_url, _encode_path, parse_propfind,
)
from models.source import Source


# Réponse type Nextcloud : base = /remote.php/dav/files/jean
_NEXTCLOUD_XML = b"""<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/remote.php/dav/files/jean/Documents/</d:href>
    <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop>
      <d:status>HTTP/1.1 200 OK</d:status></d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/jean/Documents/Sous%20dossier/</d:href>
    <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop>
      <d:status>HTTP/1.1 200 OK</d:status></d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/files/jean/Documents/facture%20001.pdf</d:href>
    <d:propstat><d:prop>
      <d:resourcetype/><d:getcontentlength>12345</d:getcontentlength>
    </d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat>
  </d:response>
</d:multistatus>"""

_BASE_PATH = "/remote.php/dav/files/jean"


def test_parse_exclut_dossier_demande():
    entrees = parse_propfind(_NEXTCLOUD_XML, _BASE_PATH, "/Documents")
    # Le dossier demandé (/Documents) est retiré → 2 enfants restants.
    chemins = {e["chemin"] for e in entrees}
    assert "/Documents" not in chemins
    assert len(entrees) == 2


def test_parse_types_taille_et_decodage():
    entrees = parse_propfind(_NEXTCLOUD_XML, _BASE_PATH, "/Documents")
    par_nom = {e["nom"]: e for e in entrees}
    # Sous-dossier : décodage %20 → espace, marqué dossier, taille None.
    assert "Sous dossier" in par_nom
    assert par_nom["Sous dossier"]["dossier"] is True
    assert par_nom["Sous dossier"]["taille"] is None
    # Fichier : taille lue, chemin relatif décodé.
    f = par_nom["facture 001.pdf"]
    assert f["dossier"] is False
    assert f["taille"] == 12345
    assert f["chemin"] == "/Documents/facture 001.pdf"


def test_parse_tri_dossiers_avant_fichiers():
    entrees = parse_propfind(_NEXTCLOUD_XML, _BASE_PATH, "/Documents")
    assert entrees[0]["dossier"] is True   # dossiers d'abord


def test_parse_href_absolu_avec_hote():
    # Certains serveurs renvoient un href complet (schéma + hôte).
    xml = b"""<?xml version="1.0"?>
    <d:multistatus xmlns:d="DAV:">
      <d:response><d:href>https://nas.local:5006/dav/photo.jpg</d:href>
        <d:propstat><d:prop><d:resourcetype/><d:getcontentlength>9</d:getcontentlength></d:prop>
        <d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>
    </d:multistatus>"""
    entrees = parse_propfind(xml, "/dav", "/")
    assert entrees == [{"nom": "photo.jpg", "dossier": False, "taille": 9, "chemin": "/photo.jpg"}]


def test_encode_path_segments():
    assert _encode_path("/Documents/Sous dossier") == "/Documents/Sous%20dossier"
    assert _encode_path("sans slash") == "/sans%20slash"


def test_base_url_ajoute_schema_et_retire_slash():
    s = Source(type="webdav", libelle="x", hote="cloud.example.com/dav/")
    assert _base_url(s) == "https://cloud.example.com/dav"
    assert _base_path("https://cloud.example.com/dav") == "/dav"


def test_base_url_manquante_leve():
    s = Source(type="webdav", libelle="x", hote="")
    try:
        _base_url(s)
        assert False, "aurait dû lever"
    except WebDAVError:
        pass
