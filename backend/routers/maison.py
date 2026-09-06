"""
Router Maison — /api/maison
============================
Diffuser un média sur une enceinte de la maison, via **Home Assistant** (LAN).

Matothèque catalogue ; elle n'a pas de lecteur. Ces deux routes servent le seul geste qui
apporte quelque chose qu'un lecteur intégré n'apporterait pas : envoyer un épisode dans la
pièce où l'on se trouve, depuis l'écran où l'on classe.

Rien ici ne s'exécute tout seul : `diffuser` est appelée par un clic, jamais par un cycle de
fond. Voir `services/maison_service` pour la portée du jeton HA.
"""

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from logger import get_logger
from services import maison_service

log = get_logger(__name__)
router = APIRouter()


class DiffuserIn(BaseModel):
    entity_id: str = Field(min_length=3, description="Entité media_player de Home Assistant")
    audio_url: str = Field(min_length=8, description="Adresse de l'audio (enclosure du flux)")
    titre: str | None = None


def _exiger_configuration() -> None:
    if not maison_service.configure():
        raise HTTPException(
            status_code=400,
            detail="Home Assistant n'est pas configuré. Renseigne son URL et un jeton dans "
                   "Paramètres › Maison — diffusion.",
        )


@router.get("/maison/enceintes", tags=["Maison"])
async def lister_enceintes() -> dict:
    """Entités `media_player` connues de Home Assistant, pour alimenter le sélecteur."""
    _exiger_configuration()
    try:
        return {"enceintes": await maison_service.enceintes()}
    except httpx.HTTPStatusError as e:
        # 401 = jeton refusé, et c'est le cas le plus fréquent : le dire plutôt que
        # « erreur HTTP », qui enverrait chercher du côté du réseau.
        if e.response.status_code == 401:
            raise HTTPException(status_code=502, detail="Home Assistant refuse le jeton (401).")
        raise HTTPException(status_code=502, detail=f"Home Assistant : HTTP {e.response.status_code}")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Home Assistant injoignable : {e}")


@router.post("/maison/diffuser", tags=["Maison"])
async def diffuser(body: DiffuserIn) -> dict:
    """Envoie l'audio sur l'enceinte choisie. Acte explicite, déclenché par un clic."""
    _exiger_configuration()
    try:
        await maison_service.diffuser(body.entity_id, body.audio_url, body.titre)
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=502, detail=f"Diffusion refusée par Home Assistant "
                                                    f"(HTTP {e.response.status_code}).")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Diffusion impossible : {e}")
    return {"diffuse": True, "enceinte": body.entity_id}
