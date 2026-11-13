"""
API de l'inventaire (module Rangement, étape 4) — `/api/inventaire/*`, administrateur seulement.

Le contrôle d'accès est fait par le middleware (`services/acces.py` : préfixe classé ADMIN et
interdit aux jetons d'automate, décision d'architecture n° 1). Ce routeur ne lit jamais le disque :
le NAS n'est monté que dans le worker. Il déclare, consulte, et **enfile** les parcours (scan,
import WizTree), que le worker exécute dans sa classe « fond ».

Postes (étape 5) : un poste porte l'agent Go ; sa création rend son jeton de portée `agent` UNE fois.
Les routes qui émettent un jeton exigent une identité d'administrateur (`admin_identifie`), comme la
création des jetons d'automate : le journal doit savoir QUI l'a émis.

Les écrans React (Carte, Postes…) viennent à l'étape 7 : ici, du JSON seulement.
"""

from collections.abc import AsyncIterator
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.auth import Utilisateur
from routers.auth import admin_identifie
from services import job_worker, runtime_config
from services.rangement import agent as agent_poste
from services.rangement import carte, postes, reglages, service
from services.rangement.depot import Depot, DoublonRacine, ScanEnCours
from services.rangement.erreurs import InventaireRefus

log = get_logger(__name__)
router = APIRouter(prefix="/inventaire")


async def obtenir_depot() -> AsyncIterator[Depot]:
    depot = service.fabrique()
    if depot is None:
        raise HTTPException(503, "Base de l'inventaire indisponible (PostgreSQL requis).")
    yield depot


def _refus(exc: InventaireRefus) -> HTTPException:
    return HTTPException(exc.statut, {"code": exc.code, "message": exc.message})


def _date(valeur: Any) -> Any:
    return valeur.isoformat() if isinstance(valeur, datetime) else valeur


def _scan_json(scan: dict[str, Any] | None) -> dict[str, Any] | None:
    if scan is None:
        return None
    champs = ("id", "statut", "declencheur", "nb_dossiers", "nb_fichiers", "volume_octets",
              "nb_ajouts", "nb_modifs", "nb_disparus", "nb_erreurs", "message")
    return {**{c: scan.get(c) for c in champs}, "debut": _date(scan.get("debut")), "fin": _date(scan.get("fin"))}


# --------------------------------------------------------------------------- #
# État et réglages                                                             #
# --------------------------------------------------------------------------- #
@router.get("/etat")
async def etat(depot: Depot = Depends(obtenir_depot)) -> dict[str, Any]:
    emplacements = []
    for e in await depot.emplacements():
        emplacements.append({"id": e.id, "libelle": e.libelle, "racine": e.racine, "actif": e.actif,
                             "source": e.source, "poste_id": e.poste_id,
                             "dernier_scan": _scan_json(await depot.dernier_scan(e.id))})
    return {"base": "ok", "emplacements": emplacements}


@router.get("/reglages")
async def lire_reglages() -> dict[str, str]:
    return {cle: runtime_config.effective(cle) for cle in reglages.CLES}


