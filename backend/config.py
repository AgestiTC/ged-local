"""
Configuration centralisée — DocFlow AI
=======================================
Toutes les variables de configuration sont lues depuis les variables
d'environnement (ou le fichier .env via pydantic-settings).

Principe : une seule instance Settings partagée dans toute l'application.
"""

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_version() -> str:
    """
    Résout la version applicative — fichier VERSION = source de vérité unique
    (convention modèle docker AgestiTC). Précédence :

    1. Fichier ``VERSION`` à la racine du repo (../VERSION) — dev bare-metal,
       et dev conteneur si le fichier est monté (cf. docker-compose.dev.yml).
    2. Variable d'env ``APP_VERSION`` — image de prod, où le fichier n'est pas
       embarqué : la CI l'injecte au build (build-arg depuis le tag git).
    3. ``0.0.0`` si rien n'est disponible.
    """
    version_file = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        # utf-8-sig : tolère un éventuel BOM en tête de fichier (Windows/PowerShell)
        v = version_file.read_text(encoding="utf-8-sig").strip()
        if v:
            return v
    except OSError:
        pass
    return os.environ.get("APP_VERSION", "0.0.0")


class Settings(BaseSettings):
    """
    Configuration de l'application.
    Les valeurs sont lues depuis l'environnement ou le fichier .env.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    debug: bool = Field(default=False, description="Mode debug")
    app_name: str = Field(default="Matothèque", description="Nom de l'application")

    # --- Base de données ---
    database_url: str = Field(
        description="URL de connexion PostgreSQL async",
        examples=["postgresql+asyncpg://docflow:password@postgres:5432/docflow"],
    )

    # --- n8n ---
    n8n_url: str = Field(default="http://localhost:5678", description="URL n8n")

    # --- Tika ---
    tika_url: str = Field(default="http://localhost:9998", description="URL Apache Tika")
    tika_timeout_ms: int = Field(default=60000, description="Timeout Tika en millisecondes")

    # --- Ollama ---
    ollama_url: str = Field(default="http://localhost:11434", description="URL Ollama")
    ollama_timeout_ms: int = Field(default=300000, description="Timeout Ollama en millisecondes")
    ollama_model_default: str = Field(default="mixtral:latest", description="Modèle principal")
    ollama_model_fast: str = Field(default="mistral:latest", description="Modèle rapide")
    ollama_model_embedding: str = Field(default="qwen3-embedding:8b", description="Modèle embeddings")
    ollama_model_embedding_fallback: str = Field(default="nomic-embed-text:latest", description="Modèle embeddings fallback")
    ollama_model_ocr: str = Field(default="glm-ocr:latest", description="Modèle OCR")

    # --- Chunking / Embeddings ---
    chunk_size: int = Field(default=500, description="Taille des chunks en tokens")
    chunk_overlap: int = Field(default=50, description="Overlap entre chunks")
    embedding_dimension: int = Field(default=4096, description="Dimension des vecteurs")

    # --- Stockage (chemins dans le conteneur = montés depuis l'hôte) ---
    storage_uploads: str = Field(default="/app/storage/uploads", description="Dossier uploads")
    storage_exports: str = Field(default="/app/storage/exports", description="Dossier exports")
    storage_templates: str = Field(default="/app/storage/templates", description="Dossier templates")
    documents_root: str = Field(default="/app/documents", description="Racine des documents surveillés")
    duplicates_dirname: str = Field(default="DOUBLON-MATOTEQUE", description="Dossier de quarantaine des doublons (à la racine du volume documents)")

    # --- Sécurité ---
    secret_key: str | None = Field(default=None, description="Clé maître Fernet (chiffrement des identifiants). Auto-générée si absente.")

    # --- Antivirus (ClamAV) ---
    clamav_enabled: bool = Field(default=True, description="Activer le scan antivirus des fichiers à l'indexation")
    clamav_host: str | None = Field(default=None, description="Hôte clamd (ex: clamav). Si vide, scan désactivé.")
    clamav_port: int = Field(default=3310, description="Port clamd")

    # --- Logging ---
    log_level: str = Field(default="INFO", description="Niveau de log")
    log_format: str = Field(default="json", description="Format de log : json | console")
    log_file: str | None = Field(default="/app/logs/docflow-backend.log", description="Fichier de log")

    @property
    def app_version(self) -> str:
        """
        Version applicative. Propriété (non liée à pydantic) pour garantir la
        précédence fichier VERSION > env APP_VERSION (cf. _read_version).
        """
        return _read_version()

    @property
    def tika_timeout(self) -> float:
        """Timeout Tika en secondes (httpx attend des secondes)."""
        return self.tika_timeout_ms / 1000

    @property
    def ollama_timeout(self) -> float:
        """Timeout Ollama en secondes."""
        return self.ollama_timeout_ms / 1000


@lru_cache
def get_settings() -> Settings:
    """
    Retourne l'instance de configuration (singleton mis en cache).
    Usage :
        from config import get_settings
        settings = get_settings()
    """
    return Settings()
