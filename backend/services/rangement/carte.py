"""La vue « carte » d'un dossier : ce que l'écran affiche, assemblé à partir du dépôt.

Porté de rangement (`app/inventaire/carte.py`), passé en asynchrone comme le dépôt.

Tout vient de la base, jamais du disque : le chemin demandé (`?chemin=Photos/2024`) n'est
qu'une clé de recherche. Un chemin inconnu rend `None` (l'écran répond 404) — aucun moyen
de sortir de l'inventaire par là.

Sources :
- taille et nombre de fichiers d'un dossier : ses totaux (calculés au scan, cf. T1) ; pour la
  racine, les compteurs du dernier scan réussi ;
- évolution : les deux derniers instantanés (dossiers jusqu'à la profondeur réglée) ;
- types : regroupement des extensions par famille (`FAMILLES`).
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from services.rangement.depot import Depot, Emplacement, chemin_enfant

FAMILLES: dict[str, tuple[str, ...]] = {
    "Photos": ("jpg", "jpeg", "png", "heic", "heif", "gif", "bmp", "tif", "tiff", "webp", "raw",
               "cr2", "cr3", "nef", "arw", "dng", "orf", "rw2", "psd", "svg"),
    "Vidéos": ("mp4", "mkv", "avi", "mov", "wmv", "m4v", "mts", "m2ts", "webm", "mpg", "mpeg",
               "3gp", "flv", "vob", "ts"),
    "Audio": ("mp3", "flac", "wav", "aac", "m4a", "ogg", "opus", "wma", "aiff", "alac"),
    "Documents": ("pdf", "doc", "docx", "odt", "rtf", "txt", "md", "xls", "xlsx", "ods", "csv",
                  "ppt", "pptx", "ppsx", "odp", "epub", "mobi", "pages", "numbers", "key", "eml", "msg"),
    "Archives": ("zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz", "iso", "img", "vhd", "vhdx",
                 "vmdk", "qcow2", "bak"),
    "Logiciels": ("exe", "msi", "apk", "dmg", "deb", "rpm", "appimage", "bat", "cmd", "ps1", "sh",
                  "jar", "spk", "pkg"),
}
_FAMILLE_DE: dict[str, str] = {ext: nom for nom, exts in FAMILLES.items() for ext in exts}
AUTRES = "Autres"


def famille(extension: str | None) -> str:
    return _FAMILLE_DE.get((extension or "").lower(), AUTRES)


@dataclass(frozen=True)
class Etape:
    libelle: str
    chemin: str


@dataclass(frozen=True)
class Ligne:
    nom: str
    chemin: str
    est_dossier: bool
    taille: int | None          # None : dossier pas encore totalisé
    pourcent: int
    nb_fichiers: int | None     # dossiers seulement
    variation: int | None       # None : pas de point de comparaison


@dataclass(frozen=True)
class PartType:
    famille: str
    nb: int
    octets: int
    pourcent: int


@dataclass(frozen=True)
class GrosFichier:
    chemin: str
    taille: int


@dataclass(frozen=True)
class Croissance:
    chemin: str
    variation: int


@dataclass
class VueDossier:
    emplacement: Emplacement
    chemin: str
    fil: list[Etape]
    taille: int | None
    nb_fichiers: int | None
    nb_dossiers: int | None
    lignes: list[Ligne]
    reste: int
    types: list[PartType] = field(default_factory=list)
    gros: list[GrosFichier] = field(default_factory=list)
    croissances: list[Croissance] = field(default_factory=list)
    dernier_scan: dict[str, Any] | None = None
    maintenant: datetime | None = None


def _pourcent(partie: int | None, tout: int | None) -> int:
    if not partie or not tout:
        return 0
    return round(partie * 100 / tout)


def _sous(chemin: str, candidat: str) -> bool:
    """`candidat` est-il strictement sous `chemin` (la racine est `""`) ?"""
    if candidat == chemin:
        return False
    return chemin == "" or candidat.startswith(chemin + "/")


async def vue_dossier(depot: Depot, emp: Emplacement, chemin: str, maintenant: datetime, *,
                limite: int = 200, nb_gros: int = 50, nb_croissances: int = 10) -> VueDossier | None:
    chemin = chemin.strip("/")
    dernier = await depot.dernier_scan(emp.id)
    if chemin:
        dossier = await depot.dossier(emp.id, chemin)
        if dossier is None:
            return None
        taille, nb_fichiers, nb_dossiers = dossier.totaux or (None, None, None)
    else:
        reussi = await depot.dernier_scan(emp.id, termine_seulement=True)
        taille = reussi["volume_octets"] if reussi else None
        nb_fichiers = reussi["nb_fichiers"] if reussi else None
        nb_dossiers = reussi["nb_dossiers"] if reussi else None

    scans = await depot.scans_avec_instantane(emp.id, 2)
    recent = await depot.tailles_instantane(scans[0]) if scans else {}
    precedent = await depot.tailles_instantane(scans[1]) if len(scans) > 1 else None

    def evolution(p: str) -> int | None:
        if precedent is None or p not in recent or p not in precedent:
            return None
        return recent[p] - precedent[p]

    enfants, total = await depot.enfants_tries(emp.id, chemin, limite)
    lignes = []
    for c in enfants:
        p = chemin_enfant(chemin, c.nom)
        t = (c.totaux[0] if c.totaux else None) if c.est_dossier else c.taille
        lignes.append(Ligne(c.nom, p, c.est_dossier, t, _pourcent(t, taille),
                            (c.totaux[1] if c.totaux else None) if c.est_dossier else None,
                            evolution(p) if c.est_dossier else None))

    par_famille: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for extension, nb, octets in await depot.repartition_types(emp.id, chemin):
        cumul = par_famille[famille(extension)]
        cumul[0] += nb
        cumul[1] += octets
    total_types = sum(o for _, o in par_famille.values())
    types = sorted((PartType(f, nb, o, _pourcent(o, total_types)) for f, (nb, o) in par_famille.items()),
                   key=lambda t: (-t.octets, t.famille))

    croissances: list[Croissance] = []
    if precedent is not None:
        for p, t in recent.items():
            if _sous(chemin, p) and p in precedent and t - precedent[p] > 0:
                croissances.append(Croissance(p, t - precedent[p]))
        croissances.sort(key=lambda c: (-c.variation, c.chemin))

    parties = chemin.split("/") if chemin else []
    fil = [Etape(emp.libelle, "")] + [Etape(nom, "/".join(parties[:i + 1])) for i, nom in enumerate(parties)]
    return VueDossier(
        emplacement=emp, chemin=chemin, fil=fil, taille=taille, nb_fichiers=nb_fichiers,
        nb_dossiers=nb_dossiers, lignes=lignes, reste=max(0, total - len(lignes)), types=types,
        gros=[GrosFichier(c, t) for c, t in await depot.plus_gros_fichiers(emp.id, chemin, nb_gros)],
        croissances=croissances[:nb_croissances], dernier_scan=dernier, maintenant=maintenant,
    )
