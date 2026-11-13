"""
Service Doublons — LA façade des doublons de Matothèque (étape 6 du plan rangement + mails)
=========================================================================================
Deux familles, une seule porte d'entrée :

- **Copies sur disque** (`copies_sur_disque`) : des fichiers au contenu identique, où qu'ils soient —
  médiathèque, autre NAS, PC équipés de l'agent. Lues dans l'INVENTAIRE (`inv_entrees`), dont les
  empreintes sont calculées la nuit en trois passes (`services/rangement/copies.py`). Plus aucun
  parcours du disque à l'ouverture de la page : l'ancien scan de `DOCUMENTS_ROOT` est retiré
  (il relisait tout à chaque fois, et ne voyait en prod qu'un dossier vide).
- **Fiches en double** (`routers/duplicates.duplicates_indexed`) : des documents de la GED de même
  contenu ou de sens proche — inchangé.

La **mise en quarantaine** (`quarantine`) et les **photos floues** restent sur le volume des
documents. Ranger les copies de l'inventaire passera par les déplacements de l'étape 10 (le NAS est
monté en lecture seule d'ici là).
"""

import ntpath
import posixpath
from pathlib import Path

from logger import get_logger
from services.rangement.depot import Depot, Emplacement

log = get_logger(__name__)


def _chemin_complet(emp: Emplacement, relatif: str) -> str:
    """Chemin lisible d'un fichier de l'inventaire : celui du NAS (« / ») ou celui du PC (« \\ »)."""
    if emp.sur_serveur:
        return posixpath.join(emp.racine, relatif)
    return ntpath.join(emp.racine, relatif.replace("/", "\\"))


def _rang_a_garder(copie: dict) -> tuple:
    """Quelle copie garder : celle du NAS avant celle d'un PC, puis la moins profonde, puis l'ordre
    alphabétique (déterministe). Une indication, pas une décision : rien n'est déplacé ici."""
    return (0 if copie["sur_serveur"] else 1, copie["relatif"].count("/"), copie["chemin"].lower())


async def copies_sur_disque(depot: Depot, limite: int = 200) -> dict:
    """Les groupes de copies connus de l'inventaire, du plus gros gisement au plus petit."""
    emplacements = {e.id: e for e in await depot.emplacements(actifs_seulement=True)}
    ids = sorted(emplacements)
    groupes = await depot.groupes_identiques(ids, limite) if ids else []
    bilan = await depot.bilan_identiques(ids) if ids else None
    sortie = []
    for g in groupes:
        fichiers = []
        for c in g.copies:
            emp = emplacements.get(c.emplacement_id)
            if emp is None:
                continue
            fichiers.append({"chemin": _chemin_complet(emp, c.chemin), "nom": posixpath.basename(c.chemin),
                             "relatif": c.chemin, "taille_octets": g.taille, "garder": False,
                             "emplacement_id": emp.id, "emplacement": emp.libelle, "sur_serveur": emp.sur_serveur})
        # Un même fichier physique peut figurer dans deux emplacements imbriqués, le temps que le
        # parent soit rescanné : il ne passe pas pour sa propre copie (on garde le plus précis).
        par_chemin: dict[str, dict] = {}
        for f in sorted(fichiers, key=lambda f: -len(emplacements[f["emplacement_id"]].racine)):
            par_chemin.setdefault(f["chemin"] if f["sur_serveur"] else f"{f['emplacement_id']}:{f['chemin']}", f)
        fichiers = list(par_chemin.values())
        if len(fichiers) < 2:
            continue
        fichiers.sort(key=lambda f: (f["emplacement"].lower(), f["relatif"].lower()))
        min(fichiers, key=_rang_a_garder)["garder"] = True
        sortie.append({"hash": g.empreinte.hex(), "taille_octets": g.taille, "fichiers": fichiers})
    derniere = await depot.derniere_passe()
    return {
        "source": "inventaire",
        "groupes": sortie,
        "nb_groupes": bilan.nb_groupes if bilan else 0,
        "nb_groupes_affiches": len(sortie),
        "nb_fichiers": sum(len(g["fichiers"]) for g in sortie),
        "octets_recuperables": bilan.recuperable if bilan else 0,
        "nb_emplacements": len(ids),
        "derniere_passe": {k: (v.isoformat() if hasattr(v, "isoformat") else v)
                           for k, v in derniere.items()} if derniere else None,
    }


