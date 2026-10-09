"""
Musique — génération d'un morceau par ComfyUI (ACE-Step 1.5 turbo) sur PC-GAME
=============================================================================
Tuile « Créer une musique ! » de la page Créer (demande de Thomas, 09/10/2026). Conçu avec la
session AIGUILLEUR, propriétaire de l'installation de ComfyUI :

- ComfyUI écoute sur le LAN de PC-GAME, le pare-feu Windows n'autorisant que le LXC. Il n'a AUCUNE
  authentification : Matothèque n'y envoie que le graphe ci-dessous.
- Matothèque ne libère PAS la carte en déchargeant les modèles des autres (JARVIS en dépend) :
  elle lit la mémoire libre (`/system_stats`) et REFUSE sous un seuil (`musique_vram_min_go`).
- Après chaque rendu, `POST /free` est OBLIGATOIRE : sinon ComfyUI garde ACE-Step (~9 Gio)
  résident indéfiniment, et la carte n'est plus libre au repos.

Tâche durable `musique` : paramètres `style`, `paroles`, `duree` (s), `langue`, `bpm`, `graine`.
Le morceau est déposé dans `storage/exports/musique/<job_id>.mp3` (partagé backend / worker).
"""
import asyncio
import random
import time
from pathlib import Path

import httpx

from config import get_settings
from logger import get_logger
from services import runtime_config
from services.job_worker import JobContext, register

log = get_logger(__name__)
settings = get_settings()

DUREE_MIN_S, DUREE_MAX_S = 10, 600
ATTENTE_MAX_S = 1800          # 30 min : 30 s d'audio prennent ~47 s, un morceau long bien plus
SUIVI_S = 3.0


class MusiqueIndisponible(RuntimeError):
    """ComfyUI absent, ou carte trop occupée : à réessayer plus tard, ce n'est pas un bug."""


def dossier_musique() -> Path:
    return Path(settings.storage_exports) / "musique"


def chemin_morceau(job_id: str) -> Path:
    return dossier_musique() / f"{job_id}.mp3"


def comfyui_url() -> str:
    return (runtime_config.effective("comfyui_url") or "").strip().rstrip("/")


def seuil_vram_go() -> float:
    try:
        return float(runtime_config.effective("musique_vram_min_go") or 8)
    except (TypeError, ValueError):
        return 8.0


def graphe(style: str, paroles: str, duree: int, langue: str, bpm: int, graine: int, prefixe: str) -> dict:
    """Graphe d'API ComfyUI d'ACE-Step 1.5 turbo (fourni par la session AIGUILLEUR, testé le 09/10).

    La durée va à DEUX endroits (94.duration, 98.seconds), la graine aussi (94.seed, 3.seed).
    """
    return {
        "97": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "ace_step_1.5_turbo_aio.safetensors"}},
        "94": {"class_type": "TextEncodeAceStepAudio1.5", "inputs": {
            "clip": ["97", 1], "tags": style, "lyrics": paroles, "seed": graine, "bpm": bpm,
            "duration": duree, "timesignature": "4", "language": langue, "keyscale": "C major",
            "generate_audio_codes": True, "cfg_scale": 2.0, "temperature": 0.85, "top_p": 0.9,
            "top_k": 0, "min_p": 0.0}},
        "78": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["97", 0], "shift": 3}},
        "98": {"class_type": "EmptyAceStep1.5LatentAudio", "inputs": {"seconds": duree, "batch_size": 1}},
        "47": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["94", 0]}},
        "3": {"class_type": "KSampler", "inputs": {
            "model": ["78", 0], "positive": ["94", 0], "negative": ["47", 0], "latent_image": ["98", 0],
            "seed": graine, "steps": 8, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "18": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["3", 0], "vae": ["97", 2]}},
        "106": {"class_type": "SaveAudioMP3", "inputs": {"audio": ["18", 0], "filename_prefix": prefixe, "quality": "V0"}},
    }


async def etat_comfyui() -> dict:
    """{configure, joignable, vram_libre_go, vram_totale_go, seuil_go, pret} — sans rien lancer."""
    url = comfyui_url()
    etat = {"configure": bool(url), "joignable": False, "vram_libre_go": None,
            "vram_totale_go": None, "seuil_go": seuil_vram_go(), "pret": False}
    if not url:
        return etat
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as c:
            r = await c.get(f"{url}/system_stats")
        r.raise_for_status()
        carte = (r.json().get("devices") or [{}])[0]
        etat["joignable"] = True
        etat["vram_libre_go"] = round((carte.get("vram_free") or 0) / 2**30, 1)
        etat["vram_totale_go"] = round((carte.get("vram_total") or 0) / 2**30, 1)
        etat["pret"] = etat["vram_libre_go"] >= etat["seuil_go"]
    except Exception as e:  # noqa: BLE001 — éteint, réseau, réponse inattendue : « injoignable »
        log.info("ComfyUI injoignable", url=url, erreur=str(e) or type(e).__name__)
    return etat


