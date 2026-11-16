"""
Règles de nommage (Rangement) — quels fichiers sont mal nommés, et pourquoi.

Choix (16/11/2026, laissé à Claude par Thomas) : **une règle par CATÉGORIE de contenu**, pas par
extension. Ce qui fait un bon nom dépend de ce qu'est le fichier (un épisode, un film, une piste) ;
l'extension ne sert qu'à reconnaître la catégorie. Les formats proposés sont ceux de Plex/Kodi, que la
Médiathèque sert déjà :

- **Épisodes de séries** : `Série - S01E01 - Titre.ext` (titre facultatif) — celui du Rangement ;
- **Films** : `Titre (Année).ext`, ou `Titre.ext` si l'année n'est pas voulue ;
- **Musique** : `01 - Titre.ext` (dans `Artiste/Album/`), ou `Artiste - Titre.ext` ;
- **Photos** : `AAAA-MM-JJ …` — ÉTEINTE par défaut (un téléphone nomme `IMG_1234.jpg`) ;
- **Défauts communs** (tous fichiers) : marque de copie, espaces en trop, nom trop long, et pour les
  vidéos et la musique, points ou « _ » à la place des espaces et étiquettes techniques (1080p, x264…).

Ce module ne fait que CONSTATER (statistiques) : il ne renomme rien. Fonctions PURES, sauf la lecture
des réglages (`runtime_config`, clé `rangement_nommage`, JSON).
"""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from services.rangement.carte import famille

CLE_CONFIG = "rangement_nommage"


@dataclass(frozen=True)
class Format:
    code: str
    libelle: str
    exemple: str


@dataclass(frozen=True)
class Categorie:
    code: str
    libelle: str
    description: str
    formats: tuple[Format, ...]
    actif_par_defaut: bool = True


CATEGORIES: tuple[Categorie, ...] = (
    Categorie("episodes", "Épisodes de séries",
              "Vidéos rangées sous une rubrique de séries, ou dont le nom porte un code S01E01.",
              (Format("serie_code_titre", "Série - S01E01 - Titre", "Arcane - S01E01 - Bienvenue.mkv"),)),
    Categorie("films", "Films", "Vidéos rangées sous un dossier « Films » (hors bonus et extraits).",
              (Format("titre_annee", "Titre (Année)", "Barbie (2023).mkv"),
               Format("titre", "Titre", "Barbie.mkv"))),
    Categorie("musique", "Musique", "Fichiers audio.",
              (Format("piste_titre", "01 - Titre", "01 - Bohemian Rhapsody.flac"),
               Format("artiste_titre", "Artiste - Titre", "Queen - Bohemian Rhapsody.flac"))),
    Categorie("photos", "Photos", "Images (hors jaquettes des films et séries).",
              (Format("date", "AAAA-MM-JJ …", "2024-07-14 Feu d'artifice.jpg"),), actif_par_defaut=False),
    Categorie("defauts", "Défauts communs", "Tous les fichiers : copies, espaces, longueur ; vidéos et musique : "
              "points ou « _ » au lieu d'espaces, étiquettes techniques.",
              (Format("standard", "Nom lisible", "Le Bureau des légendes - S01E01.mkv"),)),
)
PAR_CODE = {c.code: c for c in CATEGORIES}

#: Raisons, dans l'ordre d'affichage : code → libellé.
RAISONS: dict[str, str] = {
    "episode_format": "Épisode hors format « Série - S01E01 - Titre »",
    "film_annee": "Film sans « (Année) »",
    "musique_piste": "Piste sans numéro « 01 - Titre »",
    "musique_artiste": "Piste hors format « Artiste - Titre »",
    "photo_date": "Photo sans date « AAAA-MM-JJ » en tête",
    "separateurs": "Points ou « _ » à la place des espaces",
    "etiquettes": "Étiquettes techniques (1080p, x264, MULTi…)",
    "copie": "Marque de copie (« (1) », « - Copie »)",
    "espaces": "Espaces en trop",
    "long": "Nom trop long (plus de 150 caractères)",
}
LONGUEUR_MAX = 150
EXEMPLES_MAX = 10

# Rubriques reconnues sans plan (le plan ajoute les siennes : nœuds de gabarit `{serie}`).
RUBRIQUES_SERIES = frozenset({"series", "séries", "series tv", "séries tv", "tv shows", "tv"})
RUBRIQUES_FILMS = frozenset({"films", "film", "movies"})
_BONUS = frozenset({"extras", "bonus", "featurettes", "trailers", "behind the scenes", "samples", "sample"})
_IGNORES = frozenset({"thumbs.db", "desktop.ini", ".ds_store"})
_COMPAGNONS = frozenset({"srt", "ass", "ssa", "sub", "idx", "vtt", "nfo", "txt"})

