"""
Router Dossiers thématiques — /api/dossiers
===========================================
Veille documentaire par sujet : un **dossier** regroupe des **ressources externes**
(podcasts, chaînes, documentaires, livres, articles, études, associations) décrites
par leur URL, leur type et une note expliquant ce qu'elles apportent.

Un dossier peut être créé à vide, ou installé depuis un **seed** livré avec
l'application (`POST /dossiers/seed/{cle}`, idempotent — voir `services/dossier_seed`).

Le dossier est adressable par UUID **ou par slug** : `/dossiers/devenir-parent`
fonctionne comme `/dossiers/<uuid>`, ce qui rend les URLs du front lisibles.
"""

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.dossier import DossierThematique, Ressource
from services.dossier_seed import SEEDS, installer_seed

log = get_logger(__name__)
router = APIRouter()

# Liste de référence des types — sert au front (filtres, icônes) et documente le modèle.
# Volontairement sans contrainte CHECK en base : ajouter un type ne demande pas de migration.
TYPES_RESSOURCE = [
    "podcast", "chaine", "video", "documentaire", "emission", "film", "serie",
    "livre", "bd", "article", "etude", "rapport", "association", "prompt",
]


class DossierIn(BaseModel):
    titre: str = Field(min_length=1)
    slug: str | None = None          # dérivé du titre si absent
    description: str | None = None


class DossierPatch(BaseModel):
    titre: str | None = Field(default=None, min_length=1)
    description: str | None = None


class RessourceIn(BaseModel):
    titre: str = Field(min_length=1)
    auteur: str | None = None
    type: str = "article"
    url: str | None = None
    langue: str = "fr"
    groupe: str | None = None
    note: str | None = None
    tags: list[str] = Field(default_factory=list)
    favori: bool = False
    active: bool = True


class RessourcePatch(BaseModel):
    titre: str | None = Field(default=None, min_length=1)
    auteur: str | None = None
    type: str | None = None
    url: str | None = None
    langue: str | None = None
    groupe: str | None = None
    note: str | None = None
    tags: list[str] | None = None
    favori: bool | None = None
    active: bool | None = None
    position: int | None = None


def _slugifier(titre: str) -> str:
    """Slug ASCII-safe à partir d'un titre (accents retirés, espaces → tirets)."""
    import unicodedata
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", titre) if unicodedata.category(c) != "Mn"
    )
    slug = re.sub(r"[^a-z0-9]+", "-", sans_accents.lower()).strip("-")
    return slug or "dossier"


