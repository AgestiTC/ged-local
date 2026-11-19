"""
Router Consignes — /api/consignes (consignes de base versionnées, 11/10/2026)
=============================================================================
  GET  /consignes/{cle}         → texte d'origine, texte actif, version active + historique (récent d'abord)
  POST /consignes/{cle}         → NOUVELLE version : {texte | null (= origine), commentaire}
  POST /consignes/{cle}/rendu   → prompt final (consigne active ou fournie + critères + instructions)

Les textes d'origine sont dans le registre des prompts (`services/prompts.py`, clés
`reference.analyse` / `reference.corrigee`) ; le rendu et le garde-fou dans
`services/consignes_reference.py` (étape A6 : plus aucun texte de prompt dans le frontend).

Garde-fous côté serveur (l'interface en affiche un aperçu) :
  - seules les clés connues sont acceptées ;
  - un texte trop court, trop long ou sans structure (moins de 3 sections « ## ») est refusé ;
  - rien n'est jamais écrasé ni supprimé : restaurer = créer une version de plus ;
  - `texte` null = revenir à la consigne d'origine (celle du code), toujours possible.

Accès (services/acces.py) : lecture et rendu = utilisateur (page Créer) ; enregistrement = admin.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.consigne import ConsigneVersion
from services import consignes_reference, prompts

log = get_logger(__name__)
router = APIRouter()

CLES = set(consignes_reference.CLES)
MIN_CHARS, MAX_CHARS = consignes_reference.MIN_CHARS, consignes_reference.MAX_CHARS


class NouvelleVersion(BaseModel):
    texte: str | None = Field(default=None, description="null = revenir à la consigne d'origine")
    commentaire: str | None = Field(default=None, max_length=300)


class DemandeRendu(BaseModel):
    criteres: list[str] = Field(default_factory=list, max_length=200,
                                description="Critères de notation (déjà nettoyés par l'appelant)")
    corps: str | None = Field(default=None, max_length=MAX_CHARS,
                              description="Consigne de base à utiliser ; null = la version active")
    instructions: str = Field(default="", max_length=20_000,
                              description="Instructions complémentaires de l'acheteur (vide = aucune)")


def _cle_valide(cle: str) -> str:
    if cle not in CLES:
        raise HTTPException(status_code=404, detail=f"Consigne inconnue : {cle}")
    return cle


def _to_dict(v: ConsigneVersion) -> dict:
    return {"version": v.version, "texte": v.texte, "origine": v.texte is None, "commentaire": v.commentaire,
            "created_at": v.created_at.isoformat() if v.created_at else None}


async def _active(db: AsyncSession, cle: str) -> ConsigneVersion | None:
    return (await db.execute(select(ConsigneVersion).where(ConsigneVersion.cle == cle)
                             .order_by(ConsigneVersion.version.desc()).limit(1))).scalars().first()


@router.get("/consignes/{cle}")
async def lire(cle: str, db: AsyncSession = Depends(get_db)):
    _cle_valide(cle)
    versions = (await db.execute(select(ConsigneVersion).where(ConsigneVersion.cle == cle)
                                 .order_by(ConsigneVersion.version.desc()))).scalars().all()
    active = versions[0] if versions else None
    origine = consignes_reference.origine(cle)
    return {"cle": cle, "active": _to_dict(active) if active else None,
            "versions": [_to_dict(v) for v in versions],
            "origine_texte": origine,
            "texte_actif": active.texte if active is not None and active.texte is not None else origine,
            "min_caracteres": MIN_CHARS, "max_caracteres": MAX_CHARS,
            "min_sections": consignes_reference.MIN_SECTIONS,
            "garde_fous": [g.libelle for g in prompts.garde_fous_presents(origine)]}


@router.post("/consignes/{cle}", status_code=201)
async def enregistrer(cle: str, body: NouvelleVersion, db: AsyncSession = Depends(get_db)):
    _cle_valide(cle)
    texte = body.texte.strip() if body.texte is not None else None
    if texte is not None:
        problemes = consignes_reference.verifier(texte, cle)
        if problemes:
            raise HTTPException(
                status_code=400,
                detail="Consigne refusée : " + " ".join(problemes)
                       + " Pour repartir de zéro, rétablissez la consigne d'origine.")
    derniere = (await db.execute(select(func.max(ConsigneVersion.version))
                                 .where(ConsigneVersion.cle == cle))).scalar() or 0
    v = ConsigneVersion(cle=cle, version=derniere + 1, texte=texte,
                        commentaire=(body.commentaire or "").strip() or None)
    db.add(v)
    await db.commit()
    log.info("Consigne de base : nouvelle version", cle=cle, version=v.version, origine=texte is None)
    return _to_dict(v)


@router.post("/consignes/{cle}/rendu")
async def rendu(cle: str, body: DemandeRendu, db: AsyncSession = Depends(get_db)):
    """
    Prompt final envoyé au rapport : la consigne de base (`corps` fourni, sinon la version active,
    sinon l'origine du code) + les critères de notation + les instructions complémentaires.
    Rien n'est enregistré.
    """
    _cle_valide(cle)
    version = 0
    if body.corps is not None:
        corps = body.corps
    else:
        active = await _active(db, cle)
        version = active.version if active is not None else 0
        corps = active.texte if active is not None and active.texte is not None else consignes_reference.origine(cle)
    texte = consignes_reference.rendre(cle, corps, body.criteres, body.instructions)
    return {"cle": cle, "texte": texte, "version": version, "corps_fourni": body.corps is not None}
