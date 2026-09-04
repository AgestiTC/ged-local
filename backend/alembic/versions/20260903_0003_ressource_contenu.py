"""Ressource.contenu — texte long intégral (prompt, extrait, mode d'emploi)

`note` reste la phrase de présentation affichée en liste ; `contenu` porte le texte
complet, déplié et copiable dans l'interface. Nullable, aucun défaut : les ressources
existantes ne sont pas touchées.

Revision ID: 0003_ressource_contenu
Revises: 0002_dossiers
Create Date: 2026-09-03 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# identifiants de révision
revision: str = "0003_ressource_contenu"
down_revision: Union[str, None] = "0002_dossiers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ressources", sa.Column("contenu", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ressources", "contenu")
