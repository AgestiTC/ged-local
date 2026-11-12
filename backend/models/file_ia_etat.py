"""
Modèle FileIAEtat — état de la file IA « collante par étape »
=============================================================
Plan lots IA par modèle, étape 3 : pour les lots GPU, le worker reste sur la même étape du
traitement d'un document (contenu → enrich → embed, chacune limitée à UN modèle IA) tant qu'il en
reste en attente. L'étape courante doit être vue par TOUS les process (uvicorn --workers 2 + le
worker) : elle vit donc ici, en base, et jamais dans une variable de module. Pas dans la table
`config` non plus : son cache est relu toutes les 2 s par process, trop lent pour un état qui
change à chaque prise de jobs.

Une seule ligne aujourd'hui (`cle = 'gpu'`) ; la clé laisse la place à d'autres files.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class FileIAEtat(Base):
    __tablename__ = "file_ia_etat"

    cle: Mapped[str] = mapped_column(Text, primary_key=True, comment="file concernée : 'gpu'")
    etape: Mapped[str | None] = mapped_column(Text, comment="étape courante : contenu | enrich | embed")
    depuis: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="début de l'étape courante (borne le délai maximal)")
    nb_bascules: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0",
                                             comment="changements d'étape depuis la création (mesure)")
    maj_le: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=lambda: datetime.now().astimezone())
