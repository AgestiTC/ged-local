"""
Journal des questions posées à l'IA sur les documents (plan prompts + RAG, étape B2)
=====================================================================================
Écrit par le chat appuyé sur la GED et par le mode Question ; lu par `routers/journal_questions.py`.
Le modèle de données et la règle de conservation : `models/rag_question.py`.

**Un journal ne casse jamais ce qu'il trace** : toute erreur d'écriture est consignée (sans la
question : confidentialité) et l'appelant continue comme si de rien n'était.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update

from logger import get_logger
from models.rag_question import RagQuestion
from models.rag_retour import RagRetour

log = get_logger(__name__)

QUESTION_MAX = 20_000     # caractères gardés d'une question (un message collé peut être long)
REPONSE_MAX = 100_000     # caractères gardés d'une réponse
RETENTION_DEFAUT = 180    # jours (décision Q3) ; 0 = tout garder


def auteur_de(request) -> str | None:
    """Qui pose la question : identifiant SSO, `jeton:<nom>`, ou « api » sans authentification."""
    from services.acces import role_appelant

    try:
        return role_appelant(request)[1]
    except Exception:  # noqa: BLE001 — requête de test sans état
        return None


def versions(cles) -> list[dict]:
    """[{cle, version}] des prompts réellement servis (0 = texte d'origine du code), sans doublon."""
    from services import prompts

    return [{"cle": cle, "version": prompts.version_servie(cle)} for cle in dict.fromkeys(c for c in cles if c)]


async def ouvrir(*, origine: str, auteur: str | None, question: str, reglages: dict | None = None,
                 sources: list | None = None, modele: str | None = None, prompts_cles=(),
                 reponse: str | None = None, statut: str = "en_cours", duree_ms: int | None = None) -> str | None:
    """Inscrit une question ; rend son identifiant, ou None si le journal est indisponible."""
    from database import AsyncSessionLocal

    ligne = RagQuestion(
        id=uuid.uuid4(), origine=origine, auteur=auteur, question=(question or "")[:QUESTION_MAX],
        reglages=reglages or {}, sources=sources or [], modele=modele, prompts=versions(prompts_cles),
        reponse=(reponse[:REPONSE_MAX] if reponse is not None else None), statut=statut, duree_ms=duree_ms,
    )
    try:
        async with AsyncSessionLocal() as db:
            db.add(ligne)
            await db.commit()
        return str(ligne.id)
    except Exception as e:  # noqa: BLE001 — le journal ne casse jamais la question
        log.warning("Journal des questions : écriture impossible", origine=origine, erreur=str(e) or type(e).__name__)
        return None


async def clore(qid: str | None, *, reponse: str, statut: str, duree_ms: int) -> None:
    """Complète une question ouverte par `ouvrir` (réponse en flux : connue seulement à la fin)."""
    if not qid:
        return
    from database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(update(RagQuestion).where(RagQuestion.id == uuid.UUID(qid)).values(
                reponse=(reponse or "")[:REPONSE_MAX], statut=statut, duree_ms=duree_ms))
            await db.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("Journal des questions : clôture impossible", erreur=str(e) or type(e).__name__)


def retention_jours() -> int:
    """Conservation réglée, en jours (0 = tout garder)."""
    from services import runtime_config

    try:
        return int(float(runtime_config.effective("rag_questions_retention_jours")))
    except (TypeError, ValueError):
        return RETENTION_DEFAUT


async def purger_anciens() -> int:
    """Efface les questions plus vieilles que la conservation réglée (0 = tout garder). Rend le nombre."""
    jours = retention_jours()
    if jours <= 0:
        return 0
    from database import AsyncSessionLocal

    limite = datetime.now(timezone.utc) - timedelta(days=jours)
    try:
        async with AsyncSessionLocal() as db:
            anciennes = RagQuestion.created_at < limite
            # Retours (B3) d'abord : la cascade de la clé étrangère n'existe pas sous SQLite.
            await db.execute(delete(RagRetour).where(
                RagRetour.question_id.in_(select(RagQuestion.id).where(anciennes))))
            res = await db.execute(delete(RagQuestion).where(anciennes))
            await db.commit()
            if res.rowcount:
                log.info("Journal des questions purgé", supprimees=res.rowcount, jours=jours)
            return res.rowcount or 0
    except Exception as e:  # noqa: BLE001
        log.warning("Purge du journal des questions échouée", erreur=str(e) or type(e).__name__)
        return 0
