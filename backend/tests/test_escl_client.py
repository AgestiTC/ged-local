"""
Tests — client eSCL (sans scanner)
==================================
Le protocole est simple mais chaque appareil a ses écarts, et un scan de vitre peut mettre
une minute à rendre sa page. Ces tests fixent ce qui doit tenir sans matériel :

- on ne demande jamais une valeur que l'appareil n'annonce pas (couleur, résolution, format) ;
- la boucle `NextDocument` sait attendre (503), s'arrêter (404) et libérer le travail (DELETE) ;
- un refus du scanner devient une phrase lisible, pas un code HTTP.
"""

import httpx
import pytest

from services import escl_client as escl

CAPS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<scan:ScannerCapabilities xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm"
  xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03">
  <pwg:Version>2.63</pwg:Version>
  <pwg:MakeAndModel>Canon G3570 series</pwg:MakeAndModel>
  <scan:Platen>
    <scan:PlatenInputCaps>
      <scan:MinWidth>16</scan:MinWidth><scan:MaxWidth>2550</scan:MaxWidth>
      <scan:MinHeight>16</scan:MinHeight><scan:MaxHeight>3508</scan:MaxHeight>
      <scan:SettingProfiles><scan:SettingProfile>
        <scan:ColorModes><scan:ColorMode>Grayscale8</scan:ColorMode><scan:ColorMode>RGB24</scan:ColorMode></scan:ColorModes>
        <scan:DocumentFormats>
          <pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>
          <pwg:DocumentFormat>application/pdf</pwg:DocumentFormat>
          <scan:DocumentFormatExt>image/jpeg</scan:DocumentFormatExt>
        </scan:DocumentFormats>
        <scan:SupportedResolutions><scan:DiscreteResolutions>
          <scan:DiscreteResolution><scan:XResolution>75</scan:XResolution><scan:YResolution>75</scan:YResolution></scan:DiscreteResolution>
          <scan:DiscreteResolution><scan:XResolution>300</scan:XResolution><scan:YResolution>300</scan:YResolution></scan:DiscreteResolution>
          <scan:DiscreteResolution><scan:XResolution>600</scan:XResolution><scan:YResolution>600</scan:YResolution></scan:DiscreteResolution>
        </scan:DiscreteResolutions></scan:SupportedResolutions>
      </scan:SettingProfile></scan:SettingProfiles>
    </scan:PlatenInputCaps>
  </scan:Platen>
</scan:ScannerCapabilities>"""

CAPS_ADF_XML = CAPS_XML.replace("</scan:Platen>", """</scan:Platen>
  <scan:Adf>
    <scan:AdfSimplexInputCaps><scan:MaxWidth>2550</scan:MaxWidth><scan:MaxHeight>4200</scan:MaxHeight></scan:AdfSimplexInputCaps>
    <scan:AdfDuplexInputCaps><scan:MaxWidth>2550</scan:MaxWidth><scan:MaxHeight>4200</scan:MaxHeight></scan:AdfDuplexInputCaps>
  </scan:Adf>""")

STATUS_XML = """<?xml version="1.0"?>
<scan:ScannerStatus xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm" xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03">
  <pwg:Version>2.63</pwg:Version><pwg:State>Idle</pwg:State><scan:AdfState>ScannerAdfEmpty</scan:AdfState>
