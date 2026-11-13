"""
Worker de tâches durables — file `jobs` en base
================================================
Un worker asyncio unique, démarré au startup, consomme les jobs `pending` de la table
`jobs` (FIFO), les exécute via un **handler enregistré par type**, écrit progression et
résultat **en base** (donc consultables depuis n'importe où / survivent au changement de
page ou à la fermeture du navigateur). Au démarrage, les jobs restés `running` après un
crash sont **remis en attente** (reprise).

Enregistrer un handler ::

    from services import job_worker

    @job_worker.register("mon_type")
    async def _handler(ctx: job_worker.JobContext) -> dict:
        await ctx.report(progress=50, message="à mi-parcours…")
        if ctx.cancelled:
            return {}
        return {"resultat": "..."}

Mettre un job en file (dans un endpoint) ::

    job_id = await job_worker.enqueue(db, "mon_type", {"param": 1})
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import case, func, literal, or_, select, text, update

from database import AsyncSessionLocal, engine
from logger import get_logger
from models.file_ia_etat import FileIAEtat
from models.job import Job
from services import classement_echecs

log = get_logger(__name__)

# Concurrence PAR CLASSE de tâche. Presque tout le travail « intelligent » tape sur le même
# GPU (Ollama) : enrichissement, vision, embeddings, transcription… Les faire tourner à 4 en
# parallèle ne va PAS plus vite (Ollama sérialise sur la VRAM, RTX 4080 16 Go) et risque l'OOM.
# On distingue donc deux budgets :
#   - `gpu` : tâches qui sollicitent Ollama (LLM/vision/embeddings) → plafond bas (VRAM) ;
#   - `io`  : tâches réseau/disque (synchro NAS sans changement, réorganisation) → slots EN PLUS,
#             elles tournent librement À CÔTÉ des tâches GPU au lieu d'attendre derrière.
CONCURRENCE_GPU = 2
CONCURRENCE_IO = 3
# Rétro-compat (logs de démarrage) : capacité totale théorique.
CONCURRENCE = CONCURRENCE_GPU + CONCURRENCE_IO

# Types qui sollicitent Ollama (GPU). Tout type ABSENT de cet ensemble est réputé « io »
# (réseau/disque). Le défaut « io » est volontaire : un nouveau handler oublié ici ne monopolisera
# jamais le budget GPU — au pire il partage les slots I/O. `sync_source` est classé `io` car sa
# raison d'être est d'être quasi gratuit quand rien n'a changé (ne réveille ni Tika ni Ollama).
GPU_TYPES: frozenset[str] = frozenset({
    "enrich", "analyze", "reprise_texte", "ia_contenu", "ia_enrich", "ia_embed", "musique", "video", "presentation", "fill_template", "analyse_regroupement", "comparatif", "rapport", "idees_evolution", "comparatif_reparer",
    "index_wiki",
    "plan_propositions",   # plan de classement : propositions de l'IA (Rangement, étape 9)
    "scan_finaliser",  # assemble puis indexe AVEC l'IA immédiate (`differer_ia=False` : l'utilisateur attend sa fiche)
})
# `indexation` et `index_connector` ne sont PLUS des tâches GPU (étape 3 du plan lots IA) : depuis que
# `process_file` diffère l'IA (jobs `ia_enrich` / `ia_embed`), elles ne font que Tika, ClamAV, le
# catalogage et la transcription audio — aucun appel Ollama, ni direct ni via un service (vérifié par
# lecture : `_index_local`, `_index_smb`, `connector_jobs`). La transcription (Voxtral) sollicite pourtant
# la même carte : elle est bornée à UNE à la fois par processus (`transcription_service`), de sorte que
# les 3 slots io ne puissent pas lancer 3 transcriptions simultanées hors budget GPU.


# Classe « fond » (plan rangement + mails, étape 4) : les parcours d'inventaire du NAS. Un scan de 15 To
# dure des heures ; dans la classe `io`, il prendrait une des 3 places des synchros et de l'indexation.
# Il a donc SA place, une seule (un scan à la fois : le NAS respire, la mémoire du worker aussi), et ne
# dépend ni de la pause IA ni de la plage horaire des lots (aucun appel à Ollama).
FOND_TYPES: frozenset[str] = frozenset({"inventaire_scan", "inventaire_nuit", "inventaire_import",
                                       "inventaire_envoi", "inventaire_copies",
                                       "rangement_appliquer", "rangement_annuler"})
CONCURRENCE_FOND = 1
CLASSES: tuple[str, ...] = ("gpu", "io", "fond")


def classe_tache(type_job: str) -> str:
    """Classe d'une tâche pour le budget de concurrence : 'gpu' (Ollama), 'fond' (inventaire) ou 'io'.
    Fonction PURE."""
    if type_job in GPU_TYPES:
        return "gpu"
    return "fond" if type_job in FOND_TYPES else "io"


# Tâches qu'un utilisateur ATTEND devant son écran : elles passent devant les lots (analyse d'images,
# relance IA en masse…) au sein de leur classe. Sans ça, un tableau comparatif demandé pendant un lot
# de 2 000 analyses attendait des heures en FIFO (18/09/2026). Règle « interactif > batch » de la
# passerelle IA locale (docs/passerelle-ia-locale.md).
#
# 02/11/2026 (décision 2, docs/plan-file-ia-priorites.md) : ce sont les tâches de « Créer » — et la
# PAUSE IA ne les retient plus. Une pause oubliée du 31/10 au 02/11 avait bloqué deux comparatifs
# deux jours ; la pause sert à céder le GPU aux LOTS d'un autre usage, pas à refuser une demande
# faite à l'écran (AIGUILLEUR : « pause IA = priorité batch à zéro »).
INTERACTIF_TYPES: frozenset[str] = frozenset({
    "rapport", "comparatif", "comparatif_reparer", "presentation", "fill_template", "analyse_regroupement",
    "musique", "video",
})


def priorite(type_job: str) -> int:
    """0 = interactif (servi d'abord), 1 = lot. Fonction PURE — même règle que l'ORDER BY de `_claim`."""
    return 0 if type_job in INTERACTIF_TYPES else 1


# ─── Étapes du traitement d'un document (plan lots IA par modèle, étape 3) ───────────────────
# Un document passe par TROIS jobs chaînés, chacun limité à un modèle IA : le contenu (Tika, puis
# vision si le texte est vide), l'enrichissement (LLM), les embeddings. Avant, un seul job enchaînait
# les trois modèles : deux documents en vol demandaient deux modèles à la fois, et le troisième en
# évinçait un (~1 840 chargements de modèle par jour). `_claim` reste désormais sur la même étape
# tant qu'il en reste, pour que les places GPU travaillent sur le même modèle.
ETAPES: tuple[str, ...] = ("contenu", "enrich", "embed")
# Les anciens types (`analyze`, `enrich`, `reprise_texte`) restent acceptés le temps que la file se
# vide : ils déroulent la nouvelle chaîne et suivent l'étape qui correspond à leur premier travail.
TYPES_ETAPE: dict[str, frozenset[str]] = {
    "contenu": frozenset({"ia_contenu", "analyze", "reprise_texte"}),
    "enrich": frozenset({"ia_enrich", "enrich"}),
    "embed": frozenset({"ia_embed"}),
}
_ETAPE_DE_TYPE: dict[str, str] = {t: e for e, ts in TYPES_ETAPE.items() for t in ts}
CLE_FILE_GPU = "gpu"
# Délai maximal qu'une étape garde la carte quand les autres attendent (réglage, en minutes).
DELAI_ETAPE_DEFAUT_MIN, DELAI_ETAPE_MIN, DELAI_ETAPE_MAX = 20, 1, 240


def etape_de(type_job: str) -> str | None:
    """Étape de traitement d'un type de job ('contenu'|'enrich'|'embed'), None hors chaîne. PURE."""
    return _ETAPE_DE_TYPE.get(type_job)


def delai_etape() -> timedelta:
    """Délai maximal d'une étape (`lots_ia_etape_delai_min`, réglable à chaud), borné [1, 240] min."""
    from services import runtime_config
    try:
        minutes = int(float(runtime_config.effective("lots_ia_etape_delai_min") or DELAI_ETAPE_DEFAUT_MIN))
    except (TypeError, ValueError):
        minutes = DELAI_ETAPE_DEFAUT_MIN
    if minutes == 0:
        minutes = DELAI_ETAPE_DEFAUT_MIN
    return timedelta(minutes=max(DELAI_ETAPE_MIN, min(minutes, DELAI_ETAPE_MAX)))


def choisir_etape(courante: str | None, depuis: datetime | None, en_attente: dict[str, int],
                  maintenant: datetime, delai: timedelta) -> str | None:
    """
    Étape sur laquelle les lots GPU doivent travailler. Fonction PURE (testable sans base).

    - rien en attente → on garde la courante (None si elle est vide ou inconnue) ;
    - courante vide ou invalide → première étape du cycle qui a des jobs ;
    - courante avec des jobs, délai non dépassé → on la garde (c'est le but : un seul modèle) ;
    - sinon (étape vide, ou délai dépassé) → étape suivante du cycle qui a des jobs ;
    - aucune autre n'en a → on garde la courante.
    `depuis` inconnu compte comme un délai dépassé : mieux vaut tourner que faire attendre à vie.
    """
    avec = [e for e in ETAPES if en_attente.get(e, 0) > 0]
    valide = courante if courante in ETAPES else None
    if not avec:
        return valide
    if valide is None:
        return avec[0]
    expiree = depuis is None or maintenant - depuis >= delai
    if en_attente.get(valide, 0) > 0 and not expiree:
        return valide
    i = ETAPES.index(valide)
    for pas in range(1, len(ETAPES)):
        suivante = ETAPES[(i + pas) % len(ETAPES)]
        if en_attente.get(suivante, 0) > 0:
            return suivante
    return valide


# ─── Reprises sans tempête (plan lots IA par modèle, étape 5) ────────────────────────────────
# Un job de la chaîne IA dont le handler échoue sur un incident PASSAGER (délai dépassé, 504, passerelle
# qui dit « réessaie plus tard »…) n'est pas marqué `failed` : il retourne en `pending` avec un « pas
# avant » croissant, derrière les jobs déjà en attente, au lieu d'un échec suivi d'une relance immédiate
# qui rechargeait un modèle sur une carte déjà pleine. Au-delà de `ESSAIS_MAX` reports : `failed`.
# Interactifs (« Créer ») et priorité forcée gardent leur comportement : l'utilisateur est devant son
# écran, il vaut mieux lui montrer l'échec que le laisser attendre une heure.
TYPES_REPRISE_DIFFEREE: frozenset[str] = frozenset(_ETAPE_DE_TYPE)
REPORTS_MIN: tuple[int, ...] = (2, 5, 15, 30, 60)     # minutes avant la reprise n° 1, 2, 3, 4, 5
ESSAIS_MAX = len(REPORTS_MIN)                          # reports accordés ; le suivant fait passer `failed`


def delai_de_report(essai: int) -> timedelta:
    """Délai avant la reprise après le `essai`-ième incident passager (1 → 2 min … 5 → 60 min).
    Fonction PURE ; un rang hors bornes retombe sur le premier ou le dernier délai."""
    rang = max(1, min(int(essai), len(REPORTS_MIN)))
    return timedelta(minutes=REPORTS_MIN[rang - 1])


def reprise_differee_possible(type_job: str, forcee: bool) -> bool:
    """Ce job peut-il être reporté sur un incident passager ? Étapes de la chaîne IA seulement, et
    jamais une tâche à priorité forcée (« Continuer »). Fonction PURE."""
    return type_job in TYPES_REPRISE_DIFFEREE and not forcee


def heure_locale(quand: datetime) -> str:
    """« HH:MM » en heure de Paris ; « HH:MM UTC » si le fuseau n'est pas installé dans l'image.
    Une date naïve (SQLite) est de l'UTC. Fonction PURE."""
    quand = _en_utc(quand)
    try:
        from zoneinfo import ZoneInfo
        return quand.astimezone(ZoneInfo("Europe/Paris")).strftime("%H:%M")
    except Exception:  # noqa: BLE001 — pas de base de fuseaux : on le dit plutôt que de mentir
        return quand.strftime("%H:%M") + " UTC"


def message_reprise(pas_avant: datetime, essai: int, motif: str) -> str:
    """Message d'un job en attente de reprise (colonne `progress_message`, écran « Tâches »)."""
    return f"Reprise prévue à {heure_locale(pas_avant)} (essai {essai}/{ESSAIS_MAX}) — IA indisponible : {motif}"


def message_abandon(motif: str) -> str:
    """Message d'un job abandonné après `ESSAIS_MAX` reports."""
    return f"IA indisponible après {ESSAIS_MAX} reprises (dernier : {motif})"


def _eligible(maintenant: datetime):
    """Condition SQL : le job n'est pas reporté (ou son report est échu)."""
    return or_(Job.pas_avant.is_(None), Job.pas_avant <= maintenant)


# Un job reporté repart derrière ceux qui attendaient déjà quand il a été reporté : « fin de son étape ».
_RANG_FIFO = func.coalesce(Job.pas_avant, Job.created_at)


async def _gerer_incident_passager(job_id: str, type_job: str, exc: BaseException, annule: bool) -> str | None:
    """
    Le handler vient d'échouer : si c'est un incident IA PASSAGER d'un job de la chaîne, le REPORTE
    (retour en `pending`, `pas_avant`, `essais`+1) ou, passé `ESSAIS_MAX` reports, le marque `failed`
    avec un message lisible. Renvoie "reporte" | "abandonne" | "annule" | "ignore", ou None quand le cas
    ne relève pas de la reprise différée (l'appelant applique alors l'échec habituel).

    Seule l'exception TYPÉE `EchecPassager` compte : elle n'est levée qu'aux points d'appel de l'IA
    (enrichissement, lecture d'images, embeddings). Un délai ou un 500 de Tika, une erreur du NAS ou de
    l'antivirus, même sous forme d'erreur httpx, échouent tout de suite comme avant — rejouer ne ferait
    que relire le fichier et le repasser à Tika, avec un message « IA indisponible » faux.

    L'écriture est ATOMIQUE : `UPDATE … WHERE id = :id AND statut = 'running'`, compteur incrémenté dans
    le SET, nombre de lignes touchées vérifié. Si le job n'est plus `running` (repris par un autre
    process, annulé, terminé), on n'écrit RIEN (« ignore ») : l'appelant ne le marque pas non plus `failed`.
    """
    if not isinstance(exc, classement_echecs.EchecPassager) or type_job not in TYPES_REPRISE_DIFFEREE:
        return None
    motif = classement_echecs.decrire_echec(exc)
    try:
        async with AsyncSessionLocal() as db:
            ligne = (await db.execute(
                select(Job.essais, Job.priorite_forcee, Job.annulation_demandee).where(Job.id == uuid.UUID(job_id))
            )).first()
            if ligne is None or not reprise_differee_possible(type_job, bool(ligne.priorite_forcee)):
                return None
            essais = ligne.essais or 0
            maintenant = _now()
            garde = (Job.id == uuid.UUID(job_id), Job.statut == "running")
            if annule or ligne.annulation_demandee:   # annulation demandée pendant l'incident : on annule, on ne reporte pas
                valeurs = dict(statut="cancelled", completed_at=maintenant, pas_avant=None)
                resultat = "annule"
            elif essais >= ESSAIS_MAX:
                message = message_abandon(motif)
                valeurs = dict(statut="failed", completed_at=maintenant, pas_avant=None, erreur=message,
                               progress_message=message)
                resultat = "abandonne"
            else:
                pas_avant = maintenant + delai_de_report(essais + 1)
                valeurs = dict(statut="pending", started_at=None, completed_at=None, progress=0, pas_avant=pas_avant,
                               essais=func.coalesce(Job.essais, 0) + 1,
                               progress_message=message_reprise(pas_avant, essais + 1, motif))
                resultat = "reporte"
            touches = (await db.execute(update(Job).where(*garde).values(**valeurs))).rowcount
            await db.commit()
            if not touches:
                log.info("Report ignoré — le job n'est plus en cours", job_id=job_id, type=type_job)
                return "ignore"
            return resultat
    except Exception as e:  # noqa: BLE001 — impossible de reporter : l'échec habituel s'applique
        log.warning("Report du job impossible — échec habituel", job_id=job_id, erreur=str(e))
        return None


# Budget de slots par classe — DÉFAUTS (surchargés à chaud par la config, cf. `_budget`).
CONCURRENCE_PAR_CLASSE: dict[str, int] = {"gpu": CONCURRENCE_GPU, "io": CONCURRENCE_IO,
                                          "fond": CONCURRENCE_FOND}

# Borne de sécurité : même si un utilisateur saisit 999 dans les Paramètres, on ne dépasse pas
# (protège la VRAM / le pool de connexions Postgres). Minimum 1 (0 gèlerait la file).
_BUDGET_MIN, _BUDGET_MAX = 1, 8


def _budget(classe: str) -> int:
    """Budget de slots EFFECTIF d'une classe : config runtime (`concurrence_gpu`/`concurrence_io`,
    réglable à chaud dans les Paramètres) si valide, sinon le défaut ; borné [1, 8]."""
    from services import runtime_config
    defaut = CONCURRENCE_PAR_CLASSE.get(classe, 1)
    if classe == "fond":   # pas de réglage : un parcours du NAS à la fois, toujours
        return CONCURRENCE_FOND
    cle = "concurrence_gpu" if classe == "gpu" else "concurrence_io"
    try:
        v = int(float(runtime_config.effective(cle) or defaut))
    except (TypeError, ValueError):
        v = defaut
    return max(_BUDGET_MIN, min(v, _BUDGET_MAX))

# Au-delà de ce nombre de reprises (running→pending après crash), un job est déclaré `failed`
# plutôt que relancé en boucle (jobs fantômes qui bloqueraient la file).
MAX_REPRISES = 3

# Un job `pending` d'un type SANS handler (ligne de suivi d'une background task API, et non tâche du
# worker) qui dépasse cet âge n'a jamais démarré → il est annulé (fantôme). Grâce assez longue pour
# laisser la background task le passer `running`. (`rapport` et `comparatif` ont désormais un handler.)
AGE_PENDING_FANTOME_MIN = 15.0

# Registre { type_de_job -> handler async(ctx) -> dict|None }
_HANDLERS: dict = {}
# Ids de jobs `running` dont l'annulation a été demandée (best effort : le handler doit
# vérifier `ctx.cancelled` à des points sûrs).
_cancel_requested: set[str] = set()
_worker_task: asyncio.Task | None = None
_backup_task: asyncio.Task | None = None
_sync_task: asyncio.Task | None = None
_prewarm_task: asyncio.Task | None = None
_notif_task: asyncio.Task | None = None   # bilan « idées d'évolution » (cloche)
_matryoshka_task: asyncio.Task | None = None
_inventaire_task: asyncio.Task | None = None   # tournée de nuit de l'inventaire (Rangement)


def register(job_type: str):
    """Décorateur : enregistre un handler pour un type de job."""
    def deco(fn):
        _HANDLERS[job_type] = fn
        return fn
    return deco


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class JobContext:
    """Contexte passé au handler : paramètres du job + rapport de progression + annulation."""

    def __init__(self, job_id: str, type: str, parametres: dict | None, document_id):
        self.job_id = job_id
        self.type = type
        self.parametres = parametres or {}
        self.document_id = document_id

    @property
    def cancelled(self) -> bool:
        return self.job_id in _cancel_requested

    async def report(self, progress: int | None = None, message: str | None = None,
                     details: dict | None = None) -> None:
        """
        Écrit la progression du job en base (visible via GET /api/jobs/{id}).

        `details` : état STRUCTURÉ en cours de route (ex. `{"phase", "total", "fait"}`), rangé
        dans `resultat` le temps du job — le résultat final l'écrase à la fin. C'est ce qu'un
        autre process lit : jamais un dict en mémoire, que seul CE process verrait.
        """
        vals: dict = {}
        if progress is not None:
            vals["progress"] = max(0, min(100, int(progress)))
        if message is not None:
            vals["progress_message"] = message[:500]
        if details is not None:
            vals["resultat"] = details
        if not vals:
            return
        async with AsyncSessionLocal() as db:
            await db.execute(update(Job).where(Job.id == uuid.UUID(self.job_id)).values(**vals))
            await db.commit()


async def enqueue(db, type: str, parametres: dict | None = None, document_id=None) -> str:
    """
    Insère un job `pending` et renvoie son id (le commit reste à la charge de l'appelant).
    Injecte un **`correlation_id`** dans les paramètres s'il n'y en a pas → tout job est traçable
    de l'enfilement (API) jusqu'à son exécution (worker) sous le même identifiant (audit Phase 2).
    """
    from services import audit
    params = dict(parametres or {})
    cid = params.get("correlation_id") or audit.new_correlation_id()
    params["correlation_id"] = cid
    # Propriétaire (authentification, étape 5) : qui a lancé la tâche — seul, avec les admins, à
    # pouvoir l'arrêter ou la faire passer devant. Absent quand l'authentification est éteinte.
    if "proprietaire" not in params and audit.auteur_courant():
        params["proprietaire"] = audit.auteur_courant()
    # Rôle de l'auteur (« admin » | « utilisateur » | « jeton »), pour que le worker recontrôle qu'un job
    # GECO a bien été lancé par une session administrateur. Un identifiant de rôle, rien d'autre.
    if "proprietaire_role" not in params and audit.role_courant():
        params["proprietaire_role"] = audit.role_courant()
    job = Job(type=type, statut="pending", parametres=params, progress=0, document_id=document_id)
    db.add(job)
    await db.flush()
    await audit.emit(type, "queued", acteur="api", correlation_id=cid,
                     cible=params.get("cible") or (str(document_id) if document_id else None),
                     detail={"job_id": str(job.id)})
    return str(job.id)


async def _finaliser(job_id: str, statut: str, *, resultat: dict | None = None, erreur: str | None = None,
                     progress: int | None = None) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, uuid.UUID(job_id))
        if not job:
            return
        job.statut = statut
        job.completed_at = _now()
        if resultat is not None:
            job.resultat = resultat
        if erreur is not None:
            job.erreur = erreur[:1000]
        if progress is not None:
            job.progress = progress
        await db.commit()


