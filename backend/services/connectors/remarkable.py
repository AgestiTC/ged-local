"""
Connecteur reMarkable Cloud — LECTURE.
======================================
Indexe les documents (PDF/EPUB uploadés, notes) d'un compte **reMarkable Cloud**. L'API cloud
est **non officielle** (reverse-engineerée par la communauté, cf. `rmapi`) et peut évoluer — ce
connecteur suit les endpoints historiques ; à **valider en direct** sur un compte réel.

Appairage (une fois) : l'utilisateur récupère un **code à usage unique** sur
`https://my.remarkable.com/device/desktop`, échangé contre un **device token** durable
(chiffré en base). À chaque accès, un **user token** court est dérivé du device token.

Champs `Source` réutilisés : `identifiant` = deviceID (UUID généré) ; `secret_chiffre` = device
token (JWT, chiffré Fernet) ; `chemin_base` = dossier de départ (ID reMarkable, vide = racine).

Convention : `rel = "/{docId}/{nom}.zip"` — le téléchargement reMarkable renvoie un **zip** (contenu
du document) ; le pipeline (Tika `/rmeta`) en extrait le PDF/EPUB. `Path(rel).name` fournit le nom.
"""
from __future__ import annotations

import tempfile
import uuid as _uuid
from collections.abc import AsyncIterator

import httpx

from logger import get_logger
from models.source import Source
from services import crypto
from services.connectors.base import register

log = get_logger(__name__)

_AUTH_BASE = "https://webapp-prod.cloud.remarkable.engineering"
_DOCS_BASE = "https://document-storage-production-dot-remarkable-production.appspot.com"
_DEVICE_DESC = "desktop-windows"
_FOLDER_TYPE = "CollectionType"
_DOC_TYPE = "DocumentType"
_TIMEOUT = 30.0


class RemarkableError(RuntimeError):
    pass


async def register_device(code: str, device_id: str | None = None) -> tuple[str, str]:
    """
    Appaire un appareil via le **code à usage unique** (my.remarkable.com/device/desktop).
    Retourne `(device_id, device_token)` — le device token est **durable** (à chiffrer/stocker).
    """
    device_id = device_id or str(_uuid.uuid4())
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            f"{_AUTH_BASE}/token/json/2/device/new",
            json={"code": (code or "").strip(), "deviceDesc": _DEVICE_DESC, "deviceID": device_id},
        )
    if r.status_code != 200 or not r.text.strip():
        raise RemarkableError(f"Appairage refusé (HTTP {r.status_code}) — code périmé ou incorrect ?")
    return device_id, r.text.strip()


async def _user_token(device_token: str) -> str:
    """Dérive un user token (court) depuis le device token durable."""
    if not device_token:
        raise RemarkableError("Appareil non appairé (device token manquant)")
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            f"{_AUTH_BASE}/token/json/2/user/new",
            headers={"Authorization": f"Bearer {device_token}"}, content=b"",
        )
    if r.status_code != 200 or not r.text.strip():
        raise RemarkableError(f"Jeton utilisateur refusé (HTTP {r.status_code}) — ré-appaire l'appareil")
    return r.text.strip()


def _norm_parent(chemin: str | None) -> str:
    """Normalise un identifiant de dossier parent ('/', '', 'root' → racine = '')."""
    c = (chemin or "").strip().strip("/")
    return "" if c in ("", "root") else c


def parse_docs(items: list[dict], parent: str) -> list[dict]:
    """
    Entrées directes d'un dossier `parent` à partir de la liste **plate** reMarkable
    (chaque item porte son `Parent`). → [{nom, dossier, taille, chemin(id)}], dossiers d'abord.
    Fonction PURE (aucun I/O) → testable unitairement.
    """
    par = _norm_parent(parent)
    out: list[dict] = []
    for it in items:
        if _norm_parent(it.get("Parent", "")) != par:
            continue
        if (it.get("Type") == "TrashCan") or it.get("Parent") == "trash":
            continue
        est_dossier = it.get("Type") == _FOLDER_TYPE
        out.append({
            "nom": it.get("VissibleName") or it.get("ID", "?"),
            "dossier": est_dossier,
            "taille": None,
            "chemin": it.get("ID", ""),
        })
    out.sort(key=lambda e: (not e["dossier"], (e["nom"] or "").lower()))
    return out


