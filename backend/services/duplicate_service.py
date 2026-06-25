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
        by_hash: dict[str, list[Path]] = {}
        for p in paths:
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
