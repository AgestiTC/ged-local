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

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import AsyncSessionLocal
from logger import get_logger
from services import journal_questions, modeles_externes, prompts
from services.ollama_service import ErreurGeco, OllamaService, usage_ia
from utils.json_ia import lire_objet

log = get_logger(__name__)
settings = get_settings()
router = APIRouter()

MAX_PIECES = 5
TOP_PAR_PIECE = 3

class BesoinIn(BaseModel):
    besoin: str = Field(min_length=3)
    model: str | None = None


class QuestionIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    model: str | None = None


async def _hybride(piece: str, db: AsyncSession) -> list[dict]:
    """
    Recherche hybride pour une pièce (`recherche_hybride`, la même que la GED) ; top N docs.

    Les documents hors-sujet sont **écartés** par le gate de pertinence absolu : le score
    étant relatif au lot, sans lui l'assistant proposerait toujours des fichiers pour chaque
    pièce, même quand le corpus n'en contient aucun (cf. `services/pertinence.py`). Une pièce
    peut donc légitimement ressortir sans document.
    """
    from routers.search import recherche_hybride
    from services import pertinence

    h = await recherche_hybride(piece, db, limit=10, charger_texte=False)
    haut, bas = pertinence.seuils()
    nb_termes = pertinence.compter_termes(piece)

    out = []
    for doc, meta, score in h.candidats:
        doc_id = str(doc.id)
        pertinent, etiquette = pertinence.evaluer(
            h.cos_abs.get(doc_id), doc_id in h.ids_texte, haut, bas, nb_termes
        )
        if not pertinent:
            continue
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
    # Modèle via le routage par usage (rapide, installé) — évite le `mistral:latest` en dur
    # (supprimé de la machine → l'ancien défaut faisait échouer/ralentir la déduction).
    resolu = await modeles_externes.resoudre_modele_interactif(body.model, "enrichissement")
    ollama = OllamaService()
    model = resolu.nom
    prompt = prompts.rendre("assistant.pieces", besoin=body.besoin)   # registre (prompts A3c)
    try:
        # Usage « analyse » (prompts A3b) — PAS « enrichissement » (usage de fond, refusé à GECO) même si
        # le modèle est choisi comme pour l'enrichissement.
        with resolu.sortie("/api/assistant/pieces"), usage_ia("analyse"):   # ouvre l'envoi GECO (liste blanche) si modèle GECO
            reponse = await ollama.generate(prompt, model=model, format="json")
        data = lire_objet(reponse)
        if data is None:
            raise json.JSONDecodeError("Aucun objet JSON dans la réponse", reponse, 0)
    except ErreurGeco as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
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
async def poser_question(body: QuestionIn, request: Request) -> dict:
    """
    Sous-mode « Poser une question » (E8) : question NL → **réponse textuelle ancrée** + documents.
    Ex. « Où travaillait Thomas en juillet 2018 ? » / « Combien de temps chez LApp Muller ? ».

    La réponse ne cite QUE des faits présents dans des documents (gabarit déterministe, zéro
    invention) ; si rien n'est ancré, `reponse` est vide et `approchant=true` → l'UI propose les
    documents approchants (repli honnête, comme le bouton « Afficher quand même » de la recherche).
    """
    import time

    from services import qa_service

    resolu = await modeles_externes.resoudre_modele_interactif(body.model, "enrichissement")
    t0 = time.monotonic()
    rep: dict | None = None
    erreur: HTTPException | None = None
    try:
        # Les extraits retrouvés dans la GED partent aussi chez GECO ; chaque envoi est journalisé par
        # `OllamaService` (la marque est copiée dans les tâches créées par `asyncio.gather`).
        with resolu.sortie("/api/assistant/question"):
            rep = await qa_service.repondre(body.question, model=modeles_externes.modele_a_envoyer(resolu, body.model))
    except ErreurGeco as exc:
        erreur = HTTPException(status_code=exc.status_code, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — l'IA peut être injoignable
        log.error("Assistant question échouée", question=body.question[:80], erreur=str(exc))
        erreur = HTTPException(status_code=502, detail=f"IA injoignable ? {exc}")

    # Journal des questions (plan RAG, B2) — réussie ou non : une question sans réponse se juge aussi.
    reglages = {"modele_demande": (body.model or "").strip() or None}
    if rep is not None:
        reglages.update(intent=rep.get("intent"), confiance=rep.get("confiance"), approchant=rep.get("approchant"))
    qid = await journal_questions.ouvrir(
        origine="question", auteur=journal_questions.auteur_de(request), question=body.question,
        reglages=reglages,
        sources=[{"id": d.get("id"), "nom": d.get("nom"), "passages": []} for d in (rep or {}).get("documents") or []],
        modele=resolu.nom, prompts_cles=("qa.comprendre", "qa.extraire"),
        reponse=(rep or {}).get("reponse") or (erreur.detail if erreur else ""),
        statut="erreur" if erreur else "ok", duree_ms=int((time.monotonic() - t0) * 1000))
    if erreur:
        raise erreur
    return {**rep, "journal_id": qid}
