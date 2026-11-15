"""
Session SMB — UNE connexion qui dure toute une tâche
====================================================
Étape 2 du plan « Rangement sur Sources SMB » (docs/plan-rangement-sources-smb.md).

`smb_service` ouvre une connexion par appel : très bien pour parcourir un dossier depuis l'écran,
ruineux pour inventorier 270 000 fichiers ou calculer des empreintes. Une `SessionSmb` garde une
connexion ouverte sur UN partage le temps d'une tâche (scan, copies, rangement).

- pysmb est synchrone et une connexion n'est pas faite pour plusieurs threads : tous les appels
  passent par UN thread dédié à la session, et l'event loop n'est jamais bloquée.
- Coupure (NAS redémarré, délai dépassé) : une LECTURE est rejouée une fois sur une connexion
  neuve ; une ÉCRITURE (renommer) ne l'est jamais — elle a pu aboutir avant la coupure. La session
  se reconnecte alors au prochain appel.
- Chemins relatifs au partage, normalisés par `smb_chemins.normaliser_rel` (« .. » refusé).
- Le secret n'est gardé que dans la fabrique de connexion : ni `repr`, ni journal.

Mesures du 14/11/2026 (docs/mesures/rangement-smb-2026-11-14.md) : parcours ≈ montage CIFS,
empreintes partielles plus rapides, lecture continue ~42 Mo/s.
"""

from __future__ import annotations

import asyncio
import io
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, NamedTuple

from smb.base import NotConnectedError, SMBTimeout
from smb.smb_structs import OperationFailure

from logger import get_logger
from services import smb_service
from services.smb_chemins import normaliser_rel

log = get_logger(__name__)

# Erreurs de TRANSPORT (connexion perdue) — à distinguer d'OperationFailure (refus, absent…).
_COUPURES: tuple[type[BaseException], ...] = (NotConnectedError, SMBTimeout, ConnectionError, OSError)


class EntreeSmb(NamedTuple):
    nom: str
    est_dossier: bool
    taille: int
    mtime: float | None  # epoch ; None si le serveur ne la donne pas


def _entree(f: Any, nom: str | None = None) -> EntreeSmb:
    return EntreeSmb(nom or f.filename, bool(f.isDirectory), int(f.file_size),
                     float(getattr(f, "last_write_time", 0) or 0) or None)


class _Puits(io.RawIOBase):
    """Reçoit les octets lus (retrieveFileFromOffset écrit dans un fichier)."""

    def __init__(self) -> None:
        self.morceaux: list[bytes] = []

    def writable(self) -> bool:
        return True

    def write(self, b: Any) -> int:
        self.morceaux.append(bytes(b))
        return len(b)


