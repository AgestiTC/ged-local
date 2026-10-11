"""
Router Consignes — /api/consignes (consignes de base versionnées, 11/10/2026)
=============================================================================
  GET  /consignes/{cle}  → version active + historique (le plus récent d'abord)
  POST /consignes/{cle}  → NOUVELLE version : {texte | null (= origine), commentaire}

Garde-fous côté serveur (l'interface en ajoute) :
  - seules les clés connues sont acceptées ;
  - un texte vide ou trop court est refusé (une consigne tronquée par erreur ne passe pas) ;
  - rien n'est jamais écrasé ni supprimé : restaurer = créer une version de plus ;
  - `texte` null = revenir à la consigne d'origine (celle du code), toujours possible.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.consigne import ConsigneVersion

log = get_logger(__name__)
router = APIRouter()

CLES = {"reference_analyse", "reference_corrigee"}
MIN_CHARS, MAX_CHARS = 200, 20_000


class NouvelleVersion(BaseModel):
    texte: str | None = Field(default=None, description="null = revenir à la consigne d'origine")
    commentaire: str | None = Field(default=None, max_length=300)


def _cle_valide(cle: str) -> str:
    if cle not in CLES:
        raise HTTPException(status_code=404, detail=f"Consigne inconnue : {cle}")
    return cle


def _to_dict(v: ConsigneVersion) -> dict:
    return {"version": v.version, "texte": v.texte, "origine": v.texte is None, "commentaire": v.commentaire,
            "created_at": v.created_at.isoformat() if v.created_at else None}


@router.get("/consignes/{cle}")
async def lire(cle: str, db: AsyncSession = Depends(get_db)):
    _cle_valide(cle)
    versions = (await db.execute(select(ConsigneVersion).where(ConsigneVersion.cle == cle)
                                 .order_by(ConsigneVersion.version.desc()))).scalars().all()
    return {"cle": cle, "active": _to_dict(versions[0]) if versions else None,
            "versions": [_to_dict(v) for v in versions]}


@router.post("/consignes/{cle}", status_code=201)
async def enregistrer(cle: str, body: NouvelleVersion, db: AsyncSession = Depends(get_db)):
    _cle_valide(cle)
    texte = body.texte.strip() if body.texte is not None else None
    if texte is not None and not (MIN_CHARS <= len(texte) <= MAX_CHARS):
        raise HTTPException(
            status_code=400,
            detail=f"Consigne refusée : {len(texte)} caractères (attendu entre {MIN_CHARS} et {MAX_CHARS}). "
                   "Pour repartir de zéro, rétablissez la consigne d'origine.")
    derniere = (await db.execute(select(func.max(ConsigneVersion.version))
                                 .where(ConsigneVersion.cle == cle))).scalar() or 0
    v = ConsigneVersion(cle=cle, version=derniere + 1, texte=texte,
                        commentaire=(body.commentaire or "").strip() or None)
    db.add(v)
    await db.commit()
    log.info("Consigne de base : nouvelle version", cle=cle, version=v.version, origine=texte is None)
    return _to_dict(v)
