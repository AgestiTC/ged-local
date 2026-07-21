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
from urllib.parse import quote

from pydantic import Field, model_validator
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
    # Deux modes :
    #  1) DATABASE_URL fournie directement (dev, NAS) → utilisée telle quelle.
    #  2) DATABASE_URL absente → construite depuis les composants ci-dessous, le
    #     mot de passe étant lu depuis un FICHIER SECRET (DB_PASSWORD_FILE, ex.
    #     Docker secret /run/secrets/db_password) ou à défaut DB_PASSWORD.
    #     → permet de n'avoir AUCUN mot de passe en clair dans le .env / le compose.
    database_url: str | None = Field(
        default=None,
        description="URL de connexion PostgreSQL async. Si absente, construite depuis DB_HOST/PORT/USER/NAME + mot de passe (DB_PASSWORD_FILE > DB_PASSWORD).",
        examples=["postgresql+asyncpg://docflow:password@postgres:5432/docflow"],
    )
    db_host: str = Field(default="postgres", description="Hôte PostgreSQL (mode composants)")
    db_port: int = Field(default=5432, description="Port PostgreSQL (mode composants)")
    db_user: str = Field(default="docflow", description="Utilisateur PostgreSQL (mode composants)")
    db_name: str = Field(default="docflow", description="Base PostgreSQL (mode composants)")
    db_password: str | None = Field(default=None, description="Mot de passe DB (mode composants). Préférer DB_PASSWORD_FILE.")
    db_password_file: str | None = Field(default=None, description="Chemin d'un fichier contenant le mot de passe DB (Docker secret). Prioritaire sur DB_PASSWORD.")

    @model_validator(mode="after")
    def _resolve_database_url(self) -> "Settings":
        """Construit DATABASE_URL depuis les composants + fichier secret si non fournie."""
        if self.database_url:
            return self
        password: str | None = None
        if self.db_password_file:
            try:
                password = Path(self.db_password_file).read_text(encoding="utf-8").strip()
            except OSError as e:
                raise ValueError(f"DB_PASSWORD_FILE illisible ({self.db_password_file}) : {e}") from e
        if not password:
            password = self.db_password
        if not password:
            raise ValueError(
                "Connexion DB introuvable : définir DATABASE_URL, ou DB_PASSWORD_FILE / DB_PASSWORD "
                "(+ DB_USER, DB_NAME, DB_HOST éventuels)."
            )
        # quote(safe="") : encode tout caractère spécial du mot de passe dans l'URL
        self.database_url = (
            f"postgresql+asyncpg://{quote(self.db_user, safe='')}:{quote(password, safe='')}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )
        return self

    # --- n8n ---
    n8n_url: str = Field(default="http://localhost:5678", description="URL n8n")

    # --- BookStack (wiki externe) ---
    bookstack_url: str = Field(default="https://wiki.agesti.fr", description="URL de l'instance BookStack")
    bookstack_token_id: str | None = Field(default=None, description="Token ID de l'API BookStack")
    bookstack_token_secret: str | None = Field(default=None, description="Token Secret de l'API BookStack (chiffré en base si saisi via l'UI)")
    bookstack_timeout_ms: int = Field(default=30000, description="Timeout BookStack en millisecondes")

    # --- Tika ---
    tika_url: str = Field(default="http://localhost:9998", description="URL Apache Tika")
    tika_timeout_ms: int = Field(default=60000, description="Timeout Tika en millisecondes")

    # --- Ollama ---
    ollama_url: str = Field(default="http://localhost:11434", description="URL Ollama")
    # 5 min ne suffisaient PAS : le chargement à froid d'un modèle de 43 Go (Qwen3.6-35B) reste
    # muet plus longtemps, et le client abandonnait juste avant les premiers tokens
    # (`ReadTimeout('')` en prod, 21/07). Ce délai borne le SILENCE, pas la durée de génération :
    # dès que le flux commence, chaque morceau réarme le compteur.
    ollama_timeout_ms: int = Field(default=1800000, description="Timeout Ollama (ms) — silence maximal avant le premier octet ; doit couvrir le chargement à froid du plus gros modèle")
    # Défauts d'ENV : dernier recours quand la base n'a aucune surcharge (install neuve).
    # ⚠️ Ne jamais y laisser un modèle désinstallé : mixtral/mistral ont été supprimés et ce
    # défaut renvoyait vers un modèle inexistant (cf. bug « Modèle IA (mixtral) », 17/07).
    ollama_model_default: str = Field(default="llama3.1:latest", description="Modèle principal")
    ollama_model_fast: str = Field(default="llama3.1:latest", description="Modèle rapide")
    ollama_model_embedding: str = Field(default="qwen3-embedding:8b", description="Modèle embeddings")
    ollama_model_embedding_fallback: str = Field(default="nomic-embed-text:latest", description="Modèle embeddings fallback")
    ollama_model_ocr: str = Field(default="glm-ocr:latest", description="Modèle OCR")
    ollama_keep_alive: str = Field(default="30m", description="Maintien des modèles en VRAM (keep_alive Ollama) — évite le rechargement/swap coûteux entre requêtes")

    # --- Chunking / Embeddings ---
    chunk_size: int = Field(default=500, description="Taille des chunks en tokens")
    chunk_overlap: int = Field(default=50, description="Overlap entre chunks")
    embedding_dimension: int = Field(default=4096, description="Dimension des vecteurs")

    # --- Worker de tâches durables ---
    run_worker: bool = Field(default=True, description="Démarrer le worker de jobs DANS l'API. En déploiement, mettre à false : un conteneur `worker` dédié l'exécute (isole l'API des traitements lourds).")

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

    @property
    def bookstack_timeout(self) -> float:
        """Timeout BookStack en secondes (httpx attend des secondes)."""
        return self.bookstack_timeout_ms / 1000


@lru_cache
def get_settings() -> Settings:
    """
    Retourne l'instance de configuration (singleton mis en cache).
    Usage :
        from config import get_settings
        settings = get_settings()
    """
    return Settings()
