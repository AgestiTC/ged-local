"""
Modèle Publication — trace des documents publiés vers BookStack (passerelle wiki)
================================================================================
UNE ligne par document logique d'un projet, identifié par `(projet, cle)`. Mémorise le `page_id`
BookStack → une republication du même `cle` **met à jour la MÊME page** (jamais de doublon), et le
`contenu_hash` permet la **déduplication**. Cf. `docs/plan-passerelle-wiki-multiprojets.md` (Lot 1).
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class Publication(Base):
    __tablename__ = "publications"
    __table_args__ = (UniqueConstraint("projet", "cle", name="uq_publication_projet_cle"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    projet: Mapped[str] = mapped_column(Text, nullable=False, comment="projets_publieurs.nom")
    cle: Mapped[str] = mapped_column(Text, nullable=False, comment="identifiant logique du doc chez le projet (slug/chemin)")
    livre: Mapped[str] = mapped_column(Text, nullable=False)
    chapitre: Mapped[str | None] = mapped_column(Text)
    page_id: Mapped[int | None] = mapped_column(Integer, comment="id de page BookStack (renseigné à la 1ʳᵉ publication)")
    url: Mapped[str | None] = mapped_column(Text)
    contenu_hash: Mapped[str] = mapped_column(Text, nullable=False, comment="sha256(markdown) → déduplication")
    genere_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), comment="horodatage de génération fourni par le projet")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
