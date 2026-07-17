"""
Sauvegarde de la base — pg_dump (manuel + AUTO planifié par le worker).
=======================================================================
Crée un dump PostgreSQL (format custom `-Fc`) dans `storage/backups/` (monté hors conteneur
via `BACKUP_DIR`). L'auto est planifié dans `job_worker._backup_scheduler`.

⚠️ RESTAURATION — piège de version rencontré le 17/07 : le client `pg_dump` de cette image est
**plus récent** (v17) que le serveur PostgreSQL (v16). Un dump v17 n'est PAS lisible par le
`pg_restore` du conteneur *postgres* (v16). Restaurer via le conteneur **backend** (client v17) :

    docker cp <dump> docflow_backend:/tmp/d.dump
    docker exec -e PGPASSWORD="$(cat secrets/db_password.txt)" docflow_backend \\
      pg_restore -h postgres -U <user> -d <db> --clean --if-exists --no-owner /tmp/d.dump

(les WARNING `already exists` / `unrecognized parameter transaction_timeout` sont cosmétiques ;
pg_restore continue). Pour un dump 100 % compatible v16 : `pg_dump` DEPUIS le conteneur postgres.
Correctif de fond prévu : épingler `postgresql-client-16` dans le Dockerfile.
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
    """Sauvegardes disponibles (plus récentes d'abord) : nom, taille, dossier, date."""
    if not BACKUP_DIR.exists():
        return []
    dossier = str(BACKUP_DIR)
    out = []
    for f in sorted(BACKUP_DIR.glob("*.dump"), key=lambda p: p.name, reverse=True):
        st = f.stat()
        out.append({
            "fichier": f.name,
            "taille_octets": st.st_size,
            "dossier": dossier,
            "date": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        })
    return out


def prune(garder: int) -> int:
    """Ne conserve que les `garder` sauvegardes les plus récentes ; supprime les plus anciennes.
    Retourne le nombre de fichiers supprimés. `garder <= 0` → ne purge rien (garde-fou)."""
    if garder <= 0 or not BACKUP_DIR.exists():
        return 0
    fichiers = sorted(BACKUP_DIR.glob("*.dump"), key=lambda p: p.name, reverse=True)
    supprimes = 0
    for f in fichiers[garder:]:
        try:
            f.unlink()
            supprimes += 1
        except OSError as e:
            log.warning("Purge sauvegarde impossible", fichier=f.name, erreur=str(e))
    if supprimes:
        log.info("Anciennes sauvegardes purgées", supprimees=supprimes, gardees=garder)
    return supprimes
