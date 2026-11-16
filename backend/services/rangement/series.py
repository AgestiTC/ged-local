"""
Règle de nommage des séries (Rangement) — `Series/<Titre>/S01/<épisodes>`.

Décisions de Thomas (15/11/2026) :
- un dossier par série, puis un dossier par saison nommé **`S01`** ;
- un « pack » téléchargé (`Adolescence.S01.FRENCH.WEBRip.x264/`) est VIDÉ dans `S01` : ses fichiers
  gardent LEUR nom (Plex lit `S01E01`), seul le dossier du pack reste derrière, vide ;
- s'applique aux arrivées ET à l'existant ; ce qui est ambigu (`22.11.63/1…8`, « Livre 1 »,
  intégrales sans saison) n'est pas touché ;
- (16/11/2026) un dossier de série au nom « technique » (`Quantum.Leap.1989.iNTEGRALE.MULTi.1080p…`)
  reçoit une proposition de RENOMMAGE (`Quantum Leap 1989`) ; ses packs attendent le nouveau nom.

Fonctions PURES : aucune lecture du disque ni de la base ici.
"""

import re
import unicodedata
from dataclasses import dataclass

#: Gabarit d'un nœud du plan qui range selon cette règle.
GABARIT = "{serie}"

# « Titre<sép>S01 » ou « Titre<sép>S01E02 », suivi d'un séparateur ou de la fin du nom.
_RELEASE = re.compile(r"^(?P<titre>.+?)[ ._\-]+S(?P<saison>\d{1,2})(?:E\d{1,3}(?:-?E?\d{1,3})?)?(?=[ ._\-\[(]|$)",
                      re.IGNORECASE)
# Un dossier de saison déjà là : « S01 », « S1 », « Saison 1 », « Season 01 ».
_SAISON = re.compile(r"^(?:s|saison|season)[ ._]?0*(?P<n>\d{1,2})$", re.IGNORECASE)


@dataclass(frozen=True)
class Episode:
    titre: str     # titre lisible, tiré du nom (« Young Sherlock 2026 »)
    saison: int


def dossier_saison(n: int) -> str:
    return f"S{n:02d}"


def nettoyer_titre(brut: str) -> str:
    """« Young.Sherlock.2026 » → « Young Sherlock 2026 ». Un point ENTRE DEUX CHIFFRES est gardé :
    « 22.11.63 » reste « 22.11.63 » (remarque de Thomas, 15/11/2026)."""
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", brut)
    t = t.replace("_", " ")
    t = re.sub(r"\s+", " ", t).strip(" -")
    return t


def lire(nom: str) -> Episode | None:
    """Titre et saison d'un nom d'épisode ou de pack ; None si le nom n'en porte pas (intégrale…)."""
    m = _RELEASE.match(nom)
    if m is None:
        return None
    titre = nettoyer_titre(m.group("titre"))
    saison = int(m.group("saison"))
    if not titre or saison == 0:
        return None
    return Episode(titre, saison)


def saison_de_dossier(nom: str) -> int | None:
    """Numéro de saison d'un dossier déjà nommé comme une saison (« S01 », « Saison 2 »…)."""
    m = _SAISON.match(nom.strip())
    return int(m.group("n")) if m else None


#: Mots d'un nom de « release » qui ne font pas partie du titre (16/11/2026, cas de
#: `Quantum.Leap.1989.iNTEGRALE.MULTi.1080p.WEB.H265-TyHD`). Le titre s'arrête au PREMIER d'entre eux.
_MARQUEURS = frozenset({
    "integrale", "integral", "complete", "multi", "french", "truefrench", "vff", "vfq", "vfi", "vf", "vf2",
    "vostfr", "subfrench", "web", "webrip", "webdl", "hdtv", "bluray", "bdrip", "brrip", "dvdrip", "hdrip",
    "remux", "x264", "x265", "h264", "h265", "hevc", "avc", "aac", "ac3", "dts", "hdr", "10bit", "uhd",
    "4k", "repack", "proper",
})
_DEFINITION = re.compile(r"^\d{3,4}p$", re.IGNORECASE)
_MOT = re.compile(r"[^ ._\-\[\]()]+")


def _est_marqueur(mot: str) -> bool:
    return mot.casefold() in _MARQUEURS or bool(_DEFINITION.match(mot))


def nom_propre_serie(nom: str) -> str | None:
    """Le nom propre d'un dossier de série au nom « technique » (qualité, langue, groupe…) :
    « Quantum.Leap.1989.iNTEGRALE.MULTi.1080p.WEB.H265-TyHD » → « Quantum Leap 1989 ».
    None si le nom ne porte aucun marqueur de release (« Dark », « 22.11.63 », « STRANGER THINGS » :
    jamais touchés), ou s'il ne reste pas de titre avant le premier marqueur."""
    for m in _MOT.finditer(nom):
        if _est_marqueur(m.group()):
            titre = nettoyer_titre(nom[:m.start()].rstrip(" ._-[("))
            return titre if titre and titre != nom else None
    return None


def cle(titre: str) -> str:
    """Forme de comparaison d'un titre : sans casse, sans accents, sans ponctuation ni espaces.
    « STRANGER THINGS » = « Stranger.Things » = « stranger things »."""
    t = unicodedata.normalize("NFKD", titre)
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"[^0-9a-z]", "", t.casefold())


def dossier_serie(titre: str, existants: dict[str, str]) -> str:
    """Le dossier de la série : celui qui existe déjà sous le même titre (son nom est gardé), sinon le
    titre nettoyé. `existants` : clé → nom réel des dossiers déjà présents."""
    return existants.get(cle(titre), titre)
