"""
Propositions de modification des pages du wiki (16/11/2026)
============================================================
Tout utilisateur PROPOSE une modification d'une page BookStack depuis le lecteur Wiki de la Matothèque ;
rien n'est écrit dans BookStack sans un administrateur. L'AUTEUR (session SSO) est gardé.

`origine` dit qui applique :
- `bookstack` : page écrite dans BookStack → un admin « Applique » : la Matothèque écrit la page ;
- `cockpit`   : page publiée par un dépôt du cockpit → transmise au projet (`propositions/*.json` sur le
                NAS), le cockpit l'applique au `.md` (statut `transmise`) ;
- `projet`    : page publiée par un projet à jeton (sapyn, foulée) → la source est ailleurs : à reporter
                dans le projet à la main (statut `a_reporter`), jamais écrite dans BookStack (le prochain
                envoi du projet l'écraserait).
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base

STATUTS = ("proposee", "transmise", "a_reporter", "appliquee", "refusee")
OUVERTS = ("proposee", "a_reporter")


class PropositionWiki(Base):
    __tablename__ = "propositions_wiki"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    book_id: Mapped[int | None] = mapped_column(Integer)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    origine: Mapped[str] = mapped_column(Text, nullable=False, comment="bookstack | cockpit | projet")
    projet: Mapped[str | None] = mapped_column(Text)
    cle: Mapped[str | None] = mapped_column(Text)
    converti: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                           comment="page HTML convertie en Markdown pour l'édition")
    page_maj_le: Mapped[str | None] = mapped_column(Text, comment="updated_at BookStack à la proposition (conflit)")
    markdown_avant: Mapped[str] = mapped_column(Text, nullable=False)
    markdown_propose: Mapped[str] = mapped_column(Text, nullable=False)
    commentaire: Mapped[str] = mapped_column(Text, nullable=False, default="")
    auteur: Mapped[dict] = mapped_column(JSONB, nullable=False, comment="{identifiant, nom, email} de la session")
    statut: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    fichier_nas: Mapped[str | None] = mapped_column(Text, comment="proposition transmise au cockpit")
    decide_par: Mapped[str | None] = mapped_column(Text)
    decide_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    motif: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
