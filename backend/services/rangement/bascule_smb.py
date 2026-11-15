"""
Bascule d'un emplacement « disque monté » vers SMB — étape 8 du plan « Rangement sur Sources SMB »
(docs/plan-rangement-sources-smb.md)
=================================================================================================
Les emplacements déclarés quand le NAS était MONTÉ dans le worker (`/mnt/rangement/...`) passent en
lecture par SMB, avec la Source « Rangement », SANS être redéclarés : ils gardent leur identifiant,
donc leurs entrées, leurs empreintes, leurs instantanés et l'historique de leurs scans (le plan de
classement, les propositions et le journal suivent l'emplacement). Les chemins de l'inventaire sont
relatifs à la racine : seule la racine change.

`prefixe` couvre le cas d'un emplacement déclaré un cran trop haut (« Home-TOM » sur `/mnt/rangement`,
dont tout le contenu est sous `homes-Tom/`) : ce sous-dossier devient la racine, le reste est retiré.

Geste d'administration unique, lancé SUR LE LXC (`python -m outils.rangement_smb`), jamais par l'API :
à blanc par défaut, `--appliquer` pour écrire. Le dossier est d'abord vérifié par SMB, comme à la
déclaration. Le scan suivant dit si l'inventaire est le même : il ne doit rien ajouter ni retirer.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from services.rangement import emplacement_smb
from services.rangement.depot import Depot, DoublonRacine
from services.rangement.erreurs import InventaireRefus

log = get_logger(__name__)


@dataclass(frozen=True)
class Bascule:
    emplacement_id: int
    libelle: str
    avant: str
    apres: str
    prefixe: str
    applique: bool = False
    entrees_gardees: int | None = None
    entrees_retirees: int | None = None


def normaliser_prefixe(prefixe: str | None) -> str:
    """Sous-dossier RELATIF à la racine actuelle (« homes-Tom »), sans « .. » ni segment vide."""
    p = (prefixe or "").replace("\\", "/").strip().strip("/")
    if not p:
        return ""
    if any(s in ("", ".", "..") for s in p.split("/")):
        raise InventaireRefus("Sous-dossier invalide.", code="prefixe_invalide")
    return p


async def basculer(db: AsyncSession, depot: Depot, emplacement_id: int, source_id: str, partage: str,
                   sous_dossier: str, *, prefixe: str = "", appliquer: bool = False,
                   ouvrir: emplacement_smb.OuvrirSession | None = None) -> Bascule:
    """Vérifie tout, puis (si `appliquer`) rebranche l'emplacement sur SMB. `InventaireRefus` sinon."""
    emp = await depot.emplacement(emplacement_id)
    if emp is None:
        raise InventaireRefus("Emplacement inconnu.", code="emplacement_inconnu", statut=404)
    if not emp.sur_serveur:
        raise InventaireRefus(f"« {emp.libelle} » n'est pas un emplacement sur disque monté ({emp.source}).",
                              code="pas_serveur")
    dernier = await depot.dernier_scan(emplacement_id)
    if dernier and dernier.get("statut") == "en_cours":
        raise InventaireRefus(f"Un scan de « {emp.libelle} » est en cours : attendre sa fin.", code="scan_en_cours",
                              statut=409)
    prefixe = normaliser_prefixe(prefixe)
    if prefixe and await depot.dossier(emplacement_id, prefixe) is None:
        raise InventaireRefus(f"« {prefixe} » n'est pas un dossier connu de « {emp.libelle} ».",
                              code="prefixe_inconnu")

    src = await emplacement_smb.source_du_rangement(db, source_id)
    partage, dossier, racine = emplacement_smb.cible(src, partage, sous_dossier)
    if any(e.id != emp.id and e.racine == racine for e in await depot.emplacements()):
        raise InventaireRefus(f"{racine} est déjà un autre emplacement.", code="doublon", statut=409)
    await emplacement_smb.verifier_dossier(src, partage, dossier, ouvrir)

    bascule = Bascule(emp.id, emp.libelle, emp.racine, racine, prefixe)
    if not appliquer:
        return bascule
    try:
        gardees, retirees = await depot.rebrancher_emplacement(
            emp.id, racine=racine, source="smb", source_id=str(src.id), partage=partage,
            sous_dossier=dossier, prefixe=prefixe)
    except DoublonRacine as exc:
        raise InventaireRefus(f"{racine} est déjà un autre emplacement.", code="doublon", statut=409) from exc
    log.info("Rangement : emplacement basculé en SMB", emplacement_id=emp.id, avant=emp.racine, apres=racine,
             prefixe=prefixe or None, entrees_gardees=gardees, entrees_retirees=retirees)
    return Bascule(emp.id, emp.libelle, emp.racine, racine, prefixe, True, gardees, retirees)
