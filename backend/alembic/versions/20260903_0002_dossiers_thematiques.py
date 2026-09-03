"""Dossiers thématiques — veille documentaire par sujet

Ajoute `dossiers_thematiques` et `ressources` (ressources externes : podcasts,
documentaires, livres, articles…). Aucune table existante n'est touchée.

Revision ID: 0002_dossiers
Revises: 0001_initial
Create Date: 2026-09-03 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# identifiants de révision
revision: str = "0002_dossiers"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dossiers_thematiques",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("titre", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("origine", sa.Text(), nullable=False, server_default="manuel"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    op.create_table(
        "ressources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("dossier_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("dossiers_thematiques.id", ondelete="CASCADE"), nullable=False),
        sa.Column("titre", sa.Text(), nullable=False),
        sa.Column("auteur", sa.Text(), nullable=True),
        sa.Column("type", sa.Text(), nullable=False, server_default="article"),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("langue", sa.Text(), nullable=False, server_default="fr"),
        sa.Column("groupe", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("favori", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("ix_ressources_dossier_ordre", "ressources", ["dossier_id", "position"])


def downgrade() -> None:
    op.drop_index("ix_ressources_dossier_ordre", table_name="ressources")
    op.drop_table("ressources")
    op.drop_table("dossiers_thematiques")