class SessionSmb:
    """`async with SessionSmb(hote, partage, identifiant, secret) as s: await s.lister("/")`."""

    def __init__(self, hote: str, partage: str, identifiant: str | None = None, secret: str | None = None,
                 domaine: str | None = None, *, connecter: Callable[[], Any] | None = None) -> None:
        self.hote, self.partage, self.identifiant = hote, partage, identifiant
        # Le secret ne vit que dans cette fermeture.
        self._connecter = connecter or (lambda: smb_service._connect(hote, identifiant, secret, domaine))
        self._conn: Any = None
        self._ex: ThreadPoolExecutor | None = None
        self.connexions = 0

    def __repr__(self) -> str:
        return f"SessionSmb(hote={self.hote!r}, partage={self.partage!r}, identifiant={self.identifiant!r})"

    __str__ = __repr__

    # --- cycle de vie ---------------------------------------------------------------------------
    async def __aenter__(self) -> "SessionSmb":
        self._ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="smb-session")
        await self._dans_le_thread(self._ouvrir)
        return self

    async def __aexit__(self, *_: Any) -> None:
        ex, self._ex = self._ex, None
        if ex is None:
            return
        try:
            await asyncio.get_running_loop().run_in_executor(ex, self._fermer)
        finally:
            ex.shutdown(wait=False)

    def _ouvrir(self) -> None:
        self._conn = self._connecter()
        self.connexions += 1

    def _fermer(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 — fermer une connexion déjà morte ne doit rien casser
                pass

    async def _dans_le_thread(self, fn: Callable[[], Any]) -> Any:
        if self._ex is None:
            raise RuntimeError("Session SMB non ouverte (utiliser « async with SessionSmb(...) »)")
        return await asyncio.get_running_loop().run_in_executor(self._ex, fn)

    async def _appel(self, op: Callable[[Any], Any], *, rejouable: bool) -> Any:
        def executer() -> Any:
            if self._conn is None:
                self._ouvrir()
            try:
                return op(self._conn)
            except OperationFailure:
                raise
            except _COUPURES as exc:
                self._fermer()
                if not rejouable:
                    raise
                log.warning("Session SMB coupée, reconnexion", hote=self.hote, partage=self.partage,
                            erreur=type(exc).__name__)
                self._ouvrir()
                return op(self._conn)
        return await self._dans_le_thread(executer)

    # --- lecture (rejouable) --------------------------------------------------------------------
    async def lister(self, dossier: str) -> list[EntreeSmb]:
        """Contenu d'un dossier (« . » et « .. » écartés) : nom, dossier ?, taille, date."""
        rel = normaliser_rel(dossier)
        return await self._appel(lambda c: [_entree(f) for f in c.listPath(self.partage, rel)
                                            if f.filename not in (".", "..")], rejouable=True)

    async def stat(self, chemin: str) -> EntreeSmb | None:
        """Attributs d'un fichier ou dossier ; None s'il n'existe pas (ou n'est pas accessible)."""
        rel = normaliser_rel(chemin)

        def op(c: Any) -> EntreeSmb | None:
            try:
                return _entree(c.getAttributes(self.partage, rel), rel.rsplit("/", 1)[-1] or "/")
            except OperationFailure:
                return None
        return await self._appel(op, rejouable=True)

    async def existe(self, chemin: str) -> bool:
        return await self.stat(chemin) is not None

    async def lire(self, chemin: str, depuis: int, longueur: int) -> bytes:
        """`longueur` octets à partir de `depuis` (moins en fin de fichier)."""
        rel = normaliser_rel(chemin)

        def op(c: Any) -> bytes:
            puits = _Puits()
            c.retrieveFileFromOffset(self.partage, rel, puits, depuis, longueur)
            return b"".join(puits.morceaux)
        return await self._appel(op, rejouable=True)

    # --- écriture -------------------------------------------------------------------------------
    async def creer_dossier(self, chemin: str) -> None:
        """Crée le dossier et ses parents manquants. Idempotent, donc rejouable."""
        rel = normaliser_rel(chemin)

        def op(c: Any) -> None:
            cur = ""
            for part in [p for p in rel.split("/") if p]:
                cur = f"{cur}/{part}"
                try:
                    c.getAttributes(self.partage, cur)
                    continue
                except OperationFailure:
                    pass
                c.createDirectory(self.partage, cur)
        await self._appel(op, rejouable=True)

    async def supprimer_dossier_vide(self, chemin: str) -> None:
        """Supprime un dossier VIDE (le NAS refuse un dossier qui contient quelque chose)."""
        rel = normaliser_rel(chemin)
        if rel == "/":
            raise ValueError("On ne supprime pas la racine d'un partage")
        await self._appel(lambda c: c.deleteDirectory(self.partage, rel), rejouable=False)

    async def supprimer_fichier(self, chemin: str) -> None:
        rel = normaliser_rel(chemin)
        await self._appel(lambda c: c.deleteFiles(self.partage, rel), rejouable=False)

    async def renommer(self, source: str, destination: str) -> None:
        """Déplace dans le MÊME partage. Jamais rejoué après une coupure (il a pu aboutir)."""
        src, dst = normaliser_rel(source), normaliser_rel(destination)
        if src == "/" or dst == "/":
            raise ValueError("On ne renomme pas la racine d'un partage")
        await self._appel(lambda c: c.rename(self.partage, src, dst), rejouable=False)
