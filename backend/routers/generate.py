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
from services import runtime_config
from services.ollama_service import OllamaService

log = get_logger(__name__)
settings = get_settings()
router = APIRouter()

# Cache en mémoire des rapports générés (job_id → contenu)
# En production, utiliser Redis ou la table jobs.resultat
_rapports_cache: dict[str, str] = {}


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    """Dialogue LIBRE avec l'IA. `use_ged=True` → l'IA reçoit en contexte des extraits de la GED."""
    messages: list[ChatMessage] = Field(min_length=1)
    model: str | None = None   # None/'' → modèle par défaut des Paramètres
    use_ged: bool = False      # True → augmenter la réponse avec des extraits de documents (RAG)


async def _contexte_ged(question: str, nb: int = 5, taille: int = 1500) -> str:
    """
    Récupère des extraits de documents pertinents pour nourrir le chat (RAG).

    ⚠️ On NE cherche PAS la question brute (« peux-tu citer 3 entreprises où Thomas a travaillé ? »)
    — le full-text exige tous les mots → 0 résultat, et le gate rejette les formulations en question.
    On réutilise la **compréhension Q&R** (`qa_service`) : extraction des signaux (personnes,
    organisations, type de pièce) → récupération ciblée → extraits (texte, ou métadonnées si image).
    """
    from database import AsyncSessionLocal
    from services import qa_service, runtime_config

    model = runtime_config.model_for("chat")
    try:
        intent = await qa_service.comprendre(question, model)
        async with AsyncSessionLocal() as db:
            candidats = await qa_service.recuperer(intent, db)
    except Exception as e:  # noqa: BLE001 — un échec de récupération ne doit pas casser le chat
        log.warning("Contexte GED indisponible", erreur=str(e))
        return ""

    blocs, noms = [], []
    for c in candidats[:nb]:
        # Texte extrait, ou à défaut le résumé/tags/entités (utile pour une image sans OCR).
        brut = (c.get("texte") or "").strip() or (c.get("meta_texte") or "").strip()
        extrait = brut[:taille]
        if extrait:
            blocs.append(f"--- Document : {c['nom']} ---\n{extrait}")
            noms.append(c["nom"])
    contexte = "\n\n".join(blocs)
    log.info("Chat GED — contexte construit", question=question[:80], intent=intent.get("intent"),
             nb_candidats=len(candidats), nb_extraits=len(noms), nb_chars=len(contexte), documents=noms)
    return contexte


class ReportRequest(BaseModel):
    document_ids: list[str] = Field(..., description="IDs des documents à analyser")
    prompt: str = Field(..., min_length=1, description="Instruction utilisateur")
    model: str | None = Field(default=None, description="Modèle Ollama — vide = « Auto » (routage par usage : usage_models.rapport)")
    output_format: str = Field(default="markdown", description="markdown | text")
    mode: str | None = Field(default="rapport_libre", description="rapport_libre | classement | comparatif | wiki…")


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


async def _resoudre_modele(demande: str | None) -> str:
    """
    Modèle à utiliser pour un rapport — **validé AVANT d'ouvrir le flux**.

    `/generate` **streame** (SSE) : contrairement à l'enrichissement (`extraction.py`), on ne peut
    pas « basculer au modèle suivant » dans un `except` une fois le flux commencé. On valide donc
    en amont, tant qu'on peut encore choisir.

    Règles :
      - demande vide/None → **« Auto »** : routage par usage (`usage_models.rapport`) ;
      - demande **installée** → respectée (choix explicite de l'utilisateur) ;
      - demande **absente d'Ollama** (modèle supprimé, état client périmé) → 1er candidat de la
        même famille + trace. C'est ce cas qui cassait la génération (`mixtral` figé côté front).

    `model_candidates` ne renvoie que des modèles **réellement installés**, et retombe sur les
    modèles configurés si Ollama est injoignable → on ne bloque pas sur une panne réseau.
    """
    candidats = await runtime_config.model_candidates("rapport")
    defaut = runtime_config.model_for("rapport")
    if not candidats:                       # Ollama injoignable / aucun modèle texte listé
        return demande or defaut
    if demande:
        if demande in candidats:
            return demande
        log.warning("Modèle demandé indisponible — bascule sur un modèle installé",
                    demande=demande, retenu=candidats[0], installes=candidats)
        return candidats[0]
    # « Auto » : le défaut configuré s'il est installé, sinon le meilleur candidat disponible.
    if defaut not in candidats:
        log.warning("Modèle par défaut non installé — bascule", defaut=defaut, retenu=candidats[0])
        return candidats[0]
    return defaut


