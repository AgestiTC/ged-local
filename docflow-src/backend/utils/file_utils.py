"""
Utilitaires fichiers — DocFlow AI
===================================
"""

from pathlib import Path

# Extensions supportées par DocFlow AI
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".ppsx", ".xlsx", ".zip"}


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
