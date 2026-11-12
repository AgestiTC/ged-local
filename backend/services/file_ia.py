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

from models.file_ia_etat import FileIAEtat
from models.job import Job
from services import job_worker, runtime_config

LIBELLES = {
    "rapport": "Rapport", "comparatif": "Tableau comparatif", "comparatif_reparer": "Réparation de comparatif",
    "presentation": "Présentation", "fill_template": "Modèle à remplir",
    "analyse_regroupement": "Analyse de regroupement", "musique": "Musique", "video": "Vidéo",
    "enrich": "Enrichissement IA", "analyze": "Analyse de document", "reprise_texte": "Ré-extraction du texte",
    # Les trois étapes du traitement d'un document (plan lots IA par modèle, étape 3).
    "ia_contenu": "Lecture du contenu", "ia_enrich": "Enrichissement IA", "ia_embed": "Indexation sémantique",
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
    # `{n}` : minutes avant que le délai maximal de l'étape en cours force le changement d'étape.
    "autre_etape": "Les documents sont traités par étape, un modèle IA à la fois : celle-ci démarre "
                   "après l'étape en cours (au plus tard dans {n} min).",
    "demarrage": "Démarrage imminent…",
    "aucune": "",
}


def message(motif: str, minutes: int | None = None) -> str:
    """Texte affiché pour un motif d'attente (`{n}` = minutes avant le changement d'étape forcé)."""
    return MESSAGES[motif].replace("{n}", str(max(1, minutes or 1)))


def libelle(type_job: str) -> str:
    return LIBELLES.get(type_job, type_job.replace("_", " ").capitalize())


def _utc(d: datetime | None) -> datetime | None:
    """SQLite (tests) rend des dates naïves, Postgres des dates avec fuseau : tout en UTC."""
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def rang_etape(type_job: str, etape: str | None) -> int:
    """Distance (dans le cycle des étapes) entre l'étape courante et celle du type : 0 = elle part
    maintenant (étape courante, ou lot hors chaîne), 1-2 = elle attend son tour. PURE."""
    propre = job_worker.etape_de(type_job)
    if etape is None or propre is None or etape not in job_worker.ETAPES:
        return 0
    n = len(job_worker.ETAPES)
    return (job_worker.ETAPES.index(propre) - job_worker.ETAPES.index(etape)) % n


def etape_effective(courante: str | None, depuis: datetime | None, en_attente: dict[str, int],
                    maintenant: datetime, delai: timedelta) -> str | None:
    """Étape sur laquelle le worker travaillera à sa prochaine prise (même règle que `_claim`). PURE."""
    return job_worker.choisir_etape(courante, _utc(depuis), en_attente, maintenant, delai)


def ordre(job: dict, etape: str | None = None) -> tuple:
    """Clé d'ordre du worker : forcée, puis « Créer », puis l'étape courante avant les autres
    (`_claim` ne prend QUE l'étape courante), puis FIFO. Fonction PURE."""
    return (0 if job.get("prioritaire") else 1, job_worker.priorite(job["type"]),
            rang_etape(job["type"], etape),
            _utc(job["created_at"]) or datetime.min.replace(tzinfo=timezone.utc))


def devant(cible: dict, en_attente: list[dict], pause: bool, etape: str | None = None) -> list[dict]:
    """Tâches en attente qui partiront AVANT `cible` (en pause, les lots ne partent pas). PURE.
    `etape` : étape courante de la file GPU (None = pas de logique d'étape, FIFO simple)."""
    cle = ordre(cible, etape)
    return sorted((j for j in en_attente
                   if j["id"] != cible["id"] and ordre(j, etape) < cle
                   and not (pause and job_worker.priorite(j["type"]) == 1)),
                  key=lambda j: ordre(j, etape))


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


def raison(cible: dict, pause: bool, nb_en_cours: int, budget: int, nb_devant: int,
           autre_etape: bool = False) -> str:
    if cible["statut"] != "pending":
        return "aucune"
    if pause and job_worker.priorite(cible["type"]) == 1:
        return "pause_ia"
    if autre_etape:   # avant « tâches devant » : ce sont les AUTRES étapes qui attendent la leur
        return "autre_etape"
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

    # Étape courante de la file GPU (en base : `file_ia_etat`) — seulement pour les lots GPU.
    etape = depuis = None
    autre_etape, minutes_etape = False, None
    if classe == "gpu":
        ligne = (await db.execute(select(FileIAEtat).where(FileIAEtat.cle == job_worker.CLE_FILE_GPU))
                 ).scalar_one_or_none()
        depuis = _utc(ligne.depuis) if ligne else None
        compte: dict[str, int] = {}
        for l in en_attente:
            e = job_worker.etape_de(l["type"])
            if e:
                compte[e] = compte.get(e, 0) + 1
        delai = job_worker.delai_etape()
        etape = etape_effective(ligne.etape if ligne else None, depuis, compte, maintenant, delai)
        propre = job_worker.etape_de(job.type)
        if (cible["statut"] == "pending" and not pause and propre and etape and propre != etape
                and job_worker.priorite(job.type) == 1):
            autre_etape = True
            reste = (depuis + delai - maintenant).total_seconds() if depuis else 0
            minutes_etape = max(1, -(-int(max(reste, 0)) // 60))

    avant = devant(cible, en_attente, pause, etape) if cible["statut"] == "pending" else []
    motif = raison(cible, pause, len(en_cours), budget, len(avant), autre_etape)
    estimation = None
    if motif not in ("aucune", "pause_ia"):
        durees = await durees_recentes(db, sorted({l["type"] for l in en_cours + avant + [cible]}))
        secondes = estimer_debut_s(en_cours, avant, budget, durees, maintenant)
        estimation = {"debut": (maintenant + timedelta(seconds=secondes)).isoformat(),
                      "minutes": round(secondes / 60), "plafonnee": secondes >= HORIZON_MAX_S}

    return {
        "job_id": str(job.id), "type": job.type, "libelle": libelle(job.type), "statut": job.statut,
        "raison": motif, "message": message(motif, minutes_etape),
        "etape_courante": etape, "depuis": depuis.isoformat() if depuis else None,
        "position": len(avant) + 1 if cible["statut"] == "pending" else None,
        "nb_devant": len(avant), "devant": [_public(j) for j in avant[:NB_DEVANT_MAX]],
        "en_cours": [_public(j) for j in en_cours], "budget": budget,
        "pause_ia": pause, "prioritaire": bool(job.priorite_forcee),
        # « Continuer » n'a de sens que s'il y a quelqu'un à doubler (capture du 02/11 : proposé en tête).
        "peut_prioriser": cible["statut"] == "pending" and job_worker.priorite(job.type) == 0
                          and not job.priorite_forcee and len(avant) > 0,
        "estimation": estimation,
    }