# Consigne système des rapports. Les modèles de RAISONNEMENT (Qwen3.6-35B) déversent sinon leur
# « chain-of-thought » — souvent en anglais (« Here's a thinking process: 1. Analyze… ») — dans la
# sortie. On leur impose une réponse directe, en français, sans préambule ni réflexion visible.
SYSTEM_RAPPORT = (
    "Tu es un assistant qui rédige des rapports en FRANÇAIS à partir de documents fournis. "
    "Réponds DIRECTEMENT avec le rapport final, en français, au format Markdown. "
    "N'affiche JAMAIS ton raisonnement, tes étapes de réflexion, ni de préambule "
    "(pas de « thinking process », pas de balises <think>, pas de méta-commentaire). "
    "Commence tout de suite par le contenu demandé."
)


def _bloc_sources(sources: list[dict] | None) -> str:
    """Bloc Markdown « Sources » ajouté À LA FIN du rapport. Vide si aucun document."""
    if not sources:
        return ""
    lignes = "\n".join(f"- {s.get('nom', '?')}" for s in sources)
    n = len(sources)
    return f"\n\n---\n\n**Sources** *({n} document{'s' if n > 1 else ''})* :\n{lignes}\n"


def _titre_rapport(contenu: str, prompt: str) -> str:
    """Titre de l'historique : 1er titre Markdown, sinon début du prompt, sinon générique."""
    for ligne in contenu.split("\n"):
        if ligne.strip().startswith("#"):
            return ligne.lstrip("# ").strip()[:120]
    if prompt.strip():
        return prompt.strip()[:80]
    return "Rapport"


async def _archiver_rapport(titre: str, mode: str, prompt: str, modele: str,
                            contenu: str, sources: list[dict] | None) -> None:
    """Enregistre le rapport terminé dans l'historique persistant (table `rapports`)."""
    from database import AsyncSessionLocal
    from models.rapport import Rapport
    try:
        async with AsyncSessionLocal() as db:
            db.add(Rapport(
                titre=titre, mode=mode, prompt=prompt, modele=modele,
                contenu=contenu, nb_caracteres=len(contenu), sources=sources or [],
            ))
            await db.commit()
    except Exception as e:  # noqa: BLE001 — l'archivage ne doit jamais faire échouer la génération
        log.warning("Archivage du rapport dans l'historique échoué", erreur=str(e))


async def _generer_rapport_background(job_id: str, prompt_complet: str, model: str,
                                      sources: list[dict] | None = None,
                                      prompt_user: str = "", mode: str = "rapport_libre",
                                      correlation_id: str | None = None) -> None:
    """Génère le rapport en arrière-plan et stocke le résultat dans le cache + DB."""
    import time as _time

    from database import AsyncSessionLocal
    from services import audit

    ollama = OllamaService()
    contenu_complet = []
    _t0 = _time.monotonic()
    await audit.emit("generate_report", "start", acteur="worker", correlation_id=correlation_id,
                     cible=_titre_rapport("", prompt_user), detail={"model": model, "nb_sources": len(sources or [])})

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
            job = result.scalar_one_or_none()
            if job:
                job.statut = "running"
                job.started_at = datetime.now(tz=timezone.utc)
                await db.commit()

        # Streaming Ollama — accumuler le contenu. `think=False` supprime le raisonnement visible
        # côté Ollama : la consigne système seule ne suffisait PAS sur un modèle de raisonnement
        # (Qwen3.6-35B affichait quand même « Here's a thinking process »). Agnostique du modèle —
        # sans effet sur ceux qui n'en ont pas — donc valable quel que soit le modèle configuré.
        async for chunk in ollama.generate_stream(prompt_complet, model=model,
                                                  system=SYSTEM_RAPPORT, think=False):
            contenu_complet.append(chunk)
            # Mettre à jour le cache pour le SSE
            _rapports_cache[job_id] = "".join(contenu_complet)

        # Ajoute la liste des documents sources À LA FIN (dans tous les exports : PDF/DOCX/MD/Wiki).
        rapport_final = "".join(contenu_complet) + _bloc_sources(sources)
        _rapports_cache[job_id] = rapport_final

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
            job = result.scalar_one_or_none()
            if job:
                job.statut = "completed"
                job.completed_at = datetime.now(tz=timezone.utc)
                job.resultat = {"rapport": rapport_final, "nb_chars": len(rapport_final)}
                await db.commit()

        # Archivage dans l'historique persistant (best effort — n'échoue jamais la génération).
        titre = _titre_rapport(rapport_final, prompt_user)
        await _archiver_rapport(titre, mode, prompt_user, model, rapport_final, sources)

        log.info("Rapport généré", job_id=job_id, nb_chars=len(rapport_final))
        await audit.emit("generate_report", "success", acteur="worker", correlation_id=correlation_id,
                         cible=titre, duree_ms=int((_time.monotonic() - _t0) * 1000),
                         detail={"nb_chars": len(rapport_final), "model": model})

    except Exception as e:
        # ⚠️ `str(e)` est VIDE pour plusieurs exceptions httpx (ReadTimeout, RemoteProtocolError…) :
        # on affichait « Erreur de génération : » sans rien, et le log n'en disait pas plus — donc
        # impossible de distinguer un timeout d'un modèle absent ou d'une coupure du proxy.
        # On journalise désormais le TYPE (toujours présent) et la trace complète.
        detail = str(e) or repr(e) or "(aucun message)"
        cause = f"{type(e).__name__}: {detail}"
        log.error("Erreur génération rapport", job_id=job_id, type_erreur=type(e).__name__,
                  erreur=detail, modele=model, exc_info=True)
        _rapports_cache[job_id] = f"[Erreur de génération — {cause}]"
        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
                job = result.scalar_one_or_none()
                if job:
                    job.statut = "failed"
                    job.erreur = cause   # type + message : « failed » sans cause n'aide personne
                    job.completed_at = datetime.now(tz=timezone.utc)
                    await db.commit()
        except Exception:
            pass
        await audit.emit("generate_report", "error", acteur="worker", correlation_id=correlation_id,
                         duree_ms=int((_time.monotonic() - _t0) * 1000), message=cause)


