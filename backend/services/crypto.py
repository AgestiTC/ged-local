"""
Service de chiffrement — Fernet (AES symétrique)
================================================
Chiffre les secrets locaux stockés en base (ex. identifiants SMB des sources).
Convention modèle AgestiTC : secrets JAMAIS en clair, jamais en log.

Clé maître : variable d'env `SECRET_KEY` si présente, sinon **auto-générée**
au 1er boot et persistée dans `storage/.secret.key` (volume hôte).
⚠️ Ne JAMAIS changer la clé après mise en prod (les secrets en base deviendraient
illisibles).
"""

from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from config import get_settings
from logger import get_logger

log = get_logger(__name__)
settings = get_settings()

_PREFIX = "enc::"  # marqueur pour distinguer un secret chiffré d'un texte clair
_KEY_FILE = Path(settings.storage_uploads).parent / ".secret.key"  # storage/.secret.key

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Retourne l'instance Fernet (clé env > fichier persisté > génération)."""
    global _fernet
    if _fernet is not None:
        return _fernet

    key = settings.secret_key
    if not key:
        # Lit la clé persistée, ou en génère une nouvelle (1er boot)
        try:
            if _KEY_FILE.exists():
                key = _KEY_FILE.read_text(encoding="utf-8").strip()
            else:
                key = Fernet.generate_key().decode()
                _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
                _KEY_FILE.write_text(key, encoding="utf-8")
                log.info("Clé Fernet générée et persistée", fichier=str(_KEY_FILE))
        except OSError as exc:
            log.error("Impossible de lire/écrire la clé Fernet", erreur=str(exc))
            raise

    _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt(plaintext: str) -> str:
    """Chiffre une chaîne. Retourne un token préfixé `enc::`."""
    if plaintext is None:
        return ""
    token = _get_fernet().encrypt(plaintext.encode())
    return _PREFIX + token.decode()


def decrypt(token: str) -> str:
    """Déchiffre un token `enc::…`. Si non chiffré (legacy), retourne tel quel."""
    if not token:
        return ""
    if not token.startswith(_PREFIX):
        return token  # tolérant : valeur en clair (ne devrait pas arriver)
    try:
        return _get_fernet().decrypt(token[len(_PREFIX):].encode()).decode()
    except InvalidToken:
        log.error("Déchiffrement impossible (clé changée ?)")
        return ""


def is_encrypted(value: str) -> bool:
    """Indique si une valeur est déjà chiffrée."""
    return bool(value) and value.startswith(_PREFIX)
