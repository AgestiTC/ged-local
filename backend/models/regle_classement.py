"""
Modèle RegleClassement — classement imposé par EMPLACEMENT
==========================================================
Plan « Recevoir la documentation des autres applications » (docs/plan-reception-doc-applications.md),
étape 1. Une règle s'applique à tout document dont le chemin commence par `prefixe_chemin`
(la règle au préfixe le plus long l'emporte) :

- `categorie` / `sous_categorie` / `tags` sont posés dès l'import, avant l'IA ;
- `tag_depuis_sous_dossier` : le 1ᵉʳ sous-dossier sous le préfixe devient un tag
  (`…/Docs-applications/composeur-yealink/guide.md` → tag `composeur-yealink`) ;
- `classement` :
    * `fixe` → l'IA ne touche NI à la catégorie NI aux tags (elle calcule toujours résumé,
      entités et plongements) ; le classement survit aux nouvelles versions ;
    * `ia`   → la règle pose son classement à l'import, puis l'IA le remplace comme d'habitude
      (les tags de la règle sont conservés en tête).
"""
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base

CLASSEMENTS = ("fixe", "ia")


class RegleClassement(Base):
    __tablename__ = "regles_classement"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    prefixe_chemin: Mapped[str] = mapped_column(
        Text, nullable=False, unique=True,
        comment="Début de chemin visé, ex. smb://192.168.42.200/Partage-Nas-Mato/[GED]/Docs-applications/")
    categorie: Mapped[str | None] = mapped_column(Text)
    sous_categorie: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list | None] = mapped_column(JSON, comment="Tags posés par la règle (liste de textes)")
    tag_depuis_sous_dossier: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    classement: Mapped[str] = mapped_column(Text, default="fixe", nullable=False, comment="fixe | ia")
    actif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