@router.post("/generate/chat")
async def chat(body: ChatRequest):
    """
    Dialogue LIBRE avec l'IA (aide à la rédaction, questions, brouillon de mail…), **sans lien
    avec la GED**. Modèle = celui fourni, sinon le **modèle par défaut des Paramètres**. Réponse
    en **streaming texte** (le frontend lit le flux au fil de l'eau). `think=False` pour éviter le
    raisonnement déversé par les modèles de type Qwen.
    """
    import time as _time

    modele = (body.model or "").strip() or runtime_config.model_for("chat")
    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    derniere = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    log.info("Chat — requête reçue", modele=modele, use_ged=body.use_ged,
             nb_messages=len(messages), question=derniere[:120])

    # Option GED : on injecte en tête un message SYSTÈME contenant des extraits de documents
    # pertinents pour la dernière question → l'IA peut s'appuyer dessus (RAG), sans y être forcée.
    if body.use_ged:
        contexte = await _contexte_ged(derniere) if derniere else ""
        if contexte:
            messages = [{
                "role": "system",
                "content": (
                    "Tu peux t'appuyer sur ces extraits de documents de l'utilisateur (GED) pour "
                    "répondre. Cite le nom du document quand tu utilises une information. Si la "
                    "réponse n'y figure pas, réponds normalement avec tes connaissances.\n\n" + contexte
                ),
            }] + messages
        else:
            log.info("Chat — GED activé mais aucun extrait trouvé", question=derniere[:80])

    async def flux():
        t0 = _time.monotonic()
        nb_chars = 0
        statut = "ok"
        try:
            async for chunk in OllamaService().chat_stream(messages, model=modele, think=False):
                nb_chars += len(chunk)
                yield chunk
        except Exception as e:  # noqa: BLE001 — on informe l'utilisateur dans le flux
            statut = "erreur"
            log.error("Chat — streaming échoué", erreur=str(e), modele=modele, use_ged=body.use_ged)
            yield f"\n\n⚠️ IA injoignable ({e})."
        finally:
            log.info("Chat — terminé", statut=statut, modele=modele, use_ged=body.use_ged,
                     nb_chars_reponse=nb_chars, duree_ms=int((_time.monotonic() - t0) * 1000))

    return StreamingResponse(flux(), media_type="text/plain; charset=utf-8")


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
    model = await _resoudre_modele(request.model)
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

    # Lancer en arrière-plan. Sources = {id, nom} : nom listé en fin de rapport (traçabilité dans
    # les exports) ET id archivé dans l'historique (même si le document est supprimé plus tard).
    sources = [{"id": str(d.id), "nom": d.nom} for d in docs]
    from services import audit
    cid = audit.new_correlation_id()
    await audit.emit("generate_report", "queued", acteur="api", correlation_id=cid,
                     cible=(request.prompt or "")[:80], detail={"model": model, "nb_docs": len(docs)})
    background_tasks.add_task(
        _generer_rapport_background, job_id, prompt_complet, model, sources,
        request.prompt, request.mode or "rapport_libre", cid,
    )

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
        # Même garde que /generate/report : ne jamais figer dans le job un modèle désinstallé.
        "model": await _resoudre_modele(request.model),
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
