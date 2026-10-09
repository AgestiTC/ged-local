"""
Vidéo — animer un dessin scanné à partir d'un petit scénario (Wan 2.2 TI2V-5B, ComfyUI, PC-GAME)
================================================================================================
Tuile « Créer une vidéo ! » (demande de Thomas, 09/10/2026), conçue avec la session AIGUILLEUR qui
a mesuré l'essai M4 : 5 s de vidéo (121 images, 24 im/s) en ~4 min 30, carte VIDE.

Règles de carte, plus strictes que pour la musique (la vidéo prend TOUTE la carte, 15,1 Gio) :
- endormir Voxtral (il garde ~14 Gio 5 min après une dictée) : `POST {proxy}/voxtral/sleep` ;
- attendre qu'Ollama n'ait AUCUN modèle chargé et que Voxtral dorme — sans décharger personne ;
  nouvel essai toutes les 60 s, 30 min au plus, puis « carte occupée » en nommant les occupants ;
- pas de dépassement : sans la carte entière, ce serait un ordre de grandeur plus lent ;
- `POST /free` après chaque rendu (finally), `/interrupt` sur annulation.

Tâche durable `video` : paramètres `image` (fichier source déposé), `largeur`, `hauteur`,
`scenario`, `prompt` (anglais, facultatif), `graine`. Sortie : `storage/exports/video/<job>.mp4`.
"""
import asyncio
import json
import random
import time
import uuid
from pathlib import Path

import httpx

from config import get_settings
from logger import get_logger
from services import runtime_config
from services.job_worker import JobContext, register
from services.musique_jobs import MusiqueIndisponible, _modeles_charges, comfyui_url

log = get_logger(__name__)
settings = get_settings()

IMAGES, IPS = 121, 24                # 5 s : la durée native du modèle
ATTENTE_CARTE_MAX_S = 1800
ATTENTE_CARTE_PAS_S = 60.0
ATTENTE_RENDU_MAX_S = 1800
SUIVI_S = 5.0
FIN_PROMPT = ("Simple hand-drawn animation, the paper texture and the drawing style stay exactly the same, "
              "static camera.")
NEGATIF = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，"
           "JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，"
           "形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走")


def dossier_video() -> Path:
    return Path(settings.storage_exports) / "video"


def chemin_video(job_id: str) -> Path:
    return dossier_video() / f"{job_id}.mp4"


def proxy_url() -> str:
    """Proxy Voxtral de PC-GAME : dictée (transcription) et mise en sommeil de Voxtral."""
    return (runtime_config.effective("voxtral_proxy_url") or "").strip().rstrip("/")


def format_natif(largeur: int, hauteur: int) -> tuple[int, int]:
    """Les deux formats natifs de Wan 2.2 TI2V-5B : paysage 1280×704, portrait 704×1280."""
    return (704, 1280) if hauteur > largeur else (1280, 704)


def graphe(image: str, prompt: str, largeur: int, hauteur: int, graine: int, prefixe: str) -> dict:
    """Graphe d'API testé par la session AIGUILLEUR (essai M4, 09/10/2026)."""
    return {
        "37": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_ti2v_5B_fp16.safetensors", "weight_dtype": "default"}},
        "38": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "39": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
        "56": {"class_type": "LoadImage", "inputs": {"image": image}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["38", 0], "text": prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["38", 0], "text": NEGATIF}},
        "48": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["37", 0], "shift": 8}},
        "55": {"class_type": "Wan22ImageToVideoLatent", "inputs": {
            "vae": ["39", 0], "width": largeur, "height": hauteur, "length": IMAGES, "batch_size": 1,
            "start_image": ["56", 0]}},
        "3": {"class_type": "KSampler", "inputs": {
            "model": ["48", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["55", 0],
            "seed": graine, "steps": 20, "cfg": 5.0, "sampler_name": "uni_pc", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["39", 0]}},
        "57": {"class_type": "CreateVideo", "inputs": {"images": ["8", 0], "fps": IPS}},
        "58": {"class_type": "SaveVideo", "inputs": {"video": ["57", 0], "filename_prefix": prefixe,
                                                    "format": "mp4", "format.codec": "h264"}},
    }