async def _run(job_id: str) -> None:
    """Exécute un job déjà passé en `running` : dispatch vers le handler, finalise le statut."""
    # Charger les paramètres (valeurs simples, détachées de la session)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, uuid.UUID(job_id))
        if not job:
            return
        ctx = JobContext(job_id, job.type, job.parametres, job.document_id)
        # Priorité déclarée à la passerelle IA pour TOUS les appels de ce job (`_run` est une tâche
        # asyncio : la ContextVar ne déborde pas sur les autres jobs).
        from services.ollama_service import priorite_ia
        priorite_ia("interactif" if priorite(job.type) == 0 else "batch")
        # Recharge la config runtime AVANT chaque job → le worker prend les derniers
        # réglages UI (URLs, tokens re-saisis) sans redémarrage du conteneur.
        try:
            from services import runtime_config
            await runtime_config.load(db)
        except Exception as e:  # noqa: BLE001 — un échec de reload ne doit pas bloquer le job
            log.warning("Reload runtime_config avant job impossible", erreur=str(e))

    # Audit (Phase 2) : `correlation_id` porté par les paramètres du job (posé à l'enqueue) →
    # relie l'événement worker à l'action API/UI qui l'a déclenché. `cible` = ce qui est traité.
    from services import audit
    import time as _time
    # Ce que la tâche inscrit au journal est signé de qui l'a lancée (tâche asyncio : sans débord).
    audit.definir_auteur((ctx.parametres or {}).get("proprietaire"))
    audit.definir_role((ctx.parametres or {}).get("proprietaire_role"))
    cid = ctx.parametres.get("correlation_id")
    cible = ctx.parametres.get("cible") or (str(ctx.document_id) if ctx.document_id else None)
    t0 = _time.monotonic()
    await audit.emit(ctx.type, "start", acteur="worker", correlation_id=cid, cible=cible,
                     detail={"job_id": job_id})

    # Recontrôle (plan liste-modeles, étape 5a) : un modèle `geco/…` figé dans le job n'est exécuté que
    # pour un type INTERACTIF portant la marque d'origine posée par la route. Sinon : échec propre.
    from services import modeles_externes
    refus = await modeles_externes.controle_job(ctx.type, ctx.parametres)
    if refus:
        log.warning("Job refusé : modèle GECO non autorisé", job_id=job_id, type=ctx.type)
        await _finaliser(job_id, "failed", erreur=refus)
        await audit.emit(ctx.type, "error", acteur="worker", correlation_id=cid, cible=cible, message=refus)
        _cancel_requested.discard(job_id)
        return

    handler = _HANDLERS.get(ctx.type)
    if handler is None:
        log.warning("Aucun handler pour le job", job_id=job_id, type=ctx.type)
        await _finaliser(job_id, "failed", erreur=f"Aucun handler pour le type '{ctx.type}'")
        await audit.emit(ctx.type, "error", acteur="worker", correlation_id=cid, cible=cible,
                         message=f"Aucun handler pour le type '{ctx.type}'")
        _cancel_requested.discard(job_id)
        return

    def _ms() -> int:
        return int((_time.monotonic() - t0) * 1000)

    try:
        # Liste blanche d'envoi GECO : ouverte ICI, après le recontrôle, pour un job interactif dont le
        # modèle figé est GECO et qui porte la marque d'origine. Tout autre job : aucune marque (= refus).
        from services.ollama_service import est_geco, sortie_geco_autorisee
        if (ctx.type in modeles_externes.TYPES_JOB_GECO and est_geco(ctx.parametres.get("model"))
                and ctx.parametres.get("origine") == modeles_externes.ORIGINE_GECO):
            with sortie_geco_autorisee(f"job:{ctx.type}"):
                resultat = await handler(ctx)
        else:
            resultat = await handler(ctx)
        if ctx.cancelled:
            await _finaliser(job_id, "cancelled", resultat=resultat if isinstance(resultat, dict) else None)
            log.info("Job annulé", job_id=job_id, type=ctx.type)
            await audit.emit(ctx.type, "cancelled", acteur="worker", correlation_id=cid, cible=cible, duree_ms=_ms())
        else:
            await _finaliser(job_id, "completed", resultat=resultat if isinstance(resultat, dict) else {}, progress=100)
            log.info("Job terminé", job_id=job_id, type=ctx.type)
            await audit.emit(ctx.type, "success", acteur="worker", correlation_id=cid, cible=cible,
                             duree_ms=_ms(), detail=resultat if isinstance(resultat, dict) else None)
    except Exception as e:  # noqa: BLE001 — un job qui échoue ne doit pas tuer le worker
        # Incident passager d'une étape IA : report (ou abandon lisible), pas un échec brut.
        suite = await _gerer_incident_passager(job_id, ctx.type, e, ctx.cancelled)
        motif = classement_echecs.decrire_echec(e) if suite else ""
        if suite == "reporte":
            log.warning("Job reporté (incident passager)", job_id=job_id, type=ctx.type, motif=motif)
            await audit.emit(ctx.type, "retry", acteur="worker", correlation_id=cid, cible=cible,
                             duree_ms=_ms(), message=motif)
        elif suite == "ignore":
            log.info("Job déjà pris en charge ailleurs — rien à écrire", job_id=job_id, type=ctx.type)
        elif suite == "annule":
            log.info("Job annulé", job_id=job_id, type=ctx.type)
            await audit.emit(ctx.type, "cancelled", acteur="worker", correlation_id=cid, cible=cible,
                             duree_ms=_ms())
        else:
            if suite == "abandonne":
                log.error("Job abandonné (IA indisponible)", job_id=job_id, type=ctx.type, motif=motif)
            else:
                log.error("Job échoué", job_id=job_id, type=ctx.type, erreur=str(e))
                await _finaliser(job_id, "failed", erreur=str(e))
            await audit.emit(ctx.type, "error", acteur="worker", correlation_id=cid, cible=cible,
                             duree_ms=_ms(), message=f"{type(e).__name__}: {e}")
    finally:
        _cancel_requested.discard(job_id)