def _resume_dossier(d: DossierThematique, nb: int = 0) -> dict:
    return {
        "id": str(d.id), "titre": d.titre, "slug": d.slug,
        "description": d.description, "origine": d.origine,
        "nb_ressources": nb,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _serialiser_ressource(r: Ressource) -> dict:
    return {
        "id": str(r.id), "dossier_id": str(r.dossier_id),
        "titre": r.titre, "auteur": r.auteur, "type": r.type, "url": r.url,
        "langue": r.langue, "groupe": r.groupe, "note": r.note,
        "tags": r.tags or [], "position": r.position,
        "favori": r.favori, "active": r.active,
    }


async def _get_dossier(db: AsyncSession, ref: str) -> DossierThematique:
    """Résout un dossier par UUID **ou** par slug. 404 si introuvable."""
    d = None
    try:
        d = await db.get(DossierThematique, uuid.UUID(ref))
    except ValueError:
        d = (await db.execute(
            select(DossierThematique).where(DossierThematique.slug == ref)
        )).scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    return d


async def _get_ressource(db: AsyncSession, rid: str) -> Ressource:
    try:
        r = await db.get(Ressource, uuid.UUID(rid))
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")
    if not r:
        raise HTTPException(status_code=404, detail="Ressource introuvable")
    return r


# ─── Métadonnées ──────────────────────────────────────────────────────────────

@router.get("/dossiers/types", tags=["Dossiers"])
async def types_disponibles() -> dict:
    """Types de ressource reconnus + seeds installables (alimente les filtres du front)."""
    return {
        "types": TYPES_RESSOURCE,
        "seeds": [{"cle": k, "titre": v["titre"], "nb": len(v["ressources"])} for k, v in SEEDS.items()],
    }


# ─── Dossiers ─────────────────────────────────────────────────────────────────

@router.get("/dossiers", tags=["Dossiers"])
async def lister(db: AsyncSession = Depends(get_db)) -> dict:
    """Liste des dossiers, chacun avec son nombre de ressources actives."""
    dossiers = (await db.execute(
        select(DossierThematique).order_by(DossierThematique.created_at.desc())
    )).scalars().all()

    # Un seul GROUP BY plutôt qu'une requête par dossier.
    comptes = dict((await db.execute(
        select(Ressource.dossier_id, func.count())
        .where(Ressource.active.is_(True))
        .group_by(Ressource.dossier_id)
    )).all())

    return {"dossiers": [_resume_dossier(d, comptes.get(d.id, 0)) for d in dossiers]}


@router.post("/dossiers", status_code=201, tags=["Dossiers"])
async def creer(body: DossierIn, db: AsyncSession = Depends(get_db)) -> dict:
    slug = _slugifier(body.slug or body.titre)
    d = DossierThematique(titre=body.titre, slug=slug, description=body.description, origine="manuel")
    db.add(d)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Un dossier utilise déjà le slug « {slug} »")
    await db.refresh(d)
    log.info("Dossier thématique créé", titre=body.titre, slug=slug)
    return _resume_dossier(d)


@router.get("/dossiers/{ref}", tags=["Dossiers"])
async def detail(ref: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Dossier + toutes ses ressources, ordonnées par position.

    Le filtrage (type, langue, tag, recherche) se fait côté client : un dossier de
    veille reste de l'ordre de la centaine d'entrées, inutile de payer un aller-retour
    réseau à chaque clic sur un filtre.
    """
    d = await _get_dossier(db, ref)
    ressources = (await db.execute(
        select(Ressource)
        .where(Ressource.dossier_id == d.id)
        .order_by(Ressource.position, Ressource.titre)
    )).scalars().all()

    # Ordre d'apparition des groupes = celui de la liste (stable, pas alphabétique) :
    # il porte une progression voulue, pas un classement.
    groupes: list[str] = []
    for r in ressources:
        g = r.groupe or "Sans groupe"
        if g not in groupes:
            groupes.append(g)

    return {
        **_resume_dossier(d, sum(1 for r in ressources if r.active)),
        "groupes": groupes,
        "ressources": [_serialiser_ressource(r) for r in ressources],
    }


@router.patch("/dossiers/{ref}", tags=["Dossiers"])
async def modifier(ref: str, body: DossierPatch, db: AsyncSession = Depends(get_db)) -> dict:
    d = await _get_dossier(db, ref)
    for champ, valeur in body.model_dump(exclude_unset=True).items():
        setattr(d, champ, valeur)
    await db.commit()
    await db.refresh(d)
    return _resume_dossier(d)


@router.delete("/dossiers/{ref}", tags=["Dossiers"])
async def supprimer(ref: str, db: AsyncSession = Depends(get_db)) -> dict:
    d = await _get_dossier(db, ref)
    titre = d.titre
    # Suppression explicite des ressources : le ON DELETE CASCADE est en base, mais
    # l'ORM ne le connaît pas (pas de relationship déclarée) — on reste explicite.
    await db.execute(delete(Ressource).where(Ressource.dossier_id == d.id))
    await db.delete(d)
    await db.commit()
    log.info("Dossier thématique supprimé", titre=titre)
    return {"message": f"Dossier « {titre} » supprimé"}


# ─── Ressources ───────────────────────────────────────────────────────────────

@router.post("/dossiers/{ref}/ressources", status_code=201, tags=["Dossiers"])
async def ajouter_ressource(ref: str, body: RessourceIn, db: AsyncSession = Depends(get_db)) -> dict:
    d = await _get_dossier(db, ref)
    # Nouvelle entrée en fin de son groupe.
    position = ((await db.execute(
        select(func.max(Ressource.position)).where(Ressource.dossier_id == d.id)
    )).scalar() or 0) + 1

    r = Ressource(dossier_id=d.id, position=position, **body.model_dump())
    db.add(r)
    await db.commit()
    await db.refresh(r)
    log.info("Ressource ajoutée", dossier=d.slug, titre=body.titre, type=body.type)
    return _serialiser_ressource(r)


@router.patch("/dossiers/ressources/{rid}", tags=["Dossiers"])
async def modifier_ressource(rid: str, body: RessourcePatch, db: AsyncSession = Depends(get_db)) -> dict:
    r = await _get_ressource(db, rid)
    for champ, valeur in body.model_dump(exclude_unset=True).items():
        setattr(r, champ, valeur)
    await db.commit()
    await db.refresh(r)
    return _serialiser_ressource(r)


@router.delete("/dossiers/ressources/{rid}", tags=["Dossiers"])
async def supprimer_ressource(rid: str, db: AsyncSession = Depends(get_db)) -> dict:
    r = await _get_ressource(db, rid)
    titre = r.titre
    await db.delete(r)
    await db.commit()
    return {"message": f"Ressource « {titre} » supprimée"}


# ─── Seeds ────────────────────────────────────────────────────────────────────

@router.post("/dossiers/seed/{cle}", tags=["Dossiers"])
async def installer(cle: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Installe le dossier pré-rempli `cle` (ex. `devenir-parent`).

    Idempotent : relancé sur un dossier existant, n'ajoute que les ressources absentes.
    Les entrées modifiées ou supprimées à la main ne sont pas restaurées.
    """
    try:
        return await installer_seed(db, cle)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Seed « {cle} » inconnu")