async def etat_voxtral() -> dict | None:
    url = proxy_url()
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as c:
            r = await c.get(f"{url}/voxtral/state")
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        log.info("État de Voxtral illisible", erreur=str(e) or type(e).__name__)
        return None


async def endormir_voxtral() -> bool:
    """True si Voxtral dort (ou s'il n'y a pas de proxy) ; False si une transcription est en cours."""
    url = proxy_url()
    if not url:
        return True
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=3.0)) as c:
            r = await c.post(f"{url}/voxtral/sleep")
        return r.status_code == 200
    except Exception as e:  # noqa: BLE001
        log.info("Mise en sommeil de Voxtral impossible", erreur=str(e) or type(e).__name__)
        return False


async def etat_carte() -> dict:
    """{joignable, pret, occupants} : la vidéo exige une carte VIDE (aucun modèle, Voxtral endormi)."""
    url = comfyui_url()
    etat = {"configure": bool(url), "joignable": False, "pret": False, "occupants": []}
    if not url:
        return etat
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as c:
            (await c.get(f"{url}/system_stats")).raise_for_status()
        etat["joignable"] = True
    except Exception:  # noqa: BLE001
        return etat
    modeles = await _modeles_charges()
    occupants = [m["nom"] for m in (modeles or []) if m["go"] > 0]
    vox = await etat_voxtral()
    if vox is not None and not vox.get("sleeping"):
        occupants.append("Voxtral (dictée)")
    etat["occupants"] = occupants
    etat["pret"] = not occupants
    return etat


async def preparer_mouvement(scenario: str) -> str:
    """Scénario français → prompt anglais de MOUVEMENT (< 80 mots), par l'IA locale, keep_alive 0."""
    from services.ollama_service import OllamaService
    systeme = (
        "You write prompts for an image-to-video model that animates a hand-drawn picture. From the "
        "user's French scenario, write ONE English paragraph describing ONLY the MOTION (what moves, "
        "how), in fewer than 80 words. Do not describe the style. Answer with the paragraph only.")
    texte = (await OllamaService().generate(scenario, model=runtime_config.model_for("chat"), system=systeme,
                                           num_predict=300, keep_alive=0)).strip().strip('"')
    if not texte:
        raise RuntimeError("L'IA n'a pas su décrire le mouvement — réessaie")
    return f"{texte} {FIN_PROMPT}"


