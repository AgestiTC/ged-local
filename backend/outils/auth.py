"""
Accès de secours — `python -m outils.auth` (plan d'authentification, décision n° 5)
===================================================================================
Si le NAS (donc le SSO) est en panne, ou si le SSO est mal réglé, plus personne ne peut se connecter
à Matothèque. À lancer SUR LE LXC (`docker compose exec backend python -m outils.auth ...`), jamais
par l'API (aucune route ne l'offre) :

    --etat                 affiche l'état (suspension en cours ou non)
    --suspendre 2h         suspend le contrôle d'accès (30m, 2h, 1j ; max 24 h ; sans unité = minutes)
    --reprendre            annule la suspension tout de suite
    --eteindre             éteint l'authentification (auth_active = faux, en base) et efface toute
                           suspension : retour au fonctionnement d'avant l'étape 2

Quand utiliser quoi :
  - SSO/NAS en panne pour quelques heures : --suspendre. Elle ouvre tout SAUF les réglages
    d'authentification (oidc_*, auth_* : refusés tant que l'auth est active, pour qu'un anonyme ne
    puisse pas se déclarer admin via un autre SSO). Réactivation AUTOMATIQUE à l'échéance, 24 h max.
    À réserver à un LAN maîtrisé : pendant ce temps, toute personne qui joint l'API a tous les droits.
  - SSO durablement en panne ou mal réglé (il faut corriger les réglages) : --eteindre, corriger dans
    Paramètres, puis réactiver (l'activation exige un SSO complet et un admin déjà connecté).

Chaque action est journalisée (journal d'audit, acteur « cli », + journal applicatif). Les autres
processus relisent les réglages sous 2 secondes.
"""

import argparse
import asyncio
import re
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from models.audit import AuditEvent
from models.config import Config
from services import runtime_config
from services.acces import CLE_SUSPENSION, SUSPENSION_MAX, lire_echeance

log = get_logger(__name__)

_DUREE = re.compile(r"^(\d{1,4})([smhjd]?)$")
_UNITES = {"s": 1, "m": 60, "h": 3600, "j": 86400, "d": 86400, "": 60}


def parse_duree(texte: str) -> timedelta:
    """« 2h », « 30m », « 90s », « 1j » ; sans unité = minutes. ValueError si invalide ou hors (0, 24 h]."""
    m = _DUREE.match((texte or "").strip().lower())
    if not m:
        raise ValueError(f"Durée invalide : « {texte} » (exemples : 30m, 2h, 1j).")
    duree = timedelta(seconds=int(m.group(1)) * _UNITES[m.group(2)])
    if duree <= timedelta(0):
        raise ValueError("La durée doit être positive.")
    if duree > SUSPENSION_MAX:
        raise ValueError("Durée maximale : 24 heures (relancer la commande si besoin).")
    return duree


def _journal(db: AsyncSession, action: str, message: str, detail: dict | None = None) -> None:
    db.add(AuditEvent(acteur="cli", action=action, cible="authentification", statut="info",
                      message=message, detail=detail))
    log.warning(message, action=action, **(detail or {}))


async def suspendre(db: AsyncSession, duree: timedelta) -> datetime:
    """Écrit l'échéance (remplace une suspension en cours) ; rend la date de fin (UTC)."""
    fin = datetime.now(timezone.utc) + duree
    ligne = (await db.execute(select(Config).where(Config.cle == CLE_SUSPENSION))).scalar_one_or_none()
    if ligne is None:
        db.add(Config(cle=CLE_SUSPENSION, valeur=fin.isoformat()))
    else:
        ligne.valeur = fin.isoformat()
    _journal(db, "auth_suspension", "Contrôle d'accès SUSPENDU (accès de secours)", {"jusqua": fin.isoformat()})
    await db.commit()
    return fin


async def reprendre(db: AsyncSession) -> None:
    """Annule la suspension : le contrôle d'accès s'applique de nouveau tout de suite."""
    await db.execute(delete(Config).where(Config.cle == CLE_SUSPENSION))
    _journal(db, "auth_reprise", "Contrôle d'accès rétabli (fin de l'accès de secours)")
    await db.commit()


async def eteindre(db: AsyncSession) -> None:
    """Éteint l'authentification (même mécanisme d'écriture que les Paramètres) et efface la suspension."""
    await runtime_config.set_many(db, {"auth_active": "false"})
    await db.execute(delete(Config).where(Config.cle == CLE_SUSPENSION))
    _journal(db, "auth_extinction", "Authentification ÉTEINTE (accès de secours)",
             {"cles": ["auth_active"], "auth_active": "false"})
    await db.commit()


async def etat(db: AsyncSession) -> str:
    valeur = (await db.execute(select(Config.valeur).where(Config.cle == CLE_SUSPENSION))).scalar_one_or_none()
    fin = lire_echeance(valeur)
    if fin is None:
        return "Aucune suspension en cours : le contrôle d'accès s'applique."
    return f"Contrôle d'accès SUSPENDU jusqu'à {fin.astimezone().strftime('%d/%m/%Y %H:%M:%S')} ({fin.isoformat()})."


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m outils.auth",
                                description="Accès de secours : suspendre temporairement le contrôle d'accès.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--suspendre", metavar="DUREE", help="suspendre le contrôle d'accès (ex. 30m, 2h ; max 24h)")
    g.add_argument("--etat", action="store_true", help="afficher l'état de la suspension")
    g.add_argument("--reprendre", action="store_true", help="annuler la suspension")
    g.add_argument("--eteindre", action="store_true",
                   help="éteindre l'authentification (auth_active = faux) et effacer la suspension")
    return p


async def executer(argv: list[str], db: AsyncSession) -> str:
    """Exécute la commande et rend le message à afficher. SystemExit si les arguments sont invalides."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.suspendre is not None:
        try:
            duree = parse_duree(args.suspendre)
        except ValueError as e:
            parser.error(str(e))
        fin = await suspendre(db, duree)
        return (f"Contrôle d'accès suspendu jusqu'à {fin.astimezone().strftime('%d/%m/%Y %H:%M:%S')}. "
                "Réactivation automatique à l'échéance (ou --reprendre).")
    if args.eteindre:
        await eteindre(db)
        return ("Authentification éteinte (auth_active = faux) : l'API n'exige plus de connexion. "
                "Corrigez les réglages SSO dans Paramètres, puis réactivez.")
    if args.reprendre:
        await reprendre(db)
        return "Suspension annulée : le contrôle d'accès s'applique."
    return await etat(db)


async def _main(argv: list[str]) -> str:
    from database import AsyncSessionLocal, engine
    try:
        async with AsyncSessionLocal() as db:
            return await executer(argv, db)
    finally:
        await engine.dispose()


def main() -> None:
    print(asyncio.run(_main(sys.argv[1:])))


if __name__ == "__main__":
    main()
