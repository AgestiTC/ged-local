"""
Utilitaires fichiers — DocFlow AI
===================================
"""

from pathlib import Path

# Extensions supportées par DocFlow AI
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".ppsx", ".xlsx", ".zip"}


def sous_chemin(base: str | Path | None, chemin: str | None) -> Path:
    """
    `base` + `chemin` (relatif, venu d'une requête), GARANTI à l'intérieur de `base`.

    `Path(base) / chemin` ne normalise pas les `..` : `/docs/clientA` + `../../etc` désignait
    bel et bien `/etc` une fois résolu par l'OS — l'indexation ou le parcours d'une source
    sortait alors du dossier configuré (audit du 28/09/2026, M1). On résout, puis on vérifie
    l'appartenance, sur le modèle de la quarantaine des doublons. Lève `ValueError` sinon.

    Le chemin RENVOYÉ garde sa forme d'origine (sans résolution des liens symboliques) : les
    documents indexés sont repérés par leur chemin, et une forme différente les ferait passer
    pour nouveaux ou absents à la synchro suivante. Seule la VÉRIFICATION porte sur le résolu.
    """
    import os

    base_brute = Path(base or "/")
    if not chemin or chemin in ("", "/"):
        return base_brute
    cible = Path(os.path.normpath(base_brute / chemin.lstrip("/")))   # `..` retirés lexicalement
    racine, resolue = base_brute.resolve(), cible.resolve()
    hors = (cible != base_brute and base_brute not in cible.parents) or \
           (resolue != racine and racine not in resolue.parents)
    if hors:
        raise ValueError(f"Chemin hors du dossier de la source : {chemin}")
    return cible


def is_supported(file_path: Path) -> bool:
    """Vérifie si l'extension du fichier est supportée."""
    return file_path.suffix.lower() in SUPPORTED_EXTENSIONS


def safe_filename(name: str) -> str:
    """
    Nettoie un nom de fichier pour éviter les injections de chemin.
    Remplace les caractères dangereux par des underscores.
    """
    import re
    # Supprimer les path traversal
    name = Path(name).name
    # Remplacer les caractères non-alphanumériques (sauf ., -, _)
    name = re.sub(r"[^\w\-.]", "_", name)
    return name


def human_size(size_bytes: int) -> str:
    """Retourne une taille lisible (ex: 1.5 MB)."""
    for unit in ["o", "Ko", "Mo", "Go", "To"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} Po"


# Clés Tika usuelles portant la date de création d'un document (selon le format).
_TIKA_CREATION_KEYS = (
    "dcterms:created",
    "meta:creation-date",
    "Creation-Date",
    "pdf:docinfo:created",
    "created",
)


def creation_date_from_tika(tika_metadata: dict | None) -> str | None:
    """
    Retourne la date de création (chaîne, telle que renvoyée par Tika — souvent ISO 8601)
    trouvée dans les métadonnées Tika, ou None si absente.
    """
    if not tika_metadata:
        return None
    for cle in _TIKA_CREATION_KEYS:
        valeur = tika_metadata.get(cle)
        if valeur:
            # Tika renvoie parfois une liste de valeurs pour une même clé.
            return str(valeur[0] if isinstance(valeur, list) else valeur)
    return None