@register("video")
async def handler_video(ctx: JobContext) -> dict:
    p = ctx.parametres
    source = Path(p.get("image") or "")
    if not source.is_file():
        raise ValueError("Dessin introuvable")
    largeur, hauteur = format_natif(int(p.get("largeur") or 1280), int(p.get("hauteur") or 704))
    graine = int(p["graine"]) if p.get("graine") not in (None, "") else random.randint(0, 2**31 - 1)

    await ctx.report(3, "Traduction du scénario en mouvement…")
    prompt = (p.get("prompt") or "").strip() or await preparer_mouvement(p.get("scenario") or "")

    url = comfyui_url()
    if not url:
        raise MusiqueIndisponible("ComfyUI n'est pas relié à Matothèque (réglage comfyui_url vide)")

    # Carte VIDE exigée : on endort Voxtral, puis on attend qu'Ollama ait tout déchargé — sans forcer.
    debut = time.monotonic()
    while True:
        await endormir_voxtral()
        etat = await etat_carte()
        if not etat["joignable"]:
            raise MusiqueIndisponible("ComfyUI injoignable — PC-GAME éteint ou ComfyUI arrêté")
        if etat["pret"]:
            break
        if time.monotonic() - debut >= ATTENTE_CARTE_MAX_S:
            raise MusiqueIndisponible(f"Carte occupée depuis {ATTENTE_CARTE_MAX_S // 60} min "
                                      f"({', '.join(etat['occupants'])}) — réessayer plus tard")
        if ctx.cancelled:
            return {"annule": True}
        await ctx.report(5, f"En attente d'une carte libre ({', '.join(etat['occupants'])})…")
        await asyncio.sleep(ATTENTE_CARTE_PAS_S)

    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0)) as c:
        try:
            nom = f"matotheque_{ctx.job_id}{source.suffix.lower() or '.png'}"
            r = await c.post(f"{url}/upload/image", data={"overwrite": "true"},
                             files={"image": (nom, source.read_bytes())})
            r.raise_for_status()
            image = r.json()["name"]

            r = await c.post(f"{url}/prompt", json={"prompt": graphe(
                image, prompt, largeur, hauteur, graine, f"video/matotheque_{ctx.job_id}")})
            if r.status_code >= 400:
                raise RuntimeError(f"ComfyUI a refusé le graphe : {r.text[:300]}")
            prompt_id = r.json()["prompt_id"]

            sortie = None
            while time.monotonic() - t0 < ATTENTE_RENDU_MAX_S:
                if ctx.cancelled:
                    await c.post(f"{url}/interrupt")
                    return {"annule": True}
                h = (await c.get(f"{url}/history/{prompt_id}")).json().get(prompt_id) or {}
                statut = h.get("status") or {}
                if statut.get("completed") or statut.get("status_str") == "error":
                    if statut.get("status_str") != "success":
                        raise RuntimeError(f"ComfyUI : rendu en erreur ({statut.get('messages', [])[-1:]})")
                    sortie = (h.get("outputs", {}).get("58", {}).get("images") or [None])[0]
                    break
                # ~270 s mesurés à vide : la barre avance sur cette base, sans jamais finir seule.
                await ctx.report(min(92, 10 + int(82 * (time.monotonic() - t0) / 300)), "Animation en cours…")
                await asyncio.sleep(SUIVI_S)
            if sortie is None:
                raise RuntimeError("ComfyUI n'a rien rendu dans le délai imparti")

            await ctx.report(96, "Récupération de la vidéo…")
            f = await c.get(f"{url}/view", params={"filename": sortie["filename"],
                                                    "subfolder": sortie.get("subfolder", "video"),
                                                    "type": sortie.get("type", "output")})
            f.raise_for_status()
            dossier_video().mkdir(parents=True, exist_ok=True)
            chemin_video(ctx.job_id).write_bytes(f.content)
        finally:
            try:
                await c.post(f"{url}/free", json={"unload_models": True, "free_memory": True})
            except Exception as e:  # noqa: BLE001
                log.warning("ComfyUI /free impossible", erreur=str(e) or type(e).__name__)

    rendu = round(time.monotonic() - t0)
    log.info("Vidéo générée", job_id=ctx.job_id, rendu_s=rendu)
    return {"fichier": f"{ctx.job_id}.mp4", "prompt": prompt, "graine": graine, "rendu_s": rendu,
            "largeur": largeur, "hauteur": hauteur}


async def transcrire_dictee(contenu: bytes, type_mime: str) -> str:
    """Dictée du scénario → texte, par le proxy Voxtral de PC-GAME (100 % local).

    ⚠️ Le proxy met en cache sur (nom, taille, modèle) : un nom UNIQUE par dictée, sinon deux
    dictées de même taille renverraient le même texte (session AIGUILLEUR).
    """
    url = proxy_url()
    if not url:
        raise RuntimeError("Dictée indisponible : proxy Voxtral non configuré")
    nom = f"dictee_{uuid.uuid4().hex}.webm"
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0)) as c:
        r = await c.post(f"{url}/v1/audio/transcriptions",
                         data={"model": "whisper-1", "language": "fr"},
                         files={"file": (nom, contenu, type_mime or "audio/webm")})
    if r.status_code >= 400:
        raise RuntimeError(f"Transcription refusée ({r.status_code})")
    try:
        return (r.json().get("text") or "").strip()
    except json.JSONDecodeError:
        return r.text.strip()
