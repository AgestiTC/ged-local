"""
Rattrapage de nuit — reprend, chaque nuit et par paquets bornés, ce que rien d'autre ne relance.
==================================================================================================
Remplace le workflow n8n « réindexation » (retiré le 18/11/2026 avec n8n). Celui-ci relançait chaque
nuit TOUTES les erreurs par `POST /api/extract/{id}` — route qui ne sait lire qu'un chemin local (les
documents du NAS répondaient 422) — et ne tournait plus depuis l'activation de l'authentification.

Trois volets, chacun plafonné (`rattrapage_nuit_plafond`, 100 par défaut) :
  1. **erreurs** — documents en erreur, sans texte (Tika saturé, NAS coupé…) → `ia_contenu`,
     qui rapatrie le fichier (local ou SMB) et relance l'extraction ;
  2. **analyse IA** — documents avec texte mais sans catégorie → `ia_enrich` (hors échecs répétés) ;
  3. **vecteurs** — documents avec texte mais sans aucun vecteur, invisibles à la recherche
     sémantique → `ia_embed`.

Garde-fous :
  - un document déjà retenté par le même type de tâche dans les `RECUL_JOURS` derniers jours est
    écarté : un fichier vraiment illisible n'est pas repris chaque nuit ;
  - les tâches enfilées sont des LOTS : elles respectent la pause IA et la plage horaire des tâches
    de fond, et passent après « Créer » ;
  - Tika n'est pas engorgé : une extraction à la fois par processus (`tika_concurrence`).

Passage : une fois par nuit, à `rattrapage_nuit_heure` (« 02:00 » par défaut, heure de Paris), dans une
fenêtre de `FENETRE_H` heures. Pour le couper : plafond à 0 (un réglage vidé revient à son défaut) — un worker redémarré à 10 h ne lance pas le
rattrapage en pleine journée. Le dernier job `rattrapage_nuit` sert de repère (rien en mémoire).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from logger import get_logger
from models.document import Document
from models.job import Job
from services import job_worker, runtime_config

log = get_logger(__name__)

JOB = "rattrapage_nuit"
FENETRE_H = 4
RECUL_JOURS = 7
PLAFOND_DEFAUT = 100
PLAFOND_MAX = 2000

# Volet → (type de tâche enfilé, types qui comptent comme « déjà retenté »).
VOLETS: dict[str, tuple[str, tuple[str, ...]]] = {
    "erreurs": ("ia_contenu", ("ia_contenu", "analyze")),
    "analyse_ia": ("ia_enrich", ("ia_enrich", "enrich")),
    "vecteurs": ("ia_embed", ("ia_embed",)),
}


def maintenant_local() -> datetime:
    """Heure du foyer (la nuit se lit en heure de Paris, pas en UTC du conteneur)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(os.environ.get("TZ") or "Europe/Paris"))
    except Exception:  # noqa: BLE001 — fuseau absent de l'image
        return datetime.now().astimezone()


def lire_plafond(valeur: str | None) -> int:
    """Plafond par volet, borné [0, PLAFOND_MAX] ; illisible → défaut. 0 = rattrapage sans effet. PURE."""
    try:
        n = int(float(valeur)) if valeur not in (None, "") else PLAFOND_DEFAUT
    except (TypeError, ValueError):
        return PLAFOND_DEFAUT
    return max(0, min(n, PLAFOND_MAX))


