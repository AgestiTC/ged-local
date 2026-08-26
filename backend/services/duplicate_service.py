"""
Service Doublons — détection et mise en quarantaine
====================================================
Trouve les fichiers en double **sur le disque** (même contenu) dans le volume
des documents surveillés, indépendamment de l'index (l'ingestion ignore les
copies de même hash, donc l'index ne les retient pas).

Algorithme (optimisé) :
  1. Regroupe les fichiers par taille (les doublons ont forcément la même taille).
  2. Ne hashe (SHA256) que les fichiers partageant une taille → évite de hasher
     tout le volume.
  3. Un groupe de doublons = ≥ 2 fichiers de même hash.

Mise en quarantaine = **déplacement** des fichiers choisis vers un dossier
`DOUBLON-MATOTEQUE/` à la racine du volume (jamais de suppression définitive).
"""

from pathlib import Path

from logger import get_logger
from utils.hash_utils import compute_sha256


def _hash_partiel(p: Path, n: int = 4096) -> str:
    """Hash rapide des `n` premiers octets — 2ᵉ passe avant le SHA256 complet (coûteux).
    Deux fichiers de même taille mais de contenu différent divergent presque toujours sur leur
    début → on évite de lire/hasher entièrement des fichiers qui ne sont pas des doublons."""
    import hashlib
    h = hashlib.sha256()
    with p.open("rb") as f:
        h.update(f.read(n))
    return h.hexdigest()

log = get_logger(__name__)


def _keeper_index(paths: list[Path]) -> int:
    """
    Choisit le fichier à CONSERVER dans un groupe de doublons.
    Heuristique : chemin le moins profond (le plus « à la racine »), puis le plus
    ancien (l'original), puis ordre alphabétique pour être déterministe.
    """
    def key(p: Path):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            mtime = float("inf")
        return (len(p.parts), mtime, str(p).lower())

    best = min(range(len(paths)), key=lambda i: key(paths[i]))
    return best


def find_duplicates(root: Path, exclude_dirname: str) -> list[dict]:
    """
    Scanne `root` et retourne les groupes de fichiers en double (même contenu).

    Returns: liste de groupes, chaque groupe =
      {
        "hash": str, "taille_octets": int,
        "fichiers": [{"chemin": str, "nom": str, "relatif": str,
                      "taille_octets": int, "garder": bool}, ...]
      }
    """
    if not root.exists():
        log.warning("Racine documents introuvable pour scan doublons", root=str(root))
        return []

    by_size: dict[int, list[Path]] = {}
    for p in root.rglob("*"):
        # Ignore le dossier de quarantaine lui-même
        if exclude_dirname in p.parts:
            continue
        if not p.is_file():
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size == 0:  # on ignore les fichiers vides (tous "identiques")
            continue
        by_size.setdefault(size, []).append(p)

    groups: list[dict] = []
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue

        # 2ᵉ passe — hash PARTIEL (4 Ko) : ne garde que les fichiers dont même le DÉBUT coïncide.
        # Sur un gros corpus, ça évite de lire intégralement des fichiers volumineux de même taille
        # mais de contenu différent (le SHA256 complet ne s'applique qu'aux vrais candidats).
        by_partiel: dict[str, list[Path]] = {}
        for p in paths:
            try:
                by_partiel.setdefault(_hash_partiel(p), []).append(p)
            except OSError as exc:
                log.warning("Hash partiel impossible", fichier=str(p), erreur=str(exc))

        # 3ᵉ passe — SHA256 COMPLET, uniquement sur les groupes encore ambigus (≥ 2).
        by_hash: dict[str, list[Path]] = {}
        for candidats in by_partiel.values():
            if len(candidats) < 2:
                continue
            for p in candidats:
                try:
                    h = compute_sha256(p)
                except OSError as exc:
                    log.warning("Hash impossible", fichier=str(p), erreur=str(exc))
                    continue
                by_hash.setdefault(h, []).append(p)

        for h, ps in by_hash.items():
            if len(ps) < 2:
                continue
            ps_sorted = sorted(ps, key=lambda x: str(x).lower())
            keep = _keeper_index(ps_sorted)
            fichiers = []
            for i, p in enumerate(ps_sorted):
                fichiers.append({
                    "chemin": str(p),
                    "nom": p.name,
                    "relatif": str(p.relative_to(root)),
                    "taille_octets": size,
                    "garder": (i == keep),
                })
            groups.append({"hash": h, "taille_octets": size, "fichiers": fichiers})

    # Plus gros gisements de doublons en premier (taille × nombre)
    groups.sort(key=lambda g: g["taille_octets"] * len(g["fichiers"]), reverse=True)
    return groups


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
