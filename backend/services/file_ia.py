"""
File IA lisible — « pourquoi ma tâche attend, derrière quoi, jusqu'à quand ».
===============================================================================
Plan docs/plan-file-ia-priorites.md, étape 2 (02/11/2026). Le comparatif affichait « d'autres tâches
IA passent avant » alors que RIEN ne tournait (une pause IA oubliée) : le message mentait sur la
cause et l'utilisateur ne pouvait rien faire.

Ici : la VRAIE raison de l'attente, la position, ce qui tourne et ce qui passe devant, et un repère
temporel estimé sur les durées réelles récentes. Même ordre que le worker (`job_worker._claim`) :
forcée (« Continuer ») > « Créer » (interactif) > lots, puis FIFO ; en pause, seuls les « Créer »
partent.

Confidentialité : une tâche y est décrite par son TYPE (libellé générique), sa date et son
avancement — jamais par ses paramètres (noms de documents, candidats…). Le rôle utilisateur voit la
file, pas le contenu des tâches d'autrui.
"""
from __future__ import annotations

import heapq
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.job import Job
from services import job_worker, runtime_config

LIBELLES = {
    "rapport": "Rapport", "comparatif": "Tableau comparatif", "comparatif_reparer": "Réparation de comparatif",
    "presentation": "Présentation", "fill_template": "Modèle à remplir",
    "analyse_regroupement": "Analyse de regroupement", "musique": "Musique", "video": "Vidéo",
    "enrich": "Enrichissement IA", "analyze": "Analyse de document", "reprise_texte": "Ré-extraction du texte",
    "indexation": "Indexation", "index_wiki": "Indexation du wiki", "index_connector": "Indexation d'un connecteur",
    "idees_evolution": "Idées d'évolution", "scan_finaliser": "Finalisation de numérisation",
    "sync_source": "Synchronisation", "reorg_apply": "Réorganisation",
}
# Durée par défaut (s) quand aucun historique récent n'existe pour ce type.
DUREE_DEFAUT_S = {"comparatif": 300, "comparatif_reparer": 120, "rapport": 180, "presentation": 240,
                  "fill_template": 120, "analyse_regroupement": 180, "musique": 300, "video": 600}
DUREE_DEFAUT_AUTRES_S = 60
HORIZON_MAX_S = 24 * 3600       # au-delà, une estimation ne veut plus rien dire
NB_DEVANT_MAX = 10              # la liste affichée ; le nombre total reste exact
FENETRE_HISTORIQUE = timedelta(days=7)

MESSAGES = {
    "pause_ia": "L'IA est en pause pour les tâches de fond : celle-ci démarrera à la reprise.",
    "taches_devant": "D'autres tâches IA passent avant celle-ci.",
    "gpu_occupe": "La carte graphique est occupée : la tâche démarre dès qu'un créneau se libère.",
    "demarrage": "Démarrage imminent…",
    "aucune": "",
}


def libelle(type_job: str) -> str:
    return LIBELLES.get(type_job, type_job.replace("_", " ").capitalize())


def _utc(d: datetime | None) -> datetime | None:
    """SQLite (tests) rend des dates naïves, Postgres des dates avec fuseau : tout en UTC."""
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def ordre(job: dict) -> tuple:
    """Clé d'ordre du worker : forcée, puis « Créer », puis FIFO. Fonction PURE."""
    return (0 if job.get("prioritaire") else 1, job_worker.priorite(job["type"]),
            _utc(job["created_at"]) or datetime.min.replace(tzinfo=timezone.utc))


def devant(cible: dict, en_attente: list[dict], pause: bool) -> list[dict]:
    """Tâches en attente qui partiront AVANT `cible` (en pause, les lots ne partent pas). PURE."""
    cle = ordre(cible)
    return sorted((j for j in en_attente
                   if j["id"] != cible["id"] and ordre(j) < cle
                   and not (pause and job_worker.priorite(j["type"]) == 1)), key=ordre)


def duree(type_job: str, durees: dict[str, float]) -> float:
    return durees.get(type_job) or DUREE_DEFAUT_S.get(type_job, DUREE_DEFAUT_AUTRES_S)


def estimer_debut_s(en_cours: list[dict], avant: list[dict], budget: int,
                    durees: dict[str, float], maintenant: datetime) -> float:
    """
    Secondes avant le démarrage : simulation des créneaux (`budget` en parallèle), occupés par les
    tâches en cours (durée médiane − temps déjà écoulé), puis remplis par celles de devant. PURE.
    """
    creneaux = [max(0.0, duree(j["type"], durees) - (maintenant - _utc(j["started_at"])).total_seconds())
                if j.get("started_at") else duree(j["type"], durees) for j in en_cours]
    creneaux += [0.0] * max(0, budget - len(creneaux))
    heapq.heapify(creneaux)
    for j in avant:
        heapq.heappush(creneaux, heapq.heappop(creneaux) + duree(j["type"], durees))
    return min(heapq.heappop(creneaux), HORIZON_MAX_S)


