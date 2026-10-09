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
import json
import random
import re
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
# Carte occupée : on ATTEND qu'elle se libère (JARVIS d'abord) au lieu de refuser d'emblée.
ATTENTE_CARTE_MAX_S = 1800
ATTENTE_CARTE_PAS_S = 60.0
CARTE_GO = 16.0               # RTX 4080 SUPER de PC-GAME
BUREAU_GO = 2.0               # affichage Windows et autres : jamais disponible pour un modèle
TONALITE = re.compile(r"^[A-G](#|b)? (major|minor)$")


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


def graphe(style: str, paroles: str, duree: int, langue: str, bpm: int, graine: int, prefixe: str,
           tonalite: str = "C major") -> dict:
    """Graphe d'API ComfyUI d'ACE-Step 1.5 turbo (fourni par la session AIGUILLEUR, testé le 09/10).

    La durée va à DEUX endroits (94.duration, 98.seconds), la graine aussi (94.seed, 3.seed).
    """
    return {
        "97": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "ace_step_1.5_turbo_aio.safetensors"}},
        "94": {"class_type": "TextEncodeAceStepAudio1.5", "inputs": {
            "clip": ["97", 1], "tags": style, "lyrics": paroles, "seed": graine, "bpm": bpm,
            "duration": duree, "timesignature": "4", "language": langue, "keyscale": tonalite,
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


async def _modeles_charges() -> list[dict] | None:
    """Modèles d'Ollama en mémoire (`/api/ps`, par la passerelle) : [{nom, go}], None si muet."""
    from services.ollama_service import entetes_projet
    url = (runtime_config.effective("ollama_url") or "").rstrip("/")
    if not url:
        return None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0), headers=entetes_projet()) as c:
            r = await c.get(f"{url}/api/ps")
        r.raise_for_status()
        return [{"nom": m.get("name"), "go": round((m.get("size_vram") or 0) / 2**30, 1)}
                for m in r.json().get("models") or []]
    except Exception as e:  # noqa: BLE001
        log.info("Liste des modèles chargés indisponible", erreur=str(e) or type(e).__name__)
        return None


async def etat_comfyui() -> dict:
    """
    {configure, joignable, vram_libre_go, seuil_go, pret, modeles} — sans rien lancer.

    ⚠️ La mémoire libre ne vient PAS de ComfyUI : sous Windows, son `/system_stats` ne voit pas la
    mémoire prise par les autres processus (14,6 Gio annoncés libres avec 12,1 occupés — mesure
    de la session AIGUILLEUR, 09/10/2026). On la déduit des modèles qu'Ollama a chargés.
    """
    url = comfyui_url()
    etat = {"configure": bool(url), "joignable": False, "vram_libre_go": None,
            "vram_totale_go": CARTE_GO, "seuil_go": seuil_vram_go(), "pret": False, "modeles": []}
    if not url:
        return etat
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as c:
            (await c.get(f"{url}/system_stats")).raise_for_status()
        etat["joignable"] = True
    except Exception as e:  # noqa: BLE001 — éteint, réseau, réponse inattendue : « injoignable »
        log.info("ComfyUI injoignable", url=url, erreur=str(e) or type(e).__name__)
        return etat
    modeles = await _modeles_charges()
    if modeles is None:            # passerelle muette : on ne sait pas — on ne bloque pas pour autant
        etat["pret"] = True
        return etat
    etat["modeles"] = modeles
    etat["vram_libre_go"] = round(max(0.0, CARTE_GO - BUREAU_GO - sum(m["go"] for m in modeles)), 1)
    etat["pret"] = etat["vram_libre_go"] >= etat["seuil_go"]
    return etat


SYSTEME_STYLE = (
    "Tu prépares une demande pour ACE-Step, un modèle qui compose de la musique. Il ne connaît "
    "AUCUN nom d'artiste : il comprend seulement des mots-clés descriptifs en ANGLAIS, séparés "
    "par des virgules (genre, sous-genre, instruments précis, type et timbre de voix, ambiance, "
    "production). Si on te cite un artiste, décris son style sans le nommer. Réponds UNIQUEMENT "
    'par un objet JSON : {"tags": "...", "bpm": entier, "keyscale": "C major" ou "A minor" '
    '(forme note + major/minor), "paroles": "..."}. Pour "paroles" : reprends le texte fourni MOT '
    "POUR MOT, en ajoutant seulement des balises de structure [Verse], [Chorus], [Bridge], [Outro] "
    "sur des lignes à part ; si aucune parole n'est fournie, renvoie une chaîne vide.")


