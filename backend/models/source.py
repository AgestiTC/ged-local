"""
Modèle Source — origine de fichiers à indexer
==============================================
Une « source » décrit OÙ Matothèque va chercher des documents :
- type `local` : un chemin filesystem (volume monté, ex. NAS en prod).
- type `smb`   : un partage réseau distant (hôte + partage) lu via SMB.

Les identifiants SMB (mot de passe / token) sont stockés **chiffrés** (Fernet) —
jamais en clair (cf. services/crypto.py).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base

#: À quoi sert une source (14/11/2026, plan Rangement sur Sources SMB, S2). Deux sources peuvent viser
#: le même NAS avec deux comptes : celle de la GED (qui a indexé les documents) et celle du Rangement
#: (`svc-rangement`, qui a le droit d'écrire). La GED retrouve une source PAR L'HÔTE d'un document :
#: elle ne doit jamais tomber sur celle du Rangement — d'où ce marquage, plutôt que l'ancienneté.
USAGE_GED = "ged"
USAGE_RANGEMENT = "rangement"
USAGES = (USAGE_GED, USAGE_RANGEMENT)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False, comment="local | smb")

    # Commun
    chemin_base: Mapped[str | None] = mapped_column(Text, comment="local: chemin FS ; smb: partage ou partage/sous-dossier")

    # Spécifique SMB
    hote: Mapped[str | None] = mapped_column(Text, comment="IP/nom du serveur SMB")
    domaine: Mapped[str | None] = mapped_column(Text)
    identifiant: Mapped[str | None] = mapped_column(Text, comment="utilisateur SMB")
    secret_chiffre: Mapped[str | None] = mapped_column(Text, comment="mot de passe/token chiffré (Fernet)")

    # Synchro automatique : intervalle en minutes (None/0 = désactivée), date du dernier
    # passage et récapitulatif du dernier diff (affiché tel quel dans l'UI).
    sync_intervalle_minutes: Mapped[int | None] = mapped_column(Integer)
    dernier_sync: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dernier_sync_recap: Mapped[dict | None] = mapped_column(JSONB)
    # Fréquence PAR DOSSIER : {"partage/dossier": minutes}. 0 = jamais ; clé absente = suit
    # l'intervalle de la source. Permet de ne surveiller que les dossiers qui bougent.
    sync_dossiers: Mapped[dict | None] = mapped_column(JSONB)

    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    usage: Mapped[str] = mapped_column(Text, nullable=False, default=USAGE_GED, server_default=USAGE_GED,
                                       comment="ged | rangement — une source du Rangement ne sert jamais à la GED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
