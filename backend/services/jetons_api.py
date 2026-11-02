"""
Jetons d'automates — n8n, scripts (plan d'authentification, étape 4)
====================================================================
Un automate n'a pas de navigateur ni de compte SSO : il présente `Authorization: Bearer mato_…`.
Même modèle que les sessions et la passerelle wiki : la base ne garde que l'EMPREINTE SHA-256, le
jeton en clair n'est montré qu'une fois. Le contrôle lui-même est dans `services/acces.py` (un seul
endroit décide) ; ce module ne fait que créer, retrouver et dater les jetons.

Refusé = inconnu, révoqué ou expiré. Un jeton `lecture` n'écrit jamais ; son `role` suit le même
classement des routes que les personnes. Un jeton ne gère jamais l'authentification (`/api/auth/*`) :
il ne peut ni créer un autre jeton ni toucher aux personnes.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.auth import JetonApi

# Préfixe reconnaissable : un jeton collé par erreur dans un dépôt ou un ticket se repère au premier coup d'œil.
PREFIXE = "mato_"
PORTEES = ("lecture", "ecriture")
MAJ_UTILISATION = timedelta(minutes=1)   # au plus une écriture de « dernière utilisation » par minute


def nouveau_jeton() -> str:
    """256 bits aléatoires, URL-safe, préfixés. Montré UNE seule fois."""
    return PREFIXE + secrets.token_urlsafe(32)


def empreinte(jeton: str) -> str:
    """SHA-256 (hex) — seule forme conservée en base."""
    return hashlib.sha256(jeton.encode()).hexdigest()


def lire_bearer(request: Request) -> str | None:
    """Jeton de l'en-tête `Authorization: Bearer …`, ou None s'il n'y en a pas (ou vide)."""
    valeur = request.headers.get("authorization") or ""
    schema, _, jeton = valeur.partition(" ")
    if schema.lower() != "bearer":
        return None
    return jeton.strip() or None


def _utc(dt: datetime | None) -> datetime | None:
    """SQLite rend des dates naïves : on les lit comme UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def valide(jeton: JetonApi, maintenant: datetime) -> bool:
    """Ni révoqué, ni expiré."""
    if jeton.revoque is not None:
        return False
    fin = _utc(jeton.expire)
    return fin is None or maintenant < fin


async def authentifier(db: AsyncSession, jeton_clair: str) -> JetonApi | None:
    """Jeton valide correspondant, ou None. Date la dernière utilisation (au plus une fois par minute)."""
    jeton = (await db.execute(select(JetonApi).where(JetonApi.empreinte == empreinte(jeton_clair)))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if jeton is None or not valide(jeton, now):
        return None
    derniere = _utc(jeton.derniere_utilisation)
    if derniere is None or now - derniere >= MAJ_UTILISATION:
        # Conditionnel et en SQL direct : deux process qui servent le même automate n'écrivent pas deux fois.
        await db.execute(update(JetonApi).where(
            JetonApi.id == jeton.id,
            or_(JetonApi.derniere_utilisation.is_(None), JetonApi.derniere_utilisation < now - MAJ_UTILISATION))
            .values(derniere_utilisation=now).execution_options(synchronize_session=False))
        await db.commit()
    return jeton
