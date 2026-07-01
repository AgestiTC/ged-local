"""
Router Generate — /api/generate
================================
Génération de rapports à partir de documents sélectionnés.

Endpoints :
  POST /generate/report           → génère un rapport (streaming SSE)
  POST /generate/fill-template    → remplit un template DOCX
  GET  /generate/stream/{job_id}  → flux SSE d'un rapport en cours
  GET  /generate/status/{job_id}  → statut d'un job de génération

Le streaming SSE permet l'affichage progressif côté frontend.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from logger import get_logger
from models.document import Document
from models.job import Job
from services.ollama_service import OllamaService

log = get_logger(__name__)
settings = get_settings()
router = APIRouter()

# Cache en mémoire des rapports générés (job_id → contenu)
# En production, utiliser Redis ou la table jobs.resultat
_rapports_cache: dict[str, str] = {}


class ReportRequest(BaseModel):
    document_ids: list[str] = Field(..., description="IDs des documents à analyser")
    prompt: str = Field(..., min_length=1, description="Instruction utilisateur")
    model: str | None = Field(default=None, description="Modèle Ollama (défaut : mixtral)")
    output_format: str = Field(default="markdown", description="markdown | text")


class TemplateFillRequest(BaseModel):
    document_ids: list[str] = Field(..., description="IDs des documents sources")
    template_id: str = Field(..., description="ID du template à remplir")
    instructions: str | None = Field(default=None, description="Instructions supplémentaires")
    model: str | None = Field(default=None, description="Modèle Ollama")


def _dates_doc(doc: Document) -> str:
    """Suffixe « (créé le … · modifié le …) » pour l'en-tête d'un document dans le contexte LLM."""
    from utils.file_utils import creation_date_from_tika

    parts = []
    creation = creation_date_from_tika(doc.tika_metadata)
    if creation:
        parts.append(f"créé le {creation[:10]}")
    if doc.date_modification_fichier:
        parts.append(f"modifié le {doc.date_modification_fichier.date().isoformat()}")
    return f" ({' · '.join(parts)})" if parts else ""


def _construire_contexte(docs: list[Document], prompt: str, max_chars: int = 80000) -> str:
    """
    Construit le contexte LLM à partir des documents sélectionnés.
    Tronque intelligemment si le contexte dépasse max_chars (~20k tokens pour Mixtral).
    """
    parts = []
    chars_restants = max_chars

    for doc in docs:
        texte = doc.texte_extrait or ""
        if not texte.strip():
            continue

        entete = f"\n--- Document : {doc.nom}{_dates_doc(doc)} ---\n"
        # Réserver de la place pour l'en-tête et une marge
        espace_dispo = chars_restants - len(entete) - 200
        if espace_dispo <= 0:
            break

        if len(texte) > espace_dispo:
            texte = texte[:espace_dispo] + "\n[... document tronqué ...]"

        parts.append(entete + texte)
        chars_restants -= len(entete) + len(texte)

    contexte_docs = "\n".join(parts)
    return f"{contexte_docs}\n\n--- Instruction ---\n{prompt}"


async def _generer_rapport_background(job_id: str, prompt_complet: str, model: str) -> None:
    """Génère le rapport en arrière-plan et stocke le résultat dans le cache + DB."""
    from database import AsyncSessionLocal

    ollama = OllamaService()
    contenu_complet = []

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
            job = result.scalar_one_or_none()
            if job:
                job.statut = "running"
                job.started_at = datetime.now(tz=timezone.utc)
                await db.commit()

        # Streaming Ollama — accumuler le contenu
        async for chunk in ollama.generate_stream(prompt_complet, model=model):
            contenu_complet.append(chunk)
            # Mettre à jour le cache pour le SSE
            _rapports_cache[job_id] = "".join(contenu_complet)

        rapport_final = "".join(contenu_complet)
        _rapports_cache[job_id] = rapport_final

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
            job = result.scalar_one_or_none()
            if job:
                job.statut = "completed"
                job.completed_at = datetime.now(tz=timezone.utc)
                job.resultat = {"rapport": rapport_final, "nb_chars": len(rapport_final)}
                await db.commit()

        log.info("Rapport généré", job_id=job_id, nb_chars=len(rapport_final))

    except Exception as e:
        log.error("Erreur génération rapport", job_id=job_id, erreur=str(e))
        _rapports_cache[job_id] = f"[Erreur de génération : {e}]"
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
                job = result.scalar_one_or_none()
                if job:
                    job.statut = "failed"
                    job.erreur = str(e)
                    job.completed_at = datetime.now(tz=timezone.utc)
                    await db.commit()
        except Exception:
            pass


@router.get("/generate/models")
async def list_models():
    """
    Retourne la liste des modèles Ollama disponibles.
    Proxy vers Ollama pour éviter les problèmes CORS depuis le frontend.
    """
    ollama = OllamaService()
    try:
        models = await ollama.list_models()
        return {"models": [{"name": m} for m in models]}
    except Exception as e:
        log.warning("Impossible de récupérer les modèles Ollama", erreur=str(e))
        # Retourner les modèles par défaut si Ollama est indisponible
        defaults = [
            settings.ollama_model_default,
            settings.ollama_model_fast,
        ]
        return {"models": [{"name": m} for m in defaults]}


@router.post("/generate/report")
async def generate_report(
    request: ReportRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Lance la génération d'un rapport en arrière-plan.
    Retourne un job_id à utiliser avec /generate/stream/{job_id}.
    """
    # Documents OPTIONNELS : un tuto wiki peut être rédigé « from scratch » (prompt seul).
    docs = []
    if request.document_ids:
        doc_uuids = []
        for doc_id in request.document_ids:
            try:
                doc_uuids.append(uuid.UUID(doc_id))
            except ValueError:
                raise HTTPException(status_code=400, detail=f"ID invalide : {doc_id}")

        result = await db.execute(
            select(Document).where(Document.id.in_(doc_uuids))
        )
        docs = result.scalars().all()

        if not docs:
            raise HTTPException(status_code=404, detail="Aucun document trouvé")

    docs_sans_texte = [d.nom for d in docs if not d.texte_extrait]
    if docs_sans_texte:
        log.warning("Documents sans texte extrait", noms=docs_sans_texte)

    # Construire le contexte
    model = request.model or settings.ollama_model_default
    prompt_complet = _construire_contexte(docs, request.prompt)

    # Créer le job
    job = Job(
        type="rapport",
        statut="pending",
        parametres={
            "document_ids": request.document_ids,
            "model": model,
            "output_format": request.output_format,
        },
    )
    db.add(job)
    await db.flush()
    job_id = str(job.id)

    # Initialiser le cache
    _rapports_cache[job_id] = ""

    # Lancer en arrière-plan
    background_tasks.add_task(_generer_rapport_background, job_id, prompt_complet, model)

    log.info("Génération rapport lancée", job_id=job_id, nb_docs=len(docs), model=model)
    return {
        "job_id": job_id,
        "statut": "en_attente",
        "nb_documents": len(docs),
        "model": model,
        "stream_url": f"/api/generate/stream/{job_id}",
    }


