"""
Router Assistant — /api/assistant
=================================
Assistant de constitution de dossier : à partir d'un **besoin** en langage naturel
(« j'ai besoin de documents pour un dossier de location »), l'IA déduit la liste des
**pièces attendues**, puis pour chaque pièce on lance une **recherche hybride** dans
la GED et on propose les fichiers connus.

  POST /assistant/pieces  → {besoin} → {pieces: [{libelle, documents:[...]}]}
"""

import asyncio
import json
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import AsyncSessionLocal
from logger import get_logger
from services.ollama_service import OllamaService

log = get_logger(__name__)
settings = get_settings()
router = APIRouter()

MAX_PIECES = 5
TOP_PAR_PIECE = 3

PROMPT_PIECES = """Tu es un assistant de gestion documentaire.
À partir du besoin de l'utilisateur, liste les TYPES DE PIÈCES / DOCUMENTS attendus pour
constituer ce dossier (termes courts et génériques, en français).
Réponds UNIQUEMENT par un JSON valide : {"pieces": ["...", "...", ...]}.
Maximum 8 pièces, du plus important au moins important."""


class BesoinIn(BaseModel):
    besoin: str = Field(min_length=3)
    model: str | None = None


class QuestionIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    model: str | None = None


def _json(texte: str) -> dict:
    try:
        return json.loads(texte)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", texte, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


async def _hybride(piece: str, db: AsyncSession) -> list[dict]:
    """
    Recherche hybride (texte 40 % + sémantique 60 %) pour une pièce ; top N docs.

    Les documents hors-sujet sont **écartés** par le gate de pertinence absolu : le score
    étant normalisé par le meilleur du lot, sans lui l'assistant proposerait toujours des
    fichiers pour chaque pièce, même quand le corpus n'en contient aucun (cf.
    `services/pertinence.py`). Une pièce peut donc légitimement ressortir sans document.
    """
    from routers.search import _recherche_fulltext, _recherche_semantique
    from services import pertinence

    text_res = await _recherche_fulltext(piece, db, limit=10)
    sem_res = await _recherche_semantique(piece, db, limit=10)

    max_t = max((s for _, _, s in text_res), default=1.0) or 1.0
    max_s = max((s for _, _, s in sem_res), default=1.0) or 1.0
    scores: dict = {}
    docs: dict = {}
    for doc, meta, s in text_res:
        scores[str(doc.id)] = scores.get(str(doc.id), 0) + 0.4 * (s / max_t)
        docs[str(doc.id)] = (doc, meta)
    for doc, meta, s in sem_res:
        scores[str(doc.id)] = scores.get(str(doc.id), 0) + 0.6 * (s / max_s)
        docs[str(doc.id)] = (doc, meta)

    # Signaux ABSOLUS du gate (perdus par la normalisation ci-dessus).
    cos_abs = {str(doc.id): s for doc, _, s in sem_res}
    ids_texte = {str(doc.id) for doc, _, _ in text_res}
    haut, bas = pertinence.seuils()

    out = []
    for doc_id, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        pertinent, etiquette = pertinence.evaluer(
            cos_abs.get(doc_id), doc_id in ids_texte, haut, bas
        )
        if not pertinent:
            continue
        doc, meta = docs[doc_id]
        out.append({
            "id": doc_id, "nom": doc.nom, "extension": doc.extension,
            "categorie": meta.categorie if meta else None,
            "score": round(score, 3),
            "etiquette": etiquette,
        })
        if len(out) >= TOP_PAR_PIECE:
            break
    return out


async def _piece_isolee(libelle: str) -> dict:
    """
    Recherche les documents d'une pièce dans une **session DB dédiée** afin de pouvoir
    lancer toutes les pièces en parallèle (`AsyncSession` n'est pas concurrente).
    Résiliente : en cas d'erreur, renvoie la pièce sans documents.
    """
    try:
        async with AsyncSessionLocal() as db:
            documents = await _hybride(libelle, db)
        return {"libelle": libelle, "documents": documents}
    except Exception as exc:  # noqa: BLE001 — une pièce qui échoue ne doit pas tout faire échouer
        log.warning("Assistant : recherche d'une pièce échouée", piece=libelle, erreur=str(exc))
        return {"libelle": libelle, "documents": []}


@router.post("/assistant/pieces", tags=["Assistant"])
async def proposer_pieces(body: BesoinIn) -> dict:
    """Déduit les pièces attendues d'un besoin et propose les fichiers connus pour chacune."""
    ollama = OllamaService()
    # Modèle via le routage par usage (rapide, installé) — évite le `mistral:latest` en dur
    # (supprimé de la machine → l'ancien défaut faisait échouer/ralentir la déduction).
    from services import runtime_config
    model = body.model or runtime_config.model_for("enrichissement")
    try:
        reponse = await ollama.generate(
            f"{PROMPT_PIECES}\n\nBesoin : {body.besoin}", model=model, format="json"
        )
        data = _json(reponse)
    except Exception as exc:
        log.error("Assistant : déduction des pièces échouée", erreur=str(exc))
        raise HTTPException(status_code=502, detail=f"IA injoignable ? {exc}")

    pieces_libelles = [str(p).strip() for p in (data.get("pieces") or []) if str(p).strip()][:MAX_PIECES]
    if not pieces_libelles:
        raise HTTPException(status_code=422, detail="Aucune pièce déduite du besoin")

    # Recherches lancées EN PARALLÈLE (une session DB par pièce) — l'ordre est préservé.
    pieces = list(await asyncio.gather(*(_piece_isolee(lib) for lib in pieces_libelles)))

    log.info("Assistant pièces", besoin=body.besoin[:60], nb_pieces=len(pieces))
    return {"besoin": body.besoin, "pieces": pieces}


@router.post("/assistant/question", tags=["Assistant"])
async def poser_question(body: QuestionIn) -> dict:
    """
    Sous-mode « Poser une question » (E8) : question NL → **réponse textuelle ancrée** + documents.
    Ex. « Où travaillait Thomas en juillet 2018 ? » / « Combien de temps chez LApp Muller ? ».

    La réponse ne cite QUE des faits présents dans des documents (gabarit déterministe, zéro
    invention) ; si rien n'est ancré, `reponse` est vide et `approchant=true` → l'UI propose les
    documents approchants (repli honnête, comme le bouton « Afficher quand même » de la recherche).
    """
    from services import qa_service

    try:
        return await qa_service.repondre(body.question, model=body.model)
    except Exception as exc:  # noqa: BLE001 — l'IA peut être injoignable
        log.error("Assistant question échouée", question=body.question[:80], erreur=str(exc))
        raise HTTPException(status_code=502, detail=f"IA injoignable ? {exc}")
