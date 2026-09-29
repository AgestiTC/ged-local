"""
Modèle IAEchec — appels IA en échec, par modèle
===============================================
Un appel à Ollama qui échoue (HTTP 4xx/5xx, délai, connexion refusée, réponse vide ou
inexploitable) était jusqu'ici ABSORBÉ : le repli « même famille » passait au modèle suivant,
un `warning` partait au journal, et une fonction entière pouvait échouer des heures sans que
rien ne le dise (cf. 488 refus HTTP 400 trouvés par la capture de l'AIGUILLEUR le 05/09).

Une ligne par appel en échec. En base et non en mémoire : l'API tourne sur plusieurs
processus, plus le worker — un compteur par processus n'en verrait qu'une partie.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class IAEchec(Base):
    __tablename__ = "ia_echecs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    modele: Mapped[str] = mapped_column(Text, comment="modèle demandé (ex. llama3.1:latest)")
    operation: Mapped[str] = mapped_column(Text, comment="generate | stream | chat | embed | enrichissement")
    nature: Mapped[str] = mapped_column(
        Text, comment="http | delai | connexion | vide | inexploitable | non_json | autre")
    code_http: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)
    base_url: Mapped[str | None] = mapped_column(Text, comment="passerelle ou Ollama direct")
    # Horodaté côté Python, à la microseconde : plusieurs échecs peuvent tomber dans la même
    # seconde (retries), et « le dernier message » doit rester le dernier.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), server_default=func.now())

    __table_args__ = (
        Index("idx_ia_echecs_created", "created_at"),
        Index("idx_ia_echecs_modele", "modele"),
    )
