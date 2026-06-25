"""
Service SMB — lister partages, parcourir, lire (pysmb)
======================================================
Permet à Matothèque de découvrir et lire des fichiers sur un serveur SMB
distant (NAS), pour choisir quels dossiers indexer sans rien monter.

pysmb est synchrone → chaque appel est exécuté dans un thread (`asyncio.to_thread`)
pour ne pas bloquer l'event loop async de FastAPI.
"""

import asyncio
import tempfile
from pathlib import Path

from smb.SMBConnection import SMBConnection

from logger import get_logger

log = get_logger(__name__)

_PORT = 445  # SMB direct TCP


def _connect(hote: str, identifiant: str | None, secret: str | None, domaine: str | None) -> SMBConnection:
    """Ouvre une connexion SMB (NTLMv2, direct TCP). Invité si pas d'identifiant."""
    user = identifiant or "guest"
    pwd = secret or ""
    conn = SMBConnection(
        user, pwd, "matotheque", hote,
        domain=domaine or "",
        use_ntlm_v2=True, is_direct_tcp=True,
    )
    if not conn.connect(hote, _PORT, timeout=10):
        raise ConnectionError(f"Connexion SMB refusée sur {hote}")
    return conn


# ─── Versions synchrones (exécutées en thread) ────────────────────────────────

def _list_shares_sync(hote, identifiant, secret, domaine) -> list[str]:
    conn = _connect(hote, identifiant, secret, domaine)
    try:
        # type 0 = disque ; on exclut les partages admin/cachés ($)
        return sorted(
            s.name for s in conn.listShares()
            if getattr(s, "type", 0) == 0 and not s.name.endswith("$")
        )
    finally:
        conn.close()


def _browse_sync(hote, partage, chemin, identifiant, secret, domaine) -> list[dict]:
    conn = _connect(hote, identifiant, secret, domaine)
    try:
        entries = []
        for f in conn.listPath(partage, chemin or "/"):
            if f.filename in (".", ".."):
                continue
            entries.append({
                "nom": f.filename,
                "dossier": bool(f.isDirectory),
                "taille": int(f.file_size),
            })
        entries.sort(key=lambda e: (not e["dossier"], e["nom"].lower()))
        return entries
    finally:
        conn.close()


def _fetch_to_temp_sync(hote, partage, chemin, identifiant, secret, domaine) -> str:
    """Télécharge un fichier vers un fichier temporaire local. Retourne son chemin."""
    conn = _connect(hote, identifiant, secret, domaine)
    try:
        suffix = Path(chemin).suffix
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            conn.retrieveFile(partage, chemin, tmp)
        finally:
            tmp.close()
        return tmp.name
    finally:
        conn.close()


def _walk_files_sync(hote, partage, chemin, identifiant, secret, domaine, extensions) -> list[str]:
    """Liste récursivement les chemins de fichiers (filtrés par extension)."""
    conn = _connect(hote, identifiant, secret, domaine)
    fichiers: list[str] = []
    try:
        def _rec(rel: str):
            for f in conn.listPath(partage, rel or "/"):
                if f.filename in (".", ".."):
                    continue
                sous = f"{rel.rstrip('/')}/{f.filename}"
                if f.isDirectory:
                    _rec(sous)
                else:
                    ext = Path(f.filename).suffix.lstrip(".").lower()
                    if not extensions or ext in extensions:
                        fichiers.append(sous)
        _rec(chemin or "/")
    finally:
        conn.close()
    return fichiers


# ─── Wrappers async ───────────────────────────────────────────────────────────

async def list_shares(hote, identifiant=None, secret=None, domaine=None) -> list[str]:
    return await asyncio.to_thread(_list_shares_sync, hote, identifiant, secret, domaine)


async def browse(hote, partage, chemin="/", identifiant=None, secret=None, domaine=None) -> list[dict]:
    return await asyncio.to_thread(_browse_sync, hote, partage, chemin, identifiant, secret, domaine)


async def fetch_to_temp(hote, partage, chemin, identifiant=None, secret=None, domaine=None) -> str:
    return await asyncio.to_thread(_fetch_to_temp_sync, hote, partage, chemin, identifiant, secret, domaine)


async def walk_files(hote, partage, chemin, identifiant=None, secret=None, domaine=None, extensions=None) -> list[str]:
    return await asyncio.to_thread(_walk_files_sync, hote, partage, chemin, identifiant, secret, domaine, extensions)


async def test_connexion(hote, identifiant=None, secret=None, domaine=None) -> dict:
    """Teste la connexion et retourne {ok, partages|erreur}."""
    try:
        shares = await list_shares(hote, identifiant, secret, domaine)
        return {"ok": True, "partages": shares}
    except Exception as exc:
        log.warning("Test SMB échoué", hote=hote, erreur=str(exc))
        return {"ok": False, "erreur": str(exc)}
