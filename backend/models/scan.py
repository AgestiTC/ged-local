"""
Modèles Scan — scanners, profils de scan, boîte à scans
=======================================================
Trois objets, cf. docs/plan-scan-vers-ged.md :

- **Scanner** : un appareil joignable en eSCL (le « scan » d'AirPrint/Mopria) — une URL, des
  capacités lues sur l'appareil, un dernier état de test. Pas de découverte mDNS (elle ne
  traverse pas Docker) : l'adresse est saisie à la main.
- **ScanProfil** : la réponse à « bon répertoire, bons tags » — où ranger (destination),
  quels tags pré-appliquer, quel nom donner, avec quels réglages scanner. `classement` dit
  qui décide : `fixe` (le profil range dès l'indexation) ou `ia_confirme` (le scan attend
  dans la boîte, l'application propose un profil, l'utilisateur confirme).
- **Scan** : une ligne de la boîte à scans. Un scan capturé en eSCL y naît `en_cours`
  (pages en attente d'assemblage) ; un PDF déposé dans le dossier surveillé de la boîte y
  entre `indexe`. Dans les deux cas il en sort `range` — et reste alors un document GED
  comme un autre, la ligne ne gardant que l'origine (scanner, profil, pages).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from models.document import Base

CLASSEMENTS = ("fixe", "ia_confirme")
STATUTS_SCAN = ("en_cours", "recu", "indexe", "range", "erreur")
MODELE_NOM_DEFAUT = "{date}_{profil}"


class Scanner(Base):
    __tablename__ = "scanners"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False, default="escl", comment="escl (seul type pour l'instant)")
    url: Mapped[str] = mapped_column(Text, nullable=False, comment="http://192.168.x.y[:port] — /eSCL ajouté par le client")
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    # Capacités lues sur l'appareil au dernier test (vitre / chargeur / recto-verso / dpi…).
    capacites: Mapped[dict | None] = mapped_column(JSONB)
    dernier_test: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dernier_etat: Mapped[str | None] = mapped_column(Text, comment="ok | erreur : <message>")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ScanProfil(Base):
    __tablename__ = "scan_profils"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    icone: Mapped[str | None] = mapped_column(Text, comment="un emoji, pour la modale")
    # `smb://hote/partage/Dossier/{annee}` ou chemin local sous la racine documents.
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list | None] = mapped_column(JSONB, default=list)
    # Indices de reconnaissance pour le mode `ia_confirme` (comparés à la catégorie, aux tags
    # et au texte OCR). Vides = le profil n'est jamais proposé, seulement choisi à la main.
    mots_cles: Mapped[list | None] = mapped_column(JSONB, default=list)
    modele_nom: Mapped[str | None] = mapped_column(Text, default=MODELE_NOM_DEFAUT,
                                                   comment="{date} {annee} {mois} {heure} {profil} {nom} {n}")
    # {source: vitre|chargeur, recto_verso: bool, couleur: couleur|gris|nb, dpi: int}
    reglages: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    scanner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scanners.id", ondelete="SET NULL"))
    classement: Mapped[str] = mapped_column(Text, default="fixe", comment="fixe | ia_confirme")
    position: Mapped[int] = mapped_column(Integer, default=0)
    actif: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    scanner: Mapped["Scanner | None"] = relationship()


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    profil_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scan_profils.id", ondelete="SET NULL"))
    scanner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scanners.id", ondelete="SET NULL"))
    statut: Mapped[str] = mapped_column(Text, default="en_cours", comment="en_cours | recu | indexe | range | erreur")
    origine: Mapped[str] = mapped_column(Text, default="escl", comment="escl (capturé) | boite (déposé dans le dossier)")
    nb_pages: Mapped[int] = mapped_column(Integer, default=0)
    # Dossier des pages capturées pas encore assemblées (vitre : une page par passage).
    session_dir: Mapped[str | None] = mapped_column(Text)
    reglages: Mapped[dict | None] = mapped_column(JSONB, comment="réglages effectivement demandés au scanner")
    erreur: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    range_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profil: Mapped["ScanProfil | None"] = relationship()
    scanner: Mapped["Scanner | None"] = relationship()
