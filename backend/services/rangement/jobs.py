"""
Tâches du worker pour l'inventaire (module Rangement) — classe « fond » (`job_worker.FOND_TYPES`).

- `inventaire_scan`   : scan manuel d'un emplacement, ouvert par l'API (`{emplacement_id, scan_id}`) ;
- `inventaire_nuit`   : la tournée de nuit, emplacement par emplacement (`scan.planifier_et_scanner`) ;
- `inventaire_import` : un export WizTree déposé sur le NAS (`{nom_pc, libelle, chemin}`) ;
- `inventaire_envoi`  : l'inventaire envoyé par un agent de poste (`{emplacement_id, envoi_id, scan_id}`) ;
- `inventaire_copies` : une passe des copies sur disque, à la demande (la nuit, elle suit la tournée).

Ces tâches tournent **dans le worker seulement** : c'est lui qui porte le montage du NAS (décision
d'architecture n° 5). `planifier_nuit` est appelé par l'ordonnanceur du worker : il n'enfile la
tournée que dans la fenêtre de nuit, à l'intervalle réglé, et jamais deux fois à la fois.
"""

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select, text

from logger import get_logger
from services import job_worker
from services.rangement import agent, copies, reglages, service, wiztree
from services.rangement.depot import Depot, ScanEnCours
from services.rangement.scan import (
    Scanner,
    dans_fenetre,
    exclusions_de,
    planifier_et_scanner,
    source_pour,
)

log = get_logger(__name__)

#: Verrou d'avis Postgres de l'enfilement de la tournée (arbitraire, propre à ce module).
_VERROU_NUIT = 461_203_877


class InventaireIndisponible(RuntimeError):
    """Pas de base d'inventaire (SQLite, ou PostgreSQL injoignable)."""


def _depot() -> Depot:
    depot = service.fabrique()
    if depot is None:
        raise InventaireIndisponible("Base de l'inventaire indisponible (PostgreSQL requis).")
    return depot


async def executer_scan(depot: Depot, emplacement_id: int, scan_id: int | None,
                        arret: Callable[[], bool] | None = None) -> dict:
    """Corps du scan manuel. Le scan a été ouvert par l'API ; s'il a été clos entre-temps (scan
    orphelin interrompu, reprise du worker), on en ouvre un nouveau plutôt que d'écrire dans un scan
    fermé."""
    emp = await depot.emplacement(emplacement_id)
    if emp is None:
        if scan_id:
            await service.clore_en_echec(depot, scan_id, "emplacement supprimé")
        return {"statut": "echec", "message": "emplacement inconnu"}
    dernier = await depot.dernier_scan(emp.id)
    if not (scan_id and dernier and dernier.get("id") == scan_id and dernier.get("statut") == "en_cours"):
        try:
            scan_id = await depot.ouvrir_scan(emp.id, "manuel")
        except ScanEnCours:
            return {"statut": "ignore", "message": "un autre scan de cet emplacement tourne déjà"}
    r = reglages.lire()
    try:
        exclusions = await exclusions_de(depot, emp, r.exclusions)
        resultat = await Scanner(depot, emp, exclusions, profondeur_instantane=r.profondeur_instantane,
                                 pause_s=r.pause_ms / 1000, declencheur="manuel",
                                 racine_autorisee=r.racine_autorisee or None, arret=arret,
                                 source=await source_pour(emp, exclusions)).executer(scan_id)
        await depot.purger_instantanes(emp.id, r.instantanes_gardes)
    except Exception as exc:
        await service.clore_en_echec(depot, scan_id, type(exc).__name__)
        raise
    c = resultat.compteurs
    return {"statut": resultat.statut, "scan_id": resultat.scan_id, "message": resultat.message,
            "fichiers": c.nb_fichiers, "ajouts": c.nb_ajouts, "modifs": c.nb_modifs,
            "disparus": c.nb_disparus, "erreurs": c.nb_erreurs}


@job_worker.register(service.JOB_SCAN)
async def _handler_scan(ctx: job_worker.JobContext) -> dict:
    p = ctx.parametres
    return await executer_scan(_depot(), int(p["emplacement_id"]), p.get("scan_id"),
                               arret=lambda: ctx.cancelled)


async def _bilan(depot: Depot) -> dict | None:
    try:
        ids = [e.id for e in await depot.emplacements(actifs_seulement=True)]
        b = await depot.bilan_identiques(ids)
        return {"nb_groupes": b.nb_groupes, "recuperable": b.recuperable}
    except Exception:  # noqa: BLE001 — le bilan sert la cloche, jamais au prix de la passe
        log.warning("Bilan des copies illisible", exc_info=True)
        return None


