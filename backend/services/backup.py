"""
Sauvegarde de la base — phase MANUELLE (pg_dump).
=================================================
Crée un dump PostgreSQL (format custom `-Fc`, restaurable via `pg_restore`) dans
`storage/backups/` (monté hors conteneur). Phase 2 (auto/planifiée) = plus tard (cf. ROADMAP).
Restauration (manuelle, DESTRUCTIVE) :
    pg_restore -h <host> -U <user> -d <db> --clean --if-exists storage/backups/<fichier>.dump
"""
import asyncio
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from config import get_settings
from logger import get_logger

settings = get_settings()
log = get_logger(__name__)

BACKUP_DIR = Path("/app/storage/backups")


def _conn() -> tuple[str, str, str, str, str]:
    """(user, password, host, port, db) depuis DATABASE_URL."""
    url = settings.database_url
    m = re.match(r".+://([^:]+):([^@]+)@([^:/]+):?(\d+)?/([^?]+)", url)
    if not m:
        raise RuntimeError("DATABASE_URL non parsable")
    user, pwd, host, port, db = m.groups()
    return user, pwd, host, port or "5432", db


async def dump() -> dict:
    """Lance pg_dump → fichier .dump horodaté. Retourne {fichier, taille_octets, date}."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    user, pwd, host, port, db = _conn()
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"matotheque-{ts}.dump"
    env = {**os.environ, "PGPASSWORD": pwd}
    proc = await asyncio.create_subprocess_exec(
        "pg_dump", "-h", host, "-p", port, "-U", user, "-d", db, "-Fc", "-f", str(dest),
        env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError((err or b"").decode(errors="replace")[:400] or "pg_dump a échoué")
    taille = dest.stat().st_size
    log.info("Sauvegarde base créée", fichier=dest.name, octets=taille)
    return {"fichier": dest.name, "taille_octets": taille, "date": ts}


def liste() -> list[dict]:
    """Sauvegardes disponibles (plus récentes d'abord)."""
    if not BACKUP_DIR.exists():
        return []
    out = []
    for f in sorted(BACKUP_DIR.glob("*.dump"), key=lambda p: p.name, reverse=True):
        out.append({"fichier": f.name, "taille_octets": f.stat().st_size})
    return out
