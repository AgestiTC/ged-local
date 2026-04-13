"""
Alembic — Environnement de migration async
==========================================
Utilise SQLAlchemy async pour les migrations avec PostgreSQL + pgvector.
DATABASE_URL est lue depuis les variables d'environnement.
"""

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Ajouter le répertoire backend/ au path pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from models import Base  # noqa: E402 — doit être après sys.path

# Configuration Alembic (lit alembic.ini)
config = context.config

# Setup du logging depuis alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Métadonnées de tous les modèles → utilisées pour autogenerate
target_metadata = Base.metadata


def get_url() -> str:
    """Récupère l'URL de connexion depuis l'environnement ou alembic.ini."""
    return os.environ.get(
        "DATABASE_URL",
        config.get_main_option("sqlalchemy.url", ""),
    )


def run_migrations_offline() -> None:
    """
    Migrations en mode 'offline' — génère le SQL sans connexion DB.
    Utile pour inspecter les migrations avant de les appliquer.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Exécute les migrations sur une connexion donnée."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # Inclure les schémas PostgreSQL-spécifiques
        include_schemas=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Migrations en mode async — pour PostgreSQL avec asyncpg."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        url=get_url(),
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Point d'entrée pour les migrations en mode 'online'."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
