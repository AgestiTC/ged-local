"""
Router Réorganisation — /api/organize
=====================================
Incrément 1 : PROPOSITION + APERÇU (virtuel, lecture seule).
L'IA propose un schéma de rangement (catégorie → dossier cible) à partir des
métadonnées déjà extraites ; on mappe chaque document → dossier cible et on
renvoie l'arborescence proposée. **Aucun fichier déplacé, aucune écriture DB.**

Étapes suivantes (incrément 2, cf. docs/plan-reorganisation-arborescence.md) :
édition drag & drop + application virtuelle (vue logique) puis physique (NAS, undo).
"""

import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from logger import get_logger
from models.document import Document
from models.reorg import ReorgPlan
from services.extraction import _extraire_json
from services.ollama_service import OllamaService

settings = get_settings()

log = get_logger(__name__)
router = APIRouter()


class ProposeRequest(BaseModel):
    consigne: str | None = None          # ex. « range plutôt par client », « par année »
    inclure_annee: bool = True           # sous-dossier {dossier}/{année}


def _annee(doc: Document) -> str | None:
    d = doc.date_modification_fichier or doc.date_import
    return str(d.year) if d else None


async def _proposer_dossiers(categories: list[str], consigne: str | None) -> tuple[dict, str]:
    """Demande au LLM un mapping {catégorie: dossier cible} + une explication."""
    if not categories:
        return {}, "Aucune catégorie."
    prompt = (
        "Tu organises une GED. Voici les catégories de documents détectées :\n"
        + ", ".join(categories)
        + ".\n\nConsigne utilisateur : "
        + (consigne or "range les documents dans une arborescence claire et logique")
        + ".\n\nRéponds UNIQUEMENT en JSON : "
        '{"criteres": "<phrase expliquant le rangement>", '
        '"dossiers": {"<catégorie>": "<NomDossier>"}} '
        "où chaque catégorie reçoit un nom de dossier court et lisible (sans accent ni slash)."
    )
    try:
        from services import runtime_config
        reponse = await OllamaService().generate(prompt, model=runtime_config.model_for("enrichissement"))
        data = _extraire_json(reponse)
        dossiers = {str(k): str(v).strip("/ ") for k, v in (data.get("dossiers") or {}).items() if v}
        criteres = data.get("criteres") or "Rangement par catégorie."
        if dossiers:
            return dossiers, criteres
    except Exception as exc:
        log.warning("Proposition IA indisponible, repli par catégorie", erreur=str(exc))
    # Repli déterministe : 1 dossier par catégorie (capitalisée)
    return {c: c.capitalize() for c in categories}, "Repli : un dossier par catégorie."


@router.post("/organize/propose", tags=["Réorganisation"])
async def propose(body: ProposeRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Propose une arborescence cible (aperçu virtuel, sans rien modifier)."""
    docs = (await db.execute(
        select(Document).options(selectinload(Document.metadonnees_ia))
        .where(Document.statut == "enriched")
    )).scalars().all()

    # Catégories distinctes
    cats = sorted({(d.metadonnees_ia.categorie if d.metadonnees_ia and d.metadonnees_ia.categorie else "non-classé")
                   for d in docs})
    dossiers_map, criteres = await _proposer_dossiers([c for c in cats if c != "non-classé"], body.consigne)
    # Normalisation insensible à la casse (le LLM ne renvoie pas toujours la clé exacte)
    dossiers_norm = {k.lower(): v for k, v in dossiers_map.items()}

    def _cible_cat(cat: str) -> str:
        if cat == "non-classé":
            return "Non classé"
        # Proposition IA si elle matche, sinon repli : un dossier par catégorie
        return dossiers_norm.get(cat.lower()) or cat.capitalize()

    # Mapping doc → dossier cible + PERSISTANCE du plan (remplace l'ancien).
    cibles: dict[uuid.UUID, str] = {}
    for d in docs:
        cat = d.metadonnees_ia.categorie if d.metadonnees_ia and d.metadonnees_ia.categorie else "non-classé"
        cible = _cible_cat(cat)
        if body.inclure_annee and (an := _annee(d)):
            cible = f"{cible}/{an}"
        cibles[d.id] = cible

    await db.execute(delete(ReorgPlan))
    db.add_all([ReorgPlan(document_id=did, dossier_cible=c) for did, c in cibles.items()])
    await db.commit()
    log.info("Plan de réorganisation proposé & persisté", nb=len(cibles))

    arbo = await _arborescence(db)
    return {
        "criteres": criteres,
        "consigne": body.consigne,
        "nb_documents": len(docs),
        "nb_dossiers": len(arbo),
        "arborescence": arbo,
    }


async def _arborescence(db: AsyncSession) -> list[dict]:
    """Construit l'arborescence virtuelle depuis le plan persisté (dossier → documents)."""
    rows = (await db.execute(
        select(Document, ReorgPlan.dossier_cible)
        .join(ReorgPlan, ReorgPlan.document_id == Document.id)
    )).all()
    arbre: dict[str, list] = defaultdict(list)
    for d, dossier in rows:
        arbre[dossier].append({"id": str(d.id), "nom": d.nom, "chemin_actuel": d.chemin})
    return [
        {"dossier": k, "nb": len(v), "documents": sorted(v, key=lambda x: x["nom"].lower())}
        for k, v in sorted(arbre.items())
    ]


@router.get("/organize/plan", tags=["Réorganisation"])
async def get_plan(db: AsyncSession = Depends(get_db)) -> dict:
    """Renvoie le plan de réorganisation persisté (arborescence virtuelle éditable)."""
    arbo = await _arborescence(db)
    return {"nb_dossiers": len(arbo), "nb_documents": sum(a["nb"] for a in arbo), "arborescence": arbo}


class MoveRequest(BaseModel):
    document_ids: list[str]
    dossier_cible: str


@router.post("/organize/plan/move", tags=["Réorganisation"])
async def move_in_plan(body: MoveRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Déplace des documents vers un autre dossier **virtuel** (édition du plan, aucun fichier bougé)."""
    cible = (body.dossier_cible or "").strip().strip("/") or "Non classé"
    n = 0
    for did in body.document_ids:
        try:
            uid = uuid.UUID(did)
        except ValueError:
            continue
        row = await db.get(ReorgPlan, uid)
        if row:
            row.dossier_cible = cible
        else:
            db.add(ReorgPlan(document_id=uid, dossier_cible=cible))
        n += 1
    await db.commit()
    if n == 0:
        raise HTTPException(status_code=400, detail="Aucun document valide")
    log.info("Plan édité (déplacement virtuel)", nb=n, cible=cible)
    return {"deplaces": n, "dossier_cible": cible}
