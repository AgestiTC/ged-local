"""Documents — état du scan antivirus

Ajoute `documents.antivirus` : sain | infecte | non_scanne | desactive.

Pourquoi : le service ClamAV renvoyait « sain » aussi bien pour un fichier examiné et propre
que pour un fichier qu'il n'avait PAS PU examiner (trop gros pour la limite INSTREAM de clamd,
clamd injoignable). L'information était perdue à l'indexation, et plus un fichier était gros,
moins il était protégé. La colonne rend « non examiné » retrouvable — et donc re-scannable.

Nullable : les documents déjà indexés restent à NULL, ce qui est la vérité (on ne sait pas
dans quel état ils ont été scannés) et se distingue de « non_scanne », qui est un constat.

Revision ID: 0005_doc_antivirus
Revises: 0004_jalons
Create Date: 2026-09-06 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# identifiants de révision
revision: str = "0005_doc_antivirus"
down_revision: Union[str, None] = "0004_jalons"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("antivirus", sa.Text(), nullable=True))
    # Index partiel : on ne cherchera que les documents NON examinés, jamais les sains.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_antivirus_a_examiner "
        "ON documents (antivirus) WHERE antivirus IN ('non_scanne', 'desactive')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_antivirus_a_examiner")
    op.drop_column("documents", "antivirus")
