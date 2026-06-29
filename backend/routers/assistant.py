"""
Router Assistant — /api/assistant
=================================
Assistant de constitution de dossier : à partir d'un **besoin** en langage naturel
(« j'ai besoin de documents pour un dossier de location »), l'IA déduit la liste des
**pièces attendues**, puis pour chaque pièce on lance une **recherche hybride** dans
la GED et on propose les fichiers connus.

  POST /assistant/pieces  → {besoin} → {pieces: [{libelle, documents:[...]}]}
"""

import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from logger import get_logger
from services.ollama_service import OllamaService

log = get_logger(__name__)
settings = get_settings()
router = APIRouter()

MAX_PIECES = 8
TOP_PAR_PIECE = 3

PROMPT_PIECES = """Tu es un assistant de gestion documentaire.
À partir du besoin de l'utilisateur, liste les TYPES DE PIÈCES / DOCUMENTS attendus pour
constituer ce dossier (termes courts et génériques, en français).
Réponds UNIQUEMENT par un JSON valide : {"pieces": ["...", "...", ...]}.
Maximum 8 pièces, du plus important au moins important."""


class BesoinIn(BaseModel):
    besoin: str = Field(min_length=3)
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
    """Recherche hybride (texte 40 % + sémantique 60 %) pour une pièce ; top N docs."""
    from routers.search import _recherche_fulltext, _recherche_semantique

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

    classes = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:TOP_PAR_PIECE]
    out = []
    for doc_id, score in classes:
        doc, meta = docs[doc_id]
        out.append({
            "id": doc_id, "nom": doc.nom, "extension": doc.extension,
            "categorie": meta.categorie if meta else None,
            "score": round(score, 3),
        })
    return out


@router.post("/assistant/pieces", tags=["Assistant"])
async def proposer_pieces(body: BesoinIn, db: AsyncSession = Depends(get_db)) -> dict:
    """Déduit les pièces attendues d'un besoin et propose les fichiers connus pour chacune."""
    ollama = OllamaService()
    model = body.model or settings.ollama_model_fast
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

    pieces = []
    for libelle in pieces_libelles:
        documents = await _hybride(libelle, db)
        pieces.append({"libelle": libelle, "documents": documents})

    log.info("Assistant pièces", besoin=body.besoin[:60], nb_pieces=len(pieces))
    return {"besoin": body.besoin, "pieces": pieces}