</scan:ScannerStatus>"""


# ─── Capacités ───────────────────────────────────────────────────────────────────────

def test_capacites_vitre_seule_canon():
    c = escl.parser_capacites(CAPS_XML)
    assert c.modele == "Canon G3570 series"
    assert c.vitre and not c.chargeur and not c.recto_verso
    assert c.resolutions == [75, 300, 600]
    assert c.couleurs == ["Grayscale8", "RGB24"]
    assert "image/jpeg" in c.formats and "application/pdf" in c.formats
    assert (c.largeur_max, c.hauteur_max) == (2550, 3508)


def test_capacites_chargeur_recto_verso():
    c = escl.parser_capacites(CAPS_ADF_XML)
    assert c.vitre and c.chargeur and c.recto_verso


def test_capacites_illisibles_donnent_une_erreur_lisible():
    with pytest.raises(escl.ESCLError):
        escl.parser_capacites("<pas du xml")


def test_statut():
    s = escl.parser_statut(STATUS_XML)
    assert s.etat == "Idle" and s.disponible and s.chargeur == "ScannerAdfEmpty"


def test_base_escl_normalise():
    assert escl.base_escl("192.168.42.50") == "http://192.168.42.50/eSCL"
    assert escl.base_escl("http://192.168.42.50/") == "http://192.168.42.50/eSCL"
    assert escl.base_escl("https://scan.local:8443/eSCL") == "https://scan.local:8443/eSCL"


# ─── Réglages : on n'envoie que ce que l'appareil annonce ────────────────────────────

def test_reglages_bornes_par_les_capacites():
    c = escl.parser_capacites(CAPS_XML)
    xml = escl.construire_reglages(c, source="vitre", couleur="nb", dpi=250, recto_verso=True)
    # nb non annoncé → premier mode annoncé ; 250 → 300 (le plus proche) ; vitre → jamais duplex.
    assert "<scan:ColorMode>Grayscale8</scan:ColorMode>" in xml
    assert "<scan:XResolution>300</scan:XResolution>" in xml
    assert "<pwg:InputSource>Platen</pwg:InputSource>" in xml
    assert "<scan:Duplex>false</scan:Duplex>" in xml
    # Région bornée par le maximum annoncé (2550 > A4 : on garde A4 ; hauteur = 3508).
    assert "<pwg:Width>2480</pwg:Width>" in xml and "<pwg:Height>3508</pwg:Height>" in xml


def test_reglages_chargeur_recto_verso_et_pdf():
    c = escl.parser_capacites(CAPS_ADF_XML)
    xml = escl.construire_reglages(c, source="chargeur", couleur="couleur", dpi=300, recto_verso=True)
    assert "<pwg:InputSource>Feeder</pwg:InputSource>" in xml
    assert "<scan:Duplex>true</scan:Duplex>" in xml
    assert "<pwg:DocumentFormat>application/pdf</pwg:DocumentFormat>" in xml


def test_format_vitre_prefere_jpeg():
    c = escl.parser_capacites(CAPS_XML)
    assert escl.choisir_format(c, "vitre") == "image/jpeg"
    assert escl.choisir_format(None, "chargeur") == "application/pdf"


# ─── La boucle de numérisation contre un faux scanner ────────────────────────────────

class FauxScanner:
    """Répond comme un appareil eSCL : 201 + Location, puis 503 / 200 / 200 / 404."""

    def __init__(self, pages: int = 2, refus: int | None = None):
        self.pages = pages
        self.refus = refus
        self.appels: list[str] = []
        self._rendues = 0
        self._patiente = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.appels.append(f"{request.method} {request.url.path}")
        p = request.url.path
        if request.method == "GET" and p.endswith("/ScannerCapabilities"):
            return httpx.Response(200, content=CAPS_XML.encode())
        if request.method == "GET" and p.endswith("/ScannerStatus"):
            return httpx.Response(200, content=STATUS_XML.encode())
        if request.method == "POST" and p.endswith("/ScanJobs"):
            if self.refus:
                return httpx.Response(self.refus)
            assert b"<pwg:InputSource>" in request.content
            return httpx.Response(201, headers={"Location": "/eSCL/ScanJobs/42"})
        if request.method == "GET" and p.endswith("/ScanJobs/42/NextDocument"):
            if not self._patiente:
                self._patiente = True
                return httpx.Response(503)  # la page n'est pas encore numérisée
            if self._rendues < self.pages:
                self._rendues += 1
                return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=b"\xff\xd8page" + bytes([self._rendues]))
            return httpx.Response(404)
        if request.method == "DELETE" and p.endswith("/ScanJobs/42"):
            return httpx.Response(200)
        return httpx.Response(500)


async def test_numerisation_complete(monkeypatch):
    monkeypatch.setattr(escl, "DELAI_ENTRE_ESSAIS_S", 0)
    faux = FauxScanner(pages=2)
    client = escl.ESCLClient("http://scanner.test", transport=httpx.MockTransport(faux.handler))
    caps = await client.capacites()
    assert caps.vitre
    assert (await client.statut()).disponible
    recus = []

    async def on_doc(n):
        recus.append(n)

    docs = await client.scanner(escl.construire_reglages(caps), on_document=on_doc)
    assert [d.data for d in docs] == [b"\xff\xd8page\x01", b"\xff\xd8page\x02"]
    assert all(d.content_type == "image/jpeg" for d in docs)
    assert recus == [1, 2]
    assert "DELETE /eSCL/ScanJobs/42" in faux.appels  # le travail est libéré


async def test_refus_du_scanner_est_lisible():
    faux = FauxScanner(refus=409)
    client = escl.ESCLClient("http://scanner.test", transport=httpx.MockTransport(faux.handler))
    with pytest.raises(escl.ESCLError, match="occupé"):
        await client.scanner(escl.construire_reglages(None))


async def test_aucune_page_est_une_erreur(monkeypatch):
    monkeypatch.setattr(escl, "DELAI_ENTRE_ESSAIS_S", 0)
    faux = FauxScanner(pages=0)
    client = escl.ESCLClient("http://scanner.test", transport=httpx.MockTransport(faux.handler))
    with pytest.raises(escl.ESCLError, match="Aucune page"):
        await client.scanner(escl.construire_reglages(None))


async def test_scanner_injoignable():
    def down(_request):
        raise httpx.ConnectError("refusé")
    client = escl.ESCLClient("http://192.0.2.1", transport=httpx.MockTransport(down))
    with pytest.raises(escl.ESCLError, match="injoignable"):
        await client.capacites()
