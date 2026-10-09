"""
Router Projets — /api/projets (page Créer : brouillons, reprise, archive, corbeille)
=====================================================================================
  GET    /projets?statut=brouillon|archive|corbeille&q=   → liste légère (sans l'état)
  POST   /projets                                       → créer
  GET    /projets/{id}                                  → détail : état + résultats
  PATCH  /projets/{id}                                  → sauvegarde automatique (partielle)
  POST   /projets/{id}/archiver | /restaurer | /dupliquer
  DELETE /projets/{id}[?definitif=true]                 → corbeille, ou purge
  POST   /projets/{id}/resultats                        → rattacher ce qu'une génération a produit

Plan : docs/plan-projets-creer.md. Toutes les requêtes filtrent sur le propriétaire : aujourd'hui
une valeur unique, demain le profil actif — rien d'autre ne changera quand les profils arriveront.
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.projet import PROPRIETAIRE_PAR_DEFAUT, Projet, ProjetResultat

router = APIRouter()

CORBEILLE_JOURS = 30           # au-delà, un projet supprimé est purgé à la prochaine consultation


def proprietaire_courant() -> str:
    """Le profil actif. Unique aujourd'hui ; c'est ICI que se brancheront les profils."""
    return PROPRIETAIRE_PAR_DEFAUT


class ProjetIn(BaseModel):
    titre: str = Field(min_length=1, max_length=200)
    mode: str = Field(min_length=1, max_length=40)
    etat: dict | None = None


class ProjetPatch(BaseModel):
    titre: str | None = Field(default=None, min_length=1, max_length=200)
    mode: str | None = Field(default=None, max_length=40)
    etat: dict | None = None
    # Verrou optimiste : la date de la version que le navigateur modifie. Si le projet a changé
    # entre-temps (autre onglet), on refuse plutôt que d'écraser en silence.
    version: str | None = None


class ResultatIn(BaseModel):
    type: str = Field(pattern="^(rapport|job|presentation|morceau)$")
    ref: str = Field(min_length=1, max_length=100)
    libelle: str | None = Field(default=None, max_length=300)


def _resume(p: Projet, nb_resultats: int = 0) -> dict:
    return {"id": str(p.id), "titre": p.titre, "mode": p.mode, "statut": p.statut,
            "supprime_le": p.supprime_le.isoformat() if p.supprime_le else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
            "nb_resultats": nb_resultats}


async def _get(db: AsyncSession, projet_id: str) -> Projet:
    try:
        pid = uuid.UUID(projet_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Identifiant invalide")
    p = await db.get(Projet, pid)
    if not p or p.proprietaire != proprietaire_courant():
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return p


@router.get("/projets")
async def lister(statut: str = Query(default="brouillon", pattern="^(brouillon|archive|corbeille)$"),
                 q: str | None = Query(default=None, max_length=200),
                 db: AsyncSession = Depends(get_db)) -> dict:
    # Purge paresseuse de la corbeille : pas de tâche planifiée pour si peu.
    limite = datetime.now(timezone.utc) - timedelta(days=CORBEILLE_JOURS)
    await db.execute(delete(Projet).where(Projet.proprietaire == proprietaire_courant(),
                                          Projet.supprime_le.isnot(None), Projet.supprime_le < limite))
    nb = select(func.count(ProjetResultat.id)).where(ProjetResultat.projet_id == Projet.id).scalar_subquery()
    stmt = select(Projet, nb).where(Projet.proprietaire == proprietaire_courant())
    if statut == "corbeille":
        stmt = stmt.where(Projet.supprime_le.isnot(None))
    else:
        stmt = stmt.where(Projet.supprime_le.is_(None), Projet.statut == statut)
    if q and q.strip():
        stmt = stmt.where(Projet.titre.ilike(f"%{q.strip()}%"))
    lignes = (await db.execute(stmt.order_by(Projet.updated_at.desc()).limit(500))).all()
    await db.commit()
    return {"projets": [_resume(p, n or 0) for p, n in lignes]}


@router.post("/projets")
async def creer(body: ProjetIn, db: AsyncSession = Depends(get_db)) -> dict:
    p = Projet(titre=body.titre.strip(), mode=body.mode, etat=body.etat or {},
               proprietaire=proprietaire_courant(), updated_at=datetime.now(timezone.utc))
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return {**_resume(p), "etat": p.etat, "resultats": []}


@router.get("/projets/{projet_id}")
async def lire(projet_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    p = await _get(db, projet_id)
    res = (await db.execute(select(ProjetResultat).where(ProjetResultat.projet_id == p.id)
                            .order_by(ProjetResultat.created_at.desc()))).scalars().all()
    return {**_resume(p, len(res)), "etat": p.etat or {},
            "resultats": [{"id": str(r.id), "type": r.type, "ref": r.ref, "libelle": r.libelle,
                           "created_at": r.created_at.isoformat() if r.created_at else None} for r in res]}


@router.patch("/projets/{projet_id}")
async def sauvegarder(projet_id: str, body: ProjetPatch, db: AsyncSession = Depends(get_db)) -> dict:
    p = await _get(db, projet_id)
    if body.version and p.updated_at and body.version != p.updated_at.isoformat():
        raise HTTPException(status_code=409, detail="Ce projet a été modifié ailleurs (autre onglet) : recharge-le")
    if body.titre is not None:
        p.titre = body.titre.strip()
    if body.mode is not None:
        p.mode = body.mode
    if body.etat is not None:
        p.etat = body.etat
    p.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(p)
    return _resume(p)


async def _changer_statut(db: AsyncSession, projet_id: str, statut: str | None, restaurer: bool = False) -> dict:
    p = await _get(db, projet_id)
    if statut:
        p.statut = statut
    if restaurer:
        if p.supprime_le is None:
            p.statut = "brouillon"           # « restaurer » un archivé = le remettre en brouillon
        p.supprime_le = None
    p.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(p)
    return _resume(p)


@router.post("/projets/{projet_id}/archiver")
async def archiver(projet_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    return await _changer_statut(db, projet_id, "archive")


@router.post("/projets/{projet_id}/restaurer")
async def restaurer(projet_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Sort de la corbeille (statut d'avant conservé), ou d'archive (→ brouillon)."""
    return await _changer_statut(db, projet_id, None, restaurer=True)


