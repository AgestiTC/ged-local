"""
Router Prompts — /api/prompts
==============================
CRUD sur les prompts pré-enregistrés.

Endpoints :
  GET    /prompts         → liste des prompts
  POST   /prompts         → créer un preset
  PUT    /prompts/{id}    → modifier
  DELETE /prompts/{id}    → supprimer
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.prompt import PromptPreset

log = get_logger(__name__)
router = APIRouter()


class PromptCreate(BaseModel):
    nom: str = Field(..., min_length=1, description="Nom du preset")
    description: str | None = Field(default=None)
    prompt_text: str = Field(..., min_length=1, description="Texte du prompt")
    categorie: str | None = Field(default=None, description="rapport | classement | extraction | analyse")
    modele_prefere: str | None = Field(default=None, description="Modèle Ollama recommandé")


class PromptUpdate(BaseModel):
    nom: str | None = None
    description: str | None = None
    prompt_text: str | None = None
    categorie: str | None = None
    modele_prefere: str | None = None


def _preset_to_dict(p: PromptPreset) -> dict:
    return {
        "id": str(p.id),
        "nom": p.nom,
        "description": p.description,
        "prompt_text": p.prompt_text,
        "categorie": p.categorie,
        "modele_prefere": p.modele_prefere,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.get("/prompts")
async def list_prompts(db: AsyncSession = Depends(get_db)):
    """Liste tous les prompts pré-enregistrés, triés par catégorie puis par nom."""
    result = await db.execute(
        select(PromptPreset).order_by(PromptPreset.categorie.nulls_last(), PromptPreset.nom)
    )
    presets = result.scalars().all()
    return {"prompts": [_preset_to_dict(p) for p in presets]}


@router.post("/prompts", status_code=201)
async def create_prompt(data: PromptCreate, db: AsyncSession = Depends(get_db)):
    """Crée un nouveau prompt pré-enregistré."""
    preset = PromptPreset(
        nom=data.nom,
        description=data.description,
        prompt_text=data.prompt_text,
        categorie=data.categorie,
        modele_prefere=data.modele_prefere,
    )
    db.add(preset)
    await db.flush()
    log.info("Prompt créé", id=str(preset.id), nom=preset.nom)
    return _preset_to_dict(preset)


@router.put("/prompts/{prompt_id}")
async def update_prompt(
    prompt_id: str,
    data: PromptUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Modifie un prompt existant."""
    try:
        uuid.UUID(prompt_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")

    result = await db.execute(select(PromptPreset).where(PromptPreset.id == uuid.UUID(prompt_id)))
    preset = result.scalar_one_or_none()
    if not preset:
        raise HTTPException(status_code=404, detail="Prompt non trouvé")

    if data.nom is not None:
        preset.nom = data.nom
    if data.description is not None:
        preset.description = data.description
    if data.prompt_text is not None:
        preset.prompt_text = data.prompt_text
    if data.categorie is not None:
        preset.categorie = data.categorie
    if data.modele_prefere is not None:
        preset.modele_prefere = data.modele_prefere

    await db.flush()
    return _preset_to_dict(preset)


@router.delete("/prompts/{prompt_id}")
async def delete_prompt(prompt_id: str, db: AsyncSession = Depends(get_db)):
    """Supprime un prompt pré-enregistré."""
    try:
        uuid.UUID(prompt_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")

    result = await db.execute(select(PromptPreset).where(PromptPreset.id == uuid.UUID(prompt_id)))
    preset = result.scalar_one_or_none()
    if not preset:
        raise HTTPException(status_code=404, detail="Prompt non trouvé")

    nom = preset.nom
    await db.delete(preset)
    await db.flush()
    log.info("Prompt supprimé", id=prompt_id, nom=nom)
    return {"message": f"Prompt '{nom}' supprimé", "id": prompt_id}
