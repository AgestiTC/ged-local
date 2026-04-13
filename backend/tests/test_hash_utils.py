"""
Tests unitaires — utils/hash_utils.py
=======================================
Vérifie le calcul SHA256 et la déduplication.
"""

import hashlib
import tempfile
from pathlib import Path

import pytest
from utils.hash_utils import compute_sha256


class TestComputeSha256:
    def _creer_fichier(self, contenu: bytes) -> Path:
        """Crée un fichier temporaire avec le contenu donné."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(contenu)
            return Path(f.name)

    def test_hash_cohérent(self):
        """Le même fichier doit toujours retourner le même hash."""
        fichier = self._creer_fichier(b"contenu test identique")
        h1 = compute_sha256(fichier)
        h2 = compute_sha256(fichier)
        assert h1 == h2
        fichier.unlink()

    def test_hash_format_hexadecimal(self):
        """Le hash doit être une chaîne hexadécimale de 64 caractères."""
        fichier = self._creer_fichier(b"test")
        h = compute_sha256(fichier)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)
        fichier.unlink()

    def test_fichiers_differents_hash_differents(self):
        """Deux fichiers avec des contenus différents doivent avoir des hashs différents."""
        f1 = self._creer_fichier(b"contenu A")
        f2 = self._creer_fichier(b"contenu B")
        assert compute_sha256(f1) != compute_sha256(f2)
        f1.unlink()
        f2.unlink()

    def test_match_hashlib_standard(self):
        """Le résultat doit correspondre au calcul hashlib standard."""
        contenu = b"DocFlow AI test content 12345"
        fichier = self._creer_fichier(contenu)
        hash_attendu = hashlib.sha256(contenu).hexdigest()
        assert compute_sha256(fichier) == hash_attendu
        fichier.unlink()

    def test_fichier_vide(self):
        """Un fichier vide a un hash SHA256 connu."""
        fichier = self._creer_fichier(b"")
        h = compute_sha256(fichier)
        # SHA256 de "" = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        assert h == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        fichier.unlink()

    def test_gros_fichier(self):
        """Doit fonctionner sur un fichier de plusieurs Mo (lecture par chunks)."""
        contenu = b"A" * (5 * 1024 * 1024)  # 5 MB
        fichier = self._creer_fichier(contenu)
        h = compute_sha256(fichier)
        assert len(h) == 64
        # Vérifier contre hashlib
        hash_attendu = hashlib.sha256(contenu).hexdigest()
        assert h == hash_attendu
        fichier.unlink()
