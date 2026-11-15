"""
Emplacement SMB — déclarer un dossier du NAS à partir d'une Source (étape 3 du plan
« Rangement sur Sources SMB », docs/plan-rangement-sources-smb.md)
===================================================================================
Plus de montage par partage dans le PVE et le compose : on choisit une Source (déclarée dans
*Paramètres › Sources NAS/SMB*), un partage et un dossier. La Source doit être marquée « Rangement »
(S2) : son compte (`svc-rangement`) a le droit d'écrire, et la GED ne s'en sert jamais.

À la déclaration, le dossier est vérifié par SMB (il existe, c'est un dossier) avec UNE session —
c'est la seule fois où l'API parle au NAS pour le Rangement ; le scan, lui, passe par le worker
(étape 4). Le secret de la Source ne sort jamais d'ici : ni réponse, ni message, ni journal.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from models.source import USAGE_RANGEMENT, Source
from services import crypto, smb_chemins
from services.rangement.depot import Depot, DoublonRacine, Emplacement
from services.rangement.erreurs import InventaireRefus
from services.smb_session import SessionSmb

log = get_logger(__name__)

#: Fabrique de session (remplacée dans les tests : aucun réseau).
OuvrirSession = Callable[..., Any]


async def source_du_rangement(db: AsyncSession, source_id: str) -> Source:
    """La Source, si elle existe, est SMB et réservée au Rangement. Sinon `InventaireRefus`."""
    try:
        sid = uuid.UUID(str(source_id))
    except ValueError as exc:
        raise InventaireRefus("Source inconnue.", code="source_inconnue", statut=404) from exc
    src = await db.get(Source, sid)
    if src is None:
        raise InventaireRefus("Source inconnue.", code="source_inconnue", statut=404)
    if src.type != "smb" or not src.hote:
        raise InventaireRefus("Seule une source SMB (NAS) peut porter un emplacement.", code="source_pas_smb")
    if (src.usage or "") != USAGE_RANGEMENT:
        raise InventaireRefus("Cette source sert à la GED. Utilise une source marquée « Rangement » "
                              "(Paramètres › Sources NAS/SMB).", code="source_pas_rangement")
    return src


def ouvrir_session(src: Source, partage: str, ouvrir: OuvrirSession | None = None) -> Any:
    """Une session SMB sur ce partage, avec le compte de la Source (secret déchiffré ici seulement).
    `SessionSmb` est cherchée à l'appel : les tests la remplacent par un faux serveur."""
    secret = crypto.decrypt(src.secret_chiffre) if src.secret_chiffre else None
    return (ouvrir or SessionSmb)(src.hote, partage, src.identifiant, secret, src.domaine)


def cible(src: Source, partage: str, sous_dossier: str) -> tuple[str, str, str]:
    """(partage, dossier normalisé, racine `smb://…`), contrôlés sur le texte. `InventaireRefus` sinon."""
    partage = (partage or "").strip().strip("/")
    if not partage or "/" in partage or "\\" in partage:
        raise InventaireRefus("Partage invalide.", code="partage_invalide")
    try:
        dossier = smb_chemins.normaliser_rel(sous_dossier)
    except ValueError as exc:
        raise InventaireRefus("Dossier invalide (remontée de dossier).", code="dossier_invalide") from exc
    return partage, dossier, smb_chemins.composer(src.hote, partage, dossier)


async def declarer(db: AsyncSession, depot: Depot, libelle: str, source_id: str, partage: str,
                   sous_dossier: str, *, ouvrir: OuvrirSession | None = None) -> Emplacement:
    """Déclare `smb://hote/partage/sous_dossier`. Lève `InventaireRefus` ou `DoublonRacine`."""
    src = await source_du_rangement(db, source_id)
    partage, dossier, racine = cible(src, partage, sous_dossier)

    for emp in await depot.emplacements():
        if emp.racine == racine:
            raise DoublonRacine(racine)

    await verifier_dossier(src, partage, dossier, ouvrir)
    return await depot.creer_emplacement(libelle, racine, source="smb", source_id=str(src.id),
                                         partage=partage, sous_dossier=dossier)


async def verifier_dossier(src: Source, partage: str, dossier: str, ouvrir: OuvrirSession | None = None) -> None:
    """Le dossier existe sur le partage et ce compte peut le lire (une session). `InventaireRefus` sinon."""
    try:
        async with ouvrir_session(src, partage, ouvrir) as session:
            if dossier == "/":
                await session.lister("/")   # le partage existe et ce compte peut le lire
            else:
                entree = await session.stat(dossier)
                if entree is None or not entree.est_dossier:
                    raise InventaireRefus(f"Dossier introuvable sur le partage « {partage} » : {dossier}",
                                          code="dossier_introuvable")
    except InventaireRefus:
        raise
    except Exception as exc:  # noqa: BLE001 — NAS injoignable, partage inconnu, compte refusé
        log.warning("Emplacement SMB : vérification impossible", hote=src.hote, partage=partage,
                    erreur=type(exc).__name__)
        lieu = partage if dossier == "/" else f"{partage}{dossier}"
        raise InventaireRefus(f"Le NAS n'a pas permis de lire « {lieu} » avec cette source (serveur "
                              "injoignable, partage inconnu ou droit manquant).", code="smb_illisible") from exc


async def session_de(emp: Emplacement, ouvrir: OuvrirSession | None = None) -> Any:
    """La session SMB (non ouverte) d'un emplacement `smb`, avec le compte de sa Source, relue en base
    au moment du scan : un secret changé dans *Sources* sert dès le scan suivant. Lève
    `InventaireRefus` si la Source n'est plus utilisable par le Rangement."""
    from database import AsyncSessionLocal

    if not emp.est_smb or not emp.source_id or not emp.partage:
        raise InventaireRefus("Cet emplacement n'est pas lu par SMB.", code="pas_smb")
    async with AsyncSessionLocal() as db:
        src = await source_du_rangement(db, emp.source_id)
    return ouvrir_session(src, emp.partage, ouvrir)
