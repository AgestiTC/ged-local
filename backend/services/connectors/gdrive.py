"""
Connecteur Google Drive (LECTURE) — OAuth2 `drive.readonly`.
============================================================
Un **compte Google = une `Source`** (`type='gdrive'`) :
- `identifiant`      = e-mail du compte,
- `secret_chiffre`   = **refresh_token** OAuth (chiffré Fernet),
- `chemin_base`      = ID du dossier de départ (défaut `root` = « Mon Drive »).

Les identifiants de l'**app OAuth** (partagés par tous les comptes) sont en config :
`gdrive_client_id` / `gdrive_client_secret` (Paramètres). Un `access_token` court est obtenu à la
demande à partir du `refresh_token`.

Modèle de chemin : Drive adresse par **ID de fichier**, pas par chemin. On encode donc
`rel = "/{fileId}/{nom}"` → `fetch_to_temp` retrouve l'ID, `Path(rel).name` donne le nom (et donc
l'extension). Les documents **Google natifs** (Docs/Sheets/Slides) sont **exportés** (PDF/xlsx/pptx).

⚠️ Connecteur CLOUD : accès réseau sortant vers Google (oauth2.googleapis.com, googleapis.com).
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import httpx

from logger import get_logger
from models.source import Source
from services import runtime_config
from services.connectors.base import register
from services.crypto import decrypt

log = get_logger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/drive/v3"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
FOLDER_MIME = "application/vnd.google-apps.folder"

# Documents Google natifs → format d'export (mimeType export, extension virtuelle).
EXPORTS = {
    "application/vnd.google-apps.document": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.spreadsheet": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}


def _mtime(iso: str | None) -> float | None:
    """`modifiedTime` (RFC 3339) → epoch, pour la synchro incrémentale."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


class GoogleDriveConnector:
    type = "gdrive"

    async def _access_token(self, src: Source) -> str:
        """Échange le refresh_token du compte contre un access_token court."""
        refresh = (decrypt(src.secret_chiffre) if src.secret_chiffre else "").strip()
        # Le client_secret est stocké CHIFFRÉ (enc::…) → il faut le DÉCHIFFRER avant de l'envoyer à
        # Google (sinon on envoyait le token Fernet → `invalid_client`). Le client_id n'est pas un
        # secret (stocké en clair). `.strip()` = garde-fou copier-coller.
        cid = (runtime_config.effective("gdrive_client_id") or "").strip()
        csec = decrypt(runtime_config.effective("gdrive_client_secret") or "").strip()
        if not (cid and csec):
            raise RuntimeError("App OAuth Google non configurée (Paramètres → Client ID/Secret).")
        if not refresh:
            raise RuntimeError("Compte Google non autorisé (reconnecte le compte).")
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(TOKEN_URL, data={
                "grant_type": "refresh_token", "refresh_token": refresh,
                "client_id": cid, "client_secret": csec,
            })
            if r.status_code != 200:
                raise RuntimeError(f"Rafraîchissement du jeton refusé ({r.status_code}) — reconnecte le compte.")
            return r.json()["access_token"]

    async def _list(self, token: str, folder_id: str) -> list[dict]:
        """Contenu direct d'un dossier Drive (pagination complète)."""
        items: list[dict] = []
        page = None
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=60) as c:
            while True:
                params = {
                    "q": f"'{folder_id}' in parents and trashed=false",
                    "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime)",
                    "pageSize": 1000, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
                }
                if page:
                    params["pageToken"] = page
                r = await c.get(f"{API}/files", params=params, headers=headers)
                r.raise_for_status()
                d = r.json()
                items += d.get("files", [])
                page = d.get("nextPageToken")
                if not page:
                    break
        return items

    # ─── Interface SourceConnector ────────────────────────────────────────────
    async def test(self, src: Source) -> bool:
        token = await self._access_token(src)
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{API}/about", params={"fields": "user"}, headers={"Authorization": f"Bearer {token}"})
            return r.status_code == 200

    async def browse(self, src: Source, chemin: str = "/") -> list[dict]:
        token = await self._access_token(src)
        folder = chemin.strip("/") or (src.chemin_base or "root")
        out = []
        for f in await self._list(token, folder):
            est_dossier = f["mimeType"] == FOLDER_MIME
            out.append({"nom": f["name"], "dossier": est_dossier,
                        "taille": int(f.get("size", 0) or 0), "chemin": f["id"]})
        out.sort(key=lambda e: (not e["dossier"], e["nom"].lower()))
        return out

    async def walk_files(self, src: Source, chemin: str, extensions: set[str] | None) -> list[dict]:
        token = await self._access_token(src)
        racine = chemin.strip("/") or (src.chemin_base or "root")
        fichiers: list[dict] = []

        async def _rec(folder_id: str):
            for f in await self._list(token, folder_id):
                mime = f["mimeType"]
                if mime == FOLDER_MIME:
                    await _rec(f["id"])
                    continue
                nom = f["name"]
                # Document Google natif → extension virtuelle du format d'export.
                if mime in EXPORTS and not nom.lower().endswith(EXPORTS[mime][1]):
                    nom = nom + EXPORTS[mime][1]
                ext = nom.rsplit(".", 1)[-1].lower() if "." in nom else ""
                if extensions and ext not in extensions:
                    continue
                fichiers.append({
                    "rel": f"/{f['id']}/{nom}",
                    "taille": int(f.get("size", 0) or 0),
                    "mtime": _mtime(f.get("modifiedTime")),
                })

        await _rec(racine)
        return fichiers

    def _id_nom(self, rel: str) -> tuple[str, str]:
        parts = rel.strip("/").split("/", 1)
        return parts[0], (parts[1] if len(parts) > 1 else parts[0])

    async def fetch_to_temp(self, src: Source, rel: str) -> str:
        token = await self._access_token(src)
        fid, nom = self._id_nom(rel)
        headers = {"Authorization": f"Bearer {token}"}
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(nom)[1])
        try:
            async with httpx.AsyncClient(timeout=None) as c:
                meta = await c.get(f"{API}/files/{fid}", params={"fields": "mimeType", "supportsAllDrives": "true"}, headers=headers)
                meta.raise_for_status()
                mime = meta.json()["mimeType"]
                if mime in EXPORTS:  # document Google natif → export
                    url, params = f"{API}/files/{fid}/export", {"mimeType": EXPORTS[mime][0]}
                else:                # fichier binaire → téléchargement direct
                    url, params = f"{API}/files/{fid}", {"alt": "media", "supportsAllDrives": "true"}
                async with c.stream("GET", url, params=params, headers=headers) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes():
                        tmp.write(chunk)
        finally:
            tmp.close()
        return tmp.name

    async def stream_file(self, src: Source, rel: str) -> AsyncIterator[bytes]:
        token = await self._access_token(src)
        fid, _ = self._id_nom(rel)
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=None) as c:
            meta = await c.get(f"{API}/files/{fid}", params={"fields": "mimeType", "supportsAllDrives": "true"}, headers=headers)
            meta.raise_for_status()
            mime = meta.json()["mimeType"]
            if mime in EXPORTS:
                url, params = f"{API}/files/{fid}/export", {"mimeType": EXPORTS[mime][0]}
            else:
                url, params = f"{API}/files/{fid}", {"alt": "media", "supportsAllDrives": "true"}
            async with c.stream("GET", url, params=params, headers=headers) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes():
                    yield chunk


