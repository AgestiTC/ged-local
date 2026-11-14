"""
Scanner un emplacement par SMB — `SourceSmb` (étape 4 du plan « Rangement sur Sources SMB »)
============================================================================================
Même rôle que `SourceDisque` (le NAS monté), mais par le réseau, avec le compte de la Source
« Rangement » et UNE session SMB pour tout le scan (`smb_session.SessionSmb`).

Ce qui ne change pas, et pourquoi c'est sûr :
- **Métadonnées seulement** : `listPath` rend nom, type, taille et date ; aucun octet n'est lu.
- **Jamais « disparu » sur un doute** : un dossier refusé (droit DSM manquant, comme
  `homes/Tom/Rapport-PDF` le 14/11/2026) est tenu pour illisible — on le compte, on continue, rien
  n'en disparaît. Une COUPURE (NAS éteint, réseau perdu) n'est pas un dossier illisible : elle fait
  échouer le scan, pour qu'un NAS absent ne vide pas l'inventaire.
- **Exclusions** : les mêmes ; le « chemin absolu » d'un élément est son URI `smb://hôte/partage/…`.

Mesuré le 14/11/2026 (docs/mesures/rangement-smb-2026-11-14.md) : `homes/Tom`, 273 612 fichiers,
parcouru en 83 s sur une connexion.
"""

from __future__ import annotations

from typing import Any

from smb.smb_structs import OperationFailure

from logger import get_logger
from services import smb_chemins
from services.rangement.depot import Compteurs, Depot, Element, Emplacement, chemin_enfant
from services.rangement.exclusions import Exclusions

log = get_logger(__name__)

Listing = tuple[dict[str, Element], set[str]]


class SourceSmb:
    """`session` : une `SessionSmb` NON ouverte (ou un double de test) sur le partage de l'emplacement.
    La source l'ouvre à `verifier` et la ferme à `fermer` (appelé par le scan, quoi qu'il arrive)."""

    def __init__(self, session: Any, emplacement: Emplacement, exclusions: Exclusions) -> None:
        self.session = session
        self.emp = emplacement
        self.exclusions = exclusions
        self.base = smb_chemins.normaliser_rel(emplacement.sous_dossier or "/")
        decoupe = smb_chemins.decouper(emplacement.racine)
        self.hote = decoupe.hote if decoupe else ""
        self.partage = emplacement.partage or (decoupe.partage if decoupe else "")
        self._ouverte = False

    def _dossier(self, relatif: str) -> str:
        """Chemin dans le partage d'un élément relatif à l'emplacement (« / » = racine du partage)."""
        return smb_chemins.normaliser_rel(f"{self.base}/{relatif}") if relatif else self.base

    async def verifier(self, depot: Depot, emp: Emplacement) -> str | None:
        try:
            await self.session.__aenter__()
            self._ouverte = True
            if self.base != "/":
                entree = await self.session.stat(self.base)
                if entree is None or not entree.est_dossier:
                    return f"dossier introuvable sur le partage « {self.partage} » : {self.base}"
        except Exception as exc:  # noqa: BLE001 — NAS injoignable, compte refusé : échec, rien ne disparaît
            log.warning("Scan SMB : partage injoignable", emplacement_id=emp.id, partage=self.partage,
                        erreur=type(exc).__name__)
            return f"partage « {self.partage} » injoignable ({type(exc).__name__}) — rien n'a été marqué disparu"
        return None

    async def lister(self, relatif: str, profondeur: int, c: Compteurs) -> Listing | None:
        dossier = self._dossier(relatif)
        try:
            entrees = await self.session.lister(dossier)
        except OperationFailure:
            # Refus du NAS sur CE dossier (droit manquant, supprimé entre-temps) : illisible, on continue.
            c.nb_erreurs += 1
            log.warning("Dossier SMB illisible ignoré", emplacement_id=self.emp.id, dossier=dossier)
            return None
        # Toute autre erreur (coupure) remonte : le scan échoue, rien de plus n'est marqué disparu.
        actuels: dict[str, Element] = {}
        illisibles: set[str] = set()
        for e in entrees:
            try:
                e.nom.encode("utf-8")
            except UnicodeEncodeError:
                c.nb_erreurs += 1
                illisibles.add(e.nom)
                continue
            rel = chemin_enfant(relatif, e.nom)
            absolu = smb_chemins.composer(self.hote, self.partage, self._dossier(rel))
            if self.exclusions.exclut(e.nom, rel, absolu, profondeur, e.est_dossier):
                continue
            actuels[e.nom] = Element(e.nom, e.est_dossier, 0 if e.est_dossier else e.taille, e.mtime or 0.0)
        return actuels, illisibles

    async def fermer(self) -> None:
        if self._ouverte:
            self._ouverte = False
            await self.session.__aexit__(None, None, None)