_CODE = re.compile(r"(?<![a-z0-9])S\d{1,2}E\d{1,3}(?![0-9])", re.IGNORECASE)
_EPISODE = re.compile(r"^.+? - S\d{2}E\d{2,3}(?:-E\d{2,3})?(?: - .+)?$")
_FILM_ANNEE = re.compile(r"^.+ \((?:19|20)\d{2}\)(?: - .+)?(?: \{.+\})?$")
_PISTE = re.compile(r"^\d{1,3} - .+$")
_ARTISTE = re.compile(r"^.+ - .+$")
_PHOTO = re.compile(r"^(?:19|20)\d{2}-\d{2}-\d{2}")
# Une lettre, puis « . » ou « _ », puis une lettre ou un chiffre : « Le.Bon.Film », « Le_Bon ».
# « 22.11.63 » (chiffres de part et d'autre) n'est pas visé — cf. la règle des séries.
_SEPARATEUR = re.compile(r"[^\W\d_][._](?=[^\W_])")
_ETIQUETTES = re.compile(
    r"(?<![a-z0-9])(?:480p|576p|720p|1080p|2160p|4k|uhd|x26[45]|h\.?26[45]|hevc|10bit|web-?dl|webrip|"
    r"bluray|blu-ray|brrip|bdrip|dvdrip|hdtv|hdrip|remux|multi|vostfr|vff|vfq|vfi|truefrench|"
    r"subfrench|ac3|dts|ddp?5\.1|atmos)(?![a-z0-9])", re.IGNORECASE)
_COPIE = re.compile(r"(?:\(\d{1,3}\)|[ _-]+(?:copie|copy)(?: \(\d+\))?)$|^(?:copie de|copy of) ", re.IGNORECASE)


@dataclass(frozen=True)
class Regle:
    actif: bool
    format: str


def regles_par_defaut() -> dict[str, Regle]:
    return {c.code: Regle(c.actif_par_defaut, c.formats[0].code) for c in CATEGORIES}


def depuis_json(brut: str | None) -> dict[str, Regle]:
    """Les règles enregistrées, complétées par les défauts ; une saisie illisible retombe sur les défauts."""
    regles = regles_par_defaut()
    try:
        donnees = json.loads(brut) if brut else {}
    except ValueError:
        return regles
    if not isinstance(donnees, dict):
        return regles
    for code, v in donnees.items():
        c = PAR_CODE.get(code)
        if c is None or not isinstance(v, dict):
            continue
        fmt = v.get("format")
        regles[code] = Regle(bool(v.get("actif", regles[code].actif)),
                             fmt if fmt in {f.code for f in c.formats} else regles[code].format)
    return regles


def valider(donnees: object) -> dict[str, Regle]:
    """Contrôle une saisie : catégories et formats connus. Lève ValueError avec un message lisible."""
    if not isinstance(donnees, dict):
        raise ValueError("Règles attendues sous la forme {catégorie: {actif, format}}.")
    regles = regles_par_defaut()
    for code, v in donnees.items():
        c = PAR_CODE.get(code)
        if c is None:
            raise ValueError(f"Catégorie inconnue : {code}")
        if not isinstance(v, dict):
            raise ValueError(f"{c.libelle} : réglage illisible")
        fmt = v.get("format", regles[code].format)
        if fmt not in {f.code for f in c.formats}:
            raise ValueError(f"{c.libelle} : format inconnu « {fmt} »")
        regles[code] = Regle(bool(v.get("actif", regles[code].actif)), fmt)
    return regles


def en_json(regles: dict[str, Regle]) -> str:
    return json.dumps({k: {"actif": r.actif, "format": r.format} for k, r in regles.items()}, ensure_ascii=False)


def lire() -> dict[str, Regle]:
    from services import runtime_config
    return depuis_json(runtime_config.effective(CLE_CONFIG))


# --------------------------------------------------------------------------- #
# Diagnostic d'un fichier                                                      #
# --------------------------------------------------------------------------- #
def categorie_de(chemin: str, rubriques_series: frozenset[str] = RUBRIQUES_SERIES) -> str | None:
    """La catégorie d'un fichier (`episodes`, `films`, `musique`, `photos`), `autre`, ou None s'il
    n'est pas analysé (fichier système, dossier caché, compagnon ou jaquette d'un épisode ou d'un film)."""
    morceaux = chemin.split("/")
    nom = morceaux[-1]
    dossiers = [m.casefold() for m in morceaux[:-1]]
    if nom.casefold() in _IGNORES or nom.startswith(".") or any(m.startswith((".", "@")) for m in morceaux[:-1]):
        return None
    ext = posixpath.splitext(nom)[1].lower().lstrip(".")
    fam = famille(ext)
    sous_media = any(d in rubriques_series or d in RUBRIQUES_FILMS for d in dossiers)
    if fam == "Vidéos":
        if any(d in rubriques_series for d in dossiers) or _CODE.search(nom):
            return "episodes"
        if any(d in _BONUS for d in dossiers) or re.search(r"\b(sample|trailer)\b", nom, re.IGNORECASE):
            return "autre"
        return "films" if any(d in RUBRIQUES_FILMS for d in dossiers) else "autre"
    if fam == "Audio":
        return "musique"
    if fam == "Photos":
        return None if sous_media else "photos"
    if ext in _COMPAGNONS and sous_media:
        return None
    return "autre"


