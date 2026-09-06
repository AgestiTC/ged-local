"""Jalons — rétroplanning d'un dossier thématique

Ajoute la table `jalons` : une chose à faire, située par rapport à la date d'ancrage du
dossier (pour « Devenir parent » : la date du terme). Le temps est repéré par un entier
signé, `mois` — négatif avant la naissance, positif ensuite. Aucune table existante n'est
touchée.

Revision ID: 0004_jalons
Revises: 0003_ressource_contenu
Create Date: 2026-09-06 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# identifiants de révision
revision: str = "0004_jalons"
down_revision: Union[str, None] = "0003_ressource_contenu"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jalons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("dossier_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Négatif = avant la date d'ancrage (mois de grossesse), positif = âge en mois.
        sa.Column("mois", sa.Integer(), nullable=False),
        # Semaines d'aménorrhée, quand l'échéance se dit en SA plutôt qu'en mois.
        sa.Column("sa", sa.Integer(), nullable=True),
        sa.Column("titre", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("categorie", sa.Text(), nullable=False, server_default="preparation"),
        sa.Column("echeance", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("obligatoire", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("origine", sa.Text(), nullable=False, server_default="manuel"),
        # Suivi personnel — les seules colonnes qu'un seed ne réécrit jamais.
        sa.Column("fait", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("fait_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note_perso", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["dossier_id"], ["dossiers_thematiques.id"], ondelete="CASCADE"),
    )
    # Un planning se lit d'un coup, trié par mois puis position : un seul index composite.
    op.create_index("ix_jalons_dossier_mois", "jalons", ["dossier_id", "mois", "position"])


def downgrade() -> None:
    op.drop_index("ix_jalons_dossier_mois", table_name="jalons")
    op.drop_table("jalons")