async def _verrouiller_etat(db) -> FileIAEtat:
    """Ligne d'état de la file GPU, verrouillée (FOR UPDATE) jusqu'à la fin de la transaction.
    Deux process qui réclament en même temps se SÉRIALISENT ici : ils voient le même état, et
    l'un ne bascule pas d'étape dans le dos de l'autre. Créée à la première prise ; la course à
    la création est réglée par la base (ON CONFLICT DO NOTHING), puis on relit sous verrou."""
    requete = select(FileIAEtat).where(FileIAEtat.cle == CLE_FILE_GPU).with_for_update()
    etat = (await db.execute(requete)).scalar_one_or_none()
    if etat is not None:
        return etat
    if db.bind.dialect.name.startswith("postgres"):
        from sqlalchemy.dialects.postgresql import insert as _insert
    else:   # SQLite (tests)
        from sqlalchemy.dialects.sqlite import insert as _insert
    await db.execute(_insert(FileIAEtat).values(cle=CLE_FILE_GPU, nb_bascules=0, maj_le=_now())
                     .on_conflict_do_nothing(index_elements=["cle"]))
    return (await db.execute(requete)).scalar_one()


def _en_utc(d: datetime | None) -> datetime | None:
    """SQLite (tests) rend des dates naïves, PostgreSQL des dates avec fuseau : tout en UTC."""
    if d is None:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


