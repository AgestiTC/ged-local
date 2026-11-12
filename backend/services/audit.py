"""
Service Audit — journal d'activité métier (observabilité Phase 2)
=================================================================
`emit()` enregistre un événement dans `audit_events`. **Best effort absolu** : ne lève JAMAIS
(l'audit ne doit pas casser l'opération auditée) et n'impose aucune session à l'appelant.

Un `correlation_id` relie les événements d'une même opération à travers les couches
(UI → API → worker). Utilitaire `new_correlation_id()` pour en créer un.

**Auteur** (plan d'authentification, étape 5) : la personne ou le jeton d'automate à l'origine de
l'action. Posé une fois par requête (`services/acces.py`) ou par tâche (`job_worker._run`, depuis le
propriétaire du job) dans une ContextVar ; `emit()` le reprend d'office. Authentification éteinte :
aucun auteur (`None`), comme avant.
"""

import uuid
from contextvars import ContextVar

from database import AsyncSessionLocal
from logger import get_logger
from models.audit import AuditEvent

log = get_logger(__name__)

# Propre à la requête ou à la tâche asyncio en cours : ne déborde jamais sur une autre.
_auteur: ContextVar[str | None] = ContextVar("audit_auteur", default=None)


def definir_auteur(auteur: str | None) -> None:
    """Auteur des événements émis dans le contexte courant (requête HTTP ou tâche du worker)."""
    _auteur.set(auteur)


def auteur_courant() -> str | None:
    return _auteur.get()


# Rôle de l'acteur du contexte courant : « admin » | « utilisateur » pour une SESSION, « jeton » pour un
# automate, None si inconnu (authentification inactive ou suspendue, tâche sans propriétaire…). Posé
# comme l'auteur (middleware d'accès, worker). Sert à réserver l'IA GECO aux sessions administrateur :
# None / inconnu = « pas administrateur » (le doute refuse).
_role: ContextVar[str | None] = ContextVar("audit_role", default=None)


def definir_role(role: str | None) -> None:
    _role.set(role)


def role_courant() -> str | None:
    return _role.get()


def new_correlation_id() -> str:
    """Nouvel identifiant de corrélation (préfixé pour être reconnaissable dans les logs)."""
    return f"cor_{uuid.uuid4().hex[:16]}"


async def _ecrire(action: str, statut: str, *, acteur: str, correlation_id: str | None, cible: str | None,
                  duree_ms: int | None, message: str | None, detail: dict | None, auteur: str | None) -> None:
    """Écrit l'événement ; LAISSE REMONTER toute exception (voir `emit` et `emit_strict`)."""
    async with AsyncSessionLocal() as db:
        db.add(AuditEvent(
            correlation_id=correlation_id, acteur=acteur, action=action, cible=cible,
            auteur=auteur or _auteur.get(), statut=statut, duree_ms=duree_ms,
            message=(message or "")[:2000] or None, detail=detail,
        ))
        await db.commit()


async def emit(action: str, statut: str, *, acteur: str = "api",
               correlation_id: str | None = None, cible: str | None = None,
               duree_ms: int | None = None, message: str | None = None,
               detail: dict | None = None, auteur: str | None = None) -> None:
    """
    Enregistre un événement d'audit. **Ne lève jamais** : un échec d'audit est logué en debug
    et ignoré, pour ne pas perturber l'opération métier. `auteur` : à défaut, celui du contexte.
    """
    try:
        await _ecrire(action, statut, acteur=acteur, correlation_id=correlation_id, cible=cible,
                      duree_ms=duree_ms, message=message, detail=detail, auteur=auteur)
    except Exception as e:  # noqa: BLE001 — l'audit est secondaire, jamais bloquant
        log.debug("Audit non enregistré", action=action, statut=statut, erreur=str(e))


async def emit_strict(action: str, statut: str, *, acteur: str = "api",
                      correlation_id: str | None = None, cible: str | None = None,
                      duree_ms: int | None = None, message: str | None = None,
                      detail: dict | None = None, auteur: str | None = None) -> None:
    """
    Comme `emit`, mais **LAISSE REMONTER** l'échec d'écriture. Pour les actions qu'on ne doit pas
    faire sans trace (envoi vers GECO : pas de journal, pas d'envoi). `emit` garde son comportement.
    """
    await _ecrire(action, statut, acteur=acteur, correlation_id=correlation_id, cible=cible,
                  duree_ms=duree_ms, message=message, detail=detail, auteur=auteur)
