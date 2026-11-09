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
import re
import uuid
from typing import Literal, NamedTuple
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
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

# Le rapport en cours vit EN BASE (`jobs.resultat["rapport"]`), écrit par le worker durable
# (services/rapport_jobs.py). Avant (18/09/2026) : un dict par process uvicorn — avec `--workers 2`,
# le flux servi par l'autre process ne voyait rien et rendait un rapport vide.


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    """
    Dialogue LIBRE avec l'IA.

    `ged_mode` pilote l'appui sur la GED (RAG) :
      - "auto"     : (défaut) la GED n'est interrogée que si la question porte sur les documents
                     de l'utilisateur (pré-détection sans LLM, puis `qa_service.comprendre`) ;
      - "toujours" : récupération systématique ;
      - "jamais"   : aucun appel à `qa_service`.
    `use_ged` est conservé pour les anciens clients : True → "toujours" ; False EXPLICITE →
    "jamais" (ces clients, ex. le chat « IA Internet », disaient non à la GED : on ne leur
    ouvre pas les documents par surprise) ; absent → "auto". `ged_mode` l'emporte s'il est fourni.
    """
    messages: list[ChatMessage] = Field(min_length=1)
    model: str | None = None   # None/'' → modèle par défaut des Paramètres
    use_ged: bool | None = None
    ged_mode: Literal["auto", "toujours", "jamais"] | None = None


def _mode_ged(body: ChatRequest) -> str:
    """Mode GED effectif (voir `ChatRequest`)."""
    if body.ged_mode:
        return body.ged_mode
    if body.use_ged is True:
        return "toujours"
    if body.use_ged is False:
        return "jamais"
    return "auto"


# Vocabulaire de pièces / données personnelles : signal « la question porte sur mes documents ».
_MOTS_PIECES = (
    "licence", "attestation", "contrat", "facture", "bulletin", "fiche de paie", "fiche de paye",
    "numero", "numéro", "document", "documents", "dossier", "passeport", "carte d'identite",
    "carte d'identité", "diplome", "diplôme", "devis", "avenant", "releve", "relevé", "justificatif",
    "quittance", "assurance", "mutuelle", "impot", "impôt", "avis d'imposition", "certificat",
    "ordonnance", "cv", "scan",
)
_RE_POSSESSIF = re.compile(r"\b(mon|ma|mes)\b", re.IGNORECASE)
_RE_PIECES = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(m) for m in _MOTS_PIECES) + r")(?!\w)")


def _question_peut_etre_documentaire(question: str) -> bool:
    """
    Pré-détection BON MARCHÉ (sans LLM) : la question vise-t-elle peut-être les documents de
    l'utilisateur ? Vrai si possessif (mon/ma/mes), vocabulaire de pièces, ou nom propre
    (mot capitalisé hors début de phrase). Les faux positifs sont acceptés : `comprendre` tranche
    ensuite. Les faux négatifs restent rattrapables par le mode « toujours ».
    """
    q = (question or "").strip()
    if not q:
        return False
    bas = q.lower()
    if _RE_POSSESSIF.search(bas) or _RE_PIECES.search(bas):
        return True
    # Nom propre : mot capitalisé qui n'ouvre pas une phrase.
    debut = True
    for m in re.finditer(r"\S+", q):
        mot = m.group(0)
        mot_nu = mot.strip("\"'«»()[]{}.,;:!?…")
        if not debut and len(mot_nu) > 1 and mot_nu[:1].isupper() and not mot_nu.isupper():
            return True
        debut = mot[-1:] in ".!?:…"
    return False


def _intent_documentaire(intent: dict) -> bool:
    """L'intention extraite par `qa_service.comprendre` vise-t-elle des documents ?"""
    return bool(intent.get("personnes") or intent.get("organisations") or intent.get("type_piece")
                or (intent.get("intent") or "autre") != "autre")


