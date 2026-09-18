"""
Handler de job — rapport libre (`rapport`), généré en streaming.
================================================================
Avant le 18/09/2026, le rapport était produit par une BackgroundTask du process uvicorn qui avait
reçu la demande, le texte en cours s'accumulant dans un dict en mémoire (`_rapports_cache`). Avec
`--workers 2`, le flux SSE servi par l'AUTRE process ne voyait rien arriver, puis rendait un
rapport vide à la fin. Même défaut que le tableau comparatif (v1.110.0).

Désormais : tâche durable du worker. Le texte partiel est écrit dans `jobs.resultat["rapport"]`
environ une fois par seconde ; le flux SSE (routers/generate.py) le relit en base, depuis
n'importe quel process.
"""
import time
import uuid

from sqlalchemy import select

from database import AsyncSessionLocal
from logger import get_logger
from models.document import Document
from models.job import Job
from services.job_worker import JobContext, register

log = get_logger(__name__)

# Fréquence d'écriture du texte partiel en base : assez pour un affichage fluide, sans écrire
# une ligne par token (un rapport en compte des milliers).
_PERSISTANCE_S = 1.0


async def _persister(job_id: str, rapport: str) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, uuid.UUID(job_id))
        if job is not None:
            job.resultat = {"rapport": rapport, "nb_chars": len(rapport)}
            await db.commit()


async def _charger_documents(ids: list[str]) -> list[Document]:
    uuids = []
    for x in ids:
        try:
            uuids.append(uuid.UUID(str(x)))
        except ValueError:
            continue
    if not uuids:
        return []
    async with AsyncSessionLocal() as db:
        docs = (await db.execute(select(Document).where(Document.id.in_(uuids)))).scalars().all()
    # Conserver l'ordre choisi par l'utilisateur (il structure souvent le rapport).
    rang = {u: i for i, u in enumerate(uuids)}
    return sorted(docs, key=lambda d: rang.get(d.id, 0))


@register("rapport")
async def handler_rapport(ctx: JobContext) -> dict:
    """Paramètres : `prompt`, `model`, `document_ids`, `mode`, `sources` [{id, nom}]."""
    from routers.generate import (
        SYSTEM_RAPPORT, _archiver_rapport, _bloc_sources, _construire_contexte, _titre_rapport,
    )
    from services.ollama_service import OllamaService

    p = ctx.parametres
    prompt = p.get("prompt")
    model = p.get("model")
    if not prompt or not model:
        # Ligne créée par l'ancienne API (avant le passage au worker) : rien à régénérer.
        raise ValueError("Paramètres de rapport incomplets (prompt/modèle) — relancer la génération")
    sources = p.get("sources") or []

    docs = await _charger_documents(p.get("document_ids") or [])
    prompt_complet = _construire_contexte(docs, prompt)
    await ctx.report(10, f"Rédaction — modèle {model}…")

    morceaux: list[str] = []
    derniere_ecriture = time.monotonic()
    try:
        # `think=False` : pas de raisonnement visible (modèles Qwen) — cf. SYSTEM_RAPPORT.
        async for chunk in OllamaService().generate_stream(prompt_complet, model=model,
                                                            system=SYSTEM_RAPPORT, think=False):
            morceaux.append(chunk)
            if time.monotonic() - derniere_ecriture >= _PERSISTANCE_S:
                await _persister(ctx.job_id, "".join(morceaux))
                derniere_ecriture = time.monotonic()
            if ctx.cancelled:
                log.info("Rapport annulé", job_id=ctx.job_id, nb_chars=sum(map(len, morceaux)))
                break
    except Exception as e:  # noqa: BLE001 — on requalifie pour un message exploitable
        # ⚠️ `str(e)` est VIDE pour plusieurs exceptions httpx (ReadTimeout, RemoteProtocolError…) :
        # on garde le TYPE, sans quoi « failed » n'aide personne à distinguer timeout et modèle absent.
        cause = f"{type(e).__name__}: {str(e) or repr(e) or '(aucun message)'}"
        log.error("Erreur génération rapport", job_id=ctx.job_id, type_erreur=type(e).__name__,
                  erreur=cause, modele=model, exc_info=True)
        raise RuntimeError(cause) from e

    # Sources listées À LA FIN (reprises dans tous les exports : PDF/DOCX/MD/Wiki).
    rapport_final = "".join(morceaux) + _bloc_sources(sources)
    if not ctx.cancelled:
        await _archiver_rapport(_titre_rapport(rapport_final, prompt), p.get("mode") or "rapport_libre",
                                prompt, model, rapport_final, sources)
    log.info("Rapport généré", job_id=ctx.job_id, nb_chars=len(rapport_final), modele=model)
    return {"rapport": rapport_final, "nb_chars": len(rapport_final)}