def _safe_destination(dest_dir: Path, name: str) -> Path:
    """Évite d'écraser un fichier existant dans la quarantaine (suffixe _1, _2…)."""
    candidate = dest_dir / name
    if not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    i = 1
    while True:
        candidate = dest_dir / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def quarantine(paths: list[str], root: Path, dup_dirname: str) -> dict:
    """
    Déplace les fichiers `paths` vers `root/dup_dirname/`.
    Garde-fous : refuse tout chemin hors de `root` (anti path-traversal) et tout
    chemin déjà dans la quarantaine.

    Returns: {"deplaces": [...], "erreurs": [{"chemin", "erreur"}, ...]}
    """
    dest_dir = root / dup_dirname
    dest_dir.mkdir(parents=True, exist_ok=True)

    deplaces: list[dict] = []
    erreurs: list[dict] = []
    root_resolved = root.resolve()

    for chemin in paths:
        src = Path(chemin)
        try:
            src_resolved = src.resolve()
            # Garde-fou : le fichier doit être SOUS la racine documents
            if root_resolved not in src_resolved.parents:
                raise ValueError("hors du volume documents")
            if dup_dirname in src_resolved.parts:
                raise ValueError("déjà en quarantaine")
            if not src.is_file():
                raise FileNotFoundError("fichier introuvable")

            dest = _safe_destination(dest_dir, src.name)
            src.replace(dest)  # déplacement atomique sur le même volume
            log.info("Doublon mis en quarantaine", src=str(src), dest=str(dest))
            deplaces.append({"chemin": chemin, "destination": str(dest)})
        except (OSError, ValueError) as exc:
            log.warning("Quarantaine échouée", chemin=chemin, erreur=str(exc))
            erreurs.append({"chemin": chemin, "erreur": str(exc)})

    return {"deplaces": deplaces, "erreurs": erreurs}


# ─── Photos floues (variance du Laplacien) ─────────────────────────────────────
# Une image nette a beaucoup de contours → forte variance de son Laplacien. Une image floue
# a peu de contours → faible variance. Seuil réglable (défaut 100 : en dessous = suspect flou).
_EXT_IMAGES = {"jpg", "jpeg", "png", "bmp", "tif", "tiff", "webp"}


def _variance_laplacien(p: Path) -> float | None:
    """Variance du Laplacien d'une image en niveaux de gris (numpy + Pillow, sans OpenCV)."""
    import numpy as np
    from PIL import Image
    try:
        with Image.open(p) as im:
            g = np.asarray(im.convert("L"), dtype=np.float64)
    except Exception:  # noqa: BLE001 — image illisible/corrompue → ignorée
        return None
    if g.ndim != 2 or g.shape[0] < 3 or g.shape[1] < 3:
        return None
    # Convolution 3x3 du noyau Laplacien, calculée par décalages (pas de dépendance scipy).
    lap = (-4.0 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    return float(lap.var())


def find_blurry_images(root: Path, exclude_dirname: str, seuil: float = 100.0,
                       limite: int = 500) -> list[dict]:
    """
    Repère les images NETTETÉ FAIBLE (variance du Laplacien < `seuil`) sous `root`.
    Retourne [{chemin, relatif, nom, taille_octets, nettete}] triés du plus flou au moins flou.
    Ne supprime rien : à proposer à la revue (quarantaine réversible, comme les doublons).
    """
    if not root.exists():
        return []
    flous: list[dict] = []
    for p in root.rglob("*"):
        if exclude_dirname in p.parts or not p.is_file():
            continue
        if p.suffix.lstrip(".").lower() not in _EXT_IMAGES:
            continue
        v = _variance_laplacien(p)
        if v is None or v >= seuil:
            continue
        try:
            taille = p.stat().st_size
        except OSError:
            taille = 0
        flous.append({"chemin": str(p), "relatif": str(p.relative_to(root)), "nom": p.name,
                      "taille_octets": taille, "nettete": round(v, 1)})
    flous.sort(key=lambda d: d["nettete"])   # les plus flous d'abord
    return flous[:limite]
