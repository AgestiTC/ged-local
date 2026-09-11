"""
Client eSCL — piloter un scanner réseau sans pilote
===================================================
eSCL est le protocole de scan d'AirPrint / Mopria : du HTTP + XML sur le LAN, parlé par
la quasi-totalité des multifonctions récentes (Canon PIXMA, Brother, HP, Epson…) et par
les passerelles qui publient un scanner USB (NAPS2 « partage de scanner », AirSane).
C'est le même protocole que celui du backend `sane-airscan`.

Trois appels suffisent :

  GET  {base}/eSCL/ScannerCapabilities   → ce que sait faire l'appareil (vitre, chargeur…)
  GET  {base}/eSCL/ScannerStatus         → Idle / Processing, chargeur vide ou chargé
  POST {base}/eSCL/ScanJobs              → 201 + en-tête Location = l'URL du travail
  GET  {location}/NextDocument           → un document (200), pas encore prêt (503),
                                            plus rien (404) — on boucle jusqu'au 404
  DELETE {location}                      → libère le travail (best effort)

Rien ici ne touche à la base ni au pipeline : le client rend des octets et des
métadonnées, `scan_service` en fait un PDF puis un document. Le transport httpx est
injectable, ce qui permet de tester la boucle complète contre un faux scanner sans
matériel.

⚠️ Chaque constructeur a ses écarts (formats, `InputSource` acceptés, unités de région) :
on LIT les capacités plutôt que de supposer, et on n'envoie que des valeurs annoncées.
"""

from __future__ import annotations

import asyncio
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import httpx

from logger import get_logger

log = get_logger(__name__)

NS = {
    "pwg": "http://www.pwg.org/schemas/2010/12/sm",
    "scan": "http://schemas.hp.com/imaging/escl/2011/05/03",
}

# Format A4 en « 300ᵉ de pouce » (l'unité de région eSCL) : 8,27 × 11,69 pouces.
A4_LARGEUR, A4_HAUTEUR = 2480, 3508

# Correspondances réglages Matothèque → valeurs eSCL.
COULEURS = {"couleur": "RGB24", "gris": "Grayscale8", "nb": "BlackAndWhite1"}
SOURCES = {"vitre": "Platen", "chargeur": "Feeder"}

# Le NextDocument peut répondre 503 (page pas encore numérisée) pendant longtemps sur une
# vitre 300 dpi couleur (30 à 60 s). On attend, borné.
DELAI_ENTRE_ESSAIS_S = 1.5
ESSAIS_MAX_PAR_DOCUMENT = 120  # ≈ 3 min


class ESCLError(Exception):
    """Erreur lisible (réseau, refus du scanner, capot ouvert…) — remontée telle quelle à l'UI."""


@dataclass
class Capacites:
    """Ce que l'appareil annonce — normalisé pour l'UI et pour la construction des requêtes."""

    modele: str = ""
    vitre: bool = False
    chargeur: bool = False
    recto_verso: bool = False
    resolutions: list[int] = field(default_factory=list)
    couleurs: list[str] = field(default_factory=list)  # valeurs eSCL (RGB24, Grayscale8…)
    formats: list[str] = field(default_factory=list)   # types MIME
    largeur_max: int | None = None                     # en 300ᵉ de pouce
    hauteur_max: int | None = None

    def to_dict(self) -> dict:
        return {
            "modele": self.modele, "vitre": self.vitre, "chargeur": self.chargeur,
            "recto_verso": self.recto_verso, "resolutions": self.resolutions,
            "couleurs": self.couleurs, "formats": self.formats,
            "largeur_max": self.largeur_max, "hauteur_max": self.hauteur_max,
        }


@dataclass
class Statut:
    etat: str = "Inconnu"          # Idle | Processing | Testing | Stopped | Down
    chargeur: str | None = None    # ScannerAdfEmpty | ScannerAdfLoaded | … | None (pas de chargeur)

    @property
    def disponible(self) -> bool:
        return self.etat == "Idle"


@dataclass
class DocumentScanne:
    content_type: str
    data: bytes


def base_escl(url: str) -> str:
    """`http://192.168.1.20` → `http://192.168.1.20/eSCL` (accepte une URL déjà complète)."""
    u = (url or "").strip().rstrip("/")
    if not re.match(r"^https?://", u):
        u = "http://" + u
    if not u.lower().endswith("/escl"):
        u = u + "/eSCL"
    return u


# ─── Parsing des capacités ────────────────────────────────────────────────────────────

def _texte(el: ET.Element | None, chemin: str) -> str:
    if el is None:
        return ""
    found = el.find(chemin, NS)
    return (found.text or "").strip() if found is not None else ""


