"""
Connecteur WebDAV générique — LECTURE.
======================================
Couvre un large éventail de serveurs exposant WebDAV : **Nextcloud / ownCloud**,
**Infomaniak kDrive**, **Synology WebDAV Server**, serveurs Apache/nginx `mod_dav`,
box génériques… Auth **HTTP Basic** (pas d'OAuth) → configuration simple :

Champs `Source` réutilisés :
  - `hote`          = **URL de base WebDAV** (ex. `https://cloud.example.com/remote.php/dav/files/jean/`
                      pour Nextcloud, ou `https://nas.local:5006/` pour Synology WebDAV) ;
  - `identifiant`   = utilisateur ;
  - `secret_chiffre`= mot de passe (ou **mot de passe d'application**), chiffré Fernet ;
  - `chemin_base`   = dossier de départ relatif à l'URL de base (ex. `/Documents`).

Les chemins internes (`chemin` / `rel`) sont **relatifs à l'URL de base**, commençant
par `/`. Protocole : `PROPFIND` (listing) + `GET` (téléchargement).
"""
from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree as ET

import httpx

from logger import get_logger
from models.source import Source
from services import crypto
from services.connectors.base import register

log = get_logger(__name__)

_DAV_NS = "{DAV:}"
_TIMEOUT = 30.0


class WebDAVError(RuntimeError):
    pass


def _base_url(src: Source) -> str:
    """URL de base normalisée (avec schéma, sans slash final)."""
    h = (src.hote or "").strip()
    if not h:
        raise WebDAVError("URL de base WebDAV manquante")
    if not h.startswith(("http://", "https://")):
        h = "https://" + h
    return h.rstrip("/")


def _base_path(base: str) -> str:
    """Chemin de l'URL de base (préfixe à retirer des href renvoyés par le serveur)."""
    return urlparse(base).path.rstrip("/")


def _encode_path(rel: str) -> str:
    """Encode chaque segment d'un chemin relatif (garde les `/`)."""
    rel = "/" + (rel or "").strip("/")
    return "/".join(quote(seg) for seg in rel.split("/"))


def _url(base: str, rel: str) -> str:
    return base + _encode_path(rel)


def parse_propfind(xml_bytes: bytes, base_path: str, demande: str) -> list[dict]:
    """
    Analyse une réponse `multistatus` PROPFIND → [{nom, dossier, taille, chemin}].
    `chemin` est relatif à l'URL de base (commence par `/`). L'entrée correspondant
    au dossier **demandé** lui-même est exclue (PROPFIND Depth:1 le renvoie en tête).

    Fonction PURE (aucune I/O) → testable unitairement.
    """
    root = ET.fromstring(xml_bytes)
    demande_norm = "/" + (demande or "").strip("/")
    entrees: list[dict] = []
    for resp in root.iter(f"{_DAV_NS}response"):
        href_el = resp.find(f"{_DAV_NS}href")
        if href_el is None or not href_el.text:
            continue
        href_path = urlparse(href_el.text).path  # portion chemin, %XX encodée
        # Retire le préfixe de base → chemin relatif décodé.
        rel_enc = href_path[len(base_path):] if href_path.startswith(base_path) else href_path
        rel = "/" + unquote(rel_enc).strip("/")

        # Type + taille depuis le premier propstat "200 OK".
        dossier = False
        taille: int | None = None
        for propstat in resp.iter(f"{_DAV_NS}propstat"):
            status = propstat.find(f"{_DAV_NS}status")
            if status is not None and status.text and "200" not in status.text:
                continue
            prop = propstat.find(f"{_DAV_NS}prop")
            if prop is None:
                continue
            rtype = prop.find(f"{_DAV_NS}resourcetype")
            if rtype is not None and rtype.find(f"{_DAV_NS}collection") is not None:
                dossier = True
            length = prop.find(f"{_DAV_NS}getcontentlength")
            if length is not None and length.text and length.text.isdigit():
                taille = int(length.text)

        if rel == demande_norm:
            continue  # le dossier lui-même
        nom = unquote(rel_enc).strip("/").rsplit("/", 1)[-1]
        if not nom:
            continue
        entrees.append({"nom": nom, "dossier": dossier,
                        "taille": None if dossier else taille, "chemin": rel})
    entrees.sort(key=lambda e: (not e["dossier"], e["nom"].lower()))
    return entrees


class WebDAVConnector:
    """Connecteur WebDAV générique (lecture seule, HTTP Basic)."""

    type = "webdav"

    def _auth(self, src: Source) -> tuple[str, str]:
        mdp = crypto.decrypt(src.secret_chiffre) if src.secret_chiffre else ""
        return (src.identifiant or "", mdp)

    async def _propfind(self, src: Source, chemin: str, depth: int) -> list[dict]:
        base = _base_url(src)
        url = _url(base, chemin or "/")
        headers = {"Depth": str(depth), "Content-Type": "application/xml"}
        # Corps minimal : on ne demande que type + taille (allège la réponse).
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<d:propfind xmlns:d="DAV:"><d:prop>'
            '<d:resourcetype/><d:getcontentlength/>'
            '</d:prop></d:propfind>'
        )
        async with httpx.AsyncClient(timeout=_TIMEOUT, auth=self._auth(src), follow_redirects=True) as client:
            r = await client.request("PROPFIND", url, headers=headers, content=body)
        if r.status_code in (401, 403):
            raise WebDAVError(f"Authentification refusée (HTTP {r.status_code})")
        if r.status_code == 404:
            raise WebDAVError("Dossier introuvable (404)")
        if r.status_code not in (207, 200):
            raise WebDAVError(f"PROPFIND HTTP {r.status_code}")
        return parse_propfind(r.content, _base_path(base), chemin or "/")

    async def test(self, src: Source) -> bool:
        # Depth 0 sur le dossier de base → valide auth + joignabilité.
        await self._propfind(src, src.chemin_base or "/", depth=0)
        return True

    async def browse(self, src: Source, chemin: str = "/") -> list[dict]:
        return await self._propfind(src, chemin or "/", depth=1)

    async def walk_files(self, src: Source, chemin: str, extensions: set[str] | None = None) -> list[dict]:
        fichiers: list[dict] = []

        async def _rec(path: str, depth: int) -> None:
            if depth > 25:
                return
            for e in await self._propfind(src, path, depth=1):
                if e["dossier"]:
                    await _rec(e["chemin"], depth + 1)
                else:
                    ext = e["nom"].rsplit(".", 1)[-1].lower() if "." in e["nom"] else ""
                    if extensions is None or ext in extensions:
                        fichiers.append({"rel": e["chemin"], "taille": e["taille"]})

        await _rec(chemin or (src.chemin_base or "/"), 0)
        return fichiers

    async def stream_file(self, src: Source, rel: str) -> AsyncIterator[bytes]:
        base = _base_url(src)
        url = _url(base, rel)
        async with (
            httpx.AsyncClient(timeout=600.0, auth=self._auth(src), follow_redirects=True) as client,
            client.stream("GET", url) as r,
        ):
            if r.status_code >= 400:
                raise WebDAVError(f"Téléchargement HTTP {r.status_code}")
            async for chunk in r.aiter_bytes(65536):
                yield chunk

    async def fetch_to_temp(self, src: Source, rel: str) -> str:
        dernier = rel.rsplit("/", 1)[-1]
        suffix = ("." + dernier.rsplit(".", 1)[-1]) if "." in dernier else ""
        fd = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            async for chunk in self.stream_file(src, rel):
                fd.write(chunk)
        finally:
            fd.close()
        return fd.name


register(WebDAVConnector())
