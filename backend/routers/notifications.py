"""
Router Notifications — /api/notifications (la cloche de l'en-tête, 11/10/2026)
==============================================================================
  GET    /notifications                 → les plus récentes + nombre de non lues (les SIENNES)
  POST   /notifications/{id}/lu         → marquer lue
  POST   /notifications/lu-tout         → tout marquer lu
  DELETE /notifications/{id}            → supprimer
  POST   /notifications/idees/generer   → bilan « idées d'évolution » maintenant (tâche durable)
  GET    /notifications/preferences     → mes préférences d'alerte (+ catalogue des alertes)
  PUT    /notifications/preferences     → les enregistrer (les miennes seulement)

Étape 11 du rangement : chacun ne voit que ce qui lui est adressé (`notifier.filtre_visibles`) — une
alerte réservée aux administrateurs n'apparaît jamais à un utilisateur, même par son identifiant.
La fréquence du bilan automatique est un réglage (`notif_idees_frequence`, /api/system/config).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.notification import POSTE_LOCAL, Notification, NotificationPreference
from services import notifier

log = get_logger(__name__)
router = APIRouter()


def _uuid(valeur: str) -> uuid.UUID:
    try:
        return uuid.UUID(valeur)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")


def _to_dict(n: Notification) -> dict:
    return {
        "id": str(n.id), "type": n.type, "titre": n.titre, "contenu": n.contenu, "lu": n.lu,
        "lien": n.lien,
        "periode_debut": n.periode_debut.isoformat() if n.periode_debut else None,
        "periode_fin": n.periode_fin.isoformat() if n.periode_fin else None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


def _auth_active() -> bool:
    from services import oidc_service
    return oidc_service.auth_active()


def _qui(request: Request):
    """La personne connectée (None : authentification éteinte, ou jeton d'automate)."""
    return getattr(request.state, "utilisateur", None)


def _visibles(request: Request):
    return notifier.filtre_visibles(_qui(request), _auth_active())


@router.get("/notifications")
async def lister(request: Request, limite: int = Query(default=30, ge=1, le=200), db: AsyncSession = Depends(get_db)):
    visibles = _visibles(request)
    rows = (await db.execute(
        select(Notification).where(visibles).order_by(Notification.created_at.desc()).limit(limite))).scalars().all()
    non_lues = (await db.execute(
        select(func.count()).select_from(Notification).where(visibles, Notification.lu.is_(False)))).scalar() or 0
    return {"notifications": [_to_dict(n) for n in rows], "non_lues": non_lues}


@router.post("/notifications/lu-tout")
async def tout_lire(request: Request, db: AsyncSession = Depends(get_db)):
    await db.execute(update(Notification).where(_visibles(request), Notification.lu.is_(False))
                     .values(lu=True).execution_options(synchronize_session=False))
    await db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Préférences — déclarées AVANT les routes /{notification_id}                 #
# --------------------------------------------------------------------------- #
class PreferencesIn(BaseModel):
    alertes: dict[str, bool] = Field(default_factory=dict)
    seuil_disque_pct: int = Field(default=80, ge=50, le=99)
    seuil_croissance_pct: int = Field(default=50, ge=5, le=1000)
    seuil_croissance_gio: int = Field(default=5, ge=0, le=10_000)
    silence_debut: str | None = None
    silence_fin: str | None = None

    @field_validator("silence_debut", "silence_fin")
    @classmethod
    def _heure(cls, v: str | None) -> str | None:
        v = (v or "").strip() or None
        if not notifier.heure_valide(v):
            raise ValueError("heure attendue au format HH:MM")
        return v

    @field_validator("alertes")
    @classmethod
    def _types(cls, v: dict[str, bool]) -> dict[str, bool]:
        inconnus = set(v) - set(notifier.TYPES)
        if inconnus:
            raise ValueError(f"alertes inconnues : {', '.join(sorted(inconnus))}")
        return v


def _uid(request: Request) -> uuid.UUID:
    """À qui appartiennent les préférences : la personne connectée, sinon le poste local (auth éteinte).
    Un jeton d'automate n'a pas de préférences."""
    u = _qui(request)
    if u is not None:
        return u.id
    if _auth_active():
        raise HTTPException(status_code=403, detail="Préférences réservées à une personne connectée")
    return POSTE_LOCAL


def _peut_admin(request: Request) -> bool:
    u = _qui(request)
    return not _auth_active() or (u is not None and u.role == notifier.ADMIN)


def _prefs_dict(p: NotificationPreference, admin: bool) -> dict:
    catalogue = [{"type": t, "libelle": d["libelle"], "active": notifier.alerte_active(p, t)}
                 for t, d in notifier.TYPES.items() if admin or not d.get("admin")]
    return {"alertes": catalogue, "seuil_disque_pct": p.seuil_disque_pct,
            "seuil_croissance_pct": p.seuil_croissance_pct, "seuil_croissance_gio": p.seuil_croissance_gio,
            "silence_debut": p.silence_debut, "silence_fin": p.silence_fin}


@router.get("/notifications/preferences")
async def lire_preferences(request: Request, db: AsyncSession = Depends(get_db)):
    return _prefs_dict(await notifier.preferences(db, _uid(request)), _peut_admin(request))


@router.put("/notifications/preferences")
async def enregistrer_preferences(request: Request, body: PreferencesIn, db: AsyncSession = Depends(get_db)):
    uid = _uid(request)
    admin = _peut_admin(request)
    interdits = [t for t in body.alertes if notifier.TYPES[t].get("admin") and not admin]
    if interdits:
        raise HTTPException(status_code=403, detail="Alertes réservées aux administrateurs")
    if (body.silence_debut is None) != (body.silence_fin is None):
        raise HTTPException(status_code=422, detail="Heures de silence : début ET fin, ou aucune")
    p = await db.get(NotificationPreference, uid)
    if p is None:
        p = NotificationPreference(utilisateur_id=uid, alertes={})
        db.add(p)
    p.alertes = {**(p.alertes or {}), **body.alertes}
    p.seuil_disque_pct, p.seuil_croissance_pct = body.seuil_disque_pct, body.seuil_croissance_pct
    p.seuil_croissance_gio = body.seuil_croissance_gio
    p.silence_debut, p.silence_fin = body.silence_debut, body.silence_fin
    await db.commit()
    return _prefs_dict(p, admin)


# --------------------------------------------------------------------------- #
# Une notification                                                             #
# --------------------------------------------------------------------------- #
async def _la_mienne(request: Request, db: AsyncSession, notification_id: str) -> Notification:
    n = (await db.execute(select(Notification).where(
        Notification.id == _uuid(notification_id), _visibles(request)))).scalars().first()
    if not n:
        raise HTTPException(status_code=404, detail="Notification introuvable")
    return n


@router.post("/notifications/{notification_id}/lu")
async def marquer_lu(notification_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    n = await _la_mienne(request, db, notification_id)
    n.lu = True
    await db.commit()
    return _to_dict(n)


@router.delete("/notifications/{notification_id}")
async def supprimer(notification_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    n = await _la_mienne(request, db, notification_id)
    await db.execute(delete(Notification).where(Notification.id == n.id))
    await db.commit()
    return {"ok": True}


@router.post("/notifications/idees/generer", status_code=202)
async def generer_idees(db: AsyncSession = Depends(get_db)):
    """Bilan « idées d'évolution » à la demande : tâche durable (file GPU), suivie par son job_id."""
    from services import job_worker
    from services.idees_evolution import TYPE

    job_id = await job_worker.enqueue(db, TYPE, {"force": True})
    await db.commit()
    log.info("Bilan idées d'évolution demandé", job_id=job_id)
    return {"job_id": job_id}