# ─── Fonctions OAuth (utilisées par le routeur connectors) ─────────────────────
SCOPES = ["https://www.googleapis.com/auth/drive.readonly",
          "https://www.googleapis.com/auth/userinfo.email", "openid"]


def auth_url(redirect_uri: str, state: str) -> str:
    """URL de consentement Google (à ouvrir dans le navigateur)."""
    from urllib.parse import urlencode
    cid = runtime_config.effective("gdrive_client_id")
    if not cid:
        raise RuntimeError("Client ID Google absent (Paramètres).")
    params = {
        "client_id": cid, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent",
        "include_granted_scopes": "true", "state": state,
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


async def exchange_code(code: str, redirect_uri: str) -> dict:
    """Échange le `code` de consentement contre {refresh_token, access_token, email}."""
    cid = (runtime_config.effective("gdrive_client_id") or "").strip()
    csec = decrypt(runtime_config.effective("gdrive_client_secret") or "").strip()  # DÉCHIFFRER (enc::…)
    # Diagnostic SANS révéler le secret : forme + longueur permettent de repérer une valeur
    # tronquée / mal copiée (un vrai secret Google commence par « GOCSPX- » et fait ~35 car.).
    log.info("OAuth échange — diagnostic identifiants",
             client_id_ok=cid.endswith(".apps.googleusercontent.com"),
             secret_prefixe=csec[:8], secret_len=len(csec), redirect_uri=redirect_uri)
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(TOKEN_URL, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": cid, "client_secret": csec,
        })
        if r.status_code != 200:
            raise RuntimeError(f"Échange du code refusé ({r.status_code}) : {r.text[:200]}")
        tok = r.json()
        access = tok.get("access_token")
        refresh = tok.get("refresh_token")
        # E-mail du compte (identifie la Source).
        email = ""
        try:
            ui = await c.get(USERINFO_URL, headers={"Authorization": f"Bearer {access}"})
            if ui.status_code == 200:
                email = ui.json().get("email", "")
        except Exception:  # noqa: BLE001
            pass
    return {"refresh_token": refresh, "access_token": access, "email": email}


register(GoogleDriveConnector())
