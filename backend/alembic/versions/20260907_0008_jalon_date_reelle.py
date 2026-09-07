"""Jalons — date et horaires d'un rendez-vous réellement pris

Ajoute `jalons.date_reelle`, `jalons.heure_debut`, `jalons.heure_fin`.

Jusqu'ici un jalon ne savait dire qu'une PÉRIODE : son mois, ou ses semaines d'aménorrhée.
« Entretien prénatal le vendredi 25 septembre de 13h à 14h » n'y entrait pas — l'événement
retombait au premier jour de son mois, marqué approximatif. Ces trois colonnes portent le
FAIT plutôt que le repère : une date fixée, et l'horaire quand il y en a un.

Les heures sont du TEXTE « HH:MM », volontairement : elles sont locales et flottantes
(13h à la maternité reste 13h), là où un type horaire invite à des conversions de fuseau.

Aucun index ajouté : le planning lit toujours TOUS les jalons d'un dossier d'un coup
(quelques dizaines de lignes), l'index existant sur (dossier_id, mois, position) suffit.

Revision ID: 0008_jalon_date_reelle
Revises: 0007_flux_url
Create Date: 2026-09-07 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# identifiants de révision
revision: str = "0008_jalon_date_reelle"
down_revision: Union[str, None] = "0007_flux_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jalons", sa.Column("date_reelle", sa.Date(), nullable=True))
    op.add_column("jalons", sa.Column("heure_debut", sa.Text(), nullable=True))
    op.add_column("jalons", sa.Column("heure_fin", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jalons", "heure_fin")
    op.drop_column("jalons", "heure_debut")
    op.drop_column("jalons", "date_reelle")