async def _pending_par_etape(db, types: list[str], exclus: list | None = None,
                             maintenant: datetime | None = None) -> dict[str, int]:
    """Y a-t-il des jobs `pending` PRÊTS par étape ? (1 / 0, un EXISTS par étape : pas de comptage de
    toute la file à chaque interrogation). `exclus` : ids déjà pris dans cette transaction. Un job
    REPORTÉ (`pas_avant` dans le futur) ne compte pas : sinon une étape qui n'en contient plus que
    des reportés garderait la file collante bloquée sur elle."""
    compte: dict[str, int] = {}
    maintenant = maintenant or _now()
    for etape in ETAPES:
        types_etape = [t for t in types if etape_de(t) == etape]
        if not types_etape:
            continue
        cond = [Job.statut == "pending", Job.type.in_(types_etape), _eligible(maintenant)]
        if exclus:
            cond.append(Job.id.notin_(exclus))
        if (await db.execute(select(Job.id).where(*cond).limit(1))).first():
            compte[etape] = 1
    return compte


def _changer_etape(etat: FileIAEtat, vers: str, maintenant: datetime) -> None:
    """Consigne un changement d'étape (en base, dans la transaction de la prise) + une ligne de journal."""
    log.info("File IA : changement d'étape", de=etat.etape, vers=vers,
             depuis=str(etat.depuis) if etat.depuis else None, bascules=(etat.nb_bascules or 0) + 1)
    etat.etape, etat.depuis = vers, maintenant
    etat.nb_bascules = (etat.nb_bascules or 0) + 1
    etat.maj_le = maintenant


async def _claim_lots_par_etape(db, types: list[str], libres: int, ordre) -> list:
    """Prise des lots GPU « collante par étape », dans la transaction ouverte par `_claim`.

    Autorisés : les interactifs, les types de l'étape choisie, et les lots GPU HORS étape
    (index_wiki, idées d'évolution…) qui gardent leur FIFO. Les types d'une autre étape attendent.
    Si l'étape choisie se vide avant que les places soient remplies, on recalcule UNE fois avec
    l'étape suivante : une place ne reste pas vide pendant qu'une autre étape a du travail."""
    # Sortie anticipée SANS verrou ni écriture : `_claim` est appelé toutes les 0,3 à 1 s, le plus
    # souvent pour rien. Sans job éligible, la ligne d'état n'est même pas lue.
    maintenant = _now()
    if not (await db.execute(select(Job.id).where(Job.statut == "pending", Job.type.in_(types),
                                                  _eligible(maintenant)).limit(1))).first():
        return []
    etat = await _verrouiller_etat(db)
    delai = delai_etape()
    compte = await _pending_par_etape(db, types, maintenant=maintenant)
    etape = choisir_etape(etat.etape, _en_utc(etat.depuis), compte, maintenant, delai)
    if etape is not None and etape != etat.etape:
        _changer_etape(etat, etape, maintenant)

    # Interactifs et lots hors chaîne : jamais retenus par l'étape courante.
    hors_chaine = [t for t in types if etape_de(t) is None]

    async def _prendre(etapes_ouvertes: list[str], n: int, avec_hors_chaine: bool, exclus: list) -> list:
        permis = (hors_chaine if avec_hors_chaine else []) + [t for t in types if etape_de(t) in etapes_ouvertes]
        if not permis or n <= 0:
            return []
        cond = [Job.statut == "pending", Job.type.in_(permis), _eligible(maintenant)]
        if exclus:
            cond.append(Job.id.notin_(exclus))
        return (await db.execute(
            select(Job.id, Job.type).where(*cond)
            .order_by(case((Job.priorite_forcee.is_(True), 0), else_=1), ordre, _RANG_FIFO)
            .limit(n).with_for_update(skip_locked=True)
        )).all()

    pris = await _prendre([etape] if etape else [], libres, True, [])
    if len(pris) < libres and etape is not None:
        # Ce qui reste en attente APRÈS cette prise, par étape ; la courante est peut-être vide.
        deja = [r[0] for r in pris]
        restant = await _pending_par_etape(db, types, deja, maintenant)
        suivante = choisir_etape(etape, _en_utc(etat.depuis), restant, maintenant, delai)
        if suivante is not None and suivante != etape:
            _changer_etape(etat, suivante, maintenant)
            # Seulement l'étape suivante : les interactifs et lots hors chaîne ont déjà été offerts à la
            # première prise (les rendre encore ferait partir deux `_run` pour le même job).
            pris += await _prendre([suivante], libres - len(pris), False, deja)
    ids_vus: set = set()
    return [i for i, _t in pris if not (i in ids_vus or ids_vus.add(i))]


