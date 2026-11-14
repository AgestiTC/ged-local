"""
Ranger et annuler par SMB (étape 6 du plan « Rangement sur Sources SMB »)
=========================================================================
Les mêmes règles que `deplacements.py` (qui reste le SEUL point d'entrée des lots), appliquées à un
emplacement `smb` par UNE session SMB, avec le compte de sa Source « Rangement » :

- **Déplacer, jamais supprimer** : un renommage SMB dans le MÊME partage. Un chemin du lot est
  toujours relatif au dossier de l'emplacement et passe par `smb_chemins.normaliser_rel`, qui refuse
  « .. » : on ne sort ni du partage ni de l'emplacement. Aucune fonction ici n'efface quoi que ce soit.
- **Nom libre** (`nom_(2)`) comparé SANS casse : pour SMB, « Photo.jpg » et « photo.jpg » sont la
  même place.
- **Écriture refusée** au compte de la Source (droit DSM en lecture seule) : le lot s'arrête au
  premier refus — les suivants échoueraient de même — avec un message clair, comme la lecture
  seule du montage.
- **Coupure pendant un renommage** : le renommage n'est jamais rejoué (il a pu aboutir). On regarde
  où est l'élément : arrivé → c'est fait, on le journalise ; resté → échec de cette ligne ; NAS
  absent → le lot s'arrête là, le journal reste juste.
- **Journal** : `reorg_moves` en URI `smb://hôte/partage/chemin` ; l'annulation emprunte le chemin
  inverse, avec la session de l'emplacement du lot, et seulement dans cet emplacement.
"""

from __future__ import annotations

import posixpath
from typing import Any

from smb.smb_structs import OperationFailure

from logger import get_logger
from services import smb_chemins
from services.rangement.depot import Emplacement
from services.rangement.erreurs import RangementRefuse

log = get_logger(__name__)

#: Statuts NT d'un refus d'écrire : accès refusé, support protégé en écriture.
_REFUS_ECRITURE = frozenset({0xC0000022, 0xC00000A2})


class EcritureRefusee(Exception):
    """Le NAS refuse d'écrire au compte de la Source : inutile de continuer le lot."""


class Coupure(Exception):
    """Le NAS ne répond plus : le lot s'arrête là."""


def refus_d_ecrire(exc: BaseException) -> bool:
    if not isinstance(exc, OperationFailure):
        return False
    return any(getattr(m, "status", None) in _REFUS_ECRITURE for m in getattr(exc, "smb_messages", None) or [])


def nom_libre_sans_casse(nom: str, pris: set[str], est_dossier: bool) -> str:
    """Comme `deplacements.nom_libre`, mais « Nom » et « nom » occupent la même place (SMB). PURE."""
    plis = {p.casefold() for p in pris}
    if nom.casefold() not in plis:
        return nom
    base, ext = (nom, "") if est_dossier else posixpath.splitext(nom)
    n = 2
    while f"{base}_({n}){ext}".casefold() in plis:
        n += 1
    return f"{base}_({n}){ext}"


