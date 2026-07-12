"""
Connecteur Synology (DSM FileStation) — LECTURE.
================================================
Porté de la référence `O:\\Github\\acces-syno` (backend/synology/). Accès au NAS via :
  - **transport** : IP/host directe, DDNS, ou **QuickConnect** (relais, sans ouvrir de port) ;
  - **auth** : `SYNO.API.Auth` (login → SID) ;
  - **fichiers** : `SYNO.FileStation.List / GetInfo / Download` (stream).

Champs `Source` réutilisés : `hote` = ID QuickConnect **ou** IP/host(:port) **ou** URL ;
`identifiant` = compte DSM ; `secret_chiffre` = mot de passe DSM (chiffré Fernet) ;
`chemin_base` = dossier de départ (share-relative, ex. `/homes`).
"""
from __future__ import annotations

import json
import re
import tempfile
from collections.abc import AsyncIterator

import httpx

from logger import get_logger
from models.source import Source
from services import crypto
from services.connectors.base import register

log = get_logger(__name__)

_RESOLVER_URL = "https://global.quickconnect.to/Serv.php"


class SynologyError(RuntimeError):
    pass


def _norm_qc_id(raw: str) -> str:
    """Extrait l'ID QuickConnect de diverses formes (URL, DDNS…)."""
    s = (raw or "").strip()
    s = re.sub(r"(?i)^https?://", "", s)
    s = re.sub(r"(?i)^www\.", "", s)
    s = re.sub(r"(?i)^quickconnect\.to/+", "", s)
    s = re.sub(r"(?i)\.(direct|relay)\.quickconnect\.to.*$", "", s)
    s = re.sub(r"(?i)\.synology\.me.*$", "", s)
    return s.rstrip("/")


def _direct_base(hote: str) -> str:
    """URL DSM directe depuis un host/IP (défaut HTTPS 5001)."""
    h = (hote or "").strip()
    if h.startswith(("http://", "https://")):
        return h.rstrip("/")
    if ":" in h.split("/")[0]:            # host:port fourni
        return f"https://{h}"
    return f"https://{h}:5001"


async def _resolve_base(hote: str, timeout: float = 10.0) -> str:
    """
    URL de base DSM joignable. Si `hote` ressemble à une IP/host (point ou port) ou une URL
    → accès direct. Sinon (ID QuickConnect « nu ») → résolution via le relais Synology.
    """
    h = (hote or "").strip()
    direct_like = h.startswith(("http://", "https://")) or ("." in h) or (":" in h)
    if direct_like:
        return _direct_base(h)

    qc = _norm_qc_id(h)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(_RESOLVER_URL, json={
            "version": 1, "command": "get_server_info", "stop_when_error": False,
            "stop_when_success": True, "id": "dsm_portal_https", "serverID": qc, "is_gofile": False,
        })
        r.raise_for_status()
        data = r.json()
    server = data.get("server") or {}
    candidates: list[str] = []
    if (server.get("external") or {}).get("ip"):
        candidates.append(f"https://{server['external']['ip']}:5001")
    if (data.get("smartdns") or {}).get("host"):
        candidates.append(f"https://{data['smartdns']['host']}:5001")
    svc = data.get("service") or {}
    if svc.get("relay_ip"):
        candidates.append(f"https://{svc['relay_ip']}:{svc.get('relay_port') or 5001}")
    if not candidates:
        raise SynologyError(f"QuickConnect '{qc}' : aucun point d'accès résolu")

    # Premier candidat joignable (query.cgi).
    async with httpx.AsyncClient(timeout=6.0, verify=False) as client:
        for url in candidates:
            try:
                q = await client.get(f"{url}/webapi/query.cgi", params={
                    "api": "SYNO.API.Info", "version": 1, "method": "query", "query": "SYNO.API.Auth",
                })
                if q.status_code == 200 and q.json().get("success"):
                    return url
            except Exception:  # noqa: BLE001
                continue
    raise SynologyError(f"QuickConnect '{qc}' : aucun candidat joignable")


async def _login(base_url: str, user: str, password: str, timeout: float = 30.0) -> str:
    async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
        r = await client.get(f"{base_url}/webapi/auth.cgi", params={
            "api": "SYNO.API.Auth", "version": 6, "method": "login",
            "account": user, "passwd": password, "session": "FileStation", "format": "sid",
        })
        r.raise_for_status()
        data = r.json()
    if not data.get("success"):
        code = (data.get("error") or {}).get("code", "?")
        raise SynologyError(f"Login DSM échoué (code {code})")
    return data["data"]["sid"]


