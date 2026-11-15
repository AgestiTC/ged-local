"""
Copies sur disque par SMB — `LecteurSmb` (étape 5 du plan « Rangement sur Sources SMB »)
=======================================================================================
Les empreintes d'un emplacement `smb` se calculent comme celles du disque (`copies.py`), mais en
lisant par le réseau, avec le compte de la Source « Rangement » et UNE session SMB par emplacement
pour toute la passe (`smb_session.SessionSmb`).

- **Mêmes empreintes, au bit près** : même formule (`copies.hacher_partielle`), mêmes blocs de
  64 Kio en tête et en queue. Un fichier du NAS et sa copie sur un disque ou sur un poste se
  retrouvent donc dans le même groupe.
- **Modifié depuis le scan, ou pendant la lecture** : la taille et la date sont relues AVANT et
  APRÈS la lecture ; au moindre écart, l'empreinte est jetée (`_Change`), comme sur disque.
- **Fichier refusé ou disparu** (droit DSM manquant…) : illisible, compté, la passe continue.
- **Coupure** (NAS éteint, réseau perdu ; la session a déjà retenté une fois) : l'emplacement est
  tenu pour injoignable jusqu'à la fin de la passe — ses fichiers sont sautés sans rien enregistrer,
  la nuit suivante reprendra. On ne martèle pas un NAS absent fichier après fichier.
- Les octets lus par SMB comptent dans la limite de lecture de la nuit, comme ceux du disque.

Mesuré le 14/11/2026 (docs/mesures/rangement-smb-2026-11-14.md) : empreintes partielles 2 à 8 fois
plus rapides que par le montage, lecture continue ~42 Mo/s (200 Go ≈ 1 h 20).
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from typing import Any

from smb.smb_structs import OperationFailure

from logger import get_logger
from services import smb_chemins
from services.rangement.depot import Emplacement, Fichier
from services.rangement.exclusions import Exclusions
from services.rangement.scan import TOLERANCE_MTIME_S

log = get_logger(__name__)

#: Taille d'une lecture de l'empreinte complète par SMB : moins d'allers-retours avec le fil de la
#: session qu'avec 1 Mio, sans peser sur la mémoire.
TAILLE_LECTURE_SMB = 4 * 1024 * 1024

OuvrirSession = Callable[[Emplacement], Awaitable[Any]]


class FichierIllisible(OSError):
    """Refusé ou disparu sur le NAS : compté comme illisible, la passe continue."""


class Injoignable(Exception):
    """Le partage de l'emplacement ne répond plus pendant cette passe."""


