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
from datetime import datetime, timezone
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
from services.rangement import carte, emplacement_smb, postes, reglages, service
from services.rangement.depot import Depot, DoublonRacine, ScanEnCours
from services.rangement.erreurs import InventaireRefus
from services.rangement.scan import contient

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
                             # Emplacement SMB : la Source (son identifiant seul, jamais son secret).
                             "source_id": e.source_id, "partage": e.partage, "sous_dossier": e.sous_dossier,
                             "dernier_scan": _scan_json(await depot.dernier_scan(e.id))})
    # La racine sous laquelle un emplacement du serveur peut être déclaré (réglage) : l'écran s'en sert
    # pour pré-remplir et expliquer le champ, au lieu d'un chemin écrit en dur (14/11/2026).
    return {"base": "ok", "emplacements": emplacements,
            "racine_autorisee": reglages.lire().racine_autorisee or None}


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
async def creer_emplacement(corps: EmplacementEntrant, depot: Depot = Depends(obtenir_depot),
                            db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        racine = service.racine_normalisee(corps.racine, reglages.lire().racine_autorisee)
        await service.verifier_chevauchement(depot, racine)
        emp = await depot.creer_emplacement(corps.libelle, racine)
    except InventaireRefus as exc:
        raise _refus(exc) from exc
    except DoublonRacine as exc:
        raise HTTPException(409, "Cet emplacement est déjà déclaré.") from exc
    # Placé DANS un autre emplacement : le parent connaît encore ce sous-dossier. Tant qu'il n'est pas
    # rescanné, chaque fichier y figurerait deux fois et passerait pour sa propre copie (relevé à
    # l'essai de l'étape 6) : on relance donc son scan, qui saute désormais ce sous-emplacement.
    rescans = []
    for parent in await depot.emplacements(actifs_seulement=True):
        if parent.id == emp.id or not parent.sur_serveur or not contient(parent.racine, racine):
            continue
        try:
            scan_id = await service.ouvrir_scan_manuel(depot, parent.id)
        except (ScanEnCours, InventaireRefus):
            continue   # un scan tourne déjà, ou la tournée de nuit s'en chargera
        await job_worker.enqueue(db, service.JOB_SCAN, {"emplacement_id": parent.id, "scan_id": scan_id,
                                                        "cible": f"emplacement:{parent.id}"})
        rescans.append(parent.id)
    if rescans:
        await db.commit()
    return {"id": emp.id, "libelle": emp.libelle, "racine": emp.racine, "rescans": rescans}


class EmplacementSmbEntrant(BaseModel):
    libelle: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    source_id: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    partage: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    sous_dossier: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = "/"


@router.post("/emplacements/smb", status_code=201)
async def creer_emplacement_smb(corps: EmplacementSmbEntrant, depot: Depot = Depends(obtenir_depot),
                                db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Déclare un dossier du NAS à partir d'une Source « Rangement » : ni montage, ni chemin à taper
    (plan Rangement sur Sources SMB, étape 3). Le dossier est vérifié par SMB avant d'être retenu."""
    try:
        emp = await emplacement_smb.declarer(db, depot, corps.libelle, corps.source_id, corps.partage,
                                             corps.sous_dossier)
    except InventaireRefus as exc:
        raise _refus(exc) from exc
    except DoublonRacine as exc:
        raise HTTPException(409, "Cet emplacement est déjà déclaré.") from exc
    return {"id": emp.id, "libelle": emp.libelle, "racine": emp.racine, "source": emp.source,
            "source_id": emp.source_id, "partage": emp.partage, "sous_dossier": emp.sous_dossier}


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
# Règles de nommage et fichiers mal nommés (16/11/2026)                        #
# --------------------------------------------------------------------------- #
@router.get("/nommage/regles")
async def lire_regles_nommage() -> dict[str, Any]:
    from services.rangement import nommage
    return {"regles": nommage.regles_json(nommage.lire())}


@router.put("/nommage/regles")
async def ecrire_regles_nommage(corps: dict[str, Any], db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """`{catégorie: {actif, format}}` — catégories et formats connus seulement (400 sinon)."""
    from services.rangement import nommage
    try:
        regles = nommage.valider(corps)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    await runtime_config.set_many(db, {nommage.CLE_CONFIG: nommage.en_json(regles)})
    await db.commit()
    return {"regles": nommage.regles_json(nommage.lire())}


@router.get("/emplacements/{emplacement_id}/nommage")
async def lire_nommage(emplacement_id: int, chemin: str = "", depot: Depot = Depends(obtenir_depot),
                       db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Statistiques des noms des fichiers d'un emplacement (ou d'un de ses dossiers), d'après les règles
    de Paramètres › Rangement — règles de nommage. Lecture seule : rien n'est renommé."""
    from services.rangement import nommage_memoire
    emp = await depot.emplacement(emplacement_id)
    if emp is None:
        raise HTTPException(404, "Emplacement inconnu.")
    # Mémorisé (inv_nommage) : relu tant que le scan, les règles et le plan n'ont pas changé.
    return await nommage_memoire.bilan(depot, emp, chemin, await nommage_memoire.rubriques_series(emp, db))


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


# --------------------------------------------------------------------------- #
# Copies sur disque (étape 6)                                                  #
# --------------------------------------------------------------------------- #
@router.post("/copies", status_code=202)
async def lancer_passe_copies(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Lance une passe des copies tout de suite (sinon : chaque nuit, après la tournée). Même limite de
    lecture que la nuit ; la passe reprend là où la précédente s'est arrêtée."""
    job_id = await job_worker.enqueue(db, service.JOB_COPIES, {"cible": "copies"})
    await db.commit()
    return {"job_id": job_id, "statut": "demarre"}


# --------------------------------------------------------------------------- #
# Plan de classement (étape 9) — conception : docs/conception-plan-classement.md #
# --------------------------------------------------------------------------- #
from sqlalchemy import select as _select  # noqa: E402

from models.plan_classement import PlanNoeud, PlanProposition, PlanRegle  # noqa: E402
from services import audit  # noqa: E402
from services.rangement import plan as plan_classement  # noqa: E402


def _noeud_json(n: PlanNoeud) -> dict[str, Any]:
    return {"id": n.id, "partage": n.partage, "parent_id": n.parent_id, "nom": n.nom, "chemin": n.chemin,
            "gabarit": n.gabarit, "verrouille": n.verrouille, "origine": n.origine, "description": n.description}


def _regle_json(r: PlanRegle) -> dict[str, Any]:
    return {"id": r.id, "priorite": r.priorite, "type": r.type, "valeur": r.valeur, "noeud_id": r.noeud_id,
            "active": r.active, "origine": r.origine, "description": r.description,
            "valide_par": r.valide_par, "valide_le": _date(r.valide_le)}


def _proposition_json(p: PlanProposition) -> dict[str, Any]:
    return {"id": p.id, "emplacement_id": p.emplacement_id, "chemin": p.chemin, "est_dossier": p.est_dossier,
            "taille": p.taille, "destination": p.destination, "noeud_id": p.noeud_id, "regle_id": p.regle_id,
            "par": p.par, "raison": p.raison, "confiance": p.confiance, "statut": p.statut,
            "contenu": bool(p.contenu), "nouveau_nom": p.nouveau_nom,
            "valide_par": p.valide_par, "valide_le": _date(p.valide_le), "calcule_le": _date(p.calcule_le)}


def _nom_valide(nom: str) -> str:
    nom = (nom or "").strip()
    if not nom or len(nom) > 100 or nom in (".", "..") or any(ch in nom for ch in '/\\\x00'):
        raise HTTPException(400, "Nom de dossier invalide (ni « / », ni « \\ », 100 caractères au plus).")
    return nom


@router.get("/plan")
async def lire_plan(partage: str | None = None, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    q = _select(PlanNoeud).order_by(PlanNoeud.partage, PlanNoeud.chemin)
    if partage:
        q = q.where(PlanNoeud.partage == partage)
    noeuds = (await db.execute(q)).scalars().all()
    ids = {n.id for n in noeuds}
    regles = [r for r in (await db.execute(_select(PlanRegle).order_by(PlanRegle.priorite, PlanRegle.id)))
              .scalars().all() if not partage or r.noeud_id in ids]
    return {"noeuds": [_noeud_json(n) for n in noeuds], "regles": [_regle_json(r) for r in regles],
            "types_regle": list(plan_classement.TYPES_REGLE)}


@router.post("/plan/modele/{emplacement_id}")
async def charger_modele(emplacement_id: int, depot: Depot = Depends(obtenir_depot),
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Charge le modèle de départ du partage de cet emplacement (aujourd'hui : `media`, C5/C6)."""
    emp = await depot.emplacement(emplacement_id)
    if emp is None:
        raise HTTPException(404, "Emplacement inconnu.")
    try:
        return await plan_classement.charger_modele_media(db, depot, emp)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class NoeudEntrant(BaseModel):
    partage: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    nom: str
    parent_id: int | None = None
    description: str | None = None
    gabarit: str | None = None


class NoeudModifie(BaseModel):
    nom: str | None = None
    description: str | None = None
    gabarit: str | None = None


@router.post("/plan/noeuds", status_code=201)
async def creer_noeud(corps: NoeudEntrant, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    nom = _nom_valide(corps.nom)
    chemin = nom
    if corps.parent_id is not None:
        parent = await db.get(PlanNoeud, corps.parent_id)
        if parent is None or parent.partage != corps.partage:
            raise HTTPException(404, "Dossier parent inconnu dans ce partage.")
        chemin = f"{parent.chemin}/{nom}"
    if (await db.execute(_select(PlanNoeud).where(PlanNoeud.partage == corps.partage,
                                                   PlanNoeud.chemin == chemin))).scalars().first():
        raise HTTPException(409, "Ce dossier existe déjà dans le plan.")
    n = PlanNoeud(partage=corps.partage, parent_id=corps.parent_id, nom=nom, chemin=chemin,
                  description=(corps.description or None), gabarit=(corps.gabarit or None), origine="humain")
    db.add(n)
    await db.commit()
    return _noeud_json(n)


@router.patch("/plan/noeuds/{noeud_id}")
async def modifier_noeud(noeud_id: int, corps: NoeudModifie, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    n = await db.get(PlanNoeud, noeud_id)
    if n is None:
        raise HTTPException(404, "Dossier du plan inconnu.")
    if corps.nom is not None and corps.nom.strip() != n.nom:
        if n.verrouille:
            raise HTTPException(409, "Ce dossier est verrouillé : un autre logiciel dépend de son nom (Plex).")
        nom = _nom_valide(corps.nom)
        ancien = n.chemin
        n.nom = nom
        n.chemin = f"{ancien.rsplit('/', 1)[0]}/{nom}" if "/" in ancien else nom
        for d in (await db.execute(_select(PlanNoeud).where(PlanNoeud.partage == n.partage,
                                                             PlanNoeud.chemin.like(ancien + "/%")))).scalars().all():
            d.chemin = n.chemin + d.chemin[len(ancien):]
    if corps.description is not None:
        n.description = corps.description.strip() or None
    if corps.gabarit is not None:
        n.gabarit = corps.gabarit.strip() or None
    await db.commit()
    return _noeud_json(n)


@router.delete("/plan/noeuds/{noeud_id}")
async def supprimer_noeud(noeud_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    n = await db.get(PlanNoeud, noeud_id)
    if n is None:
        raise HTTPException(404, "Dossier du plan inconnu.")
    if n.verrouille:
        raise HTTPException(409, "Ce dossier est verrouillé : il ne se supprime pas du plan.")
    if (await db.execute(_select(PlanRegle.id).where(PlanRegle.noeud_id == n.id))).first():
        raise HTTPException(409, "Des règles visent ce dossier : retire-les d'abord.")
    await db.delete(n)
    await db.commit()
    return {"id": noeud_id, "supprime": True}


class RegleEntrante(BaseModel):
    type: str
    valeur: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    noeud_id: int
    priorite: int = 100
    description: str | None = None
    active: bool = True


class RegleModifiee(BaseModel):
    active: bool | None = None
    priorite: int | None = None


@router.post("/plan/regles", status_code=201)
async def creer_regle(corps: RegleEntrante, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    if corps.type not in plan_classement.TYPES_REGLE:
        raise HTTPException(400, f"Type de règle inconnu : {corps.type}")
    if await db.get(PlanNoeud, corps.noeud_id) is None:
        raise HTTPException(404, "Dossier cible inconnu.")
    qui = audit.auteur_courant()
    r = PlanRegle(type=corps.type, valeur=corps.valeur, noeud_id=corps.noeud_id, priorite=corps.priorite,
                  description=(corps.description or None), active=corps.active, origine="humain",
                  valide_par=qui if corps.active else None,
                  valide_le=datetime.now(timezone.utc) if corps.active else None)
    db.add(r)
    await db.commit()
    return _regle_json(r)


@router.patch("/plan/regles/{regle_id}")
async def modifier_regle(regle_id: int, corps: RegleModifiee, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    r = await db.get(PlanRegle, regle_id)
    if r is None:
        raise HTTPException(404, "Règle inconnue.")
    if corps.active is not None and corps.active != r.active:
        r.active = corps.active
        if corps.active:   # activer une règle = la valider : qui, quand
            r.valide_par, r.valide_le = audit.auteur_courant(), datetime.now(timezone.utc)
    if corps.priorite is not None:
        r.priorite = corps.priorite
    await db.commit()
    return _regle_json(r)


@router.delete("/plan/regles/{regle_id}")
async def supprimer_regle(regle_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    r = await db.get(PlanRegle, regle_id)
    if r is None:
        raise HTTPException(404, "Règle inconnue.")
    await db.delete(r)
    await db.commit()
    return {"id": regle_id, "supprime": True}


@router.post("/plan/calcul/{emplacement_id}", status_code=202)
async def calculer_propositions(emplacement_id: int, ia: bool = True, depot: Depot = Depends(obtenir_depot),
                                db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Recalcule les propositions (tâche du worker : l'IA locale peut prendre du temps)."""
    if await depot.emplacement(emplacement_id) is None:
        raise HTTPException(404, "Emplacement inconnu.")
    job_id = await job_worker.enqueue(db, "plan_propositions", {"emplacement_id": emplacement_id, "ia": ia,
                                                               "cible": f"emplacement:{emplacement_id}"})
    await db.commit()
    return {"job_id": job_id, "statut": "demarre"}


@router.post("/plan/titres/{emplacement_id}", status_code=202)
async def calculer_titres(emplacement_id: int, depot: Depot = Depends(obtenir_depot),
                          db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Propose de renommer les épisodes rangés en « Série - S01E01 - Titre » d'après Plex (tâche du worker)."""
    if await depot.emplacement(emplacement_id) is None:
        raise HTTPException(404, "Emplacement inconnu.")
    if not (runtime_config.effective("plex_url") or "").strip():
        raise HTTPException(400, "Plex n'est pas configuré (Paramètres › Plex).")
    job_id = await job_worker.enqueue(db, "plan_titres_episodes", {"emplacement_id": emplacement_id,
                                                                   "cible": f"emplacement:{emplacement_id}"})
    await db.commit()
    return {"job_id": job_id, "statut": "demarre"}


@router.get("/plan/propositions")
async def lister_propositions(emplacement_id: int, statut: str | None = None,
                              db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    q = _select(PlanProposition).where(PlanProposition.emplacement_id == emplacement_id)
    if statut:
        q = q.where(PlanProposition.statut == statut)
    props = (await db.execute(q.order_by(PlanProposition.taille.desc()))).scalars().all()
    compte: dict[str, int] = {}
    for p in props:
        compte[p.statut] = compte.get(p.statut, 0) + 1
    return {"propositions": [_proposition_json(p) for p in props], "compte": compte}


class Decision(BaseModel):
    statut: str
    destination: str | None = None


@router.post("/plan/propositions/{proposition_id}/decision")
async def decider_proposition(proposition_id: int, corps: Decision, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    p = await db.get(PlanProposition, proposition_id)
    if p is None:
        raise HTTPException(404, "Proposition inconnue.")
    try:
        await plan_classement.decider(db, p, corps.statut, audit.auteur_courant(), corps.destination)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _proposition_json(p)


@router.post("/plan/regles/{regle_id}/valider-propositions")
async def valider_par_regle(regle_id: int, emplacement_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Valide d'un coup les propositions encore ouvertes d'une même règle (pour cet emplacement)."""
    props = (await db.execute(_select(PlanProposition).where(
        PlanProposition.emplacement_id == emplacement_id, PlanProposition.regle_id == regle_id,
        PlanProposition.statut == "proposee"))).scalars().all()
    qui, maintenant = audit.auteur_courant(), datetime.now(timezone.utc)
    for p in props:
        p.statut, p.valide_par, p.valide_le = "validee", qui, maintenant
    await db.commit()
    return {"validees": len(props)}


@router.post("/plan/renommages/valider")
async def valider_renommages(emplacement_id: int, serie: str | None = None,
                             db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Valide d'un coup les RENOMMAGES d'épisodes encore ouverts — ceux d'une série
    (`<rubrique>/<série>/…`, casse ignorée) ou tous. Ils n'ont pas de règle : sans ça, un clic par fichier."""
    props = (await db.execute(_select(PlanProposition).where(
        PlanProposition.emplacement_id == emplacement_id, PlanProposition.nouveau_nom.is_not(None),
        PlanProposition.est_dossier.is_(False), PlanProposition.statut == "proposee"))).scalars().all()
    if serie is not None:
        cible = serie.casefold()
        props = [p for p in props if len(p.chemin.split("/")) > 2 and p.chemin.split("/")[1].casefold() == cible]
    qui, maintenant = audit.auteur_courant(), datetime.now(timezone.utc)
    for p in props:
        p.statut, p.valide_par, p.valide_le = "validee", qui, maintenant
    await db.commit()
    return {"validees": len(props)}



# --------------------------------------------------------------------------- #
# Ranger par lots, avec annulation (étape 10)                                  #
# --------------------------------------------------------------------------- #
from models.plan_classement import PlanLot  # noqa: E402
from services.rangement import deplacements  # noqa: E402


def _lot_json(lot: PlanLot) -> dict[str, Any]:
    return {"id": str(lot.id), "emplacement_id": lot.emplacement_id, "libelle": lot.libelle, "statut": lot.statut,
            "operations": lot.operations, "nb": lot.nb, "octets": lot.octets, "message": lot.message,
            "cree_par": lot.cree_par, "cree_le": _date(lot.cree_le), "range_le": _date(lot.range_le),
            "annule_par": lot.annule_par, "annule_le": _date(lot.annule_le)}


class LotEntrant(BaseModel):
    emplacement_id: int
    proposition_ids: list[int] | None = None
    libelle: str = ""


@router.post("/rangement/apercu")
async def apercu_lot(corps: LotEntrant, depot: Depot = Depends(obtenir_depot),
                     db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Ce que ferait un lot, sans rien créer ni déplacer."""
    emp = await depot.emplacement(corps.emplacement_id)
    if emp is None:
        raise HTTPException(404, "Emplacement inconnu.")
    try:
        ops = await deplacements.apercu(db, depot, emp, corps.proposition_ids)
    except deplacements.RangementRefuse as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"operations": ops, "nb": len(ops), "octets": sum(o["taille"] for o in ops)}


@router.post("/rangement/lots", status_code=201)
async def creer_lot(corps: LotEntrant, depot: Depot = Depends(obtenir_depot),
                    db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    emp = await depot.emplacement(corps.emplacement_id)
    if emp is None:
        raise HTTPException(404, "Emplacement inconnu.")
    try:
        lot = await deplacements.creer_lot(db, depot, emp, corps.libelle, audit.auteur_courant(), corps.proposition_ids)
    except deplacements.RangementRefuse as exc:
        raise HTTPException(400, str(exc)) from exc
    return _lot_json(lot)


@router.get("/rangement/lots")
async def lister_lots(emplacement_id: int | None = None, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    q = _select(PlanLot).order_by(PlanLot.cree_le.desc()).limit(100)
    if emplacement_id is not None:
        q = q.where(PlanLot.emplacement_id == emplacement_id)
    return {"lots": [_lot_json(lot) for lot in (await db.execute(q)).scalars().all()]}


async def _lancer(db: AsyncSession, lot_id: str, type_job: str, attendus: tuple[str, ...],
                  extra: dict[str, Any] | None = None) -> dict[str, Any]:
    import uuid as _uuid
    try:
        lot = await db.get(PlanLot, _uuid.UUID(lot_id))
    except ValueError:
        lot = None
    if lot is None:
        raise HTTPException(404, "Lot inconnu.")
    if lot.statut not in attendus:
        raise HTTPException(409, f"Ce lot est « {lot.statut} ».")
    job_id = await job_worker.enqueue(db, type_job, {"lot_id": lot_id, "par": audit.auteur_courant(),
                                                     "cible": f"lot:{lot.libelle}", **(extra or {})})
    await db.commit()
    return {"job_id": job_id, "statut": "demarre"}


@router.post("/rangement/lots/{lot_id}/appliquer", status_code=202)
async def appliquer_lot(lot_id: str, retirer_vides: bool = False, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Range le lot (tâche du worker). `retirer_vides` : retire ensuite les dossiers que le lot a vidés."""
    return await _lancer(db, lot_id, "rangement_appliquer", ("pret",), {"retirer_vides": retirer_vides})


@router.post("/rangement/lots/{lot_id}/retirer-vides", status_code=202)
async def retirer_vides_lot(lot_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Retire les dossiers que ce lot a vidés (packs de série…), s'ils sont vides. Annuler le lot les recrée."""
    return await _lancer(db, lot_id, "rangement_retirer_vides", ("range", "partiel"))


@router.post("/rangement/lots/{lot_id}/annuler", status_code=202)
async def annuler_lot(lot_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Annule CE lot (et lui seul) : chaque fichier revient à sa place ; le journal garde tout."""
    return await _lancer(db, lot_id, "rangement_annuler", ("range", "partiel", "annule_partiel"))
