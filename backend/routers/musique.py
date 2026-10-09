"""
Router Musique — /api/musique
=============================
  GET  /musique/etat                → ComfyUI joignable ? mémoire libre sur la carte ?
  POST /musique                     → met en file une tâche durable `musique`
  GET  /musique/{job_id}/fichier    → le morceau (MP3) produit par la tâche
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.job import Job
from services import job_worker
from services.musique_jobs import DUREE_MAX_S, DUREE_MIN_S, chemin_morceau, etat_comfyui, preparer_style

router = APIRouter()


class MusiqueIn(BaseModel):
    style: str = Field(default="", max_length=1000, description="genre, instruments, ambiance, voix…")
    paroles: str = Field(default="", max_length=8000, description="avec [Verse] / [Chorus], ou vide")
    duree: int = Field(default=60, ge=DUREE_MIN_S, le=DUREE_MAX_S, description="secondes")
    langue: str = Field(default="fr", max_length=5)
    bpm: int = Field(default=110, ge=10, le=300)
    graine: int | None = Field(default=None, ge=0, description="vide = au hasard")
    keyscale: str = Field(default="C major", max_length=20, description="« C major », « A minor »…")
    # « Lancer quand même » : pour CE morceau seulement, ignorer le seuil de mémoire libre.
    forcer: bool = False


class PreparerIn(BaseModel):
    style: str = Field(default="", max_length=1000)
    paroles: str = Field(default="", max_length=8000)
    langue: str = Field(default="fr", max_length=5)


@router.post("/musique/preparer")
async def preparer(body: PreparerIn) -> dict:
    """Style libre → mots-clés ACE-Step, tempo, tonalité, paroles balisées (IA locale)."""
    if not body.style.strip() and not body.paroles.strip():
        raise HTTPException(status_code=422, detail="Décris un style ou écris des paroles")
    try:
        return await preparer_style(body.style, body.paroles, body.langue)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/musique/etat")
async def etat(db: AsyncSession = Depends(get_db)) -> dict:
    """État de ComfyUI, plus le nombre de tâches de Matothèque qui occupent la carte en ce moment :
    quand la carte est pleine, c'est souvent Matothèque elle-même (IA, embeddings) — autant le dire."""
    from sqlalchemy import func, select

    e = await etat_comfyui()
    e["taches_matotheque"] = int((await db.execute(
        select(func.count()).select_from(Job).where(
            Job.statut == "running", Job.type.in_(sorted(job_worker.GPU_TYPES - {"musique"})))
    )).scalar() or 0)
    return e


@router.post("/musique")
async def creer(body: MusiqueIn, db: AsyncSession = Depends(get_db)) -> dict:
    if not body.style.strip() and not body.paroles.strip():
        raise HTTPException(status_code=422, detail="Décris un style ou écris des paroles")
    job_id = await job_worker.enqueue(db, "musique", {**body.model_dump(), "cible": (body.style or "musique")[:60]})
    await db.commit()
    return {"job_id": job_id}


@router.get("/musique/{job_id}/fichier")
async def fichier(job_id: str, db: AsyncSession = Depends(get_db)):
    try:
        job = await db.get(Job, uuid.UUID(job_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Identifiant invalide")
    if not job or job.type != "musique" or job.statut != "completed":
        raise HTTPException(status_code=404, detail="Morceau introuvable ou pas encore prêt")
    chemin = chemin_morceau(job_id)
    if not chemin.exists():
        raise HTTPException(status_code=404, detail="Fichier du morceau absent")
    return FileResponse(chemin, media_type="audio/mpeg", filename=f"matotheque-{job_id[:8]}.mp3")
