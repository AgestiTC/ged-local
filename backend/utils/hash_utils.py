"""
Utilitaires Hash — SHA256 et déduplication
==========================================
"""

import hashlib
from pathlib import Path


def compute_sha256(file_path: Path, chunk_size: int = 65536) -> str:
    """
    Calcule le hash SHA256 d'un fichier par chunks (économise la RAM).

    Args:
        file_path: Chemin vers le fichier
        chunk_size: Taille des chunks de lecture (64 KB par défaut)

    Returns:
        Hash SHA256 hexadécimal (64 caractères)
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()
