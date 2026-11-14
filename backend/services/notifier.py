"""
Le seul point d'entrée des notifications (plan rangement + mails, décision d'architecture n° 4).

Un producteur (le Rangement aujourd'hui, les mails demain) décrit un `Evenement` ; `notifier()` décide :

- **à qui** : les administrateurs pour une alerte réservée (`pour_role="admin"`), la personne qui a
  lancé la tâche quand on la connaît ; authentification éteinte → une seule ligne « pour le rôle »
  (personne n'est connecté, le poste local lit tout) ;
- **si** : selon les préférences de CHAQUE destinataire (alerte coupée, seuils) — une ligne par
  personne, donc les réglages de l'une ne touchent jamais l'autre ;
- **quand** : pendant ses heures de silence, la notification est écrite mais masquée jusqu'à leur
  fin (`visible_le`) ;
- **combien** : une seule non lue par (destinataire, clé) — la suivante la remplace.

`filtre_visibles()` est la règle de lecture, appliquée par la route de la cloche.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import and_, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from models.auth import Utilisateur
from models.notification import POSTE_LOCAL, Notification, NotificationPreference

log = get_logger(__name__)

ADMIN = "admin"

#: Les alertes qu'une personne peut couper. `admin` : réservée aux administrateurs (le Rangement est
#: un module admin) ; `defaut` : active tant que la personne n'a rien choisi.
TYPES: dict[str, dict] = {
    "rangement_hors_plan": {"libelle": "Éléments hors du plan de classement", "admin": True, "defaut": True},
    "rangement_disque": {"libelle": "Place disque (seuil d'occupation)", "admin": True, "defaut": True},
    "rangement_croissance": {"libelle": "Croissance anormale d'un dossier", "admin": True, "defaut": True},
    "rangement_doublons": {"libelle": "Nouvelles copies sur disque", "admin": True, "defaut": True},
    "rangement_taches": {"libelle": "Fin des tâches de rangement", "admin": True, "defaut": True},
}

_HEURE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


@dataclass
class Evenement:
    type: str
    cle: str
    titre: str
    contenu: str
    lien: str | None = None
    #: Mesures comparées aux seuils de chaque destinataire (`pct`, `octets`).
    mesures: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Préférences                                                                  #
# --------------------------------------------------------------------------- #
def heure_valide(valeur: str | None) -> bool:
    return valeur is None or bool(_HEURE.match(valeur))


def _defaut(uid: uuid.UUID) -> NotificationPreference:
    return NotificationPreference(utilisateur_id=uid, alertes={}, seuil_disque_pct=80, seuil_croissance_pct=50,
                                  seuil_croissance_gio=5, silence_debut=None, silence_fin=None)


async def preferences(db: AsyncSession, uid: uuid.UUID | None) -> NotificationPreference:
    """Les préférences d'une personne (`None` = poste local) ; valeurs par défaut si rien n'est enregistré.
    L'objet rendu n'est PAS ajouté à la session."""
    uid = uid or POSTE_LOCAL
    return await db.get(NotificationPreference, uid) or _defaut(uid)


def alerte_active(pref: NotificationPreference, type_: str) -> bool:
    valeur = (pref.alertes or {}).get(type_)
    return bool(TYPES.get(type_, {}).get("defaut", True)) if valeur is None else bool(valeur)


def accepte(pref: NotificationPreference, ev: Evenement) -> bool:
    """Cette personne veut-elle cette notification ? PURE."""
    if not alerte_active(pref, ev.type):
        return False
    m = ev.mesures or {}
    if ev.type == "rangement_disque":
        return float(m.get("pct", 0)) >= pref.seuil_disque_pct
    if ev.type == "rangement_croissance":
        return (float(m.get("pct", 0)) >= pref.seuil_croissance_pct
                and int(m.get("octets", 0)) >= pref.seuil_croissance_gio * 1024 ** 3)
    return True


def fin_de_silence(pref: NotificationPreference, maintenant_local: datetime) -> datetime | None:
    """Si `maintenant_local` tombe dans les heures de silence, l'instant (UTC) où elles finissent. PURE.
    La plage peut passer minuit (22:00 → 07:00). Plage vide ou incomplète : jamais de silence."""
    if not (pref.silence_debut and pref.silence_fin and heure_valide(pref.silence_debut)
            and heure_valide(pref.silence_fin)) or pref.silence_debut == pref.silence_fin:
        return None
    debut = time.fromisoformat(pref.silence_debut)
    fin = time.fromisoformat(pref.silence_fin)
    h = maintenant_local.timetz().replace(tzinfo=None)
    dans = (debut <= h < fin) if debut < fin else (h >= debut or h < fin)
    if not dans:
        return None
    jour = maintenant_local.date() if h < fin else maintenant_local.date() + timedelta(days=1)
    echeance = datetime.combine(jour, fin, tzinfo=maintenant_local.tzinfo)
    return echeance.astimezone(timezone.utc)


def _maintenant_local() -> datetime:
    from services.rangement.service import maintenant_local
    return maintenant_local()


# --------------------------------------------------------------------------- #
# Destinataires et écriture                                                    #
# --------------------------------------------------------------------------- #
def _auth_active() -> bool:
    try:
        from services import oidc_service
        return oidc_service.auth_active()
    except Exception:  # noqa: BLE001 — sans réglages lisibles, on ne vise personne en particulier
        return False


async def destinataires(db: AsyncSession, pour_role: str | None, proprietaire: str | None = None) -> list[Utilisateur | None]:
    """Les personnes visées. `None` dans la liste = une ligne sans destinataire nommé (lue selon `pour_role`)."""
    if not _auth_active():
        return [None]
    q = select(Utilisateur).where(Utilisateur.bloque.is_(False))
    if pour_role == ADMIN:
        q = q.where(Utilisateur.role == ADMIN)
    gens = list((await db.execute(q)).scalars().all())
    if proprietaire:
        lui = [u for u in gens if u.identifiant == proprietaire]
        if lui:
            return lui
    return gens or [None]


async def _ecrire(db: AsyncSession, ev: Evenement, uid: uuid.UUID | None, pour_role: str | None,
                  visible_le: datetime | None) -> None:
    """Remplace la non lue de même clé, sinon insère. L'index unique partiel (PostgreSQL) arbitre
    deux écritures simultanées : la perdante relit et remplace."""
    for _ in range(2):
        q = select(Notification).where(Notification.cle == ev.cle, Notification.lu.is_(False))
        q = q.where(Notification.utilisateur_id == uid) if uid else q.where(Notification.utilisateur_id.is_(None))
        n = (await db.execute(q.limit(1))).scalars().first()
        try:
            async with db.begin_nested():
                if n is None:
                    n = Notification(cle=ev.cle, utilisateur_id=uid)
                    db.add(n)
                n.type, n.titre, n.contenu, n.lien = ev.type, ev.titre, ev.contenu, ev.lien
                n.pour_role, n.visible_le = pour_role, visible_le
                n.created_at = datetime.now(timezone.utc)
            return
        except IntegrityError:
            continue


async def notifier(db: AsyncSession, ev: Evenement, *, pour_role: str | None = ADMIN,
                   proprietaire: str | None = None, maintenant_local: datetime | None = None) -> int:
    """Écrit la notification pour chaque destinataire qui la veut. Rend le nombre de lignes écrites.
    N'engage pas la transaction : l'appelant fait `commit`."""
    if pour_role is None and TYPES.get(ev.type, {}).get("admin"):
        pour_role = ADMIN
    maintenant_local = maintenant_local or _maintenant_local()
    ecrites = 0
    for u in await destinataires(db, pour_role, proprietaire):
        pref = await preferences(db, u.id if u else None)
        if not accepte(pref, ev):
            continue
        await _ecrire(db, ev, u.id if u else None, pour_role, fin_de_silence(pref, maintenant_local))
        ecrites += 1
    if ecrites:
        log.info("Notification", type=ev.type, cle=ev.cle, destinataires=ecrites)
    return ecrites


# --------------------------------------------------------------------------- #
# Lecture                                                                      #
# --------------------------------------------------------------------------- #
def filtre_visibles(utilisateur: Utilisateur | None, auth_active: bool, maintenant: datetime | None = None):
    """Ce que voit une personne dans la cloche. Authentification éteinte : tout (sauf le silence)."""
    maintenant = maintenant or datetime.now(timezone.utc)
    pas_en_silence = or_(Notification.visible_le.is_(None), Notification.visible_le <= maintenant)
    if not auth_active:
        return pas_en_silence
    est_admin = utilisateur is not None and utilisateur.role == ADMIN
    pour_tous = and_(Notification.utilisateur_id.is_(None),
                     true() if est_admin else Notification.pour_role.is_(None))
    a_moi = Notification.utilisateur_id == utilisateur.id if utilisateur is not None else None
    qui = or_(pour_tous, a_moi) if a_moi is not None else pour_tous
    return and_(qui, pas_en_silence)
