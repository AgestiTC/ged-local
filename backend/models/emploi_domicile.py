"""
Modèles Intervenant & Entretien — module emploi à domicile
==========================================================
Deux tables, et la façon dont elles se répartissent le travail est le seul vrai choix ici.

## `emploi_domicile_intervenants` — la PERSONNE

C'est **la même ligne du premier appel téléphonique jusqu'à la fin du contrat** : seul le
`statut` évolue (`a_contacter` → `entretien` → `retenue` → `employee` → `terminee` /
`ecartee`). Une table « candidates » et une table « salariées » obligeraient à ressaisir une
identité déjà connue **au moment où l'on signe** — le pire moment pour retaper une adresse.

## `emploi_domicile_entretiens` — la RENCONTRE

**Les réponses de la checklist appartiennent à l'entretien, pas à la personne.** C'était
l'erreur du plan initial, et elle se voit dès le deuxième rendez-vous : on revient chez la
même assistante maternelle, on repose une partie des questions, et certaines réponses ont
changé. Les écraser ferait disparaître l'information la plus utile — *ce qui a bougé entre
les deux visites*.

Un intervenant a donc N entretiens (appel, visite, seconde visite…), chacun avec :

- son **rendez-vous** (`date_prevue`, créneau, lieu) et son **statut** de suivi ;
- ses **réponses** (`reponses`, JSONB indexé par la **clé stable** des questions, cf.
  `services/emploi_domicile/contenu`) ;
- son **impression** et ses notes, écrites à chaud.

Un second entretien peut **reprendre** les réponses du précédent (`POST …/entretiens` avec
`reprendre_de`) : on ne repose pas quarante questions, on met à jour ce qui a changé — et
l'écran peut montrer les écarts.

## Pourquoi JSONB pour les réponses

Une table `reponses(entretien_id, cle, valeur)` n'apporterait qu'une jointure : Matothèque
est mono-utilisateur, les réponses se lisent et s'écrivent toujours **en bloc, pour un
entretien**, et jamais en travers de tous les entretiens. Même raisonnement que le suivi
porté par la ligne `jalons`.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from models.document import Base


class Intervenant(Base):
    """Une personne qu'on envisage d'employer, puis qu'on emploie."""

    __tablename__ = "emploi_domicile_intervenants"
    __table_args__ = (
        Index("ix_ed_intervenants_dossier", "dossier_id", "statut"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Rattaché au dossier qui porte la capacité `emploi-domicile` : « Devenir parent »
    # aujourd'hui, « Employer chez soi » demain. Supprimer le dossier emporte ses intervenants.
    dossier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dossiers_thematiques.id", ondelete="CASCADE"), nullable=False
    )
    # Profil au sens de `services/emploi_domicile/profils` : il décide du guichet et du contrat.
    profil: Mapped[str] = mapped_column(Text, nullable=False, default="assmat")

    nom: Mapped[str] = mapped_column(Text, nullable=False)
    prenom: Mapped[str | None] = mapped_column(Text)
    telephone: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    commune: Mapped[str | None] = mapped_column(Text)
    adresse: Mapped[str | None] = mapped_column(Text, comment="Lieu d'accueil pour une assistante maternelle")

    # Agrément (profil assmat) — l'échéance est la donnée qu'on oublie de regarder.
    agrement_numero: Mapped[str | None] = mapped_column(Text)
    agrement_echeance: Mapped[date | None] = mapped_column(Date)
    places: Mapped[int | None] = mapped_column(Integer, comment="Nombre de places de l'agrément")

    # Conditions ANNONCÉES, en texte libre : « 4,20 € net/h », « 3,50 € + 4 € d'entretien ».
    # Un champ numérique forcerait à choisir entre brut et net au moment où l'on note à la
    # volée ce qui vient d'être dit au téléphone.
    tarif_annonce: Mapped[str | None] = mapped_column(Text)
    disponibilite: Mapped[str | None] = mapped_column(Text)

    # 'a_contacter' | 'entretien' | 'retenue' | 'employee' | 'ecartee' | 'terminee'
    # Sans contrainte CHECK, comme `ressources.type` : ajouter un état ne doit pas demander
    # de migration.
    statut: Mapped[str] = mapped_column(Text, nullable=False, default="a_contacter")
    note: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Entretien(Base):
    """Une rencontre avec un intervenant : le rendez-vous, et la checklist qu'on y remplit."""

    __tablename__ = "emploi_domicile_entretiens"
    __table_args__ = (
        Index("ix_ed_entretiens_intervenant", "intervenant_id", "rang"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    intervenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("emploi_domicile_intervenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 1, 2, 3… — l'ordre des rencontres. Sert à nommer (« 2ᵉ entretien ») et à proposer la
    # reprise des réponses du précédent.
    rang: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 'telephone' | 'visite' | 'seconde_visite' | 'suivi'
    type: Mapped[str] = mapped_column(Text, nullable=False, default="visite")

    # Le rendez-vous. `date_prevue` sans heure = journée entière, comme pour les jalons.
    date_prevue: Mapped[date | None] = mapped_column(Date)
    # Horaires en TEXTE « HH:MM » : ces heures sont locales et flottantes (14 h chez elle
    # reste 14 h), alors qu'un type horaire invite à des conversions de fuseau qui
    # décaleraient le rendez-vous. Même choix que `jalons`.
    heure_debut: Mapped[str | None] = mapped_column(Text)
    heure_fin: Mapped[str | None] = mapped_column(Text)
    lieu: Mapped[str | None] = mapped_column(Text)

    # 'planifie' | 'fait' | 'annule'
    statut: Mapped[str] = mapped_column(Text, nullable=False, default="planifie")

    # Réponses de la checklist, indexées par la CLÉ STABLE de la question :
    #   {"lieu_animaux_tabac": {"avis": "reserve", "texte": "un chien, calme"}}
    # `avis` ∈ 'ok' | 'reserve' | 'non' | null (pas encore répondu).
    reponses: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict,
                                           server_default="'{}'::jsonb")

    # Ce qu'aucune grille ne capture, et qui décide pourtant : l'impression générale.
    # 1 à 5, saisie APRÈS la visite. Volontairement séparée des réponses : une grille
    # parfaitement remplie ne fait pas une bonne rencontre.
    impression: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)

    # Jalon créé depuis cet entretien, s'il a été posé dans le planning du dossier. On garde
    # le lien pour ne pas en créer deux, et pour proposer l'export .ics déjà en place.
    jalon_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jalons.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