class RangeurSmb:
    """Déplace (ou remet) les éléments d'UN emplacement `smb`. `session` : une SessionSmb OUVERTE."""

    def __init__(self, session: Any, emplacement: Emplacement) -> None:
        self.session = session
        self.emp = emplacement
        decoupe = smb_chemins.decouper(emplacement.racine)
        self.hote = decoupe.hote if decoupe else ""
        self.partage = emplacement.partage or (decoupe.partage if decoupe else "")
        self.base = smb_chemins.normaliser_rel(emplacement.sous_dossier or "/")

    # --- chemins ----------------------------------------------------------------------------------
    def dans_le_partage(self, relatif: str) -> str:
        """Chemin dans le partage d'un chemin relatif à l'emplacement (« .. » refusé : ValueError)."""
        return smb_chemins.normaliser_rel(f"{self.base}/{relatif}") if relatif else self.base

    def uri(self, chemin: str) -> str:
        return smb_chemins.composer(self.hote, self.partage, chemin)

    def depuis_uri(self, uri: str) -> str:
        """Chemin dans le partage d'une URI du journal ; refuse une URI d'un autre partage ou hors de
        l'emplacement (on n'annule jamais ailleurs que là où le lot a rangé)."""
        c = smb_chemins.decouper(uri)
        if c is None or c.hote.casefold() != self.hote.casefold() or c.partage.casefold() != self.partage.casefold():
            raise RangementRefuse("pas dans le partage de cet emplacement")
        if self.base != "/" and not c.rel.casefold().startswith(self.base.casefold() + "/"):
            raise RangementRefuse("hors de l'emplacement")
        return c.rel

    # --- vérification préalable -------------------------------------------------------------------
    async def verifier(self) -> None:
        """Le dossier de l'emplacement existe et se lit avec ce compte (sinon le lot est refusé)."""
        if self.base == "/":
            await self.session.lister("/")
            return
        e = await self.session.stat(self.base)
        if e is None or not e.est_dossier:
            raise RangementRefuse(f"Dossier introuvable sur le partage « {self.partage} » : {self.base}")

    # --- écritures --------------------------------------------------------------------------------
    async def _renommer(self, source: str, destination: str) -> None:
        """Renomme ; après une coupure, constate où est l'élément au lieu de rejouer."""
        try:
            await self.session.renommer(source, destination)
            return
        except OperationFailure as exc:
            if refus_d_ecrire(exc):
                raise EcritureRefusee() from exc
            raise RangementRefuse("le NAS a refusé ce déplacement") from exc
        except Exception as exc:  # noqa: BLE001 — coupure : a-t-il abouti ?
            try:
                parti = await self.session.stat(source) is None
                arrive = await self.session.stat(destination) is not None
            except Exception as exc2:  # noqa: BLE001 — NAS absent : on ne sait pas, on s'arrête
                raise Coupure(f"{type(exc2).__name__} ; déplacement vers « {destination} » peut-être fait, "
                              "à vérifier (absent du journal)") from exc
            if parti and arrive:
                log.warning("Renommage SMB abouti malgré la coupure", emplacement_id=self.emp.id)
                return
            if not parti and not arrive:
                raise RangementRefuse(f"coupure réseau ({type(exc).__name__}), rien n'a bougé") from exc
            raise Coupure(f"{type(exc).__name__} ; « {source} » et « {destination} » dans un état incertain, "
                          "à vérifier (absent du journal)") from exc

    async def _creer_dossier(self, dossier: str) -> None:
        try:
            await self.session.creer_dossier(dossier)
        except OperationFailure as exc:
            if refus_d_ecrire(exc):
                raise EcritureRefusee() from exc
            raise

    async def deplacer(self, op: dict) -> tuple[str, str]:
        """Un déplacement du lot. Rend (source, destination) en URI `smb://` pour le journal."""
        try:
            source = self.dans_le_partage(op["source"])
            dossier = self.dans_le_partage(op["dossier"])
        except ValueError as exc:
            raise RangementRefuse("hors de l'emplacement") from exc
        if source == self.base:
            raise RangementRefuse("la racine de l'emplacement ne se déplace pas")
        try:
            e = await self.session.stat(source)
            if e is None:
                raise RangementRefuse("introuvable (déjà bougé ou disparu)")
            if dossier != "/":
                await self._creer_dossier(dossier)
            nom = op["nom"]
            if await self.session.stat(posixpath.join(dossier, nom)) is not None:  # pris depuis l'aperçu
                nom = nom_libre_sans_casse(nom, {x.nom for x in await self.session.lister(dossier)},
                                           e.est_dossier)
        except (RangementRefuse, EcritureRefusee):
            raise
        except OperationFailure as exc:
            raise RangementRefuse("le NAS a refusé ce déplacement") from exc
        except Exception as exc:  # noqa: BLE001 — coupure (déjà retentée une fois par la session)
            raise Coupure(type(exc).__name__) from exc
        destination = posixpath.join(dossier, nom)
        await self._renommer(source, destination)
        return self.uri(source), self.uri(destination)

    async def remettre(self, uri_source: str, uri_destination: str) -> None:
        """Défait un déplacement du journal : l'élément revient de `destination` à `source`."""
        source, destination = self.depuis_uri(uri_source), self.depuis_uri(uri_destination)
        try:
            if await self.session.stat(destination) is None:
                raise RangementRefuse("introuvable à sa nouvelle place (déplacé depuis ?)")
            if await self.session.stat(source) is not None:
                raise RangementRefuse("l'ancienne place est reprise par un autre fichier")
            parent = posixpath.dirname(source) or "/"
            if parent != "/":
                await self._creer_dossier(parent)
        except (RangementRefuse, EcritureRefusee):
            raise
        except OperationFailure as exc:
            raise RangementRefuse("le NAS a refusé ce retour") from exc
        except Exception as exc:  # noqa: BLE001
            raise Coupure(type(exc).__name__) from exc
        await self._renommer(destination, source)
