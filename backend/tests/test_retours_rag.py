"""
Retours sur les réponses de l'IA (plan prompts + RAG, étape B3). Questions, documents et auteurs FICTIFS.

Acceptation du plan : un retour s'enregistre en un clic. Plus : seul l'auteur de la question juge,
chaque champ s'envoie seul (les autres restent), une source jugée doit être une source de la
réponse, et le retour disparaît avec sa question.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.rag_question import RagQuestion
from models.rag_retour import RagRetour
from services import journal_questions

DOC_A = "11111111-1111-1111-1111-111111111111"
DOC_B = "22222222-2222-2222-2222-222222222222"
INCONNU = "33333333-3333-3333-3333-333333333333"


def _en_tant_que(role, qui):
    return patch("routers.journal_questions.role_appelant", lambda _r: (role, qui))


async def _question(db, auteur="alice", **extra) -> str:
    q = RagQuestion(origine="chat", auteur=auteur, question="question fictive", statut="ok", reponse="réponse fictive",
                    sources=[{"id": DOC_A, "nom": "a.pdf", "passages": [3]}, {"id": DOC_B, "nom": "b.pdf", "passages": []}],
                    **extra)
    db.add(q)
    await db.commit()
    return str(q.id)


async def _nb_retours(db) -> int:
    return (await db.execute(select(func.count()).select_from(RagRetour))).scalar_one()


def _juger(client, qid, corps):
    return client.put(f"/api/journal-questions/{qid}/retour", json=corps)


class TestUnClic:
    @pytest.mark.asyncio
    async def test_pouce_seul(self, client, db_session):
        qid = await _question(db_session)
        with _en_tant_que("utilisateur", "alice"):
            r = await _juger(client, qid, {"avis": "utile"})
            assert r.status_code == 200
            assert r.json()["retour"]["avis"] == "utile"
            d = (await client.get(f"/api/journal-questions/{qid}")).json()
        assert d["retour"]["avis"] == "utile" and d["peut_juger"] is True and d["avis"] == "utile"

    @pytest.mark.asyncio
    async def test_chaque_champ_seul_les_autres_restent(self, client, db_session):
        qid = await _question(db_session)
        with _en_tant_que("utilisateur", "alice"):
            await _juger(client, qid, {"avis": "inutile"})
            await _juger(client, qid, {"sources": {DOC_A: "hors_sujet"}})
            await _juger(client, qid, {"sources": {DOC_B: "pertinent"}})
            r = (await _juger(client, qid, {"correction": "  La bonne réponse fictive.  "})).json()["retour"]
        assert r["avis"] == "inutile"
        assert r["sources"] == {DOC_A: "hors_sujet", DOC_B: "pertinent"}
        assert r["correction"] == "La bonne réponse fictive."

    @pytest.mark.asyncio
    async def test_retirer_puis_plus_de_ligne(self, client, db_session):
        qid = await _question(db_session)
        with _en_tant_que("utilisateur", "alice"):
            await _juger(client, qid, {"avis": "utile", "sources": {DOC_A: "pertinent"}})
            await _juger(client, qid, {"sources": {DOC_A: None}})
            r = await _juger(client, qid, {"avis": None})
        assert r.json() == {"retour": None}
        assert await _nb_retours(db_session) == 0

    @pytest.mark.asyncio
    async def test_un_retour_vide_ne_cree_rien(self, client, db_session):
        qid = await _question(db_session)
        with _en_tant_que("utilisateur", "alice"):
            assert (await _juger(client, qid, {"correction": "   "})).json() == {"retour": None}
        assert await _nb_retours(db_session) == 0


class TestQuiJuge:
    @pytest.mark.asyncio
    async def test_l_admin_lit_mais_ne_juge_pas_la_question_d_un_autre(self, client, db_session):
        qid = await _question(db_session, auteur="bob")
        with _en_tant_que("admin", "thomas"):
            assert (await client.get(f"/api/journal-questions/{qid}")).json()["peut_juger"] is False
            assert (await _juger(client, qid, {"avis": "utile"})).status_code == 403

    @pytest.mark.asyncio
    async def test_un_utilisateur_ne_voit_pas_celle_d_un_autre(self, client, db_session):
        qid = await _question(db_session, auteur="bob")
        with _en_tant_que("utilisateur", "alice"):
            assert (await _juger(client, qid, {"avis": "utile"})).status_code == 404


class TestValidation:
    @pytest.mark.asyncio
    async def test_source_hors_de_la_reponse_refusee(self, client, db_session):
        qid = await _question(db_session)
        with _en_tant_que("utilisateur", "alice"):
            assert (await _juger(client, qid, {"sources": {INCONNU: "pertinent"}})).status_code == 422
        assert await _nb_retours(db_session) == 0

    @pytest.mark.asyncio
    async def test_valeurs_inconnues_refusees(self, client, db_session):
        qid = await _question(db_session)
        with _en_tant_que("utilisateur", "alice"):
            assert (await _juger(client, qid, {"avis": "bof"})).status_code == 422
            assert (await _juger(client, qid, {"sources": {DOC_A: "peut-être"}})).status_code == 422


class TestBilanEtFiltres:
    @pytest.mark.asyncio
    async def test_bilan_et_filtres(self, client, db_session):
        q1 = await _question(db_session)
        q2 = await _question(db_session)
        await _question(db_session)
        with _en_tant_que("utilisateur", "alice"):
            await _juger(client, q1, {"avis": "utile"})
            await _juger(client, q2, {"avis": "inutile", "correction": "corrigée"})
            corps = (await client.get("/api/journal-questions")).json()
            assert corps["retours"] == {"utile": 1, "inutile": 1, "corrigees": 1}
            assert corps["total"] == 3

            def lister(avis):
                return client.get("/api/journal-questions", params={"avis": avis})

            assert [q["id"] for q in (await lister("utile")).json()["questions"]] == [q1]
            inutiles = (await lister("inutile")).json()["questions"]
            assert [q["id"] for q in inutiles] == [q2] and inutiles[0]["corrigee"] is True
            assert (await lister("corrigee")).json()["total"] == 1
            assert (await lister("avec")).json()["total"] == 2
            assert (await lister("sans")).json()["total"] == 1
            assert (await lister("nimporte")).status_code == 422


class TestDisparaitAvecSaQuestion:
    @pytest.mark.asyncio
    async def test_effacer_la_question(self, client, db_session):
        qid = await _question(db_session)
        with _en_tant_que("utilisateur", "alice"):
            await _juger(client, qid, {"avis": "utile"})
            await client.delete(f"/api/journal-questions/{qid}")
        assert await _nb_retours(db_session) == 0

    @pytest.mark.asyncio
    async def test_tout_effacer_ne_touche_que_les_siennes(self, client, db_session):
        a = await _question(db_session)
        b = await _question(db_session, auteur="bob")
        with _en_tant_que("utilisateur", "alice"):
            await _juger(client, a, {"avis": "utile"})
        with _en_tant_que("utilisateur", "bob"):
            await _juger(client, b, {"avis": "inutile"})
        with _en_tant_que("utilisateur", "alice"):
            await client.delete("/api/journal-questions")
        restants = (await db_session.execute(select(RagRetour.avis))).scalars().all()
        assert restants == ["inutile"]

    @pytest.mark.asyncio
    async def test_purge_de_conservation(self, test_engine):
        fabrique = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
        with patch("database.AsyncSessionLocal", fabrique):
            async with fabrique() as db:
                vieille = await _question(db, created_at=datetime.now(timezone.utc) - timedelta(days=400))
                recente = await _question(db)
                db.add(RagRetour(question_id=uuid.UUID(vieille), avis="utile"))
                db.add(RagRetour(question_id=uuid.UUID(recente), avis="inutile"))
                await db.commit()
            assert await journal_questions.purger_anciens() == 1
            async with fabrique() as db:
                assert (await db.execute(select(RagRetour.avis))).scalars().all() == ["inutile"]