class LecteurSmb:
    """Lit les fichiers d'UN emplacement `smb` le temps d'une passe des copies. La session s'ouvre au
    premier fichier à lire (une passe peut n'en lire aucun) et se ferme à `fermer`."""

    def __init__(self, emplacement: Emplacement, exclusions: Exclusions,
                 ouvrir: OuvrirSession | None = None) -> None:
        from services.rangement import copies  # import ici : copies importe ce module

        self._copies = copies
        self.emp = emplacement
        self.exclusions = exclusions.pour_smb(emplacement.sous_dossier)   # « @… » de tête : cf. pour_smb
        self._ouvrir = ouvrir
        self.base = smb_chemins.normaliser_rel(emplacement.sous_dossier or "/")
        decoupe = smb_chemins.decouper(emplacement.racine)
        self.hote = decoupe.hote if decoupe else ""
        self.partage = emplacement.partage or (decoupe.partage if decoupe else "")
        self._session: Any = None
        self.panne: str | None = None

    def chemin(self, relatif: str) -> str:
        """Chemin dans le partage d'un fichier relatif à l'emplacement."""
        return smb_chemins.normaliser_rel(f"{self.base}/{relatif}")

    def exclu(self, relatif: str) -> bool:
        """Mêmes exclusions qu'au scan SMB : le « chemin absolu » est l'URI `smb://hôte/partage/…`."""
        return self._copies.exclu(
            self.exclusions, self.emp.racine, relatif,
            absolu=lambda parties: smb_chemins.composer(self.hote, self.partage, self.chemin("/".join(parties))))

    async def _session_ouverte(self) -> Any:
        if self.panne is not None:
            raise Injoignable(self.panne)
        if self._session is None:
            try:
                if self._ouvrir is not None:
                    session = await self._ouvrir(self.emp)
                else:  # résolu à l'appel : un secret changé dans *Sources* sert dès la passe suivante
                    from services.rangement import emplacement_smb
                    session = await emplacement_smb.session_de(self.emp)
                await session.__aenter__()
            except Exception as exc:  # noqa: BLE001 — Source retirée, NAS éteint, compte refusé
                self._en_panne(exc)
                raise Injoignable(self.panne) from exc
            self._session = session
        return self._session

    def _en_panne(self, exc: BaseException) -> None:
        self.panne = type(exc).__name__
        log.warning("Copies sur disque : partage SMB injoignable, emplacement sauté pour cette passe",
                    emplacement_id=self.emp.id, partage=self.partage, erreur=self.panne)

    async def _verifier(self, session: Any, chemin: str, f: Fichier) -> None:
        """Le fichier est-il toujours celui de l'inventaire ? Sinon, son empreinte ne vaudrait rien."""
        e = await session.stat(chemin)
        if e is None:
            raise FichierIllisible("absent ou refusé")
        if e.est_dossier or e.taille != f.taille or f.mtime is None \
                or abs((e.mtime or 0.0) - f.mtime) > TOLERANCE_MTIME_S:
            raise self._copies._Change()

    async def _partielle(self, session: Any, chemin: str, taille: int) -> tuple[bytes, bytes | None, int]:
        bloc = self._copies.TAILLE_BLOC
        tete = await session.lire(chemin, 0, bloc)
        if taille > 2 * bloc:
            queue = await session.lire(chemin, taille - bloc, bloc)
            complete = None
        else:  # petit fichier : lu en entier, l'empreinte complète est offerte (comme sur disque)
            queue = await session.lire(chemin, len(tete), taille) if len(tete) < taille else b""
            complete = hashlib.sha256(tete + queue).digest()
        return self._copies.hacher_partielle(taille, tete, queue), complete, len(tete) + len(queue)

    async def _complete(self, session: Any, chemin: str, taille: int) -> tuple[bytes, int]:
        h = hashlib.sha256()
        boucle = asyncio.get_running_loop()
        lus = 0
        while lus < taille:
            bloc = await session.lire(chemin, lus, TAILLE_LECTURE_SMB)
            if not bloc:
                break
            # Le calcul part dans le fil des copies (priorité basse) : la boucle du worker reste libre.
            await boucle.run_in_executor(self._copies._LECTEUR, h.update, bloc)
            lus += len(bloc)
        return h.digest(), lus

    async def lire(self, f: Fichier, complete: bool) -> tuple[bytes | None, bytes | None, int]:
        """(partielle, complète, octets lus). Lève `_Change`, `FichierIllisible` ou `Injoignable`."""
        session = await self._session_ouverte()
        chemin = self.chemin(f.chemin)
        try:
            await self._verifier(session, chemin, f)
            if complete:
                totale, lus = await self._complete(session, chemin, f.taille)
                partielle = f.partielle
            else:
                partielle, totale, lus = await self._partielle(session, chemin, f.taille)
            await self._verifier(session, chemin, f)  # modifié PENDANT la lecture
        except (self._copies._Change, FichierIllisible):
            raise
        except OperationFailure as exc:  # refus du NAS sur CE fichier
            raise FichierIllisible("refusé") from exc
        except Exception as exc:  # noqa: BLE001 — coupure : la session a déjà retenté une fois
            self._en_panne(exc)
            await self.fermer()
            raise Injoignable(self.panne) from exc
        return partielle, totale, lus

    async def fermer(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            try:
                await session.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001 — fermer une connexion morte ne doit rien casser
                pass