# Consignes système du chat (RAG). Deux cas, l'intention générale n'en reçoit AUCUNE.
CONSIGNE_GED_EXTRAITS = (
    "Tu peux t'appuyer sur ces extraits de documents de l'utilisateur (GED) pour répondre. "
    "Cite le nom du document quand tu utilises une information. Si la question porte sur une "
    "personne ou une pièce précise (licence, contrat, numéro…) et que l'information demandée ne "
    "figure PAS dans ces extraits, dis-le clairement (« Cette information ne figure pas dans les "
    "documents retrouvés ») au lieu de la déduire de tes connaissances générales ou de l'inventer. "
    "Pour toute autre question, réponds normalement avec tes connaissances.\n\n"
)
CONSIGNE_GED_VIDE = (
    "La question de l'utilisateur porte sur ses propres documents (GED), mais aucun document "
    "pertinent n'a été retrouvé. N'invente AUCUNE information (nom, numéro, date, montant) et ne "
    "réponds pas avec des connaissances générales sur une personne ou une pièce. Réponds : "
    "« Je n'ai pas trouvé ce document dans la GED. » Tu peux suggérer de reformuler la question "
    "(nom complet, type de pièce) ou de vérifier que le document a bien été indexé."
)


class ContexteGed(NamedTuple):
    """Résultat de `_contexte_ged` : texte à injecter + documents cités ({id, nom})."""
    contexte: str
    sources: list[dict]
    documentaire: bool = False   # l'intention visait des documents (même si aucun extrait n'a été trouvé)


_AUCUN_CONTEXTE = ContexteGed("", [])
_NB_SOURCES_ENTETE = 5
_NOM_SOURCE_MAX = 80
_ENTETE_SOURCES_MAX = 3000       # taille MAX de la valeur ENCODÉE (les proxys coupent vers 8 Ko)
_QUESTION_MAX = 500              # question transmise à `comprendre`


def _entetes_ged(ctx: ContexteGed) -> dict[str, str]:
    """
    En-têtes de réponse destinés au front. Un en-tête HTTP est ASCII : `X-Ged-Sources` =
    JSON `[{"id","nom"}, …]` puis percent-encoding (`urllib.parse.quote`, safe=""), à décoder
    côté client par `decodeURIComponent` + `JSON.parse`. Noms tronqués, liste bornée.
    """
    sources = [{"id": s.get("id"), "nom": str(s.get("nom", ""))[:_NOM_SOURCE_MAX]}
               for s in ctx.sources[:_NB_SOURCES_ENTETE]] if ctx.contexte else []
    valeur = quote(json.dumps(sources, ensure_ascii=False), safe="")
    while sources and len(valeur) > _ENTETE_SOURCES_MAX:   # CJK/accents : x9 à l'encodage
        sources.pop()
        valeur = quote(json.dumps(sources, ensure_ascii=False), safe="")
    return {"X-Ged-Utilise": "1" if ctx.contexte else "0", "X-Ged-Sources": valeur}


async def _contexte_ged(question: str, nb: int = 5, taille: int = 1500, auto: bool = False) -> ContexteGed:
    """
    Récupère des extraits de documents pertinents pour nourrir le chat (RAG).

    ⚠️ On NE cherche PAS la question brute (« peux-tu citer 3 entreprises où Thomas a travaillé ? »)
    — le full-text exige tous les mots → 0 résultat, et le gate rejette les formulations en question.
    On réutilise la **compréhension Q&R** (`qa_service`) : extraction des signaux (personnes,
    organisations, type de pièce) → récupération ciblée → extraits (texte, ou métadonnées si image).

    `auto=True` : si `comprendre` ne voit aucun signal documentaire, on ne récupère rien.
    """
    from database import AsyncSessionLocal
    from services import qa_service, runtime_config

    model = runtime_config.model_for("chat")
    try:
        intent = await qa_service.comprendre(question[:_QUESTION_MAX], model)
        documentaire = _intent_documentaire(intent)
        if auto and not documentaire:
            log.info("Chat GED auto — intention non documentaire", nb_chars_question=len(question))
            return _AUCUN_CONTEXTE
        async with AsyncSessionLocal() as db:
            candidats = await qa_service.recuperer(intent, db)
    except Exception as e:  # noqa: BLE001 — un échec de récupération ne doit pas casser le chat
        log.warning("Contexte GED indisponible", erreur=str(e))
        return _AUCUN_CONTEXTE

    blocs, sources = [], []
    for c in candidats[:nb]:
        # Texte extrait, ou à défaut le résumé/tags/entités (utile pour une image sans OCR).
        brut = (c.get("texte") or "").strip() or (c.get("meta_texte") or "").strip()
        extrait = brut[:taille]
        if extrait:
            blocs.append(f"--- Document : {c['nom']} ---\n{extrait}")
            sources.append({"id": c.get("id"), "nom": c["nom"]})
    contexte = "\n\n".join(blocs)
    # Journal sans la question ni les noms de documents (confidentialité) : compteurs seulement.
    log.info("Chat GED — contexte construit", intent=intent.get("intent"),
             nb_candidats=len(candidats), nb_extraits=len(sources), nb_chars=len(contexte))
    return ContexteGed(contexte, sources, documentaire)


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