async def _claim(classe: str, libres: int, interactifs_seulement: bool = False) -> list[str]:
    """Réserve atomiquement jusqu'à `libres` jobs pending d'une CLASSE donnée ('gpu'|'io'),
    pending → running (FOR UPDATE SKIP LOCKED), en FIFO au sein de la classe.

    Réclamer par classe (deux appels dans la boucle) garantit qu'une rafale de tâches GPU ne prive
    jamais les tâches I/O de leurs slots, et réciproquement — c'est tout l'intérêt du parallélisme
    par classe : synchro NAS / réorganisation tournent EN MÊME TEMPS que l'enrichissement IA.

    Lots GPU (hors pause, sans tâche forcée en attente) : file COLLANTE PAR ÉTAPE — voir
    `_claim_lots_par_etape`. Interactif, priorité forcée, pause IA et classe `io` n'ont aucune
    logique d'étape : leur ordre est inchangé.

    ⚠️ On ne réclame QUE les types possédant un handler enregistré. Certains « jobs » de la table ne
    sont PAS traités par ce worker mais par une *background task* FastAPI dans l'API — la ligne
    `jobs` ne sert qu'au suivi. Sans ce filtre, le worker rafle ces jobs, ne trouve pas de handler et
    les marque `failed` (vu le 23/07 avec `rapport`, qui a depuis son propre handler). C'était
    masqué tant que la file était saturée de synchros ; dès qu'elle se vide, la course se perd."""
    if libres <= 0:
        return []
    types = [t for t in _HANDLERS if classe_tache(t) == classe]
    if interactifs_seulement:   # pause IA : seules les tâches de « Créer » partent
        types = [t for t in types if priorite(t) == 0]
    if not types:
        return []
    # Forcée (« Continuer »), puis interactif, puis FIFO (cf. `priorite`) : la liste IN est vide-safe,
    # `types` ne l'est jamais ici.
    interactifs = [t for t in types if priorite(t) == 0]
    ordre = (case((Job.type.in_(interactifs), 0), else_=1) if interactifs else literal(1))
    maintenant = _now()   # un job REPORTÉ (`pas_avant` futur) n'est ni pris, ni attendu, ni compté
    async with AsyncSessionLocal() as db:
        # Tant qu'une tâche forcée attend, aucun LOT ne prend de créneau : elle part au prochain libre.
        forcee_en_attente = bool((await db.execute(
            select(Job.id).where(Job.statut == "pending", Job.priorite_forcee.is_(True), Job.type.in_(types),
                                 _eligible(maintenant))
            .limit(1)
        )).first())
        if forcee_en_attente and interactifs:
            types = interactifs
        par_etape = classe == "gpu" and not interactifs_seulement and not (forcee_en_attente and interactifs)
        if par_etape:
            rows = await _claim_lots_par_etape(db, types, libres, ordre)
        else:
            rows = (await db.execute(
                select(Job.id).where(Job.statut == "pending", Job.type.in_(types), _eligible(maintenant))
                # `case` plutôt que `.desc()` : en Postgres, DESC place les NULL EN TÊTE.
                .order_by(case((Job.priorite_forcee.is_(True), 0), else_=1), ordre, _RANG_FIFO)
                .limit(libres).with_for_update(skip_locked=True)
            )).scalars().all()
        ids = [str(r) for r in rows]
        if ids:
            await db.execute(
                update(Job).where(Job.id.in_(rows)).values(statut="running", started_at=_now(), progress=0,
                                                           pas_avant=None)   # `essais` reste : il borne les reports
            )
        await db.commit()   # valide aussi l'état de la file (étape courante) : même transaction
        return ids


async def _purger_pending_fantomes() -> None:
    """
    Annule les jobs `pending` d'un type SANS handler (ex. `rapport`) plus vieux que
    `AGE_PENDING_FANTOME_MIN` : ils ne seront jamais réclamés par le worker (`_claim` filtre par
    type) et resteraient `pending` à vie. C'est ce qu'on a dû nettoyer à la main le 23/07.
    """
    types = list(_HANDLERS.keys())
    limite = _now() - timedelta(minutes=AGE_PENDING_FANTOME_MIN)
    async with AsyncSessionLocal() as db:
        cond = (Job.statut == "pending") & (Job.created_at < limite)
        if types:
            cond = cond & Job.type.notin_(types)
        res = await db.execute(update(Job).where(cond).values(
            statut="cancelled", completed_at=_now(),
            erreur="Annulé automatiquement (job pending fantôme : aucun handler)"))
        await db.commit()
        if res.rowcount:
            log.warning("Jobs pending fantômes annulés", nb=res.rowcount)


async def _relire_annulations() -> None:
    """
    Peuple `_cancel_requested` depuis la BASE : l'annulation est demandée par l'API (autre
    process) via la colonne `jobs.annulation_demandee`. Le worker la relit à chaque tick pour que
    `ctx.cancelled` (synchrone, lit le set local) la voie — c'est ce qui manquait (« Annuler »
    sans effet en déploiement API/worker séparés).
    """
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Job.id).where(Job.statut == "running", Job.annulation_demandee.is_(True))
        )).scalars().all()
    for r in rows:
        _cancel_requested.add(str(r))


async def _worker_loop() -> None:
    import time as _t

    from services import runtime_config

    # On mémorise la classe de chaque tâche en cours → budget de slots suivi PAR CLASSE.
    en_cours: dict[asyncio.Task, str] = {}
    prochaine_relecture = 0.0
    while True:
        try:
            await _relire_annulations()   # propage les annulations demandées via la base
            # Relit la config toutes les ~10 s (pas à chaque tick : lecture DB) → un changement de
            # budget dans les Paramètres s'applique à chaud, sans redéploiement du worker.
            if _t.monotonic() >= prochaine_relecture:
                try:
                    async with AsyncSessionLocal() as db:
                        # Silencieux : toutes les 10 s, « Runtime config chargée » noyait le
                        # journal du worker (la liste complète des surcharges, 6 fois par minute).
                        await runtime_config.load(db, journal=False)
                except Exception as e:  # noqa: BLE001 — un reload raté ne doit pas figer la file
                    log.warning("Reload config worker impossible", erreur=str(e))
                prochaine_relecture = _t.monotonic() + 10.0
            # PAUSE IA : on cesse de réclamer les LOTS GPU (analyses, indexation…) → Ollama se libère
            # pour un autre usage. Les tâches de « Créer » partent quand même (02/11/2026, décision 2) ;
            # les tâches en cours se terminent ; l'I/O (synchro, réorg) continue.
            # Hors de la PLAGE HORAIRE des lots (étape 4 du plan lots IA) : même conduite que la pause.
            ia_pause = runtime_config.lots_ia_suspendus()
            claimed = 0
            for classe in CLASSES:
                actifs = sum(1 for c in en_cours.values() if c == classe)
                ids = await _claim(classe, _budget(classe) - actifs,
                                   interactifs_seulement=(classe == "gpu" and ia_pause))
                for jid in ids:
                    t = asyncio.create_task(_run(jid))
                    en_cours[t] = classe
                    t.add_done_callback(lambda tt: en_cours.pop(tt, None))  # retire la tâche finie
                claimed += len(ids)
            # Rythme : court s'il reste des slots occupés, plus long si tout est vide.
            await asyncio.sleep(0.3 if (claimed or en_cours) else 1.0)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — le worker ne doit jamais s'arrêter sur une erreur
            log.error("Erreur dans la boucle worker", erreur=str(e))
            await asyncio.sleep(1.0)


