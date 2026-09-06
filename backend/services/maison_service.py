"""
Service Maison — diffuser un média sur une enceinte via Home Assistant
======================================================================
Matothèque **catalogue**, elle ne rejoue pas : on n'écoute pas un podcast devant sa GED. Mais
depuis la fiche d'une ressource, on peut envoyer un épisode sur une enceinte de la maison — le
bon média dans la bonne pièce, depuis l'écran où l'on classe.

**Reste local.** Home Assistant est sur le LAN, comme Ollama. Ce service ne parle qu'à lui.
L'enceinte, elle, ira chercher l'audio chez l'éditeur du podcast : c'est le minimum
incompressible pour écouter quoi que ce soit, et ça ne passe pas par Matothèque.

⚠️ **Le jeton HA est un passe-partout.** Un jeton de longue durée Home Assistant donne accès à
TOUTE son API — pas seulement aux enceintes. C'est une limite de HA, pas un choix de notre part,
et l'écran de réglage doit le dire plutôt que laisser croire à une portée restreinte. Il est
stocké chiffré (Fernet), comme les autres secrets.
"""

import httpx

from logger import get_logger
from services import runtime_config
from services.crypto import decrypt

log = get_logger(__name__)

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def configure() -> bool:
    """Vrai si une URL et un jeton sont renseignés. Sans les deux, la fonction reste muette."""
    return bool(runtime_config.effective("ha_url") and runtime_config.effective("ha_token"))


def _base() -> str:
    return (runtime_config.effective("ha_url") or "").rstrip("/")


def _entetes() -> dict:
    return {
        "Authorization": f"Bearer {decrypt(runtime_config.effective('ha_token') or '')}",
        "Content-Type": "application/json",
    }


async def enceintes() -> list[dict]:
    """
    Les entités `media_player` connues de HA : `{entity_id, nom, etat}`.

    On liste ce qui EXISTE plutôt que de faire saisir un identifiant à la main — une faute de
    frappe dans `media_player.cuisine` donnerait un échec sans explication.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(f"{_base()}/api/states", headers=_entetes())
        resp.raise_for_status()
        etats = resp.json()

    trouvees = [
        {
            "entity_id": e["entity_id"],
            "nom": (e.get("attributes") or {}).get("friendly_name") or e["entity_id"],
            # `unavailable` = l'enceinte est éteinte ou hors réseau. On la montre quand même,
            # grisée : son absence de la liste ferait croire qu'elle n'existe pas.
            "etat": e.get("state"),
        }
        for e in etats if e.get("entity_id", "").startswith("media_player.")
    ]
    trouvees.sort(key=lambda x: x["nom"].lower())
    return trouvees


async def diffuser(entity_id: str, audio_url: str, titre: str | None = None) -> None:
    """
    Envoie `audio_url` sur l'enceinte `entity_id` (service HA `media_player.play_media`).

    Acte explicite, jamais automatique : c'est un clic de l'utilisateur qui l'appelle, et rien
    dans l'application ne le déclenche seul.
    """
    charge: dict = {
        "entity_id": entity_id,
        "media_content_id": audio_url,
        "media_content_type": "music",
    }
    if titre:
        # Certains lecteurs (Chromecast, Sonos) affichent ces métadonnées ; les autres les
        # ignorent sans broncher.
        charge["extra"] = {"title": titre}

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(
            f"{_base()}/api/services/media_player/play_media",
            headers=_entetes(), json=charge,
        )
        resp.raise_for_status()
    log.info("Diffusion lancée", enceinte=entity_id, titre=titre)


async def check_health() -> bool:
    """Vrai si HA répond et accepte le jeton. Sert au voyant, pas au chemin de diffusion."""
    if not configure():
        return False
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(f"{_base()}/api/", headers=_entetes())
        return resp.status_code == 200
    except Exception:  # noqa: BLE001 — un voyant ne doit jamais faire tomber l'appelant
        return False
