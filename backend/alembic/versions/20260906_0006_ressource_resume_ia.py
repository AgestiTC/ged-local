"""Ressources — résumé IA persistant

Ajoute `ressources.resume_ia` : la proposition de résumé produite par l'IA locale.

Pourquoi une colonne à part et pas `note` : la **note** est ce que l'utilisateur assume, le
**résumé** est une suggestion qu'il garde sous la main, corrige, ou promeut en note. Les
confondre reviendrait à laisser une IA écrire dans un champ de curation sans que personne ne
l'ait décidé.

Pourquoi la persister : elle ne vivait qu'en mémoire du navigateur. Recharger la page effaçait
le texte, et il fallait refaire tourner le modèle pour retrouver ce qu'on avait déjà lu.

Revision ID: 0006_resume_ia
Revises: 0005_doc_antivirus
Create Date: 2026-09-06 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# identifiants de révision
revision: str = "0006_resume_ia"
down_revision: Union[str, None] = "0005_doc_antivirus"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ressources", sa.Column("resume_ia", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("ressources", "resume_ia")