async def _logout(base_url: str, sid: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            await client.get(f"{base_url}/webapi/auth.cgi", params={
                "api": "SYNO.API.Auth", "version": 6, "method": "logout", "session": "FileStation", "_sid": sid,
            })
    except Exception:  # noqa: BLE001
        pass


async def _list(base_url: str, sid: str, path: str, timeout: float = 30.0) -> list[dict]:
    """Liste un dossier (ou les partages à la racine) → [{nom, dossier, taille, chemin}]."""
    is_root = path in ("", "/")
    params: dict = {"_sid": sid, "api": "SYNO.FileStation.List", "version": 2}
    if is_root:
        params["method"] = "list_share"
    else:
        params |= {"method": "list", "folder_path": path, "additional": json.dumps(["size", "type"])}
    async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
        r = await client.get(f"{base_url}/webapi/entry.cgi", params=params)
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise SynologyError(f"List code={(data.get('error') or {}).get('code')}")
    raw = data.get("data", {}).get("shares" if is_root else "files", [])
    out = []
    for it in raw:
        isdir = bool(it.get("isdir", is_root))
        size = None if isdir else (it.get("additional", {}) or {}).get("size")
        out.append({"nom": it.get("name", ""), "dossier": isdir,
                    "taille": size, "chemin": it.get("path", "")})
    out.sort(key=lambda e: (not e["dossier"], e["nom"].lower()))
    return out


class SynologyConnector:
    """Connecteur DSM FileStation (lecture)."""

    type = "synology"

    async def _base_and_sid(self, src: Source) -> tuple[str, str]:
        base = await _resolve_base(src.hote or "")
        mdp = crypto.decrypt(src.secret_chiffre) if src.secret_chiffre else ""
        sid = await _login(base, src.identifiant or "", mdp)
        return base, sid

    async def test(self, src: Source) -> bool:
        base, sid = await self._base_and_sid(src)
        await _logout(base, sid)
        return True

    async def browse(self, src: Source, chemin: str = "/") -> list[dict]:
        base, sid = await self._base_and_sid(src)
        try:
            return await _list(base, sid, chemin or "/")
        finally:
            await _logout(base, sid)

    async def walk_files(self, src: Source, chemin: str, extensions: set[str] | None = None) -> list[dict]:
        base, sid = await self._base_and_sid(src)
        fichiers: list[dict] = []
        try:
            async def _rec(path: str, depth: int) -> None:
                if depth > 25:
                    return
                for e in await _list(base, sid, path):
                    if e["dossier"]:
                        await _rec(e["chemin"], depth + 1)
                    else:
                        ext = e["nom"].rsplit(".", 1)[-1].lower() if "." in e["nom"] else ""
                        if extensions is None or ext in extensions:
                            fichiers.append({"rel": e["chemin"], "taille": e["taille"]})
            await _rec(chemin or "/", 0)
        finally:
            await _logout(base, sid)
        return fichiers

    async def stream_file(self, src: Source, rel: str) -> AsyncIterator[bytes]:
        base, sid = await self._base_and_sid(src)
        params = {"api": "SYNO.FileStation.Download", "version": 2, "method": "download",
                  "path": rel, "mode": "download", "_sid": sid}
        try:
            async with (
                httpx.AsyncClient(timeout=600.0, verify=False) as client,
                client.stream("GET", f"{base}/webapi/entry.cgi", params=params) as r,
            ):
                r.raise_for_status()
                if "json" in r.headers.get("content-type", "").lower():
                    raise SynologyError("Download refusé (fichier absent/droits ?)")
                async for chunk in r.aiter_bytes(65536):
                    yield chunk
        finally:
            await _logout(base, sid)

    async def fetch_to_temp(self, src: Source, rel: str) -> str:
        suffix = ("." + rel.rsplit(".", 1)[-1]) if "." in rel.rsplit("/", 1)[-1] else ""
        fd = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            async for chunk in self.stream_file(src, rel):
                fd.write(chunk)
        finally:
            fd.close()
        return fd.name


register(SynologyConnector())
