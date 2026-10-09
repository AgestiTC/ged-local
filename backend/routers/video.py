"""
Router Vidéo — /api/video (« Créer une vidéo ! » : animer un dessin scanné)
===========================================================================
  GET  /video/etat               → ComfyUI joignable ? carte libre (qui l'occupe) ? dictée possible ?
  POST /video                    → dessin (JPG/PNG) + scénario → tâche durable `video`
  POST /video/dictee             → audio dicté (webm) → texte, par le proxy Voxtral (100 % local)
  GET  /video/{job_id}/fichier   → la vidéo MP4 produite
"""
import io
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.job import Job
from services import job_worker
from services.video_jobs import chemin_video, dossier_video, etat_carte, transcrire_dictee

router = APIRouter()

IMAGE_MAX_OCTETS = 25 * 1024 * 1024
AUDIO_MAX_OCTETS = 25 * 1024 * 1024
EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


@router.get("/video/etat")
async def etat() -> dict:
    return await etat_carte()


@router.post("/video")
async def creer(image: UploadFile = File(...), scenario: str = Form(default="", max_length=4000),
                prompt: str = Form(default="", max_length=2000), db: AsyncSession = Depends(get_db)) -> dict:
    if not scenario.strip() and not prompt.strip():
        raise HTTPException(status_code=422, detail="Décris ce qui doit bouger (scénario)")
    ext = EXTENSIONS.get((image.content_type or "").lower())
    if not ext:
        raise HTTPException(status_code=415, detail="Dessin attendu en JPG, PNG ou WebP")
    contenu = await image.read()
    if len(contenu) > IMAGE_MAX_OCTETS:
        raise HTTPException(status_code=413, detail="Image trop lourde (25 Mo au plus)")
    try:
        from PIL import Image
        largeur, hauteur = Image.open(io.BytesIO(contenu)).size
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=422, detail="Image illisible")
    dossier_video().mkdir(parents=True, exist_ok=True)
    source = dossier_video() / f"src_{uuid.uuid4().hex}{ext}"
    source.write_bytes(contenu)
    job_id = await job_worker.enqueue(db, "video", {
        "image": str(source), "largeur": largeur, "hauteur": hauteur,
        "scenario": scenario.strip(), "prompt": prompt.strip(), "cible": (scenario or "vidéo")[:60]})
    await db.commit()
    return {"job_id": job_id, "orientation": "portrait" if hauteur > largeur else "paysage"}


@router.post("/video/dictee")
async def dictee(audio: UploadFile = File(...)) -> dict:
    contenu = await audio.read()
    if not contenu:
        raise HTTPException(status_code=422, detail="Enregistrement vide")
    if len(contenu) > AUDIO_MAX_OCTETS:
        raise HTTPException(status_code=413, detail="Dictée trop longue")
    try:
        return {"texte": await transcrire_dictee(contenu, audio.content_type or "audio/webm")}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/video/{job_id}/fichier")
async def fichier(job_id: str, db: AsyncSession = Depends(get_db)):
    try:
        job = await db.get(Job, uuid.UUID(job_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Identifiant invalide")
    if not job or job.type != "video" or job.statut != "completed":
        raise HTTPException(status_code=404, detail="Vidéo introuvable ou pas encore prête")
    chemin = chemin_video(job_id)
    if not chemin.exists():
        raise HTTPException(status_code=404, detail="Fichier de la vidéo absent")
    return FileResponse(chemin, media_type="video/mp4", filename=f"matotheque-{job_id[:8]}.mp4")