def _caps_entree(caps: ET.Element | None) -> tuple[list[int], list[str], list[str], int | None, int | None]:
    """Résolutions, modes couleur, formats, dimensions max d'un bloc *InputCaps."""
    if caps is None:
        return [], [], [], None, None
    resolutions: list[int] = []
    for r in caps.findall(".//scan:DiscreteResolution/scan:XResolution", NS):
        try:
            v = int((r.text or "").strip())
            if v not in resolutions:
                resolutions.append(v)
        except ValueError:
            continue
    couleurs = [(c.text or "").strip() for c in caps.findall(".//scan:ColorMode", NS) if c.text]
    formats: list[str] = []
    for f in caps.findall(".//pwg:DocumentFormat", NS) + caps.findall(".//scan:DocumentFormatExt", NS):
        t = (f.text or "").strip()
        if t and t not in formats:
            formats.append(t)

    def _int(chemin: str) -> int | None:
        t = _texte(caps, chemin)
        try:
            return int(t) if t else None
        except ValueError:
            return None

    return sorted(set(resolutions)), list(dict.fromkeys(couleurs)), formats, _int("scan:MaxWidth"), _int("scan:MaxHeight")


def parser_capacites(xml: str | bytes) -> Capacites:
    """Normalise un `ScannerCapabilities` — tolérant : un bloc absent n'est pas une erreur."""
    try:
        racine = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ESCLError(f"Réponse ScannerCapabilities illisible : {e}") from e
    c = Capacites(modele=_texte(racine, "pwg:MakeAndModel"))

    platen = racine.find("scan:Platen/scan:PlatenInputCaps", NS)
    adf_simplex = racine.find("scan:Adf/scan:AdfSimplexInputCaps", NS)
    adf_duplex = racine.find("scan:Adf/scan:AdfDuplexInputCaps", NS)
    c.vitre = platen is not None
    c.chargeur = adf_simplex is not None or adf_duplex is not None
    c.recto_verso = adf_duplex is not None

    for bloc in (platen, adf_simplex, adf_duplex):
        res, coul, fmts, lmax, hmax = _caps_entree(bloc)
        c.resolutions = sorted(set(c.resolutions) | set(res))
        c.couleurs = list(dict.fromkeys(c.couleurs + coul))
        c.formats = list(dict.fromkeys(c.formats + fmts))
        if bloc is platen or c.largeur_max is None:
            c.largeur_max = lmax or c.largeur_max
            c.hauteur_max = hmax or c.hauteur_max
    return c


def parser_statut(xml: str | bytes) -> Statut:
    try:
        racine = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ESCLError(f"Réponse ScannerStatus illisible : {e}") from e
    return Statut(etat=_texte(racine, "pwg:State") or "Inconnu",
                  chargeur=_texte(racine, "scan:AdfState") or None)


# ─── Construction d'une requête de scan ───────────────────────────────────────────────

def choisir_format(capacites: Capacites | None, source: str) -> str:
    """
    Le format à demander. Sur un chargeur, un PDF multi-pages évite l'assemblage ; sur la
    vitre, le JPEG est universel (le PDF direct n'est pas garanti page à page). On ne demande
    jamais un format que l'appareil n'annonce pas.
    """
    formats = (capacites.formats if capacites else []) or ["image/jpeg", "application/pdf"]
    if source == "chargeur" and "application/pdf" in formats:
        return "application/pdf"
    if "image/jpeg" in formats:
        return "image/jpeg"
    if "application/pdf" in formats:
        return "application/pdf"
    return formats[0]


def choisir_resolution(capacites: Capacites | None, dpi: int) -> int:
    """La résolution annoncée la plus proche (par défaut 300 dpi, la norme pour de l'OCR)."""
    dispo = (capacites.resolutions if capacites else []) or []
    if not dispo:
        return dpi
    return min(dispo, key=lambda r: (abs(r - dpi), r))


def construire_reglages(capacites: Capacites | None, source: str = "vitre", couleur: str = "couleur",
                        dpi: int = 300, recto_verso: bool = False) -> str:
    """Le XML `ScanSettings` d'un travail. Valeurs bornées par les capacités connues."""
    src = SOURCES.get(source, "Platen")
    mode = COULEURS.get(couleur, "RGB24")
    if capacites and capacites.couleurs and mode not in capacites.couleurs:
        mode = capacites.couleurs[0]
    res = choisir_resolution(capacites, dpi)
    fmt = choisir_format(capacites, source)
    largeur = min(A4_LARGEUR, capacites.largeur_max) if capacites and capacites.largeur_max else A4_LARGEUR
    hauteur = min(A4_HAUTEUR, capacites.hauteur_max) if capacites and capacites.hauteur_max else A4_HAUTEUR
    duplex = "true" if (recto_verso and src == "Feeder") else "false"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<scan:ScanSettings xmlns:pwg="{NS["pwg"]}" xmlns:scan="{NS["scan"]}">\n'
        "  <pwg:Version>2.63</pwg:Version>\n"
        '  <pwg:ScanRegions pwg:MustHonor="true">\n'
        "    <pwg:ScanRegion>\n"
        "      <pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits>\n"
        "      <pwg:XOffset>0</pwg:XOffset>\n      <pwg:YOffset>0</pwg:YOffset>\n"
        f"      <pwg:Width>{largeur}</pwg:Width>\n      <pwg:Height>{hauteur}</pwg:Height>\n"
        "    </pwg:ScanRegion>\n"
        "  </pwg:ScanRegions>\n"
        f"  <pwg:InputSource>{src}</pwg:InputSource>\n"
        f"  <scan:ColorMode>{mode}</scan:ColorMode>\n"
        f"  <scan:XResolution>{res}</scan:XResolution>\n  <scan:YResolution>{res}</scan:YResolution>\n"
        f"  <pwg:DocumentFormat>{fmt}</pwg:DocumentFormat>\n"
        f"  <scan:DocumentFormatExt>{fmt}</scan:DocumentFormatExt>\n"
        f"  <scan:Duplex>{duplex}</scan:Duplex>\n"
        "</scan:ScanSettings>\n"
    )