def passage_du(maintenant: datetime, heure_min: int | None, dernier: datetime | None) -> bool:
    """
    Faut-il enfiler le rattrapage maintenant ? Fonction PURE.

    `maintenant` : heure locale (avec fuseau) ; `heure_min` : minutes depuis minuit (None = coupé) ;
    `dernier` : création du dernier rattrapage (avec fuseau, None = jamais).
    Dû si l'on est dans [heure, heure + FENETRE_H[ et qu'aucun passage n'a eu lieu depuis l'heure du jour.
    """
    if heure_min is None:
        return False
    seuil = maintenant.replace(hour=heure_min // 60, minute=heure_min % 60, second=0, microsecond=0)
    if maintenant < seuil:
        seuil -= timedelta(days=1)          # avant l'heure du jour : la fenêtre est celle de la veille
    if maintenant >= seuil + timedelta(hours=FENETRE_H):
        return False
    return dernier is None or dernier < seuil


def _selecteurs():
    """Sélecteurs déjà utilisés par les boutons de Paramètres › Maintenance (une seule définition)."""
    from routers.documents import _a_reenrichir, _a_vectoriser, _en_echec_repete, _scope_filter
    return {
        "erreurs": select(Document).where(_scope_filter("erreurs")).where(Document.doublon_de.is_(None)),
        "analyse_ia": _a_reenrichir().where(~Document.id.in_(_en_echec_repete())),
        "vecteurs": _a_vectoriser(),
    }


async def executer(db, plafond: int, maintenant_utc: datetime | None = None) -> dict:
    """Enfile les trois volets (sans commit). Rend le nombre de documents remis en file par volet."""
    maintenant_utc = maintenant_utc or datetime.now(timezone.utc)
    recul = maintenant_utc - timedelta(days=RECUL_JOURS)
    bilan: dict[str, int] = {}
    for volet, base in _selecteurs().items():
        type_job, deja_types = VOLETS[volet]
        recents = select(Job.document_id).where(
            Job.type.in_(deja_types), Job.document_id.isnot(None),
            (Job.created_at >= recul) | Job.statut.in_(("pending", "running")),
        )
        docs = [] if plafond <= 0 else (await db.execute(
            base.where(~Document.id.in_(recents)).order_by(Document.updated_at).limit(plafond)
        )).scalars().all()
        for doc in docs:
            parametres = {"document_id": str(doc.id), "cible": doc.nom, "origine": JOB}
            if type_job == "ia_enrich":
                # Comme « Relancer l'IA » : pas de vecteurs recalculés ici, le volet « vecteurs »
                # reprend les documents qui n'en ont aucun.
                parametres["embed"] = False
            await job_worker.enqueue(db, type_job, parametres, document_id=doc.id)
        bilan[volet] = len(docs)
    return bilan


@job_worker.register(JOB)
async def _handler(ctx: job_worker.JobContext) -> dict:
    from database import AsyncSessionLocal

    plafond = lire_plafond(runtime_config.effective("rattrapage_nuit_plafond"))
    await ctx.report(10, "Recherche des documents à reprendre…")
    async with AsyncSessionLocal() as db:
        bilan = await executer(db, plafond)
        await db.commit()
    total = sum(bilan.values())
    log.info("Rattrapage de nuit enfilé", plafond=plafond, total=total, **bilan)
    return {"ok": True, "plafond": plafond, "total": total, **bilan}


async def planifier() -> str | None:
    """Enfile le rattrapage s'il est dû. Rend l'identifiant du job créé, ou None."""
    from sqlalchemy import text

    from database import AsyncSessionLocal, engine

    heure = runtime_config.lire_heure(runtime_config.effective("rattrapage_nuit_heure"))
    maintenant = maintenant_local()
    if heure is None:
        return None
    async with AsyncSessionLocal() as db:
        # Un seul enfilement même si plusieurs process font tourner le planificateur.
        if engine.dialect.name.startswith("postgres") and not (await db.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtext('rattrapage_nuit'))"))).scalar():
            return None
        dernier = (await db.execute(
            select(Job.created_at).where(Job.type == JOB).order_by(Job.created_at.desc()).limit(1)
        )).scalar()
        if dernier is not None and dernier.tzinfo is None:
            dernier = dernier.replace(tzinfo=timezone.utc)   # SQLite (tests) : dates naïves = UTC
        if not passage_du(maintenant, heure, dernier):
            await db.rollback()
            return None
        job_id = await job_worker.enqueue(db, JOB, {"cible": "rattrapage de nuit"})
        await db.commit()
    log.info("Rattrapage de nuit planifié", job_id=job_id)
    return job_id


async def dernier_bilan(db) -> dict | None:
    """Dernier passage (date, statut, bilan) — pour Paramètres › Maintenance."""
    job = (await db.execute(
        select(Job).where(Job.type == JOB).order_by(Job.created_at.desc()).limit(1)
    )).scalars().first()
    if job is None:
        return None
    quand = job.completed_at or job.created_at
    return {"date": quand.isoformat() if quand else None, "statut": job.statut,
            "resultat": job.resultat or None, "erreur": job.erreur}
