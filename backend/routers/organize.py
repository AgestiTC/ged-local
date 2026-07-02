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


# ─── Phase 3 : application PHYSIQUE (NAS/SMB) + undo ───────────────────────────

def parse_smb(chemin: str | None):
    """`smb://host/share/rel` → (host, share, rel_avec_slash) ou None (non-SMB)."""
    if not chemin or not chemin.startswith("smb://"):
        return None
    raw = chemin[len("smb://"):]
    try:
        host, rest = raw.split("/", 1)
        share, tail = rest.split("/", 1)
    except ValueError:
        return None
    return host, share, "/" + tail


def dest_rel(dossier_cible: str, filename: str) -> str:
    d = (dossier_cible or "").strip().strip("/")
    return f"/{d}/{filename}" if d else f"/{filename}"


@router.post("/organize/apply/dry-run", tags=["Réorganisation"])
async def apply_dry_run(db: AsyncSession = Depends(get_db)) -> dict:
    """Simulation : liste les déplacements PHYSIQUES qui seraient effectués. Rien n'est déplacé."""
    rows = (await db.execute(
        select(Document, ReorgPlan.dossier_cible).join(ReorgPlan, ReorgPlan.document_id == Document.id)
    )).all()
    moves: list[dict] = []
    for d, dossier in rows:
        parsed = parse_smb(d.chemin)
        if not parsed:
            moves.append({"id": str(d.id), "nom": d.nom, "source": d.chemin, "dest": None, "warn": "non-SMB (ignoré)"})
            continue
        host, share, rel = parsed
        drel = dest_rel(dossier, d.nom)
        dest = f"smb://{host}/{share}{drel}"
        moves.append({"id": str(d.id), "nom": d.nom, "source": d.chemin, "dest": dest,
                      "warn": "déjà à sa place" if rel == drel else None})
    a_deplacer = sum(1 for m in moves if m["dest"] and m["warn"] is None)
    ignores = sum(1 for m in moves if not m["dest"])
    return {"total": len(moves), "a_deplacer": a_deplacer, "ignores": ignores, "moves": moves[:1000]}


@router.post("/organize/apply", tags=["Réorganisation"])
async def apply_physique(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Applique le plan **au NAS** (déplacement SMB réel), en **tâche durable**, avec journal pour
    l'undo. ⚠️ Destructif (déplace des fichiers) — à déclencher sur **confirmation** côté UI.
    """
    import uuid as _uuid

    from services import job_worker
    batch = str(_uuid.uuid4())
    job_id = await job_worker.enqueue(db, "reorg_apply", {"batch_id": batch})
    await db.commit()
    log.info("Application réorganisation mise en file", batch=batch, job_id=job_id)
    return {"job_id": job_id, "batch_id": batch, "statut": "pending"}


@router.post("/organize/undo", tags=["Réorganisation"])
async def undo_last(db: AsyncSession = Depends(get_db)) -> dict:
    """Annule la **dernière** application (remet les fichiers à leur place), en tâche durable."""
    from models.reorg import ReorgMove

    last = (await db.execute(
        select(ReorgMove.batch_id).order_by(ReorgMove.applied_at.desc()).limit(1)
    )).scalar_one_or_none()
    if not last:
        raise HTTPException(status_code=404, detail="Aucune application à annuler")
    from services import job_worker
    job_id = await job_worker.enqueue(db, "reorg_undo", {"batch_id": str(last)})
    await db.commit()
    return {"job_id": job_id, "batch_id": str(last), "statut": "pending"}