@router.post("/projets/{projet_id}/dupliquer")
async def dupliquer(projet_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    src = await _get(db, projet_id)
    p = Projet(titre=f"{src.titre} (copie)"[:200], mode=src.mode, etat=dict(src.etat or {}),
               proprietaire=proprietaire_courant(), updated_at=datetime.now(timezone.utc))
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return _resume(p)


@router.delete("/projets/{projet_id}")
async def supprimer(projet_id: str, definitif: bool = False, db: AsyncSession = Depends(get_db)) -> dict:
    """Corbeille par défaut (récupérable 30 jours). `definitif` purge le projet et ses liens — PAS les
    rapports, tableaux ou morceaux qu'il a produits, qui restent dans leur historique."""
    p = await _get(db, projet_id)
    if definitif:
        await db.execute(delete(ProjetResultat).where(ProjetResultat.projet_id == p.id))
        await db.delete(p)
        await db.commit()
        return {"id": projet_id, "supprime": "definitif"}
    p.supprime_le = datetime.now(timezone.utc)
    await db.commit()
    return {"id": projet_id, "supprime": "corbeille"}


@router.post("/projets/{projet_id}/resultats")
async def rattacher(projet_id: str, body: ResultatIn, db: AsyncSession = Depends(get_db)) -> dict:
    p = await _get(db, projet_id)
    deja = (await db.execute(select(ProjetResultat.id).where(
        ProjetResultat.projet_id == p.id, ProjetResultat.type == body.type, ProjetResultat.ref == body.ref))).first()
    if not deja:
        db.add(ProjetResultat(projet_id=p.id, type=body.type, ref=body.ref, libelle=body.libelle))
        p.updated_at = datetime.now(timezone.utc)
        await db.commit()
    return {"ok": True}