# Clé de verrou d'avis Postgres pour la reprise des orphelins (arbitraire, propre à ce projet).
_REPRISE_LOCK = 918273645


def purger_temporaires(age_heures: float = 6.0) -> int:
    """
    Supprime les temporaires ORPHELINS (`/tmp/tmp*`) laissés par les fetch SMB interrompus.

    Les appelants suppriment normalement leur temporaire dans un `finally` — mais celui-ci **ne
    s'exécute pas** si le process est tué (conteneur redémarré, disque plein, job annulé). Résultat
    vécu le 21/07 : **3 740 fichiers / 15 Go** dans le worker (dont un ZIP de 8,9 Go), disque saturé
    et PostgreSQL bloqué. On ne touche qu'aux fichiers plus vieux que `age_heures` : les traitements
    en cours (récents) sont épargnés.
    """
    import tempfile as _tf
    import time as _t

    limite = _t.time() - age_heures * 3600
    nb, octets = 0, 0
    try:
        for f in Path(_tf.gettempdir()).glob("tmp*"):
            try:
                st = f.stat()
                if f.is_file() and st.st_mtime < limite:
                    octets += st.st_size
                    f.unlink()
                    nb += 1
            except OSError:
                pass
    except OSError:
        return 0
    if nb:
        log.warning("Temporaires orphelins purgés", nb=nb, octets=octets, age_heures=age_heures)
    return nb


async def _purger_rapports_anciens() -> None:
    """Supprime les rapports de l'historique plus vieux que `rapports_purge_jours` (0 = jamais)."""
    from services import runtime_config
    try:
        jours = int(float(runtime_config.effective("rapports_purge_jours") or 0))
    except (TypeError, ValueError):
        jours = 0
    if jours <= 0:
        return
    from sqlalchemy import delete as _delete
    from models.rapport import Rapport
    limite = _now() - timedelta(days=jours)
    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(_delete(Rapport).where(Rapport.created_at < limite))
            await db.commit()
            if res.rowcount:
                log.info("Historique des rapports purgé", supprimes=res.rowcount, jours=jours)
    except Exception as e:  # noqa: BLE001
        log.warning("Purge de l'historique échouée", erreur=str(e))


async def _purger_audit_ancien() -> int:
    """
    Supprime les événements d'audit plus vieux que `audit_retention_jours` (0 = tout garder).
    Rend le nombre supprimé. Le défaut est 0 : effacer des traces ne se décide pas à la place
    de l'utilisateur.
    """
    from services import runtime_config
    try:
        jours = int(float(runtime_config.effective("audit_retention_jours") or 0))
    except (TypeError, ValueError):
        jours = 0
    if jours <= 0:
        return 0
    from sqlalchemy import delete as _delete
    from models.audit import AuditEvent
    limite = _now() - timedelta(days=jours)
    try:
        async with AsyncSessionLocal() as db:
            res = await db.execute(_delete(AuditEvent).where(AuditEvent.created_at < limite))
            await db.commit()
            if res.rowcount:
                log.info("Journal d'audit purgé", supprimes=res.rowcount, jours=jours)
            return res.rowcount or 0
    except Exception as e:  # noqa: BLE001
        log.warning("Purge du journal d'audit échouée", erreur=str(e))
        return 0


async def _notifications_scheduler() -> None:
    """
    Bilan périodique « idées d'évolution » (cloche de l'en-tête, 11/10/2026) : toutes les 6 h, met
    la tâche en file quand elle est due (`notif_idees_frequence` : mensuel | trimestriel |
    desactive). Une erreur est journalisée mais n'arrête jamais le planificateur.
    """
    from services import idees_evolution

    await asyncio.sleep(600)   # laisse le démarrage se stabiliser
    while True:
        try:
            await idees_evolution.planifier_si_du()
        except Exception as e:  # noqa: BLE001
            log.warning("Planification du bilan d'idées d'évolution échouée", erreur=str(e))
        await asyncio.sleep(6 * 3600)


async def _backup_scheduler() -> None:
    """
    Sauvegarde AUTOMATIQUE de la base par le worker : `pg_dump` toutes les N heures + purge des
    plus anciennes (config `backup_auto_heures` / `backup_retention`, éditables à chaud).

    Tourne dans le worker (process unique), pas dans l'API (multi-uvicorn). Une sauvegarde ratée
    est journalisée mais **ne tue pas** le planificateur. Délai initial pour ne pas dumper au boot.
    """
    from services import backup, runtime_config

    def _heures() -> float:
        try:
            return float(runtime_config.effective("backup_auto_heures") or 0)
        except (TypeError, ValueError):
            return 0.0

    await asyncio.sleep(300)   # laisse le démarrage se stabiliser
    while True:
        # Purge périodique des temporaires orphelins : sur une indexation longue (65k fichiers),
        # /tmp ne doit jamais gonfler même si des traitements ont été interrompus.
        purger_temporaires()
        # Purge de l'historique des rapports (rapports_purge_jours ; 0 = jamais).
        await _purger_rapports_anciens()
        # Conservation du journal d'audit (audit_retention_jours ; 0 = tout garder).
        await _purger_audit_ancien()
        # Échecs IA : 30 jours suffisent à voir une tendance (ia_echecs.CONSERVATION_JOURS).
        from services import ia_echecs
        await ia_echecs.purger()
        # Annule les jobs pending fantômes (type sans handler resté pending trop longtemps).
        try:
            await _purger_pending_fantomes()
        except Exception as e:  # noqa: BLE001
            log.warning("Purge des pending fantômes échouée", erreur=str(e))
        heures = _heures()
        if heures <= 0:
            await asyncio.sleep(1800)   # désactivé : on relit la config dans 30 min
            continue
        try:
            garder = int(runtime_config.effective("backup_retention") or 4)
        except (TypeError, ValueError):
            garder = 4
        try:
            # Purge AVANT le dump : libère la place du plus ancien pour accueillir le nouveau
            # (sur un petit disque, purger après ne servait à rien — le dump échouait avant).
            backup.prune(max(garder - 1, 1))
            info = await backup.dump()
            log.info("Sauvegarde auto effectuée", **info, retention=garder)
        except Exception as e:  # noqa: BLE001 — ne jamais laisser une sauvegarde ratée arrêter le cycle
            log.error("Sauvegarde auto échouée", erreur=str(e), libre=backup.espace_libre())
        finally:
            # Purge même en cas d'ÉCHEC : sinon les tentatives ratées s'accumulaient sans
            # jamais nettoyer (incident 21/07 : 12 fichiers résiduels + disque plein).
            try:
                backup.prune(garder)
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(max(_heures(), 0.1) * 3600)


# Clé de verrou d'avis Postgres pour la planification des synchros (un seul process planifie).
_SYNC_LOCK = 918273646

# Périodicité du tick de planification. Ce n'est PAS l'intervalle des synchros (réglé par source) :
# c'est la fréquence à laquelle on regarde si l'une d'elles est due.
TICK_SYNC_S = 300


def synchro_due(dernier_sync: datetime | None, intervalle_minutes: int | None,
                maintenant: datetime | None = None) -> bool:
    """
    Une synchro est-elle due ? Fonction PURE (testable sans base).

    - intervalle absent/nul/négatif → synchro auto désactivée ;
    - jamais synchronisée → due immédiatement ;
    - sinon due une fois l'intervalle écoulé depuis le dernier passage.
    """
    if not intervalle_minutes or intervalle_minutes <= 0:
        return False
    if dernier_sync is None:
        return True
    return dernier_sync + timedelta(minutes=intervalle_minutes) <= (maintenant or _now())


def cle_dossier(partage: str | None, chemin: str | None) -> str:
    """Clé d'un périmètre de synchro dans `sources.sync_dossiers` : « partage/dossier »."""
    return f"{partage or ''}{chemin or '/'}"