async def _resoudre_modele(demande: str | None, usage: str = "rapport") -> str:
    """
    Modèle à utiliser pour un `usage` (rapport, chat…) — **validé AVANT d'ouvrir le flux**.

    `/generate` **streame** (SSE) : contrairement à l'enrichissement (`extraction.py`), on ne peut
    pas « basculer au modèle suivant » dans un `except` une fois le flux commencé. On valide donc
    en amont, tant qu'on peut encore choisir.

    Règles :
      - demande vide/None → **« Auto »** : routage par usage (`usage_models[usage]`) ;
      - demande **installée** → respectée (choix explicite de l'utilisateur) ;
      - demande OU défaut **absent d'Ollama** (modèle supprimé, config/état client périmé) → 1er
        candidat installé de la même famille + trace. C'est ce cas qui « proposait un modèle
        disparu » et cassait la génération/le chat.

    `model_candidates` ne renvoie que des modèles **réellement installés**, et retombe sur les
    modèles configurés si Ollama est injoignable → on ne bloque pas sur une panne réseau.
    """
    candidats = await runtime_config.model_candidates(usage)
    defaut = runtime_config.model_for(usage)
    if not candidats:                       # Ollama injoignable / aucun modèle de cette famille listé
        return demande or defaut
    if demande:
        if demande in candidats:
            return demande
        log.warning("Modèle demandé indisponible — bascule sur un modèle installé",
                    usage=usage, demande=demande, retenu=candidats[0], installes=candidats)
        return candidats[0]
    # « Auto » : le défaut configuré s'il est installé, sinon le meilleur candidat disponible.
    if defaut not in candidats:
        log.warning("Modèle par défaut non installé — bascule", usage=usage, defaut=defaut, retenu=candidats[0])
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


# La génération elle-même est le handler `rapport` du worker durable : services/rapport_jobs.py.