def raison(cible: dict, pause: bool, nb_en_cours: int, budget: int, nb_devant: int) -> str:
    if cible["statut"] != "pending":
        return "aucune"
    if pause and job_worker.priorite(cible["type"]) == 1:
        return "pause_ia"
    if nb_devant:
        return "taches_devant"
    if nb_en_cours >= budget:
        return "gpu_occupe"
    return "demarrage"


def _public(j: dict) -> dict:
    """Ce qu'on montre d'une tâche : type, libellé, depuis, avancement — jamais ses paramètres."""
    depuis = _utc(j.get("started_at") or j.get("created_at"))
    return {"type": j["type"], "libelle": libelle(j["type"]), "statut": j["statut"],
            "depuis": depuis.isoformat() if depuis else None, "avancement": j.get("progress") or 0,
            "prioritaire": bool(j.get("prioritaire")), "creer": job_worker.priorite(j["type"]) == 0}


def _ligne(job: Job) -> dict:
    return {"id": str(job.id), "type": job.type, "statut": job.statut, "created_at": job.created_at,
            "started_at": job.started_at, "progress": job.progress, "prioritaire": bool(job.priorite_forcee)}


async def durees_recentes(db: AsyncSession, types: list[str]) -> dict[str, float]:
    """Durée MÉDIANE (s) par type, sur les tâches terminées des 7 derniers jours."""
    depuis = datetime.now(timezone.utc) - FENETRE_HISTORIQUE
    rows = (await db.execute(
        select(Job.type, Job.started_at, Job.completed_at)
        .where(Job.statut == "completed", Job.type.in_(types), Job.completed_at >= depuis,
               Job.started_at.is_not(None))
        .order_by(Job.completed_at.desc()).limit(2000)
    )).all()
    par_type: dict[str, list[float]] = {}
    for type_job, debut, fin in rows:
        secondes = (_utc(fin) - _utc(debut)).total_seconds()
        if secondes > 0:
            par_type.setdefault(type_job, []).append(secondes)
    return {t: median(v) for t, v in par_type.items()}


async def etat_file(db: AsyncSession, job: Job) -> dict:
    """État de la file vu depuis `job` (même classe de budget : GPU ou I/O)."""
    classe = job_worker.classe_tache(job.type)
    gpu = sorted(job_worker.GPU_TYPES)
    meme_classe = Job.type.in_(gpu) if classe == "gpu" else Job.type.notin_(gpu)
    pause = classe == "gpu" and runtime_config.ia_en_pause()
    budget = job_worker._budget(classe)
    maintenant = datetime.now(timezone.utc)

    actifs = (await db.execute(
        select(Job).where(Job.statut.in_(("pending", "running")), meme_classe)
        .order_by(Job.created_at).limit(500)
    )).scalars().all()
    lignes = [_ligne(j) for j in actifs]
    en_cours = [l for l in lignes if l["statut"] == "running"]
    en_attente = [l for l in lignes if l["statut"] == "pending"]
    cible = _ligne(job)

    avant = devant(cible, en_attente, pause) if cible["statut"] == "pending" else []
    motif = raison(cible, pause, len(en_cours), budget, len(avant))
    estimation = None
    if motif not in ("aucune", "pause_ia"):
        durees = await durees_recentes(db, sorted({l["type"] for l in en_cours + avant + [cible]}))
        secondes = estimer_debut_s(en_cours, avant, budget, durees, maintenant)
        estimation = {"debut": (maintenant + timedelta(seconds=secondes)).isoformat(),
                      "minutes": round(secondes / 60), "plafonnee": secondes >= HORIZON_MAX_S}

    return {
        "job_id": str(job.id), "type": job.type, "libelle": libelle(job.type), "statut": job.statut,
        "raison": motif, "message": MESSAGES[motif],
        "position": len(avant) + 1 if cible["statut"] == "pending" else None,
        "nb_devant": len(avant), "devant": [_public(j) for j in avant[:NB_DEVANT_MAX]],
        "en_cours": [_public(j) for j in en_cours], "budget": budget,
        "pause_ia": pause, "prioritaire": bool(job.priorite_forcee),
        "peut_prioriser": cible["statut"] == "pending" and job_worker.priorite(job.type) == 0
                          and not job.priorite_forcee,
        "estimation": estimation,
    }
