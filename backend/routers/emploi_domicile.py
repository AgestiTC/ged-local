"""
Router Emploi à domicile — /api/emploi-domicile
==============================================
Sert l'onglet du module (« Nounou » dans « Devenir parent ») : **fiches et checklist, en
lecture seule**. Aucune table, aucune écriture, aucune sortie réseau.

  GET /emploi-domicile/profils              → la table des profils (guichet, lieu, aide)
  GET /emploi-domicile/fiches?profil=assmat → fiches + checklist + liens officiels

Le **profil** est une donnée, pas un écran : c'est lui qui porte le guichet (Pajemploi ou
CESU), l'aide et le libellé de l'onglet. Ajouter un profil ne touche aucune ligne
d'interface — même principe que le registre fiscal.

Un profil dont le contenu n'est pas encore écrit renvoie quand même le tronc commun (même
convention collective, même contrat) **et le dit** dans `avertissements` : afficher un écran
vide se lirait « il n'y a rien à savoir », ce qui est faux.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from logger import get_logger
from services.emploi_domicile import contenu
from services.emploi_domicile.profils import PROFILS, profil as get_profil

log = get_logger(__name__)
router = APIRouter()


def _serialiser_profil(p) -> dict:
    return {
        "cle": p.cle, "onglet": p.onglet, "libelle": p.libelle, "lieu": p.lieu,
        "guichet": p.guichet, "aide": p.aide, "socle": p.socle, "resume": p.resume,
        "documente": p.documente,
    }


@router.get("/emploi-domicile/profils", tags=["Emploi à domicile"])
async def profils() -> dict:
    """La table des profils — c'est elle qui décide du guichet, de l'aide et du libellé."""
    return {"profils": [_serialiser_profil(p) for p in PROFILS.values()]}


@router.get("/emploi-domicile/fiches", tags=["Emploi à domicile"])
async def fiches(profil: str | None = Query(default=None)) -> dict:
    """
    Tout ce qu'affiche l'onglet, en un seul appel : l'écran n'a rien à recomposer.

    `verifie_le` et `avertissement` accompagnent toujours le contenu — une fiche
    réglementaire sans sa date se lit comme si elle était à jour.
    """
    p = get_profil(profil)

    avertissements: list[str] = []
    if not p.documente:
        avertissements.append(
            f"Le profil « {p.libelle} » n'a pas encore de contenu propre. Les fiches "
            "ci-dessous valent quand même : c'est la même convention collective et le même "
            "contrat. Ce qui manque, ce sont les points spécifiques à ce profil."
        )
    if p.cle != "assmat":
        avertissements.append(
            "La checklist d'entretien est écrite pour l'accueil d'un enfant. Son ossature "
            "(cadre, lieu, quotidien, argent, contrat) vaut pour toute embauche à domicile, "
            "mais le détail est calibré pour une assistante maternelle."
        )

    return {
        "profil": _serialiser_profil(p),
        "verifie_le": contenu.VERIFIE_LE.isoformat(),
        "avertissement": contenu.AVERTISSEMENT,
        "avertissements": avertissements,
        "fiches": contenu.fiches(p),
        "checklist": contenu.checklist(p),
        "liens": contenu.LIENS,
    }
