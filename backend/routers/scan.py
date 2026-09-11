"""
Router Scan — /api/scan
=======================
Scanners (eSCL), profils de scan, boîte à scans et travaux de numérisation.

  GET/PUT   /scan/config                     → dossier de la boîte (surveillé par les sources)
  CRUD      /scan/scanners  · POST /scan/scanners/{id}/test (capacités + statut, stockés)
  CRUD      /scan/profils
  POST      /scan/jobs                       → lance une capture (tâche durable `scan_capture`)
  POST      /scan/{id}/page-suivante         → vitre : une page de plus
  POST      /scan/{id}/terminer              → assemble, indexe, range si profil `fixe`
  GET       /scan/inbox                      → la boîte (rattache d'abord les nouveaux dépôts)
  GET       /scan/{id} · GET /scan/{id}/pages/{n} (aperçu d'une page capturée)
  POST      /scan/{id}/ranger                → applique/confirme un profil (tâche `scan_ranger`)
  POST      /scan/{id}/proposer              → quel profil ressemble à ce scan
  DELETE    /scan/{id}                       → retire la ligne (le document GED reste)

Tout ce qui touche au réseau ou déplace un fichier passe par une tâche durable : la page
peut être fermée, l'UI suit le job. Aucun déplacement sans profil choisi ou confirmé.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.document import Document
from models.metadata import MetadonneeIA
from models.scan import CLASSEMENTS, Scan, Scanner, ScanProfil
from services import escl_client, runtime_config, scan_service

log = get_logger(__name__)
router = APIRouter()


# ─── Schémas ───────────────────────────────────────────────────────────────────────────

class ConfigIn(BaseModel):
    boite_chemin: str = ""


class ScannerIn(BaseModel):
    nom: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=3, max_length=300)
    actif: bool = True


class ProfilIn(BaseModel):
    nom: str = Field(min_length=1, max_length=120)
    icone: str | None = Field(default=None, max_length=8)
    destination: str = Field(min_length=1, max_length=500)
    tags: list[str] = []
    mots_cles: list[str] = []
    modele_nom: str | None = Field(default=None, max_length=120)
    reglages: dict = {}
    scanner_id: str | None = None
    classement: str = "fixe"
    position: int = 0
    actif: bool = True


class ScanJobIn(BaseModel):
    scanner_id: str
    profil_id: str | None = None
    reglages: dict = {}
    # None = déduit : chargeur → tout d'un coup ; vitre → une page, puis « page suivante ».
    finaliser: bool | None = None


class RangerIn(BaseModel):
    profil_id: str | None = None
    nom: str | None = Field(default=None, max_length=200)


def _uuid(v: str, quoi: str = "identifiant") -> uuid.UUID:
    try:
        return uuid.UUID(str(v))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{quoi} invalide")


def _scanner_dict(s: Scanner) -> dict:
    return {"id": str(s.id), "nom": s.nom, "type": s.type, "url": s.url, "actif": s.actif,
            "capacites": s.capacites, "dernier_test": s.dernier_test.isoformat() if s.dernier_test else None,
            "dernier_etat": s.dernier_etat}


def _profil_dict(p: ScanProfil) -> dict:
    return {"id": str(p.id), "nom": p.nom, "icone": p.icone, "destination": p.destination,
            "tags": p.tags or [], "mots_cles": p.mots_cles or [], "modele_nom": p.modele_nom,
            "reglages": p.reglages or {}, "scanner_id": str(p.scanner_id) if p.scanner_id else None,
            "classement": p.classement, "position": p.position, "actif": p.actif}


def _verifier_destination(destination: str) -> str:
    try:
        d = scan_service.resoudre_destination(destination)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not d:
        raise HTTPException(status_code=400, detail="Destination requise")
    if not d.startswith("smb://") and not scan_service.local_autorise(d):
        raise HTTPException(status_code=400, detail="Une destination locale doit être sous la racine documents "
                                                    "(sinon utilise smb://hote/partage/dossier)")
    if d.startswith("smb://") and not scan_service.parse_smb(d):
        raise HTTPException(status_code=400, detail="Destination SMB attendue sous la forme smb://hote/partage/dossier")
    return destination.strip()


async def _get_scan(db: AsyncSession, scan_id: str) -> Scan:
    s = await db.get(Scan, _uuid(scan_id, "scan"))
    if not s:
        raise HTTPException(status_code=404, detail="Scan introuvable")
    return s


# ─── Config (boîte) ────────────────────────────────────────────────────────────────────

@router.get("/scan/config", tags=["Scan"])
async def get_config() -> dict:
    return {"boite_chemin": scan_service.boite_prefixe()}


@router.put("/scan/config", tags=["Scan"])
async def set_config(body: ConfigIn, db: AsyncSession = Depends(get_db)) -> dict:
    chemin = body.boite_chemin.strip().replace("\\", "/").rstrip("/")
    if chemin and not chemin.startswith("smb://") and not scan_service.local_autorise(chemin):
        raise HTTPException(status_code=400, detail="Un dossier local doit être sous la racine documents")
    await runtime_config.set_many(db, {"scan_boite_chemin": chemin})
    return {"boite_chemin": chemin}


# ─── Scanners ──────────────────────────────────────────────────────────────────────────

@router.get("/scan/scanners", tags=["Scan"])
async def lister_scanners(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(Scanner).order_by(Scanner.nom))).scalars().all()
    return {"scanners": [_scanner_dict(s) for s in rows]}


@router.post("/scan/scanners", status_code=201, tags=["Scan"])
async def creer_scanner(body: ScannerIn, db: AsyncSession = Depends(get_db)) -> dict:
    s = Scanner(nom=body.nom.strip(), url=escl_client.base_escl(body.url), actif=body.actif, type="escl")
    db.add(s)
    await db.flush()
    return _scanner_dict(s)


@router.put("/scan/scanners/{scanner_id}", tags=["Scan"])
async def modifier_scanner(scanner_id: str, body: ScannerIn, db: AsyncSession = Depends(get_db)) -> dict:
    s = await db.get(Scanner, _uuid(scanner_id))
    if not s:
        raise HTTPException(status_code=404, detail="Scanner introuvable")
    nouvelle_url = escl_client.base_escl(body.url)
    if nouvelle_url != s.url:
        s.capacites, s.dernier_test, s.dernier_etat = None, None, None  # à re-tester
    s.nom, s.url, s.actif = body.nom.strip(), nouvelle_url, body.actif
    await db.flush()
    return _scanner_dict(s)


@router.delete("/scan/scanners/{scanner_id}", tags=["Scan"])
async def supprimer_scanner(scanner_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    s = await db.get(Scanner, _uuid(scanner_id))
    if not s:
        raise HTTPException(status_code=404, detail="Scanner introuvable")
    await db.delete(s)
    await db.flush()
    return {"supprime": True}


@router.post("/scan/scanners/{scanner_id}/test", tags=["Scan"])
async def tester_scanner(scanner_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Interroge l'appareil (capacités + statut) et mémorise le résultat sur la fiche."""
    s = await db.get(Scanner, _uuid(scanner_id))
    if not s:
        raise HTTPException(status_code=404, detail="Scanner introuvable")
    client = escl_client.ESCLClient(s.url)
    s.dernier_test = datetime.now(tz=timezone.utc)
    try:
        caps = await client.capacites()
        statut = await client.statut()
    except escl_client.ESCLError as e:
        s.dernier_etat = f"erreur : {e}"
        await db.flush()
        return {"ok": False, "erreur": str(e), "scanner": _scanner_dict(s)}
    s.capacites = caps.to_dict()
    s.dernier_etat = "ok"
    await db.flush()
    return {"ok": True, "capacites": caps.to_dict(), "statut": {"etat": statut.etat, "chargeur": statut.chargeur},
            "scanner": _scanner_dict(s)}