async def _passe_copies(depot: Depot, a_la_demande: bool, arret) -> dict:
    """Une passe des copies, encadrée par le bilan avant/après : la cloche signale les NOUVELLES
    copies (étape 11), pas celles déjà connues."""
    rc = reglages.lire_copies()
    avant = await _bilan(depot)
    resultat = await copies.executer(depot, reglages.lire(), taille_min=rc.taille_min, limite_nuit=rc.limite_nuit,
                                     horloge=service.maintenant_local, a_la_demande=a_la_demande, arret=arret)
    if resultat.get("statut") not in ("ignore",):
        resultat["bilan_avant"], resultat["bilan_apres"] = avant, await _bilan(depot)
    return resultat


@job_worker.register(service.JOB_NUIT)
async def _handler_nuit(ctx: job_worker.JobContext) -> dict:
    """La tournée : les scans d'abord, puis — s'il reste de la nuit — une passe des copies sur disque.
    Les deux dans la même tâche : la classe « fond » n'a qu'une place, et une passe ne lit jamais
    pendant un scan."""
    depot = _depot()
    resultats = await planifier_et_scanner(depot, reglages.lire(), service.maintenant_local(),
                                           arret=lambda: ctx.cancelled)
    passe = None if ctx.cancelled else await _passe_copies(depot, False, lambda: ctx.cancelled)
    return {"scans": [{"scan_id": r.scan_id, "statut": r.statut} for r in resultats], "copies": passe}


@job_worker.register(service.JOB_COPIES)
async def _handler_copies(ctx: job_worker.JobContext) -> dict:
    """Passe des copies à la demande : à toute heure, dans la même limite de lecture par nuit."""
    return await _passe_copies(_depot(), True, lambda: ctx.cancelled)


@job_worker.register(service.JOB_IMPORT)
async def _handler_import(ctx: job_worker.JobContext) -> dict:
    p = ctx.parametres
    return await wiztree.importer(_depot(), str(p.get("nom_pc", "")), str(p.get("libelle", "")),
                                  str(p.get("chemin", "")), reglages.lire().racine_autorisee)


# --------------------------------------------------------------------------- #
# Ordonnanceur de nuit                                                         #
# --------------------------------------------------------------------------- #
def tournee_due(maintenant_local: datetime, derniere: datetime | None, r: reglages.ReglagesInventaire,
                maintenant_utc: datetime) -> bool:
    """Faut-il enfiler la tournée maintenant ? PURE.

    Non si les scans automatiques sont coupés (intervalle 0), hors de la fenêtre de nuit, ou si la
    dernière tournée date de moins d'un intervalle. Le délai minimal ENTRE DEUX SCANS d'un même
    emplacement est appliqué par la tournée elle-même.
    """
    if r.intervalle_min <= 0:
        return False
    if not dans_fenetre(maintenant_local.hour, r.heure_debut, r.heure_fin):
        return False
    if derniere is None:
        return True
    if derniere.tzinfo is None:
        derniere = derniere.replace(tzinfo=timezone.utc)
    return (maintenant_utc - derniere).total_seconds() >= r.intervalle_min * 60


async def planifier_nuit() -> str | None:
    """Enfile la tournée de nuit si elle est due. Rend l'identifiant du job créé, ou None."""
    from database import AsyncSessionLocal, engine
    from models.job import Job

    if not engine.dialect.name.startswith("postgres"):
        return None  # pas de tables d'inventaire sous SQLite
    r = reglages.lire()
    async with AsyncSessionLocal() as db:
        # Un seul enfilement à la fois, même si plusieurs process font tourner l'ordonnanceur.
        if not (await db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _VERROU_NUIT})).scalar():
            return None
        en_vol = (await db.execute(
            select(Job.id).where(Job.type == service.JOB_NUIT, Job.statut.in_(("pending", "running"))).limit(1)
        )).first()
        if en_vol:
            return None
        derniere = (await db.execute(
            select(Job.created_at).where(Job.type == service.JOB_NUIT)
            .order_by(Job.created_at.desc()).limit(1)
        )).scalar()
        if not tournee_due(service.maintenant_local(), derniere, r, datetime.now(timezone.utc)):
            await db.rollback()
            return None
        job_id = await job_worker.enqueue(db, service.JOB_NUIT, {"cible": "inventaire"})
        await db.commit()
    log.info("Tournée d'inventaire enfilée", job_id=job_id)
    return job_id