def raisons(chemin: str, regles: dict[str, Regle], rubriques_series: frozenset[str] = RUBRIQUES_SERIES
            ) -> tuple[str | None, list[str]]:
    """(catégorie, raisons) d'un fichier ; raisons vides = bien nommé (ou rien d'actif pour lui)."""
    cat = categorie_de(chemin, rubriques_series)
    if cat is None:
        return None, []
    nom = chemin.rsplit("/", 1)[-1]
    tige = posixpath.splitext(nom)[0]
    sortie: list[str] = []
    r = regles.get(cat)
    if r is not None and r.actif:
        if cat == "episodes" and not _EPISODE.match(tige):
            sortie.append("episode_format")
        elif cat == "films" and r.format == "titre_annee" and not _FILM_ANNEE.match(tige):
            sortie.append("film_annee")
        elif cat == "musique" and r.format == "piste_titre" and not _PISTE.match(tige):
            sortie.append("musique_piste")
        elif cat == "musique" and r.format == "artiste_titre" and not _ARTISTE.match(tige):
            sortie.append("musique_artiste")
        elif cat == "photos" and not _PHOTO.match(tige):
            sortie.append("photo_date")
    d = regles.get("defauts")
    if d is not None and d.actif:
        media = cat in ("episodes", "films", "musique") or famille(posixpath.splitext(nom)[1].lstrip(".")) == "Vidéos"
        if media and " " not in tige.strip() and len(_SEPARATEUR.findall(tige)) >= 2:
            sortie.append("separateurs")
        if media and _ETIQUETTES.search(tige.replace("_", " ")):
            sortie.append("etiquettes")
        if _COPIE.search(tige.strip()):
            sortie.append("copie")
        if tige != tige.strip() or "  " in nom:
            sortie.append("espaces")
        if len(nom) > LONGUEUR_MAX:
            sortie.append("long")
    return cat, sortie


# --------------------------------------------------------------------------- #
# Bilan d'un emplacement                                                       #
# --------------------------------------------------------------------------- #
@dataclass
class _Compte:
    fichiers: int = 0
    mal_nommes: int = 0


@dataclass
class _Raison:
    nb: int = 0
    exemples: list[str] = field(default_factory=list)


def bilan(fichiers: Iterable[tuple[str, int]], regles: dict[str, Regle],
          rubriques_series: frozenset[str] = RUBRIQUES_SERIES) -> dict:
    """Statistiques des noms d'un ensemble de fichiers (chemin, taille). PURE."""
    total = analyses = mal = octets_mal = 0
    par_cat: dict[str, _Compte] = {}
    par_raison: dict[str, _Raison] = {}
    for chemin, taille in fichiers:
        total += 1
        cat, rs = raisons(chemin, regles, rubriques_series)
        if cat is None:
            continue
        analyses += 1
        c = par_cat.setdefault(cat, _Compte())
        c.fichiers += 1
        if not rs:
            continue
        mal += 1
        octets_mal += taille
        c.mal_nommes += 1
        for code in rs:
            x = par_raison.setdefault(code, _Raison())
            x.nb += 1
            if len(x.exemples) < EXEMPLES_MAX:
                x.exemples.append(chemin)
    libelles = {c.code: c.libelle for c in CATEGORIES} | {"autre": "Autres fichiers"}
    ordre = [c.code for c in CATEGORIES if c.code != "defauts"] + ["autre"]
    return {
        "fichiers": total,
        "analyses": analyses,
        "mal_nommes": mal,
        "octets_mal_nommes": octets_mal,
        "categories": [{"code": k, "libelle": libelles[k], "actif": k == "autre" or regles[k].actif,
                        "fichiers": par_cat[k].fichiers, "mal_nommes": par_cat[k].mal_nommes}
                       for k in ordre if k in par_cat],
        "raisons": [{"code": k, "libelle": RAISONS[k], "nb": par_raison[k].nb, "exemples": par_raison[k].exemples}
                    for k in RAISONS if k in par_raison],
    }


def regles_json(regles: dict[str, Regle]) -> list[dict]:
    """Les règles telles que l'écran Paramètres les affiche."""
    return [{"code": c.code, "libelle": c.libelle, "description": c.description,
             "actif": regles[c.code].actif, "format": regles[c.code].format,
             "formats": [{"code": f.code, "libelle": f.libelle, "exemple": f.exemple} for f in c.formats]}
            for c in CATEGORIES]
