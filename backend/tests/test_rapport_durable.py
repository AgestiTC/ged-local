"""
Rapport libre — tâche durable du worker (audit du 18/09/2026).

Avant : BackgroundTask + dict en mémoire par process ; avec `--workers 2`, le flux SSE servi par
l'autre process ne voyait rien et rendait un rapport vide. Désormais le texte partiel est en base.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from models.job import Job
from services import job_worker as jw
from services import rapport_jobs


def _ctx(**params) -> MagicMock:
    ctx = MagicMock()
    ctx.job_id = str(uuid.uuid4())
    ctx.parametres = {"prompt": "Résume.", "model": "m", "document_ids": [], "sources": [], **params}
    ctx.cancelled = False
    ctx.report = AsyncMock()
    return ctx


def _ollama_stream(*morceaux, erreur: Exception | None = None):
    async def _gen(*_a, **_k):
        for m in morceaux:
            yield m
        if erreur:
            raise erreur
    o = MagicMock()
    o.generate_stream = _gen
    return o


class TestHandler:
    @pytest.mark.asyncio
    async def test_rapport_complet_avec_sources_et_archive(self):
        ctx = _ctx(sources=[{"id": "1", "nom": "facture.pdf"}])
        with patch("services.ollama_service.OllamaService", return_value=_ollama_stream("# Titre\n", "Corps.")), \
             patch.object(rapport_jobs, "_charger_documents", AsyncMock(return_value=[])), \
             patch.object(rapport_jobs, "_persister", AsyncMock()), \
             patch("routers.generate._archiver_rapport", AsyncMock()) as archiver:
            res = await rapport_jobs.handler_rapport(ctx)

        assert res["rapport"].startswith("# Titre\nCorps.")
        assert "facture.pdf" in res["rapport"]          # bloc Sources en fin de rapport
        assert archiver.await_args.args[0] == "Titre"   # titre de l'historique

    @pytest.mark.asyncio
    async def test_texte_partiel_ecrit_en_base_pendant_la_redaction(self):
        with patch("services.ollama_service.OllamaService", return_value=_ollama_stream("a", "b", "c")), \
             patch.object(rapport_jobs, "_charger_documents", AsyncMock(return_value=[])), \
             patch.object(rapport_jobs, "_PERSISTANCE_S", 0.0), \
             patch.object(rapport_jobs, "_persister", AsyncMock()) as persister, \
             patch("routers.generate._archiver_rapport", AsyncMock()):
            await rapport_jobs.handler_rapport(_ctx())
        assert persister.await_args_list[-1].args[1] == "abc"

    @pytest.mark.asyncio
    async def test_erreur_qualifiee_par_son_type(self):
        """`str(ReadTimeout())` est vide : le type doit figurer dans le motif d'échec."""
        import httpx
        with patch("services.ollama_service.OllamaService",
                   return_value=_ollama_stream("début", erreur=httpx.ReadTimeout(""))), \
             patch.object(rapport_jobs, "_charger_documents", AsyncMock(return_value=[])), \
             patch.object(rapport_jobs, "_persister", AsyncMock()):
            with pytest.raises(RuntimeError, match="ReadTimeout"):
                await rapport_jobs.handler_rapport(_ctx())

    @pytest.mark.asyncio
    async def test_ligne_de_l_ancienne_api_refusee(self):
        ctx = _ctx()
        ctx.parametres = {"document_ids": [], "model": "m"}   # pas de prompt : ancien format
        with pytest.raises(ValueError, match="incomplets"):
            await rapport_jobs.handler_rapport(ctx)

    def test_rapport_est_interactif_et_gpu(self):
        assert jw.priorite("rapport") == 0 and jw.classe_tache("rapport") == "gpu"


async def _job(db_session, statut: str, resultat=None, erreur=None) -> str:
    job = Job(type="rapport", statut=statut, parametres={}, resultat=resultat, erreur=erreur)
    db_session.add(job)
    await db_session.commit()
    return str(job.id)


class TestEndpoints:
    @pytest.mark.asyncio
    async def test_lancement_met_en_file(self, client):
        with patch("routers.generate._resoudre_modele", new=AsyncMock(return_value="m")), \
             patch("services.job_worker.enqueue", new=AsyncMock(return_value=str(uuid.uuid4()))) as enqueue:
            r = await client.post("/api/generate/report", json={"document_ids": [], "prompt": "Tuto."})
        assert r.status_code == 200
        assert enqueue.await_args.args[1] == "rapport"
        assert enqueue.await_args.args[2]["prompt"] == "Tuto."

    @pytest.mark.asyncio
    async def test_flux_termine_lu_en_base(self, client, db_session, test_engine):
        job_id = await _job(db_session, "completed", {"rapport": "Rapport final", "nb_chars": 13})
        with patch("database.AsyncSessionLocal", async_sessionmaker(test_engine, expire_on_commit=False)):
            r = await client.get(f"/api/generate/stream/{job_id}")
        assert '"chunk": "Rapport final"' in r.text
        assert '"done": true' in r.text and '"rapport_complet": "Rapport final"' in r.text

    @pytest.mark.asyncio
    async def test_flux_echec_garde_le_contrat_du_frontend(self, client, db_session, test_engine):
        job_id = await _job(db_session, "failed", {"rapport": "début"}, erreur="ReadTimeout: (aucun message)")
        with patch("database.AsyncSessionLocal", async_sessionmaker(test_engine, expire_on_commit=False)):
            r = await client.get(f"/api/generate/stream/{job_id}")
        import json
        fin = json.loads([l for l in r.text.splitlines() if l.startswith("data: ")][-1][6:])
        assert fin["statut"] == "failed"
        assert fin["rapport_complet"].startswith("[Erreur de génération") and "ReadTimeout" in fin["erreur"]

    @pytest.mark.asyncio
    async def test_statut_compte_les_caracteres_en_base(self, client, db_session):
        job_id = await _job(db_session, "running", {"rapport": "x" * 42, "nb_chars": 42})
        r = await client.get(f"/api/generate/status/{job_id}")
        assert r.json()["nb_chars_generes"] == 42