# ─── Client ────────────────────────────────────────────────────────────────────────────

class ESCLClient:
    def __init__(self, url: str, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 20.0):
        self.base = base_escl(url)
        self._transport = transport
        self._timeout = timeout

    def _client(self, timeout: float | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=timeout or self._timeout)

    async def capacites(self) -> Capacites:
        try:
            async with self._client() as c:
                r = await c.get(f"{self.base}/ScannerCapabilities")
        except httpx.HTTPError as e:
            raise ESCLError(f"Scanner injoignable ({self.base}) : {e}") from e
        if r.status_code != 200:
            raise ESCLError(f"ScannerCapabilities → HTTP {r.status_code}")
        return parser_capacites(r.content)

    async def statut(self) -> Statut:
        try:
            async with self._client() as c:
                r = await c.get(f"{self.base}/ScannerStatus")
        except httpx.HTTPError as e:
            raise ESCLError(f"Scanner injoignable ({self.base}) : {e}") from e
        if r.status_code != 200:
            raise ESCLError(f"ScannerStatus → HTTP {r.status_code}")
        return parser_statut(r.content)

    async def scanner(self, reglages_xml: str, on_document=None) -> list[DocumentScanne]:
        """
        Lance un travail et rapatrie tous ses documents. `on_document(n)` est appelé à
        chaque document reçu (progression). Lève `ESCLError` avec un message lisible.
        """
        docs: list[DocumentScanne] = []
        async with self._client(timeout=60.0) as c:
            try:
                r = await c.post(f"{self.base}/ScanJobs", content=reglages_xml.encode("utf-8"),
                                 headers={"Content-Type": "text/xml"})
            except httpx.HTTPError as e:
                raise ESCLError(f"Scanner injoignable ({self.base}) : {e}") from e
            if r.status_code not in (200, 201):
                raise ESCLError(_expliquer_refus(r.status_code))
            location = r.headers.get("Location") or r.headers.get("location")
            if not location:
                raise ESCLError("Le scanner a accepté le travail sans indiquer son adresse (Location)")
            if location.startswith("/"):
                # Location relative : on la rattache à l'hôte du scanner.
                m = re.match(r"^(https?://[^/]+)", self.base)
                location = (m.group(1) if m else self.base) + location
            location = location.rstrip("/")

            try:
                essais = 0
                while True:
                    try:
                        rd = await c.get(f"{location}/NextDocument")
                    except httpx.HTTPError as e:
                        raise ESCLError(f"Connexion perdue pendant la numérisation : {e}") from e
                    if rd.status_code == 200:
                        essais = 0
                        docs.append(DocumentScanne(content_type=(rd.headers.get("Content-Type") or "application/octet-stream").split(";")[0].strip(),
                                                   data=rd.content))
                        if on_document:
                            await on_document(len(docs))
                        continue
                    if rd.status_code == 404:
                        break  # plus de document : le travail est fini
                    if rd.status_code == 503:
                        essais += 1
                        if essais > ESSAIS_MAX_PAR_DOCUMENT:
                            raise ESCLError("Le scanner ne rend pas la page (délai dépassé)")
                        await asyncio.sleep(DELAI_ENTRE_ESSAIS_S)
                        continue
                    raise ESCLError(_expliquer_refus(rd.status_code))
            finally:
                try:
                    await c.delete(location)
                except httpx.HTTPError:
                    pass
        if not docs:
            raise ESCLError("Aucune page reçue — chargeur vide ou capot ouvert ?")
        return docs


def _expliquer_refus(code: int) -> str:
    return {
        409: "Le scanner est occupé (un autre travail est en cours)",
        503: "Le scanner n'est pas prêt (capot ouvert, chargeur vide ou en veille)",
        400: "Réglages refusés par le scanner (source, résolution ou format non pris en charge)",
        401: "Le scanner demande une authentification",
        403: "Le scanner refuse l'accès",
    }.get(code, f"Le scanner a répondu HTTP {code}")
