"""
Configuration centralisée — DocFlow AI
=======================================
Toutes les variables de configuration sont lues depuis les variables
d'environnement (ou le fichier .env via pydantic-settings).

Principe : une seule instance Settings partagée dans toute l'application.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    app_name: str = Field(default="DocFlow AI", description="Nom de l'application")
    app_version: str = Field(default="0.1.0", description="Version de l'application")

    # --- Base de données ---
    database_url: str = Field(
        description="URL de connexion PostgreSQL async",
        examples=["postgresql+asyncpg://docflow:password@postgres:5432/docflow"],
    )

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

    # --- Logging ---
    log_level: str = Field(default="INFO", description="Niveau de log")
    log_format: str = Field(default="json", description="Format de log : json | console")
    log_file: str | None = Field(default="/app/logs/docflow-backend.log", description="Fichier de log")

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