def intervalle_dossier(cle: str, defaut: int | None, reglages: dict | None) -> int:
    """Minutes entre deux synchros de CE dossier : son réglage, sinon celui de la source."""
    propre = (reglages or {}).get(cle)
    try:
        return max(0, int(propre if propre is not None else (defaut or 0)))
    except (TypeError, ValueError):
        return max(0, int(defaut or 0))


def dossiers_dus(scopes: list[dict], defaut: int | None, reglages: dict | None,
                 etats: dict[str, tuple[datetime | None, bool]],
                 maintenant: datetime | None = None) -> list[dict]:
    """
    Périmètres à synchroniser MAINTENANT. Fonction PURE (testable sans base).

    `etats` : par clé, (date de la dernière synchro mise en file, une synchro est-elle déjà en
    file ou en cours ?). Un dossier déjà occupé passe son tour — sinon une synchro plus longue
    que son intervalle s'empilerait sur elle-même.
    """
    dus = []
    for sc in scopes:
        cle = cle_dossier(sc.get("partage"), sc.get("chemin"))
        dernier, occupe = etats.get(cle, (None, False))
        if not occupe and synchro_due(dernier, intervalle_dossier(cle, defaut, reglages), maintenant):
            dus.append(sc)
    return dus


async def etats_synchro(db, source_id: str) -> dict[str, tuple[datetime | None, bool]]:
    """Par dossier d'une source : (dernière synchro mise en file, une synchro est-elle active ?)."""
    lignes = (await db.execute(text(
        "SELECT parametres->>'partage', parametres->>'chemin', max(created_at), "
        "       bool_or(statut IN ('pending','running')) "
        "FROM jobs WHERE type = 'sync_source' AND parametres->>'source_id' = :sid GROUP BY 1, 2"
    ), {"sid": source_id})).all()
    return {cle_dossier(partage, chemin): (dernier, bool(actif)) for partage, chemin, dernier, actif in lignes}


async def _planifier_syncs() -> int:
    """
    Enfile une synchro pour chaque DOSSIER dont l'intervalle est écoulé (son réglage propre, ou
    à défaut celui de la source). Renvoie le nombre de sources déclenchées.

    Trois garde-fous :
    - **verrou d'avis Postgres** : en multi-process, un seul planifie (sinon N fois les jobs) ;
    - **jamais deux fois le même dossier**, et rien pendant une `indexation` de la source (une
      synchro pendant une indexation manuelle se marcheraient dessus) ;
    - l'échéance se compte depuis la **mise en file**, pas la fin : un scan long ne provoque pas
      une rafale de re-planifications au tick suivant.
    """
    from models.source import Source
    from routers.sources import _scopes_indexes

    declenchees = 0
    async with AsyncSessionLocal() as db:
        # Verrou **transactionnel** (`_xact_`) : libéré automatiquement au COMMIT/ROLLBACK.
        # ⚠️ Ne PAS utiliser `pg_try_advisory_lock` ici : un `commit()` rend la connexion au pool,
        # et l'`unlock` du `finally` s'exécuterait alors sur une AUTRE connexion — il ne libérerait
        # rien et le verrou resterait pris à vie (constaté : tous les ticks suivants renonçaient
        # en silence, `pg_locks` montrait le verrou tenu par une connexion `idle`).
        got = (await db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _SYNC_LOCK})).scalar()
        if not got:
            return 0
        sources = (await db.execute(select(Source).where(Source.actif.is_(True)))).scalars().all()

        for src in sources:
            reglages = src.sync_dossiers or {}
            # Rien à planifier : ni intervalle de source, ni dossier réglé à part.
            if not (src.sync_intervalle_minutes or 0) > 0 and not any(
                    intervalle_dossier(c, 0, reglages) > 0 for c in reglages):
                continue

            indexation = (await db.execute(text(
                "SELECT 1 FROM jobs WHERE statut IN ('pending','running') AND type = 'indexation' "
                "AND parametres->>'source_id' = :sid LIMIT 1"
            ), {"sid": str(src.id)})).scalar()
            if indexation:
                log.info("Synchro auto reportée — une indexation de la source est en cours", source=src.libelle)
                continue

            scopes = await _scopes_indexes(db, src)
            if not scopes:
                continue   # rien d'indexé : rien à comparer

            dus = dossiers_dus(scopes, src.sync_intervalle_minutes, reglages,
                               await etats_synchro(db, str(src.id)))
            if not dus:
                continue
            for sc in dus:
                await enqueue(db, "sync_source", {"source_id": str(src.id),
                                                  "chemin": sc["chemin"], "partage": sc["partage"],
                                                  "auto": True})
            src.dernier_sync = _now()
            declenchees += 1
            log.info("Synchro auto planifiée", source=src.libelle, nb_dossiers=len(dus),
                     sur=len(scopes), intervalle_source_min=src.sync_intervalle_minutes)

        # Un seul commit, en fin de transaction : il valide les jobs enfilés ET libère le verrou.
        await db.commit()
    return declenchees


async def _sync_scheduler() -> None:
    """Tick de planification des synchros automatiques. Une erreur n'arrête jamais le cycle."""
    await asyncio.sleep(120)   # laisse le démarrage se stabiliser
    while True:
        try:
            await _planifier_syncs()
        except Exception as e:  # noqa: BLE001
            log.error("Planification des synchros échouée", erreur=str(e))
        await asyncio.sleep(TICK_SYNC_S)


async def _prewarm_scheduler() -> None:
    """
    Maintient le GROS modèle de rapport **résident** en mémoire, pour éviter qu'un premier rapport
    après inactivité doive le recharger à froid (43 Go → plusieurs minutes, risque de 502 via le
    proxy). Modèle **lu dans les Paramètres** (`model_for("rapport")`), jamais en dur → suit un
    changement de modèle sans redéploiement. Période < `keep_alive` pour ne jamais se décharger.

    Best effort : Ollama injoignable ou modèle absent ⇒ on log et on réessaie au tour suivant,
    jamais d'arrêt du planificateur. Cf. mémoire cold-load — approche à améliorer plus tard.
    """
    from config import get_settings
    from services import runtime_config
    from services.ollama_service import OllamaService

    settings = get_settings()
    ollama = OllamaService()
    await asyncio.sleep(30)   # laisse le démarrage se stabiliser avant de charger un gros modèle
    while True:
        # Réglable À CHAUD (Paramètres) : sur un GPU PARTAGÉ (JARVIS/FOULEE), on peut couper le prewarm
        # pour rendre la VRAM. Relu à chaque cycle → activer/désactiver depuis l'UI prend effet sans
        # redémarrage. (Le défaut vient de l'env `OLLAMA_PREWARM_ENABLED`.)
        if runtime_config.prewarm_actif():
            modele = runtime_config.model_for("rapport")
            try:
                if modele and not await ollama.is_loaded(modele):
                    ok = await ollama.warm(modele)
                    if ok:
                        log.info("Modèle de rapport pré-chargé (maintenu chaud)", modele=modele)
            except Exception as e:  # noqa: BLE001 — ne jamais laisser le prewarm tuer le worker
                log.warning("Pré-chargement — cycle en erreur", erreur=str(e) or type(e).__name__)
        minutes = max(settings.ollama_prewarm_minutes, 1.0)
        await asyncio.sleep(minutes * 60)


_MATRYOSHKA_LOCK = 771037  # clé de verrou d'avis dédiée au backfill/index Matryoshka (E7)