# ─── Profils ───────────────────────────────────────────────────────────────────────────

@router.get("/scan/profils", tags=["Scan"])
async def lister_profils(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(ScanProfil).order_by(ScanProfil.position, ScanProfil.nom))).scalars().all()
    return {"profils": [_profil_dict(p) for p in rows]}


def _appliquer_profil(p: ScanProfil, body: ProfilIn) -> None:
    if body.classement not in CLASSEMENTS:
        raise HTTPException(status_code=400, detail=f"classement attendu : {' | '.join(CLASSEMENTS)}")
    p.nom = body.nom.strip()
    p.icone = (body.icone or "").strip() or None
    p.destination = _verifier_destination(body.destination)
    p.tags = [t.strip() for t in body.tags if t and t.strip()]
    p.mots_cles = [m.strip() for m in body.mots_cles if m and m.strip()]
    p.modele_nom = (body.modele_nom or "").strip() or None
    p.reglages = {k: v for k, v in (body.reglages or {}).items() if k in ("source", "recto_verso", "couleur", "dpi")}
    p.scanner_id = _uuid(body.scanner_id, "scanner") if body.scanner_id else None
    p.classement = body.classement
    p.position = body.position
    p.actif = body.actif


@router.post("/scan/profils", status_code=201, tags=["Scan"])
async def creer_profil(body: ProfilIn, db: AsyncSession = Depends(get_db)) -> dict:
    p = ScanProfil()
    _appliquer_profil(p, body)
    db.add(p)
    await db.flush()
    return _profil_dict(p)


