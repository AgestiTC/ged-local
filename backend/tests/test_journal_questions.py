"""
Journal des questions posées à l'IA sur les documents (plan prompts + RAG, étape B2).
Questions, documents et auteurs FICTIFS.

Acceptation du plan : chaque question du chat et du mode Question est retrouvable avec ses sources
et sa version de prompt. Plus : chacun ne voit que les siennes, conservation bornée, et le journal
ne casse jamais la question qu'il trace.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.rag_question import RagQuestion
from services import journal_questions, runtime_config

DOC = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def base(test_engine):
    """Le service ouvre ses propres sessions (`database.AsyncSessionLocal`) : on les pointe sur la base de test."""
    fabrique = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)
    with patch("database.AsyncSessionLocal", fabrique):
        yield fabrique


async def _lignes(fabrique) -> list[RagQuestion]:
    async with fabrique() as db:
        return list((await db.execute(select(RagQuestion).order_by(RagQuestion.created_at))).scalars())


# ─── Service ──────────────────────────────────────────────────────────────────

class TestService:
    @pytest.mark.asyncio
    async def test_ouvrir_puis_clore(self, base):
        qid = await journal_questions.ouvrir(
            origine="chat", auteur="alice", question="Où est le contrat fictif ?",
            reglages={"ged_mode": "auto"}, sources=[{"id": DOC, "nom": "contrat-fictif.pdf", "passages": [12]}],
            modele="modele-fictif", prompts_cles=["chat.ged.extraits", None, "chat.ged.extraits"])
        await journal_questions.clore(qid, reponse="Dans le dossier fictif.", statut="ok", duree_ms=42)
        [q] = await _lignes(base)
        assert str(q.id) == qid and q.statut == "ok" and q.reponse == "Dans le dossier fictif." and q.duree_ms == 42
        assert q.sources[0]["passages"] == [12]
        assert q.prompts == [{"cle": "chat.ged.extraits", "version": 0}]   # sans doublon ni clé vide

    @pytest.mark.asyncio
    async def test_version_servie_tracee(self, base):
        with patch("services.prompts.version_servie", lambda cle: 3 if cle == "qa.comprendre" else 0):
            await journal_questions.ouvrir(origine="question", auteur="a", question="q fictive",
                                           prompts_cles=("qa.comprendre", "qa.extraire"))
        [q] = await _lignes(base)
        assert q.prompts == [{"cle": "qa.comprendre", "version": 3}, {"cle": "qa.extraire", "version": 0}]

    @pytest.mark.asyncio
    async def test_journal_indisponible_ne_casse_rien(self):
        casse = MagicMock(side_effect=RuntimeError("base fictive en panne"))
        with patch("database.AsyncSessionLocal", casse):
            assert await journal_questions.ouvrir(origine="chat", auteur="a", question="q") is None
            await journal_questions.clore("00000000-0000-0000-0000-000000000001", reponse="r", statut="ok", duree_ms=1)

    @pytest.mark.asyncio
    async def test_textes_bornes(self, base):
        await journal_questions.ouvrir(origine="chat", auteur="a", question="x" * 30_000, reponse="y" * 200_000, statut="ok")
        [q] = await _lignes(base)
        assert len(q.question) == journal_questions.QUESTION_MAX and len(q.reponse) == journal_questions.REPONSE_MAX


class TestConservation:
    def test_180_jours_par_defaut(self):
        assert journal_questions.retention_jours() == 180

    @pytest.mark.asyncio
    async def test_purge_des_anciennes(self, base):
        async with base() as db:
            db.add(RagQuestion(origine="chat", auteur="a", question="vieille", statut="ok",
                               created_at=datetime.now(timezone.utc) - timedelta(days=200)))
            db.add(RagQuestion(origine="chat", auteur="a", question="récente", statut="ok",
                               created_at=datetime.now(timezone.utc) - timedelta(days=10)))
            await db.commit()
        assert await journal_questions.purger_anciens() == 1
        assert [q.question for q in await _lignes(base)] == ["récente"]

    @pytest.mark.asyncio
    async def test_zero_garde_tout(self, base):
        runtime_config._overrides["rag_questions_retention_jours"] = "0"
        async with base() as db:
            db.add(RagQuestion(origine="chat", auteur="a", question="vieille", statut="ok",
                               created_at=datetime.now(timezone.utc) - timedelta(days=900)))
            await db.commit()
        assert await journal_questions.purger_anciens() == 0
        assert len(await _lignes(base)) == 1


# ─── Routes de consultation ───────────────────────────────────────────────────

async def _semer(db):
    for auteur, q in (("alice", "question fictive d'Alice"), ("bob", "question fictive de Bob")):
        db.add(RagQuestion(origine="chat", auteur=auteur, question=q, statut="ok", reponse="r",
                           sources=[{"id": DOC, "nom": "fictif.pdf", "passages": []}],
                           prompts=[{"cle": "chat.ged.extraits", "version": 0}]))
    await db.commit()


def _en_tant_que(role, qui):
    return patch("routers.journal_questions.role_appelant", lambda _r: (role, qui))


class TestRoutes:
    @pytest.mark.asyncio
    async def test_chacun_ses_questions(self, client, db_session):
        await _semer(db_session)
        with _en_tant_que("utilisateur", "alice"):
            r = await client.get("/api/journal-questions", params={"tous": "true"})   # `tous` ignoré : pas admin
        assert r.status_code == 200
        corps = r.json()
        assert corps["total"] == 1 and corps["questions"][0]["question"] == "question fictive d'Alice"
        assert corps["retention_jours"] == 180

    @pytest.mark.asyncio
    async def test_admin_voit_tout(self, client, db_session):
        await _semer(db_session)
        with _en_tant_que("admin", "thomas"):
            assert (await client.get("/api/journal-questions")).json()["total"] == 0
            assert (await client.get("/api/journal-questions", params={"tous": "true"})).json()["total"] == 2

    @pytest.mark.asyncio
    async def test_detail_avec_sources_et_versions(self, client, db_session):
        await _semer(db_session)
        with _en_tant_que("utilisateur", "alice"):
            qid = (await client.get("/api/journal-questions")).json()["questions"][0]["id"]
            d = (await client.get(f"/api/journal-questions/{qid}")).json()
        assert d["sources"][0]["nom"] == "fictif.pdf" and d["prompts"] == [{"cle": "chat.ged.extraits", "version": 0}]

    @pytest.mark.asyncio
    async def test_celle_d_un_autre_est_introuvable(self, client, db_session):
        await _semer(db_session)
        with _en_tant_que("admin", "x"):
            bob = [q for q in (await client.get("/api/journal-questions", params={"tous": "true"})).json()["questions"]
                   if q["auteur"] == "bob"][0]["id"]
        with _en_tant_que("utilisateur", "alice"):
            assert (await client.get(f"/api/journal-questions/{bob}")).status_code == 404
            assert (await client.delete(f"/api/journal-questions/{bob}")).status_code == 404

    @pytest.mark.asyncio
    async def test_effacer_les_siennes(self, client, db_session):
        await _semer(db_session)
        with _en_tant_que("utilisateur", "alice"):
            assert (await client.delete("/api/journal-questions", params={"tous": "true"})).json() == {"supprimees": 1}
        with _en_tant_que("admin", "x"):
            restantes = (await client.get("/api/journal-questions", params={"tous": "true"})).json()["questions"]
        assert [q["auteur"] for q in restantes] == ["bob"]

    @pytest.mark.asyncio
    async def test_origine_inconnue(self, client):
        assert (await client.get("/api/journal-questions", params={"origine": "autre"})).status_code == 422


# ─── Le chat et le mode Question écrivent au journal ──────────────────────────

class _OllamaFactice:
    async def chat_stream(self, messages, model=None, think=False):
        yield "Réponse "
        yield "fictive."


@pytest.fixture
def journal():
    ouvrir = AsyncMock(return_value="22222222-2222-2222-2222-222222222222")
    clore = AsyncMock()
    with patch.object(journal_questions, "ouvrir", ouvrir), patch.object(journal_questions, "clore", clore):
        yield SimpleNamespace(ouvrir=ouvrir, clore=clore)


@pytest.fixture
def chat_isole():
    async def _resoudre(demande=None, usage="rapport"):
        from services.modeles_externes import ModeleResolu
        return ModeleResolu(demande or "modele-fictif")
    long_doc = {"id": DOC, "nom": "manuel-fictif.pdf", "texte": "Sommaire. " + "z" * 5000, "meta_texte": ""}
    with patch("routers.generate._resoudre_complet", new=AsyncMock(side_effect=_resoudre)), \
         patch("routers.generate._recherche_mots_cles", new=AsyncMock(return_value=[long_doc])), \
         patch("services.qa_service.comprendre", AsyncMock(return_value={"intent": "recherche", "type_piece": ["manuel"]})), \
         patch("services.passages.meilleurs_passages", AsyncMock(return_value={DOC: [(130, "Passage fictif.")]})), \
         patch("routers.generate.OllamaService", _OllamaFactice):
        yield


def _chat(client, question, **extra):
    return client.post("/api/generate/chat", json={"messages": [{"role": "user", "content": question}], **extra})


class TestChat:
    @pytest.mark.asyncio
    async def test_question_tracee_avec_passages_et_prompts(self, client, journal, chat_isole):
        r = await _chat(client, "Que dit le manuel fictif ?", ged_mode="toujours")
        assert r.status_code == 200 and r.text == "Réponse fictive."
        assert r.headers["X-Rag-Question"] == "22222222-2222-2222-2222-222222222222"
        kw = journal.ouvrir.await_args.kwargs
        assert kw["origine"] == "chat" and kw["question"] == "Que dit le manuel fictif ?"
        assert kw["sources"] == [{"id": DOC, "nom": "manuel-fictif.pdf", "passages": [130]}]
        assert [c for c in kw["prompts_cles"] if c] == ["qa.comprendre", "chat.ged.extraits"]
        assert kw["reglages"]["ged_mode"] == "toujours" and kw["modele"] == "modele-fictif"
        fin = journal.clore.await_args
        assert fin.args[0] == "22222222-2222-2222-2222-222222222222"
        assert fin.kwargs["reponse"] == "Réponse fictive." and fin.kwargs["statut"] == "ok"

    @pytest.mark.asyncio
    async def test_mode_jamais_non_trace(self, client, journal, chat_isole):
        r = await _chat(client, "Rédige un mail fictif", ged_mode="jamais")
        assert r.status_code == 200 and "X-Rag-Question" not in r.headers
        journal.ouvrir.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_reponse_interrompue(self, journal, chat_isole):
        from routers import generate
        corps = generate.ChatRequest(messages=[{"role": "user", "content": "Que dit le manuel fictif ?"}], ged_mode="toujours")
        rep = await generate.chat(corps, SimpleNamespace(state=SimpleNamespace()))
        flux = rep.body_iterator
        assert await flux.__anext__() == "Réponse "
        await flux.aclose()                       # le navigateur coupe (bouton Arrêter)
        assert journal.clore.await_args.kwargs["statut"] == "interrompue"
        assert journal.clore.await_args.kwargs["reponse"] == "Réponse "

    @pytest.mark.asyncio
    async def test_journal_en_panne_le_chat_repond(self, client, chat_isole):
        with patch("database.AsyncSessionLocal", MagicMock(side_effect=RuntimeError("panne fictive"))):
            r = await _chat(client, "Que dit le manuel fictif ?", ged_mode="toujours")
        assert r.status_code == 200 and r.text == "Réponse fictive." and "X-Rag-Question" not in r.headers


@pytest.fixture
def question_isolee():
    from services.modeles_externes import ModeleResolu
    with patch("services.modeles_externes.resoudre_modele_interactif", AsyncMock(return_value=ModeleResolu("modele-fictif"))):
        yield


class TestModeQuestion:
    @pytest.mark.asyncio
    async def test_question_tracee(self, client, journal, question_isolee):
        rep = {"question": "Où travaillait Jean Exemple ?", "intent": {"intent": "employeur_a_date"},
               "reponse": "Chez Entreprise Fictive.", "confiance": "Haute", "approchant": False,
               "documents": [{"id": DOC, "nom": "paie-fictive.pdf", "extension": "pdf"}]}
        with patch("services.qa_service.repondre", AsyncMock(return_value=rep)):
            r = await client.post("/api/assistant/question", json={"question": "Où travaillait Jean Exemple ?"})
        assert r.status_code == 200 and r.json()["journal_id"] == "22222222-2222-2222-2222-222222222222"
        kw = journal.ouvrir.await_args.kwargs
        assert kw["origine"] == "question" and kw["reponse"] == "Chez Entreprise Fictive." and kw["statut"] == "ok"
        assert kw["sources"] == [{"id": DOC, "nom": "paie-fictive.pdf", "passages": []}]
        assert tuple(kw["prompts_cles"]) == ("qa.comprendre", "qa.extraire")
        assert kw["reglages"]["confiance"] == "Haute"

    @pytest.mark.asyncio
    async def test_echec_trace_puis_502(self, client, journal, question_isolee):
        with patch("services.qa_service.repondre", AsyncMock(side_effect=RuntimeError("Ollama fictif injoignable"))):
            r = await client.post("/api/assistant/question", json={"question": "Où travaillait Jean Exemple ?"})
        assert r.status_code == 502
        kw = journal.ouvrir.await_args.kwargs
        assert kw["statut"] == "erreur" and "injoignable" in kw["reponse"]