@router.put("/reglages")
async def ecrire_reglages(corps: dict[str, str], db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    try:
        valeurs = reglages.valider(corps)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await runtime_config.set_many(db, valeurs)
    await db.commit()
    return {cle: runtime_config.effective(cle) for cle in reglages.CLES}


# --------------------------------------------------------------------------- #
# Emplacements et scans                                                        #
# --------------------------------------------------------------------------- #
class EmplacementEntrant(BaseModel):
    # `strip_whitespace` AVANT `min_length` : un libellé fait d'espaces est refusé (422).
    libelle: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    racine: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class ActivationEntrante(BaseModel):
    actif: bool


@router.post("/emplacements", status_code=201)
async def creer_emplacement(corps: EmplacementEntrant, depot: Depot = Depends(obtenir_depot)) -> dict[str, Any]:
    try:
        racine = service.racine_normalisee(corps.racine, reglages.lire().racine_autorisee)
        await service.verifier_chevauchement(depot, racine)
        emp = await depot.creer_emplacement(corps.libelle, racine)
    except InventaireRefus as exc:
        raise _refus(exc) from exc
    except DoublonRacine as exc:
        raise HTTPException(409, "Cet emplacement est déjà déclaré.") from exc
    return {"id": emp.id, "libelle": emp.libelle, "racine": emp.racine}


@router.patch("/emplacements/{emplacement_id}")
async def activer_emplacement(emplacement_id: int, corps: ActivationEntrante,
                              depot: Depot = Depends(obtenir_depot)) -> dict[str, Any]:
    if await depot.emplacement(emplacement_id) is None:
        raise HTTPException(404, "Emplacement inconnu.")
    await depot.activer_emplacement(emplacement_id, corps.actif)
    return {"id": emplacement_id, "actif": corps.actif}


@router.post("/emplacements/{emplacement_id}/scan", status_code=202)
async def scanner(emplacement_id: int, depot: Depot = Depends(obtenir_depot),
                  db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        scan_id = await service.ouvrir_scan_manuel(depot, emplacement_id)
    except LookupError as exc:
        raise HTTPException(404, "Emplacement inconnu.") from exc
    except ScanEnCours as exc:
        raise HTTPException(409, "Un scan de cet emplacement est déjà en cours.") from exc
    except InventaireRefus as exc:
        raise _refus(exc) from exc
    try:
        job_id = await job_worker.enqueue(db, service.JOB_SCAN,
                                          {"emplacement_id": emplacement_id, "scan_id": scan_id,
                                           "cible": f"emplacement:{emplacement_id}"})
        await db.commit()
    except Exception:
        # Le scan ouvert ne doit pas bloquer l'emplacement : on le clôt avant de remonter l'erreur.
        await service.clore_en_echec(depot, scan_id, "lancement du scan impossible")
        raise
    return {"scan_id": scan_id, "job_id": job_id, "statut": "demarre"}


@router.get("/emplacements/{emplacement_id}/carte")
async def lire_carte(emplacement_id: int, chemin: str = "",
                     limite: Annotated[int, Query(ge=1, le=1000)] = 200,
                     depot: Depot = Depends(obtenir_depot)) -> dict[str, Any]:
    emp = await depot.emplacement(emplacement_id)
    if emp is None:
        raise HTTPException(404, "Emplacement inconnu.")
    vue = await carte.vue_dossier(depot, emp, chemin, service.maintenant_local(), limite=limite)
    if vue is None:
        raise HTTPException(404, "Dossier inconnu de l'inventaire.")
    sortie = asdict(vue)
    sortie["emplacement"] = {"id": emp.id, "libelle": emp.libelle, "racine": emp.racine, "source": emp.source}
    sortie["dernier_scan"] = _scan_json(vue.dernier_scan)
    sortie["maintenant"] = _date(vue.maintenant)
    return sortie


# --------------------------------------------------------------------------- #
# Import WizTree                                                               #
# --------------------------------------------------------------------------- #
class ImportEntrant(BaseModel):
    nom_pc: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    libelle: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] = ""
    chemin: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


@router.post("/imports", status_code=202)
async def importer(corps: ImportEntrant, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Enfile l'import d'un export WizTree déposé sur le NAS. Le worker relit le fichier, le
    recontrôle (chemin réel, taille, format) et l'inventorie ; le résultat est celui de la tâche."""
    from services.rangement import agent
    try:
        chemin = service.chemin_fichier_import(corps.chemin, reglages.lire().racine_autorisee)
        nom_pc = agent.nom_poste_valide(corps.nom_pc)
    except InventaireRefus as exc:
        raise _refus(exc) from exc
    job_id = await job_worker.enqueue(db, service.JOB_IMPORT,
                                      {"nom_pc": nom_pc, "libelle": corps.libelle, "chemin": chemin,
                                       "cible": f"import:{nom_pc}"})
    await db.commit()
    return {"job_id": job_id, "statut": "demarre"}


# --------------------------------------------------------------------------- #
# Postes (agent de poste, étape 5)                                             #
# --------------------------------------------------------------------------- #
def _poste_json(p, emps) -> dict[str, Any]:
    return {"id": p.id, "nom": p.nom, "actif": p.actif, "version": p.version,
            "dernier_contact": _date(p.dernier_contact), "jeton": p.jeton_id is not None,
            "lecture_jour": _date(p.lecture_jour), "lecture_octets": p.lecture_octets,
            "emplacements": [{"id": e.id, "libelle": e.libelle, "racine": e.racine, "source": e.source,
                              "actif": e.actif} for e in emps if e.poste_id == p.id]}


class PosteEntrant(BaseModel):
    nom: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class DossierDePosteEntrant(BaseModel):
    libelle: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    racine: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


def _nom(acteur: Utilisateur) -> str:
    return getattr(acteur, "identifiant", None) or getattr(acteur, "email", None) or str(acteur.id)


@router.get("/postes")
async def lister_postes(depot: Depot = Depends(obtenir_depot)) -> dict[str, Any]:
    emps = await depot.emplacements()
    return {"postes": [_poste_json(p, emps) for p in await depot.postes()]}


@router.post("/postes", status_code=201)
async def creer_poste(corps: PosteEntrant, acteur: Utilisateur = Depends(admin_identifie),
                      depot: Depot = Depends(obtenir_depot), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Crée le poste et son jeton de portée `agent`, rendu EN CLAIR — la seule fois."""
    try:
        poste, clair = await postes.creer_poste(db, depot, corps.nom, _nom(acteur), acteur.id)
    except InventaireRefus as exc:
        raise _refus(exc) from exc
    log.warning("Poste d'inventaire créé (jeton émis)", poste=poste.nom, acteur=_nom(acteur))
    return {**_poste_json(poste, []), "jeton_clair": clair}


@router.post("/postes/{poste_id}/jeton")
async def nouveau_jeton(poste_id: int, acteur: Utilisateur = Depends(admin_identifie),
                        depot: Depot = Depends(obtenir_depot), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Nouveau jeton (l'ancien est révoqué aussitôt) ; rendu EN CLAIR une seule fois."""
    try:
        clair = await postes.renouveler_jeton(db, depot, poste_id, _nom(acteur), acteur.id)
    except LookupError as exc:
        raise HTTPException(404, "Poste inconnu.") from exc
    log.warning("Jeton de poste renouvelé", poste_id=poste_id, acteur=_nom(acteur))
    return {"id": poste_id, "jeton_clair": clair}


@router.patch("/postes/{poste_id}")
async def activer_poste(poste_id: int, corps: ActivationEntrante,
                        depot: Depot = Depends(obtenir_depot)) -> dict[str, Any]:
    if await depot.poste(poste_id) is None:
        raise HTTPException(404, "Poste inconnu.")
    await depot.activer_poste(poste_id, corps.actif)
    return {"id": poste_id, "actif": corps.actif}


@router.post("/postes/{poste_id}/emplacements", status_code=201)
async def confier_dossier(poste_id: int, corps: DossierDePosteEntrant,
                          depot: Depot = Depends(obtenir_depot)) -> dict[str, Any]:
    """Confie un dossier du PC (ex. `C:\\Users\\Thomas`) à son agent."""
    try:
        emp = await agent_poste.declarer_emplacement(depot, poste_id, corps.libelle, corps.racine, source="agent")
    except LookupError as exc:
        raise HTTPException(404, "Poste inconnu.") from exc
    except InventaireRefus as exc:
        raise _refus(exc) from exc
    return {"id": emp.id, "libelle": emp.libelle, "racine": emp.racine, "poste_id": poste_id}