@router.post("/generate/chat")
async def chat(body: ChatRequest):
    """
    Dialogue LIBRE avec l'IA (aide à la rédaction, questions, brouillon de mail…), **sans lien
    avec la GED**. Modèle = celui fourni, sinon le **modèle par défaut des Paramètres**. Réponse
    en **streaming texte** (le frontend lit le flux au fil de l'eau). `think=False` pour éviter le
    raisonnement déversé par les modèles de type Qwen.
    """
    import time as _time

    # Résolution ROBUSTE : si le modèle demandé/par défaut n'est plus installé (supprimé côté
    # Ollama), on bascule sur un modèle texte réellement présent → plus de « IA injoignable »
    # à cause d'une config périmée. (Même garde que les rapports.)
    modele = await _resoudre_modele((body.model or "").strip() or None, "chat")
    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    derniere = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    mode = _mode_ged(body)
    log.info("Chat — requête reçue", modele=modele, ged_mode=mode,
             nb_messages=len(messages), nb_chars_question=len(derniere))

    # Appui sur la GED (RAG) : message SYSTÈME en tête avec des extraits pertinents pour la dernière
    # question. "jamais" → aucun appel à qa_service ; "auto" → seulement si la question semble
    # documentaire (pré-détection sans LLM, puis `comprendre`) ; "toujours" → systématique.
    ctx = _AUCUN_CONTEXTE
    if derniere and mode != "jamais" and (mode == "toujours" or _question_peut_etre_documentaire(derniere)):
        ctx = await _contexte_ged(derniere, auto=(mode == "auto"))
    if ctx.contexte:
        messages = [{"role": "system", "content": CONSIGNE_GED_EXTRAITS + ctx.contexte}] + messages
    elif ctx.documentaire:
        # Question documentaire sans aucun extrait : on interdit d'inventer (étape 2 du plan).
        messages = [{"role": "system", "content": CONSIGNE_GED_VIDE}] + messages
        log.info("Chat — question documentaire sans extrait", mode=mode)

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
            log.error("Chat — streaming échoué", erreur=str(e), modele=modele, ged_mode=mode)
            yield f"\n\n⚠️ IA injoignable ({e})."
        finally:
            log.info("Chat — terminé", statut=statut, modele=modele, ged_mode=mode,
                     nb_chars_reponse=nb_chars, duree_ms=int((_time.monotonic() - t0) * 1000))

    return StreamingResponse(flux(), media_type="text/plain; charset=utf-8", headers=_entetes_ged(ctx))


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
    db: AsyncSession = Depends(get_db),
):
    """
    Met la génération d'un rapport en file (tâche durable du worker, prioritaire sur les lots).
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

    # Modèle validé AVANT la mise en file (cf. `_resoudre_modele`) : jamais un modèle désinstallé.
    model = await _resoudre_modele(request.model)

    # Sources = {id, nom} : nom listé en fin de rapport (traçabilité dans les exports) ET id archivé
    # dans l'historique (même si le document est supprimé plus tard). Le contexte est reconstruit
    # par le worker à partir des ids : on n'embarque pas 80 000 caractères dans les paramètres.
    sources = [{"id": str(d.id), "nom": d.nom} for d in docs]
    from services import job_worker
    job_id = await job_worker.enqueue(db, "rapport", {
        "document_ids": [s["id"] for s in sources],
        "prompt": request.prompt,
        "model": model,
        "mode": request.mode or "rapport_libre",
        "output_format": request.output_format,
        "sources": sources,
        "cible": (request.prompt or "")[:80],
    })
    await db.commit()

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
        """
        Relit le rapport partiel EN BASE à chaque tour : n'importe quel process uvicorn peut servir
        ce flux. Un commentaire SSE part toutes les ~15 s de silence (attente dans la file, chargement
        à froid du modèle) : sans lui, le proxy nginx coupe un flux muet au bout de 60 s.
        """
        from database import AsyncSessionLocal

        position_envoyee = 0
        attente, max_attente = 0.0, 3600.0   # chargement à froid d'un gros modèle + rédaction longue
        depuis_signal = 0.0

        while attente < max_attente:
            async with AsyncSessionLocal() as db2:
                row = (await db2.execute(
                    select(Job.statut, Job.erreur, Job.resultat).where(Job.id == uuid.UUID(job_id))
                )).one_or_none()
            if row is None:
                yield f"data: {json.dumps({'chunk': '', 'done': True, 'statut': 'failed', 'erreur': 'Job introuvable'})}\n\n"
                return
            statut, erreur, resultat = row
            contenu_actuel = (resultat or {}).get("rapport") or ""

            nouveau_contenu = contenu_actuel[position_envoyee:]
            if nouveau_contenu:
                yield f"data: {json.dumps({'chunk': nouveau_contenu, 'done': False})}\n\n"
                position_envoyee = len(contenu_actuel)
                depuis_signal = 0.0

            if statut in ("completed", "failed", "cancelled"):
                # Contrat inchangé pour le frontend : en échec, `rapport_complet` porte le message
                # d'erreur (c'est lui qui s'affiche), `erreur` la cause technique.
                rapport_final = contenu_actuel if statut == "completed" else (
                    f"[Erreur de génération — {erreur or 'génération interrompue'}]")
                yield "data: " + json.dumps({
                    "chunk": "", "done": True, "statut": statut,
                    "rapport_complet": rapport_final, "erreur": erreur,
                }) + "\n\n"
                return

            await asyncio.sleep(0.5)
            attente += 0.5
            depuis_signal += 0.5
            if depuis_signal >= 15:
                yield ": attente\n\n"   # commentaire SSE, ignoré par EventSource
                depuis_signal = 0.0

        # Délai dépassé : le rapport continue côté worker, il sera dans l'historique.
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

    # Progression approximative : taille du texte déjà écrit en base par le worker.
    nb_chars = int((job.resultat or {}).get("nb_chars") or 0)

    return {
        "job_id": job_id,
        "statut": job.statut,
        "nb_chars_generes": nb_chars,
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