def _mots(t: str) -> list[str]:
    return re.findall(r"\w+", re.sub(r"\[[^\]]*\]", " ", t).lower())


async def preparer_style(style: str, paroles: str, langue: str) -> dict:
    """
    Traduit une demande libre (« à la façon de Grand Corps Malade ») en ce qu'ACE-Step comprend :
    des mots-clés DESCRIPTIFS en anglais — il ne connaît pas les artistes —, un tempo et une
    tonalité ; et pose [Verse] / [Chorus] sur des paroles qui n'en ont pas. Par l'IA locale
    (usage « chat »). Renvoie {tags, bpm, keyscale, paroles}.
    """
    from services.extraction import _extraire_json
    from services.ollama_service import OllamaService

    demande = f"Style demandé : {style or '(aucun)'}\nLangue du chant : {langue}\nParoles :\n{paroles or '(aucune)'}"
    brut = await OllamaService().generate(demande, model=runtime_config.model_for("chat"),
                                          system=SYSTEME_STYLE, format="json", num_predict=1500)
    try:
        d = _extraire_json(brut)
    except (json.JSONDecodeError, ValueError):
        raise RuntimeError("L'IA n'a pas rendu de réponse exploitable — réessaie")
    tags = str(d.get("tags") or "").strip()[:1000]
    if not tags:
        raise RuntimeError("L'IA n'a proposé aucun mot-clé — réessaie")
    try:
        bpm = max(10, min(300, int(d.get("bpm") or 110)))
    except (TypeError, ValueError):
        bpm = 110
    tonalite = str(d.get("keyscale") or "").strip()
    texte = str(d.get("paroles") or "").strip()
    # L'IA ne doit qu'AJOUTER des balises : si elle a réécrit le texte, on garde l'original.
    if paroles.strip() and _mots(texte) != _mots(paroles):
        texte = paroles.strip()
    return {"tags": tags, "bpm": bpm, "keyscale": tonalite if TONALITE.match(tonalite) else "C major",
            "paroles": texte}


def borner(params: dict) -> dict:
    """Paramètres de la tâche, bornés et complétés (graine tirée si absente)."""
    duree = max(DUREE_MIN_S, min(DUREE_MAX_S, int(params.get("duree") or 60)))
    bpm = max(10, min(300, int(params.get("bpm") or 110)))
    graine = params.get("graine")
    tonalite = str(params.get("keyscale") or "").strip()
    return {
        "keyscale": tonalite if TONALITE.match(tonalite) else "C major",
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
    # Carte occupée : on ATTEND (JARVIS passe avant, son modèle se décharge vite) plutôt que de
    # refuser — sauf dépassement autorisé par l'utilisateur pour ce morceau.
    debut_attente = time.monotonic()
    while not etat["pret"] and not ctx.parametres.get("forcer"):
        if time.monotonic() - debut_attente >= ATTENTE_CARTE_MAX_S:
            raise MusiqueIndisponible(
                f"Carte occupée depuis {ATTENTE_CARTE_MAX_S // 60} min ({etat['vram_libre_go']} Gio libres, "
                f"{etat['seuil_go']} requis) — réessayer plus tard")
        if ctx.cancelled:
            return {"annule": True}
        occupants = ", ".join(m["nom"] for m in etat.get("modeles") or []) or "d'autres programmes"
        await ctx.report(5, f"En attente que la carte se libère ({occupants})…")
        await asyncio.sleep(ATTENTE_CARTE_PAS_S)
        etat = await etat_comfyui()
        if not etat["joignable"]:
            raise MusiqueIndisponible("ComfyUI injoignable — PC-GAME éteint ou ComfyUI arrêté")

    if not etat["pret"]:
        # Dépassement autorisé par l'utilisateur, pour ce morceau : ComfyUI débordera en mémoire
        # partagée (plus lent), sans décharger les modèles des autres.
        log.warning("Musique lancée sous le seuil de mémoire (dépassement autorisé)",
                    vram_libre_go=etat["vram_libre_go"], seuil_go=etat["seuil_go"])
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0)) as c:
        try:
            r = await c.post(f"{url}/prompt", json={"prompt": graphe(
                p["style"], p["paroles"], p["duree"], p["langue"], p["bpm"], p["graine"],
                f"audio/matotheque_{ctx.job_id}", p["keyscale"])})
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