def collect_documents(items: list[dict], racine: str) -> list[dict]:
    """
    Parcourt (en profondeur) l'arbre des dossiers depuis `racine` et renvoie les **documents**
    → [{rel: "/{id}/{nom}.zip", taille}]. PURE : opère sur la liste plate déjà récupérée.
    """
    par_parent: dict[str, list[dict]] = {}
    for it in items:
        par_parent.setdefault(_norm_parent(it.get("Parent", "")), []).append(it)

    fichiers: list[dict] = []
    vus: set[str] = set()

    def _rec(parent: str, depth: int) -> None:
        if depth > 30:
            return
        for it in par_parent.get(_norm_parent(parent), []):
            iid = it.get("ID", "")
            if not iid or iid in vus:
                continue
            vus.add(iid)
            if it.get("Type") == _FOLDER_TYPE:
                _rec(iid, depth + 1)
            elif it.get("Type") == _DOC_TYPE:
                nom = (it.get("VissibleName") or iid).replace("/", "_")
                fichiers.append({"rel": f"/{iid}/{nom}.zip", "taille": None})

    _rec(racine, 0)
    return fichiers


class RemarkableConnector:
    """Connecteur reMarkable Cloud (lecture seule)."""

    type = "remarkable"

    async def _token(self, src: Source) -> str:
        device_token = crypto.decrypt(src.secret_chiffre) if src.secret_chiffre else ""
        return await _user_token(device_token)

    async def _list(self, token: str, doc_id: str | None = None, with_blob: bool = False) -> list[dict]:
        params = {}
        if doc_id:
            params["doc"] = doc_id
        if with_blob:
            params["withBlob"] = "true"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(
                f"{_DOCS_BASE}/document-storage/json/2/docs",
                headers={"Authorization": f"Bearer {token}"}, params=params,
            )
        if r.status_code != 200:
            raise RemarkableError(f"Liste documents refusée (HTTP {r.status_code})")
        data = r.json()
        return data if isinstance(data, list) else []

    async def test(self, src: Source) -> bool:
        token = await self._token(src)
        await self._list(token)  # une requête suffit à valider auth + joignabilité
        return True

    async def browse(self, src: Source, chemin: str = "/") -> list[dict]:
        token = await self._token(src)
        items = await self._list(token)
        return parse_docs(items, chemin or src.chemin_base or "")

    async def walk_files(self, src: Source, chemin: str, extensions: set[str] | None = None) -> list[dict]:
        token = await self._token(src)
        items = await self._list(token)
        return collect_documents(items, _norm_parent(chemin or src.chemin_base or ""))

    def _id_nom(self, rel: str) -> tuple[str, str]:
        parts = rel.strip("/").split("/", 1)
        return parts[0], (parts[1] if len(parts) > 1 else parts[0])

    async def _blob_url(self, token: str, doc_id: str) -> str:
        items = await self._list(token, doc_id=doc_id, with_blob=True)
        for it in items:
            if it.get("ID") == doc_id and it.get("BlobURLGet"):
                return it["BlobURLGet"]
        raise RemarkableError("Lien de téléchargement introuvable (document absent ?)")

    async def stream_file(self, src: Source, rel: str) -> AsyncIterator[bytes]:
        token = await self._token(src)
        doc_id, _ = self._id_nom(rel)
        url = await self._blob_url(token, doc_id)
        async with (
            httpx.AsyncClient(timeout=600.0) as client,
            client.stream("GET", url) as r,
        ):
            if r.status_code >= 400:
                raise RemarkableError(f"Téléchargement HTTP {r.status_code}")
            async for chunk in r.aiter_bytes(65536):
                yield chunk

    async def fetch_to_temp(self, src: Source, rel: str) -> str:
        fd = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        try:
            async for chunk in self.stream_file(src, rel):
                fd.write(chunk)
        finally:
            fd.close()
        return fd.name


register(RemarkableConnector())