def borner(params: dict) -> dict:
    """Paramètres de la tâche, bornés et complétés (graine tirée si absente)."""
    duree = max(DUREE_MIN_S, min(DUREE_MAX_S, int(params.get("duree") or 60)))
    bpm = max(10, min(300, int(params.get("bpm") or 110)))
    graine = params.get("graine")
    return {
        "style": (params.get("style") or "").strip()[:1000],
        "paroles": (params.get("paroles") or "").strip()[:8000],
        "duree": duree, "bpm": bpm,
        "langue": (params.get("langue") or "fr").strip()[:5] or "fr",
        "graine": int(graine) if graine not in (None, "") else random.randint(0, 2**31 - 1),
    }


@register("musique")
async def handler_musique(ctx: JobContext) -> dict:
    p = borner(ctx.parametres)
    if not p["style"] and not p["paroles"]:
        raise ValueError("Décris un style ou écris des paroles")

    url = comfyui_url()
    await ctx.report(5, "Vérification de la carte graphique…")
    etat = await etat_comfyui()
    if not etat["configure"]:
        raise MusiqueIndisponible("ComfyUI n'est pas encore relié à Matothèque (réglage comfyui_url vide)")
    if not etat["joignable"]:
        raise MusiqueIndisponible("ComfyUI injoignable — PC-GAME éteint ou ComfyUI arrêté")
    if not etat["pret"]:
        raise MusiqueIndisponible(
            f"Carte occupée ({etat['vram_libre_go']} Gio libres, {etat['seuil_go']} requis) — réessayer plus tard")

    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as c:
        try:
            r = await c.post(f"{url}/prompt", json={"prompt": graphe(
                p["style"], p["paroles"], p["duree"], p["langue"], p["bpm"], p["graine"],
                f"audio/matotheque_{ctx.job_id}")})
            if r.status_code >= 400:
                raise RuntimeError(f"ComfyUI a refusé le graphe : {r.text[:300]}")
            prompt_id = r.json()["prompt_id"]

            await ctx.report(15, "Composition en cours…")
            sortie = None
            while time.monotonic() - t0 < ATTENTE_MAX_S:
                if ctx.cancelled:
                    await c.post(f"{url}/interrupt")
                    return {"annule": True}
                h = (await c.get(f"{url}/history/{prompt_id}")).json().get(prompt_id) or {}
                statut = h.get("status") or {}
                if statut.get("completed") or statut.get("status_str") == "error":
                    if statut.get("status_str") != "success":
                        raise RuntimeError(f"ComfyUI : rendu en erreur ({statut.get('messages', [])[-1:]})")
                    sortie = (h.get("outputs", {}).get("106", {}).get("audio") or [None])[0]
                    break
                ecoule = time.monotonic() - t0
                # Pas de vraie progression côté ComfyUI : on avance vers 90 % au rythme mesuré
                # (~1,6 s de calcul par seconde d'audio), sans jamais l'atteindre.
                await ctx.report(min(90, 15 + int(75 * ecoule / max(30, p["duree"] * 1.6))), "Composition en cours…")
                await asyncio.sleep(SUIVI_S)
            if sortie is None:
                raise RuntimeError("ComfyUI n'a rien rendu dans le délai imparti")

            await ctx.report(95, "Récupération du morceau…")
            f = await c.get(f"{url}/view", params={"filename": sortie["filename"],
                                                    "subfolder": sortie.get("subfolder", ""),
                                                    "type": sortie.get("type", "output")})
            f.raise_for_status()
            dossier_musique().mkdir(parents=True, exist_ok=True)
            chemin_morceau(ctx.job_id).write_bytes(f.content)
        finally:
            # OBLIGATOIRE (session AIGUILLEUR) : sinon ACE-Step reste résident (~9 Gio) indéfiniment.
            try:
                await c.post(f"{url}/free", json={"unload_models": True, "free_memory": True})
            except Exception as e:  # noqa: BLE001 — ne masque pas l'erreur du rendu
                log.warning("ComfyUI /free impossible", erreur=str(e) or type(e).__name__)

    duree_rendu = round(time.monotonic() - t0)
    log.info("Morceau généré", job_id=ctx.job_id, duree=p["duree"], rendu_s=duree_rendu)
    return {**p, "fichier": f"{ctx.job_id}.mp3", "rendu_s": duree_rendu}
