"""
Handler de job — tableau comparatif multi-groupes (`comparatif`).
=================================================================
Avant le 18/09/2026, la comparaison tournait dans une `asyncio.create_task` du process uvicorn qui
avait reçu la demande, avec son état dans un dict en mémoire. Le backend tourne avec `--workers 2` :
le suivi (SSE) ou le téléchargement arrivait une fois sur deux sur l'AUTRE process → « Job
introuvable ». Désormais : tâche durable du worker, progression écrite dans `jobs.resultat["events"]`,
relue par n'importe quel process. Le calcul (critères → groupes → synthèse) reste dans
routers/compare.py ; ce module ne fait que l'orchestrer.

Module séparé (comme regroupement_jobs.py), importé au démarrage par main.py et worker.py.
"""
import uuid

from database import AsyncSessionLocal
from logger import get_logger
from models.document import Document
from models.job import Job
from services.job_worker import JobContext, register

log = get_logger(__name__)


async def _persister(job_id: str, resultat: dict) -> None:
    """Écrit l'état courant (événements compris) dans `jobs.resultat` — lu par le flux SSE."""
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, uuid.UUID(job_id))
        if job is not None:
            job.resultat = dict(resultat)   # nouvel objet : SQLAlchemy détecte le changement JSONB
            await db.commit()


@register("comparatif")
async def handler_comparatif(ctx: JobContext) -> dict:
    """
    Paramètres : `groupes` [{nom, document_ids}], `colonnes` (vides = déduites par l'IA),
    `model`, `instructions`, `synthese` (bool), `template_id` (repris au téléchargement).
    """
    from routers.compare import (
        _analyser_groupe, _charger_documents, _deduire_colonnes, _synthetiser_ecarts,
    )
    from services.ollama_service import OllamaService

    p = ctx.parametres
    groupes = p.get("groupes") or []
    if len(groupes) < 2:
        raise ValueError("Au moins 2 groupes sont nécessaires")
    model = p.get("model")
    instructions = p.get("instructions")
    colonnes: list[str] = list(p.get("colonnes") or [])
    ollama = OllamaService()
    total = len(groupes)

    etat: dict = {"events": [], "colonnes": colonnes, "groupes": [], "synthese": None,
                  "criteres_par_defaut": False, "groupes_en_echec": []}

    async def emettre(evt: dict) -> None:
        etat["events"].append(evt)
        await _persister(ctx.job_id, etat)

    # Étape 0 — critères déduits par l'IA (ni template, ni saisie manuelle)
    if not colonnes:
        await emettre({"statut": "criteres", "message": "Détermination des critères de comparaison…"})
        echantillon: list[Document] = []
        for g in groupes:
            echantillon += await _charger_documents(list(g.get("document_ids") or [])[:2])
        colonnes, par_defaut = await _deduire_colonnes(echantillon, instructions, model, ollama)
        etat["colonnes"], etat["criteres_par_defaut"] = colonnes, par_defaut
        await emettre({"statut": "criteres", "colonnes": colonnes})
        if par_defaut:
            await emettre({"statut": "criteres",
                           "message": "L'IA n'a proposé aucun critère exploitable : critères génériques utilisés."})

    for idx, g in enumerate(groupes, start=1):
        if ctx.cancelled:
            log.info("Comparatif annulé", job_id=ctx.job_id, groupes_faits=idx - 1)
            return etat
        nom = g.get("nom") or f"Groupe {idx}"
        await ctx.report(int(100 * (idx - 1) / (total + 1)), f"Analyse de « {nom} » ({idx}/{total})…")
        await emettre({"groupe": nom, "statut": "running", "index": idx, "total": total})

        docs = await _charger_documents(list(g.get("document_ids") or []))
        valeurs, ok = await _analyser_groupe(
            nom_groupe=nom, docs=docs, colonnes=colonnes,
            instructions=instructions, model=model, ollama=ollama,
        )
        ligne = {"nom": nom, "valeurs": valeurs}
        if not ok:
            ligne["echec_ia"] = True
            etat["groupes_en_echec"].append(nom)
        etat["groupes"].append(ligne)
        await emettre({"groupe": nom, "statut": "done", "index": idx, "total": total, "echec_ia": not ok})

    # Tous les groupes en échec : ce n'est pas un tableau, c'est un échec — on le dit.
    if etat["groupes_en_echec"] and len(etat["groupes_en_echec"]) == total:
        raise RuntimeError("L'IA n'a rien pu extraire pour aucun groupe (réponses sans JSON exploitable) "
                           "— vérifier le modèle « rapport » dans les Paramètres")

    # Synthèse des écarts (facultative — le tableau reste exploitable si elle échoue)
    if p.get("synthese", True):
        await emettre({"statut": "synthese", "message": "Rédaction de la synthèse des écarts…"})
        etat["synthese"] = await _synthetiser_ecarts(colonnes, etat["groupes"], instructions, model, ollama)

    log.info("Tableau comparatif généré", job_id=ctx.job_id, nb_groupes=total, nb_criteres=len(colonnes),
             groupes_en_echec=etat["groupes_en_echec"], criteres_par_defaut=etat["criteres_par_defaut"])
    return etat   # écrit dans jobs.resultat par le worker, avec le statut « completed »