@job_worker.register(service.JOB_ENVOI)
async def _handler_envoi(ctx: job_worker.JobContext) -> dict:
    """Le scan d'un envoi d'agent : mêmes règles que le NAS (`SourceEnvoi`). L'envoi est effacé."""
    p = ctx.parametres
    depot = _depot()
    envoi_id, scan_id = int(p["envoi_id"]), int(p["scan_id"])
    emp = await depot.emplacement(int(p["emplacement_id"]))
    if emp is None:
        await depot.clore_envoi(envoi_id, "abandonne")
        await service.clore_en_echec(depot, scan_id, "emplacement supprimé")
        return {"statut": "echec", "message": "emplacement inconnu"}
    try:
        statut = await agent.traiter_envoi(depot, emp, envoi_id, scan_id, "agent")
    except Exception as exc:  # noqa: BLE001 — un scan ouvert ne reste jamais « en cours »
        await service.clore_en_echec(depot, scan_id, type(exc).__name__)
        raise
    return {"statut": statut, "scan_id": scan_id, "emplacement_id": emp.id}


# --------------------------------------------------------------------------- #
# Plan de classement (étape 9)                                                 #
# --------------------------------------------------------------------------- #
@job_worker.register("plan_propositions")
async def _handler_plan(ctx: job_worker.JobContext) -> dict:
    """Recalcule les propositions du plan pour un emplacement ; l'IA locale pour ce qu'aucune règle
    ne place (`ia: false` → règles seules). Classe GPU : elle interroge Ollama, en priorité « lot »."""
    from database import AsyncSessionLocal
    from services.rangement import plan

    p = ctx.parametres
    depot = _depot()
    emp = await depot.emplacement(int(p["emplacement_id"]))
    if emp is None:
        return {"statut": "echec", "message": "emplacement inconnu"}
    async with AsyncSessionLocal() as db:
        return await plan.calculer(db, depot, emp, ia=plan.proposer_par_ia if p.get("ia", True) else None,
                                   arret=lambda: ctx.cancelled,
                                   nouveaux_seulement=bool(p.get("nouveaux_seulement")))



# --------------------------------------------------------------------------- #
# Ranger par lots (étape 10)                                                   #
# --------------------------------------------------------------------------- #
async def _lot_et_emplacement(db, lot_id: str):
    import uuid as _uuid

    from models.plan_classement import PlanLot
    lot = await db.get(PlanLot, _uuid.UUID(lot_id))
    if lot is None:
        raise ValueError("lot inconnu")
    depot = _depot()
    emp = await depot.emplacement(lot.emplacement_id)
    if emp is None:
        raise ValueError("emplacement inconnu")
    return lot, emp, depot


async def _rescanner(depot, emp) -> None:
    """Après un rangement ou une annulation, l'inventaire se remet à jour par un scan."""
    from database import AsyncSessionLocal
    try:
        scan_id = await service.ouvrir_scan_manuel(depot, emp.id)
    except Exception:  # noqa: BLE001 — un scan tourne déjà, ou la tournée de nuit s'en chargera
        return
    async with AsyncSessionLocal() as db:
        await job_worker.enqueue(db, service.JOB_SCAN, {"emplacement_id": emp.id, "scan_id": scan_id,
                                                        "cible": f"emplacement:{emp.id}"})
        await db.commit()


@job_worker.register("rangement_appliquer")
async def _handler_ranger(ctx: job_worker.JobContext) -> dict:
    from database import AsyncSessionLocal
    from services.rangement import deplacements
    async with AsyncSessionLocal() as db:
        lot, emp, depot = await _lot_et_emplacement(db, ctx.parametres["lot_id"])
        try:
            lot = await deplacements.appliquer(db, lot, emp, racine_autorisee=reglages.lire().racine_autorisee or None,
                                               arret=lambda: ctx.cancelled)
        except deplacements.RangementRefuse as exc:
            return {"statut": "refuse", "message": str(exc)}
        resultat = {"statut": lot.statut, "message": lot.message}
    await _rescanner(depot, emp)
    return resultat


@job_worker.register("rangement_annuler")
async def _handler_annuler(ctx: job_worker.JobContext) -> dict:
    from database import AsyncSessionLocal
    from services.rangement import deplacements
    async with AsyncSessionLocal() as db:
        lot, emp, depot = await _lot_et_emplacement(db, ctx.parametres["lot_id"])
        try:
            lot = await deplacements.annuler(db, lot, ctx.parametres.get("par"))
        except deplacements.RangementRefuse as exc:
            return {"statut": "refuse", "message": str(exc)}
        resultat = {"statut": lot.statut, "message": lot.message}
    await _rescanner(depot, emp)
    return resultat
