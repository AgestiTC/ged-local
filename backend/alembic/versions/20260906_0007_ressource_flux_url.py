"""Ressources — URL du flux (podcast)

Ajoute `ressources.flux_url` : l'adresse du flux RSS/Atom d'un podcast.

Distincte de `url`, qui pointe la page de l'émission. C'est le FLUX qui donne les épisodes et
l'adresse de leur audio (`<enclosure>`) — donc ce qu'il faut pour lister, puis diffuser.

⚠️ Ne pas confondre avec la table `flux_rss`, qui abonne un DOSSIER à une veille : ici le flux
décrit UNE ressource et n'alimente aucune veille. Les réunir ferait déverser les épisodes de
chaque podcast catalogué dans les nouveautés du dossier.

Revision ID: 0007_flux_url
Revises: 0006_resume_ia
Create Date: 2026-09-06 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# identifiants de révision
revision: str = "0007_flux_url"
down_revision: Union[str, None] = "0006_resume_ia"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ressources", sa.Column("flux_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ressources", "flux_url")
