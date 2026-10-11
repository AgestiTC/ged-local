"""
Router Templates — /api/templates
===================================
Gestion des templates DOCX/PDF pour le remplissage automatique.

Endpoints :
  GET    /templates          → liste des templates
  POST   /templates          → uploader un nouveau template
  GET    /templates/{id}     → détail + champs détectés
  GET    /templates/{id}/fichier → le fichier enregistré (téléchargement)
  GET    /templates/{id}/apercu  → ce que le Tableau comparatif reconnaît dans un classeur
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

EXTENSIONS_TEMPLATES = {"docx", "pdf", "xlsx"}


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


def _detecter_champs_xlsx(chemin: Path) -> list[dict]:
    """
    Détecte les champs d'un template XLSX : en-têtes de la première ligne
    + cellules contenant {{ champ }}.
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(chemin), read_only=True, data_only=True)
        ws = wb.active
        champs: list[dict] = []
        vus: set[str] = set()

        # En-têtes ligne 1
        first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
        for cell in first_row:
            if cell and isinstance(cell, str) and cell.strip():
                nom = cell.strip()
                if nom not in vus:
                    vus.add(nom)
                    champs.append({"nom": nom, "type": "texte", "description": None})

        # Patterns {{ champ }} dans tout le classeur
        for row in ws.iter_rows(min_row=2, values_only=True):
            for cell in row:
                if cell and isinstance(cell, str):
                    for match in re.findall(r"\{\{\s*(\w+)\s*\}\}", cell):
                        if match not in vus:
                            vus.add(match)
                            champs.append({"nom": match, "type": "texte", "description": None})
        wb.close()
        return champs
    except Exception as e:
        log.warning("Impossible de détecter les champs XLSX", erreur=str(e))
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
        raise HTTPException(status_code=400, detail=f"Extension non supportée : .{ext} (accepté : .docx, .xlsx, .pdf)")

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

    # Détecter les champs selon le type
    if ext == "docx":
        champs = _detecter_champs_docx(chemin)
    elif ext == "xlsx":
        champs = _detecter_champs_xlsx(chemin)
    else:
        champs = []

    description = f"Template {ext.upper()} — {len(champs)} champ(s) détecté(s)"
    if ext == "xlsx":
        # Grille d'analyse des offres (critères en lignes) : ce sont ses critères qu'on annonce,
        # pas le titre de la ligne 1. À utiliser en mode « Tableau comparatif ».
        from services.grille_analyse import apercu_classeur
        apercu = apercu_classeur(chemin)
        if apercu["type"] in ("grille", "liste"):
            champs = [{"nom": c["nom"], "type": "critere", "description": c["documents"]}
                      for c in apercu["criteres"]]
            description = (f"Grille d'analyse — {len(champs)} critère(s), "
                           f"{apercu['nb_candidats']} candidat(s) · mode Tableau comparatif"
                           if apercu["type"] == "grille" else
                           f"Grille d'analyse — liste de {len(champs)} critère(s) · mode Tableau comparatif")

    nom_affichage = Path(file.filename).stem.replace("_", " ").replace("-", " ").title()

    template = Template(
        nom=nom_affichage,
        description=description,
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


async def _template_ou_404(template_id: str, db: AsyncSession) -> Template:
    try:
        template_uuid = uuid.UUID(template_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")
    template = (await db.execute(select(Template).where(Template.id == template_uuid))).scalar_one_or_none()
    if not template:
        raise HTTPException(status_code=404, detail="Template non trouvé")
    if not Path(template.chemin_fichier).is_file():
        raise HTTPException(status_code=404, detail="Fichier du template introuvable sur le disque")
    return template


@router.get("/templates/{template_id}/fichier")
async def telecharger_template(template_id: str, db: AsyncSession = Depends(get_db)):
    """Le fichier du modèle tel qu'il est enregistré dans Matothèque (à ouvrir dans Excel / Word)."""
    template = await _template_ou_404(template_id, db)
    chemin = Path(template.chemin_fichier)
    media = {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
    }.get(template.type, "application/octet-stream")
    from routers.export import _fichier_reponse
    return _fichier_reponse(chemin.read_bytes(), chemin.name, media)


@router.get("/templates/{template_id}/apercu")
async def apercu_template(template_id: str, db: AsyncSession = Depends(get_db)):
    """
    Ce que le Tableau comparatif reconnaît dans un modèle Excel (grille, liste de critères,
    colonnes) — recalculé à chaque appel : un modèle déposé avant une amélioration de la
    reconnaissance en profite sans être redéposé.
    """
    template = await _template_ou_404(template_id, db)
    if template.type != "xlsx":
        return {"type": "inconnu", "criteres": [], "nb_candidats": None,
                "message": "Aperçu disponible pour les classeurs Excel uniquement."}
    from services.grille_analyse import apercu_classeur
    return apercu_classeur(Path(template.chemin_fichier))


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
