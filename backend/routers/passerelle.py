"""
Router Passerelle — /api/passerelle (wiki multi-projets)
========================================================
Lot 2 (auth + admin) + Lot 3 (publication par manifeste).

  Dépendance `projet_authentifie`  → protège l'endpoint de PUBLICATION par jeton Bearer.
  POST   /passerelle/publish                 → publier/synchroniser un MANIFESTE (auth jeton) [Lot 3]
  POST   /passerelle/projets                 → enregistrer un projet + générer son jeton (montré 1×)
  GET    /passerelle/projets                 → lister les projets (sans le hash de jeton)
  POST   /passerelle/projets/{nom}/regenerer → rotation du jeton
  PATCH  /passerelle/projets/{nom}           → (dés)activer / modifier la liste blanche des livres

⚠️ Les endpoints d'administration reposent sur la **confiance réseau** (comme le reste de l'API) —
c'est l'endpoint de publication (Lot 3) qui exige le jeton. Le jeton en clair n'est **jamais stocké**
ni ré-affiché : à copier au moment de la création/rotation.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.publieur import ProjetPublieur
from services import publication_service, publieur_auth
from services.bookstack_service import BookStackService

log = get_logger(__name__)
router = APIRouter()

_AVERT_JETON = "Copie ce jeton MAINTENANT : il n'est jamais ré-affiché (seul son hash est conservé)."


def _projet_dict(p: ProjetPublieur) -> dict:
    """Sérialise un projet SANS jamais exposer le hash du jeton."""
    return {
        "nom": p.nom,
        "livres_autorises": p.livres_autorises,
        "actif": p.actif,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "last_used_at": p.last_used_at.isoformat() if p.last_used_at else None,
    }


async def projet_authentifie(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ProjetPublieur:
    """
    Dépendance d'authentification des endpoints de PUBLICATION : lit `Authorization: Bearer <jeton>`,
    hache et retrouve le projet actif. **401** si jeton absent/invalide/révoqué. Utilisée par le Lot 3.
    """
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    projet = await publieur_auth.authentifier(db, token)
    if not projet:
        raise HTTPException(status_code=401, detail="Jeton de publication absent, invalide ou révoqué.")
    return projet


# ─── Administration des projets publieurs ─────────────────────────────────────
class ProjetCreate(BaseModel):
    nom: str = Field(min_length=1, description="Nom du projet (ex. « sapyn »)")
    livres_autorises: list[str] = Field(default_factory=list, description="Livres BookStack où ce projet peut publier")


class ProjetUpdate(BaseModel):
    livres_autorises: list[str] | None = None
    actif: bool | None = None   # false = révoquer (le jeton cesse d'authentifier)


@router.post("/passerelle/projets", tags=["Passerelle"])
async def creer_projet(body: ProjetCreate, db: AsyncSession = Depends(get_db)) -> dict:
    """Enregistre un projet publieur et **génère son jeton** (renvoyé UNE seule fois)."""
    try:
        projet, jeton = await publieur_auth.creer_projet(db, body.nom, body.livres_autorises)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {**_projet_dict(projet), "jeton": jeton, "avertissement": _AVERT_JETON}


@router.get("/passerelle/projets", tags=["Passerelle"])
async def lister_projets(db: AsyncSession = Depends(get_db)) -> dict:
    """Liste des projets publieurs (jamais le hash de jeton)."""
    projets = await publieur_auth.lister_projets(db)
    return {"projets": [_projet_dict(p) for p in projets]}


@router.post("/passerelle/projets/{nom}/regenerer", tags=["Passerelle"])
async def regenerer_jeton(nom: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Rotation du jeton d'un projet (l'ancien cesse immédiatement de fonctionner)."""
    try:
        jeton = await publieur_auth.regenerer_jeton(db, nom)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"nom": nom, "jeton": jeton, "avertissement": _AVERT_JETON}


@router.patch("/passerelle/projets/{nom}", tags=["Passerelle"])
async def modifier_projet(nom: str, body: ProjetUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    """(Dés)active un projet (révocation via `actif=false`) et/ou modifie sa liste blanche de livres."""
    try:
        projet = await publieur_auth.definir(db, nom, actif=body.actif, livres_autorises=body.livres_autorises)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _projet_dict(projet)


# ─── Publication (Lot 3) — endpoint MANIFESTE, protégé par jeton ───────────────
class PageManifeste(BaseModel):
    cle: str = Field(min_length=1, description="Identifiant logique du doc chez le projet (slug/chemin)")
    livre: str = Field(min_length=1)
    chapitre: str | None = None
    titre: str = Field(min_length=1)
    markdown: str
    genere_le: datetime | None = None   # horodatage de génération (ISO) — avertit si plus ancien


class Manifeste(BaseModel):
    pages: list[PageManifeste] = Field(min_length=1)
    etagere: str | None = None   # étagère BookStack où regrouper les livres (ex. « Projets AgestiTC »)


@router.post("/passerelle/publish", tags=["Passerelle"])
async def publier(
    body: Manifeste,
    projet: ProjetPublieur = Depends(projet_authentifie),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Publie/synchronise la doc d'un projet vers BookStack à partir de son **manifeste** (arbre complet).
    Auth par jeton (dépendance). Déroulé : autorisation des livres (liste blanche) → rapprochement
    (créer/màj/inchangées/retraits) → appels BookStack → upsert `publications`. Cf. plan § Lot 3.
    """
    try:
        return await publication_service.publier_manifeste(
            db, projet, [p.model_dump() for p in body.pages], body.etagere, service=BookStackService(), log=log)
    except publication_service.PublicationRefusee as e:
        raise HTTPException(status_code=e.statut, detail=e.message)


# ─── Docs déposées par le cockpit sur NAS-MATO (16/11/2026) ────────────────────
@router.post("/passerelle/docs-cockpit/relever", tags=["Passerelle"], status_code=202)
async def relever_docs_cockpit() -> dict:
    """Lance tout de suite le relevé de `[GED]/Docs-applications` (sinon : toutes les 15 min)."""
    from services import docs_cockpit
    job_id = await docs_cockpit.planifier()
    return {"job_id": job_id, "statut": "demarre" if job_id else "deja_en_cours"}
