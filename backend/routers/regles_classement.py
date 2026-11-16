"""
Router Règles de classement — /api/regles-classement (ADMIN, cf. services/acces.py)
===================================================================================
Plan « Recevoir la documentation des autres applications », étape 1.

  GET    /regles-classement          → liste
  POST   /regles-classement          → créer
  PUT    /regles-classement/{id}     → modifier
  DELETE /regles-classement/{id}     → supprimer (les documents déjà classés gardent leur fiche)

Une règle ne s'applique qu'aux imports et versions À VENIR (et aux ré-enrichissements) : elle ne
reclasse pas rétroactivement l'existant.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.regle_classement import CLASSEMENTS, RegleClassement

log = get_logger(__name__)
router = APIRouter()


class RegleIn(BaseModel):
    libelle: str = Field(min_length=1, max_length=200)
    prefixe_chemin: str = Field(min_length=3, max_length=1000,
                                description="Début de chemin, ex. smb://192.168.42.200/Partage-Nas-Mato/[GED]/Docs-applications/")
    categorie: str | None = Field(default=None, max_length=200)
    sous_categorie: str | None = Field(default=None, max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=30)
    tag_depuis_sous_dossier: bool = True
    classement: str = "fixe"
    actif: bool = True

    @field_validator("classement")
    @classmethod
    def _classement(cls, v: str) -> str:
        if v not in CLASSEMENTS:
            raise ValueError(f"classement attendu : {' | '.join(CLASSEMENTS)}")
        return v

    @field_validator("prefixe_chemin")
    @classmethod
    def _prefixe(cls, v: str) -> str:
        v = v.strip()
        # Préfixe de DOSSIER : toujours terminé par « / », sinon « …/Docs » couvrirait « …/Docs-perso ».
        return v if v.endswith("/") else v + "/"

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        propres = []
        for t in v:
            t = str(t).strip()[:100]
            if t and t not in propres:
                propres.append(t)
        return propres


def _dict(r: RegleClassement) -> dict:
    return {
        "id": str(r.id),
        "libelle": r.libelle,
        "prefixe_chemin": r.prefixe_chemin,
        "categorie": r.categorie,
        "sous_categorie": r.sous_categorie,
        "tags": r.tags or [],
        "tag_depuis_sous_dossier": r.tag_depuis_sous_dossier,
        "classement": r.classement,
        "actif": r.actif,
    }


async def _charger(db: AsyncSession, regle_id: str) -> RegleClassement:
    try:
        rid = uuid.UUID(regle_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Identifiant de règle invalide")
    regle = (await db.execute(select(RegleClassement).where(RegleClassement.id == rid))).scalar_one_or_none()
    if regle is None:
        raise HTTPException(status_code=404, detail="Règle introuvable")
    return regle


@router.get("/regles-classement")
async def lister(db: AsyncSession = Depends(get_db)) -> dict:
    regles = (await db.execute(select(RegleClassement).order_by(RegleClassement.prefixe_chemin))).scalars().all()
    return {"regles": [_dict(r) for r in regles]}


@router.post("/regles-classement")
async def creer(body: RegleIn, db: AsyncSession = Depends(get_db)) -> dict:
    regle = RegleClassement(**body.model_dump())
    db.add(regle)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Une règle existe déjà pour ce préfixe")
    log.info("Règle de classement créée", libelle=regle.libelle, prefixe=regle.prefixe_chemin)
    return _dict(regle)


@router.put("/regles-classement/{regle_id}")
async def modifier(regle_id: str, body: RegleIn, db: AsyncSession = Depends(get_db)) -> dict:
    regle = await _charger(db, regle_id)
    for cle, valeur in body.model_dump().items():
        setattr(regle, cle, valeur)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Une règle existe déjà pour ce préfixe")
    return _dict(regle)


@router.delete("/regles-classement/{regle_id}")
async def supprimer(regle_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    regle = await _charger(db, regle_id)
    await db.delete(regle)
    await db.commit()
    log.info("Règle de classement supprimée", libelle=regle.libelle)
    return {"ok": True}