async def _matryoshka_scheduler() -> None:
    """
    Prépare la recherche sémantique accélérée (E7), **une seule fois**, en tâche de fond :
      1. **backfill** de `embedding_small` (préfixe 1024-d L2-normalisé du 4096) pour les lignes
         existantes — dérivé en SQL via `l2_normalize(subvector(embedding, 1, 1024))`, sans ré-embed ;
      2. création de l'**index HNSW** (cosine) sur `embedding_small` — indexable car ≤ 2000 dims.

    Idempotent et best-effort : par lots pour ne pas verrouiller la table, protégé par un verrou
    d'avis (un seul process uvicorn le fait), `CREATE INDEX CONCURRENTLY` en AUTOCOMMIT (non bloquant).
    Après le 1ᵉ passage, les nouveaux embeddings sont déjà remplis à l'insertion → plus rien à faire.
    """
    await asyncio.sleep(20)  # laisse le démarrage se stabiliser
    try:
        async with AsyncSessionLocal() as db:
            got = (await db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _MATRYOSHKA_LOCK})).scalar()
            if not got:
                log.info("Backfill Matryoshka délégué à un autre worker (verrou pris)")
                return
            try:
                total = 0
                while True:
                    res = await db.execute(text("""
                        UPDATE embeddings SET embedding_small = l2_normalize(subvector(embedding, 1, 1024))
                        WHERE id IN (
                            SELECT id FROM embeddings
                            WHERE embedding_small IS NULL AND embedding IS NOT NULL
                            LIMIT 2000
                        )
                    """))
                    await db.commit()
                    n = res.rowcount or 0
                    total += n
                    if n:
                        log.info("Backfill embedding_small", lot=n, cumul=total)
                    if n < 2000:
                        break
                if total:
                    log.info("Backfill Matryoshka terminé", lignes=total)
            finally:
                await db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _MATRYOSHKA_LOCK})
                await db.commit()

        # Index HNSW en AUTOCOMMIT (CREATE INDEX CONCURRENTLY interdit en transaction).
        # Opérateur choisi d'après le type RÉEL de la colonne : `halfvec` depuis le 29/09/2026
        # (scripts/migrer-halfvec.sql), `vector` sur une base pas encore migrée — le code
        # fonctionne sur les deux, l'index doit suivre.
        autocommit = engine.execution_options(isolation_level="AUTOCOMMIT")
        async with autocommit.connect() as conn:
            type_col = (await conn.execute(text(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'embeddings'::regclass AND attname = 'embedding_small'"
            ))).scalar() or ""
            ops = "halfvec_cosine_ops" if type_col.startswith("halfvec") else "vector_cosine_ops"
            await conn.execute(text(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_embeddings_small_hnsw "
                f"ON embeddings USING hnsw (embedding_small {ops})"
            ))
        log.info("Index HNSW embedding_small prêt (recherche sémantique accélérée)")
    except Exception as e:  # noqa: BLE001 — ne jamais laisser ce préparatif tuer le worker
        log.warning("Préparation recherche accélérée (Matryoshka) — échec non bloquant",
                    erreur=str(e) or type(e).__name__)


# Rythme de l'ordonnanceur de l'inventaire. L'intervalle RÉEL entre deux tournées est le réglage
# `inventaire_intervalle_min` ; ce tick sert seulement à le voir changer sans redémarrage.
TICK_INVENTAIRE_S = 60


async def _inventaire_scheduler() -> None:
    """Enfile la tournée de nuit de l'inventaire quand elle est due. Une erreur n'arrête jamais le cycle."""
    await asyncio.sleep(90)   # laisse le démarrage se stabiliser
    while True:
        try:
            from services.rangement import jobs as inventaire_jobs
            await inventaire_jobs.planifier_nuit()
        except Exception as e:  # noqa: BLE001
            log.error("Planification de l'inventaire échouée", erreur=str(e))
        await asyncio.sleep(TICK_INVENTAIRE_S)


async def start() -> None:
    """Démarre le worker : reprise des jobs orphelins puis lancement de la boucle."""
    global _worker_task, _backup_task, _sync_task, _prewarm_task, _matryoshka_task, _notif_task, _inventaire_task
    # Reprise : jobs restés 'running' après un crash → remis 'pending'.
    # ⚠️ En prod l'API tourne avec plusieurs process uvicorn (`--workers`), donc plusieurs boucles
    # worker. On protège la reprise par un **verrou d'avis Postgres** : UN SEUL process remet les
    # orphelins au démarrage (sinon double reset concurrent / risque de ré-injection d'un job en cours).
    async with AsyncSessionLocal() as db:
        # Verrou TRANSACTIONNEL : libéré par le commit. L'ancienne version prenait un verrou de
        # session puis committait avant de le relâcher — l'`unlock` tombait sur une autre
        # connexion du pool et le verrou FUYAIT, si bien que les démarrages suivants sautaient
        # définitivement la reprise (« déléguée à un autre worker » alors qu'il n'y en avait pas).
        got = (await db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": _REPRISE_LOCK})).scalar()
        if got:
            # Jobs fantômes : au-delà de MAX_REPRISES tentatives de reprise, on déclare le job
            # `failed` au lieu de le relancer indéfiniment (un job qui crashe le worker à chaque
            # exécution le bloquerait sinon en boucle). Sinon : running→pending, reprises + 1.
            morts = await db.execute(
                update(Job).where(Job.statut == "running", Job.reprises >= MAX_REPRISES)
                .values(statut="failed", completed_at=_now(),
                        erreur=f"Abandonné après {MAX_REPRISES} reprises (job instable)")
            )
            res = await db.execute(
                update(Job).where(Job.statut == "running")
                .values(statut="pending", started_at=None, progress=0,
                        annulation_demandee=False, reprises=Job.reprises + 1)
            )
            await db.commit()
            if res.rowcount:
                log.warning("Jobs orphelins remis en attente au démarrage", nb=res.rowcount,
                            abandonnes=morts.rowcount or 0)
        else:
            log.info("Reprise des orphelins déléguée à un autre worker (verrou déjà pris)")
    # Nettoie les temporaires laissés par un arrêt brutal précédent (fetch SMB interrompu).
    purger_temporaires()
    _worker_task = asyncio.create_task(_worker_loop())
    _backup_task = asyncio.create_task(_backup_scheduler())   # sauvegarde auto de la base
    _sync_task = asyncio.create_task(_sync_scheduler())       # synchro auto des sources
    _prewarm_task = asyncio.create_task(_prewarm_scheduler()) # garde le modèle de rapport chaud
    _notif_task = asyncio.create_task(_notifications_scheduler())  # bilan « idées d'évolution » (cloche)
    # Backfill + index HNSW (E7, une fois). Référence GARDÉE et arrêt propre, comme ses voisines :
    # sans référence, une tâche asyncio peut être ramassée en cours de route, et `stop()` ne
    # l'interrompait pas (audit du 28/09/2026).
    _matryoshka_task = asyncio.create_task(_matryoshka_scheduler())
    # Tournée de nuit de l'inventaire : seulement là où ses tâches sont enregistrées (le worker).
    if "inventaire_nuit" in _HANDLERS:
        _inventaire_task = asyncio.create_task(_inventaire_scheduler())
    log.info("Worker de jobs démarré", concurrence_gpu=CONCURRENCE_GPU, concurrence_io=CONCURRENCE_IO,
             handlers=sorted(_HANDLERS))


async def stop() -> None:
    """Arrête proprement la boucle worker + les planificateurs (sauvegarde, synchro)."""
    global _worker_task, _backup_task, _sync_task, _prewarm_task, _matryoshka_task, _notif_task, _inventaire_task
    for tache in (_worker_task, _backup_task, _sync_task, _prewarm_task, _matryoshka_task, _notif_task,
                  _inventaire_task):
        if tache:
            tache.cancel()
            try:
                await tache
            except asyncio.CancelledError:
                pass
    _worker_task = None
    _backup_task = None
    _sync_task = None
    _prewarm_task = None
    _matryoshka_task = None
    _notif_task = None
    _inventaire_task = None


async def request_cancel(db, job_id: str) -> str | None:
    """
    Demande l'annulation d'un job. `pending` → annulé direct ; `running` → drapeau EN BASE
    (`annulation_demandee`) que le worker relit à chaque tick (`_relire_annulations`). On met
    aussi à jour le set local au cas où API et worker partagent le process (mono-conteneur).
    """
    job = await db.get(Job, uuid.UUID(job_id))
    if not job:
        return None
    if job.statut == "pending":
        job.statut = "cancelled"
        job.completed_at = _now()
        await db.commit()
    elif job.statut == "running":
        job.annulation_demandee = True
        await db.commit()
        _cancel_requested.add(str(job.id))
    return job.statut


# ─── Handler de démonstration (preuve de bout en bout, sans effet de bord) ──────────────
@register("demo")
async def _handler_demo(ctx: JobContext) -> dict:
    """Job de démo : progresse par étapes en dormant, pour valider le pipeline durable."""
    etapes = int(ctx.parametres.get("etapes", 5))
    for i in range(etapes):
        if ctx.cancelled:
            break
        await asyncio.sleep(1.0)
        await ctx.report(progress=round((i + 1) / etapes * 100), message=f"Étape {i + 1}/{etapes}")
    return {"message": "Démo terminée", "etapes": etapes}