@router.put("/scan/profils/{profil_id}", tags=["Scan"])
async def modifier_profil(profil_id: str, body: ProfilIn, db: AsyncSession = Depends(get_db)) -> dict:
    p = await db.get(ScanProfil, _uuid(profil_id))
    if not p:
        raise HTTPException(status_code=404, detail="Profil introuvable")
    _appliquer_profil(p, body)
    await db.flush()
    return _profil_dict(p)


@router.delete("/scan/profils/{profil_id}", tags=["Scan"])
async def supprimer_profil(profil_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    p = await db.get(ScanProfil, _uuid(profil_id))
    if not p:
        raise HTTPException(status_code=404, detail="Profil introuvable")
    await db.delete(p)
    await db.flush()
    return {"supprime": True}


# ─── Travaux de numérisation ───────────────────────────────────────────────────────────

@router.post("/scan/jobs", status_code=202, tags=["Scan"])
async def lancer_scan(body: ScanJobIn, db: AsyncSession = Depends(get_db)) -> dict:
    from services import job_worker

    scanner = await db.get(Scanner, _uuid(body.scanner_id, "scanner"))
    if not scanner or not scanner.actif:
        raise HTTPException(status_code=404, detail="Scanner introuvable ou désactivé")
    profil = await db.get(ScanProfil, _uuid(body.profil_id, "profil")) if body.profil_id else None
    if body.profil_id and not profil:
        raise HTTPException(status_code=404, detail="Profil introuvable")
    reglages = dict((profil.reglages or {}) if profil else {})
    reglages.update({k: v for k, v in (body.reglages or {}).items() if v is not None})
    source = reglages.get("source") or "vitre"
    if source == "chargeur" and scanner.capacites and not scanner.capacites.get("chargeur"):
        raise HTTPException(status_code=400, detail="Ce scanner n'a pas de chargeur")
    finaliser = body.finaliser if body.finaliser is not None else (source == "chargeur")

    scan = Scan(scanner_id=scanner.id, profil_id=profil.id if profil else None, statut="en_cours",
                origine="escl", reglages=reglages, nb_pages=0)
    db.add(scan)
    await db.flush()
    scan.session_dir = str(scan_service.dossier_session(scan.id))
    job_id = await job_worker.enqueue(db, "scan_capture", {"scan_id": str(scan.id), "finaliser": finaliser,
                                                           "cible": str(scan.id)})
    log.info("Scan lancé", scan=str(scan.id), scanner=scanner.nom, profil=profil.nom if profil else None, finaliser=finaliser)
    return {"scan_id": str(scan.id), "job_id": job_id, "finaliser": finaliser}


@router.post("/scan/{scan_id}/page-suivante", status_code=202, tags=["Scan"])
async def page_suivante(scan_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    from services import job_worker
    scan = await _get_scan(db, scan_id)
    if scan.statut not in ("en_cours", "erreur") or not scan.scanner_id:
        raise HTTPException(status_code=409, detail="Ce scan n'attend plus de page")
    scan.statut = "en_cours"
    job_id = await job_worker.enqueue(db, "scan_capture", {"scan_id": str(scan.id), "finaliser": False, "cible": str(scan.id)})
    return {"scan_id": str(scan.id), "job_id": job_id}


@router.post("/scan/{scan_id}/terminer", status_code=202, tags=["Scan"])
async def terminer(scan_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    from services import job_worker
    scan = await _get_scan(db, scan_id)
    if scan.statut not in ("en_cours", "erreur"):
        raise HTTPException(status_code=409, detail="Ce scan est déjà assemblé")
    if not scan_service.pages_session(scan.id):
        raise HTTPException(status_code=409, detail="Aucune page capturée")
    job_id = await job_worker.enqueue(db, "scan_finaliser", {"scan_id": str(scan.id), "cible": str(scan.id)})
    return {"scan_id": str(scan.id), "job_id": job_id}


# ─── Boîte ─────────────────────────────────────────────────────────────────────────────

@router.get("/scan/inbox", tags=["Scan"])
async def boite(tout: bool = False, db: AsyncSession = Depends(get_db)) -> dict:
    nouveaux = await scan_service.rattacher_nouveaux(db)
    items = await scan_service.lister_boite(db, tout=tout)
    return {"scans": items, "nouveaux": nouveaux, "boite_chemin": scan_service.boite_prefixe()}


@router.get("/scan/{scan_id}", tags=["Scan"])
async def detail(scan_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    scan = await _get_scan(db, scan_id)
    doc = await db.get(Document, scan.document_id) if scan.document_id else None
    meta = (await db.execute(select(MetadonneeIA).where(MetadonneeIA.document_id == scan.document_id))).scalar_one_or_none() if doc else None
    d = scan_service.serialiser(scan, doc, meta)
    d["pages_capturees"] = len(scan_service.pages_session(scan.id))
    return d


@router.get("/scan/{scan_id}/pages/{n}", tags=["Scan"])
async def apercu_page(scan_id: str, n: int, db: AsyncSession = Depends(get_db)):
    scan = await _get_scan(db, scan_id)
    pages = scan_service.pages_session(scan.id)
    if n < 1 or n > len(pages):
        raise HTTPException(status_code=404, detail="Page introuvable")
    p = pages[n - 1]
    return FileResponse(str(p), media_type=scan_service.type_mime(p))


@router.post("/scan/{scan_id}/proposer", tags=["Scan"])
async def proposer(scan_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    scan = await _get_scan(db, scan_id)
    if not scan.document_id:
        return {"proposition": None}
    doc = await db.get(Document, scan.document_id)
    meta = (await db.execute(select(MetadonneeIA).where(MetadonneeIA.document_id == scan.document_id))).scalar_one_or_none()
    profils = (await db.execute(select(ScanProfil).where(ScanProfil.actif.is_(True)).order_by(ScanProfil.position))).scalars().all()
    return {"proposition": scan_service.proposer_profil(
        profils, categorie=meta.categorie if meta else None, sous_categorie=meta.sous_categorie if meta else None,
        tags=meta.tags if meta else None, nom=doc.nom if doc else None, texte=doc.texte_extrait if doc else None)}


@router.post("/scan/{scan_id}/ranger", status_code=202, tags=["Scan"])
async def ranger(scan_id: str, body: RangerIn, db: AsyncSession = Depends(get_db)) -> dict:
    from services import job_worker
    scan = await _get_scan(db, scan_id)
    if not scan.document_id:
        raise HTTPException(status_code=409, detail="Ce scan n'est pas encore indexé")
    pid = body.profil_id or (str(scan.profil_id) if scan.profil_id else None)
    if not pid:
        raise HTTPException(status_code=400, detail="Choisis un profil de rangement")
    profil = await db.get(ScanProfil, _uuid(pid, "profil"))
    if not profil:
        raise HTTPException(status_code=404, detail="Profil introuvable")
    scan.profil_id = profil.id
    job_id = await job_worker.enqueue(db, "scan_ranger", {"scan_id": str(scan.id), "profil_id": str(profil.id),
                                                          "nom": body.nom, "cible": str(scan.id)})
    return {"scan_id": str(scan.id), "job_id": job_id}


@router.delete("/scan/{scan_id}", tags=["Scan"])
async def retirer(scan_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Retire la ligne de la boîte. Le document GED, lui, n'est pas touché."""
    scan = await _get_scan(db, scan_id)
    scan_service.nettoyer_session(scan.id)
    await db.delete(scan)
    await db.flush()
    return {"supprime": True}
