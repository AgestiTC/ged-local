"""
Router Templates — /api/templates
===================================
Gestion des templates DOCX/PDF pour le remplissage automatique.

Endpoints :
  GET    /templates          → liste des templates
  POST   /templates          → uploader un nouveau template
  GET    /templates/{id}     → détail + champs détectés
  DELETE /templates/{id}     → supprimer
"""

import re
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from logger import get_logger
from models.template import Template

log = get_logger(__name__)
settings = get_settings()
router = APIRouter()

EXTENSIONS_TEMPLATES = {"docx", "pdf"}


def _detecter_champs_docx(chemin: Path) -> list[dict]:
    """
    Détecte les champs {{ champ }} dans un template DOCX.
    Retourne une liste de {nom, type, description}.
    """
    try:
        from docx import Document as DocxDocument
        doc = DocxDocument(str(chemin))
        texte_complet = "\n".join(p.text for p in doc.paragraphs)

        # Chercher les patterns {{ nom_champ }}
        champs = re.findall(r"\{\{\s*(\w+)\s*\}\}", texte_complet)
        # Dédupliquer en préservant l'ordre
        vus = set()
        champs_uniques = []
        for c in champs:
            if c not in vus:
                vus.add(c)
                champs_uniques.append({"nom": c, "type": "texte", "description": None})
        return champs_uniques
    except Exception as e:
        log.warning("Impossible de détecter les champs DOCX", erreur=str(e))
        return []


def _template_to_dict(t: Template, avec_champs: bool = False) -> dict:
    data = {
        "id": str(t.id),
        "nom": t.nom,
        "description": t.description,
        "type": t.type,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }
    if avec_champs:
        data["champs"] = t.champs or []
    return data


@router.get("/templates")
async def list_templates(db: AsyncSession = Depends(get_db)):
    """Liste tous les templates disponibles."""
    result = await db.execute(select(Template).order_by(Template.nom))
    templates = result.scalars().all()
    return {"templates": [_template_to_dict(t) for t in templates]}


@router.post("/templates", status_code=201)
async def upload_template(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload un template DOCX.
    Les champs {{ champ }} sont détectés automatiquement.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Nom de fichier manquant")

    ext = Path(file.filename).suffix.lstrip(".").lower()
    if ext not in EXTENSIONS_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"Extension non supportée : .{ext} (accepté : .docx, .pdf)")

    templates_dir = Path(settings.storage_templates)
    templates_dir.mkdir(parents=True, exist_ok=True)

    # Sauvegarder le fichier
    nom_safe = Path(file.filename).name
    chemin = templates_dir / nom_safe
    if chemin.exists():
        stem = Path(nom_safe).stem
        chemin = templates_dir / f"{stem}_{uuid.uuid4().hex[:6]}.{ext}"

    async with aiofiles.open(chemin, "wb") as f:
        while chunk := await file.read(65536):
            await f.write(chunk)

    # Détecter les champs (DOCX uniquement)
    champs = _detecter_champs_docx(chemin) if ext == "docx" else []

    nom_affichage = Path(file.filename).stem.replace("_", " ").replace("-", " ").title()

    template = Template(
        nom=nom_affichage,
        description=f"Template {ext.upper()} — {len(champs)} champ(s) détecté(s)",
        type=ext,
        chemin_fichier=str(chemin),
        champs=champs,
    )
    db.add(template)
    await db.flush()

    log.info("Template uploadé", nom=template.nom, nb_champs=len(champs))
    return {**_template_to_dict(template, avec_champs=True), "nb_champs": len(champs)}


@router.get("/templates/{template_id}")
async def get_template(template_id: str, db: AsyncSession = Depends(get_db)):
    """Retourne le détail d'un template et ses champs détectés."""
    try:
        uuid.UUID(template_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")

    result = await db.execute(select(Template).where(Template.id == uuid.UUID(template_id)))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template non trouvé")

    return _template_to_dict(template, avec_champs=True)


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, db: AsyncSession = Depends(get_db)):
    """Supprime un template (le fichier physique est aussi supprimé)."""
    try:
        uuid.UUID(template_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")

    result = await db.execute(select(Template).where(Template.id == uuid.UUID(template_id)))
    template = result.scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template non trouvé")

    nom = template.nom
    chemin = Path(template.chemin_fichier)

    await db.delete(template)
    await db.flush()

    # Supprimer le fichier physique
    if chemin.exists():
        chemin.unlink()

    log.info("Template supprimé", id=template_id, nom=nom)
    return {"message": f"Template '{nom}' supprimé", "id": template_id}