@router.get("/generate/stream/{job_id}")
async def stream_rapport(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Stream SSE du rapport en cours de génération.
    Le client reçoit les chunks au fur et à mesure.

    Format SSE :
      data: {"chunk": "...", "done": false}
      data: {"chunk": "", "done": true, "rapport_complet": "..."}
    """
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de job invalide")

    # Vérifier que le job existe
    result = await db.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trouvé")

    async def event_generator():
        """Génère les événements SSE."""
        position_envoyee = 0
        max_attente = 300  # 5 minutes max
        attente_totale = 0

        while attente_totale < max_attente:
            contenu_actuel = _rapports_cache.get(job_id, "")
            nouveau_contenu = contenu_actuel[position_envoyee:]

            if nouveau_contenu:
                data = json.dumps({"chunk": nouveau_contenu, "done": False})
                yield f"data: {data}\n\n"
                position_envoyee = len(contenu_actuel)

            # Vérifier si terminé (re-lire depuis DB)
            from database import AsyncSessionLocal
            async with AsyncSessionLocal() as db2:
                res = await db2.execute(select(Job.statut, Job.erreur).where(Job.id == uuid.UUID(job_id)))
                row = res.one_or_none()
                if row:
                    statut, erreur = row
                    if statut in ("completed", "failed"):
                        rapport_final = _rapports_cache.get(job_id, "")
                        data = json.dumps({
                            "chunk": "",
                            "done": True,
                            "statut": statut,
                            "rapport_complet": rapport_final,
                            "erreur": erreur,
                        })
                        yield f"data: {data}\n\n"
                        # Nettoyer le cache après envoi
                        _rapports_cache.pop(job_id, None)
                        return

            await asyncio.sleep(0.5)
            attente_totale += 0.5

        # Timeout
        yield f"data: {json.dumps({'chunk': '', 'done': True, 'statut': 'timeout'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Désactiver le buffering Nginx
        },
    )


@router.get("/generate/status/{job_id}")
async def get_generation_status(job_id: str, db: AsyncSession = Depends(get_db)):
    """Statut d'un job de génération (sans le contenu du rapport)."""
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de job invalide")

    result = await db.execute(select(Job).where(Job.id == job_uuid))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trouvé")

    # Progression approximative : taille actuelle du cache
    contenu_actuel = _rapports_cache.get(job_id, "")

    return {
        "job_id": job_id,
        "statut": job.statut,
        "nb_chars_generes": len(contenu_actuel),
        "erreur": job.erreur,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.post("/generate/fill-template")
async def fill_template(
    request: TemplateFillRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Remplit un template DOCX (tâche durable) : renvoie un `job_id` immédiatement. Une fois
    le job `completed`, le fichier est récupérable via `GET /generate/fill-template/download/{job_id}`.
    """
    if not request.document_ids:
        raise HTTPException(status_code=400, detail="Aucun document sélectionné")
    if not request.template_id:
        raise HTTPException(status_code=422, detail="template_id requis")

    from services import job_worker
    job_id = await job_worker.enqueue(db, "fill_template", {
        "document_ids": request.document_ids,
        "template_id": request.template_id,
        "instructions": request.instructions,
        "model": request.model or settings.ollama_model_default,
    })
    await db.commit()
    log.info("Remplissage template mis en file (job durable)", job_id=job_id)
    return {"job_id": job_id, "statut": "pending"}


@router.get("/generate/fill-template/download/{job_id}")
async def download_filled_template(job_id: str, db: AsyncSession = Depends(get_db)):
    """Télécharge le DOCX produit par un job `fill_template` terminé."""
    import os

    from fastapi.responses import FileResponse

    try:
        job = await db.get(Job, uuid.UUID(job_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de job invalide")
    if not job or job.type != "fill_template":
        raise HTTPException(status_code=404, detail="Job de remplissage non trouvé")
    if job.statut != "completed":
        raise HTTPException(status_code=409, detail=f"Job non terminé (statut : {job.statut})")

    res = job.resultat or {}
    chemin = res.get("path")
    if not chemin or not os.path.exists(chemin):
        raise HTTPException(status_code=404, detail="Fichier généré introuvable")
    return FileResponse(
        path=chemin,
        filename=res.get("filename", "document-rempli.docx"),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
