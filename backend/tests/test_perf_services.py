"""
Tests — plan de performance du 29/09/2026 (docs/plan-perf-2026-09.md)
====================================================================
Étape 4 : `/api/system/services` interroge ses six services EN PARALLÈLE.
Enchaînées, les sondes coûtaient ~2,6 s en prod ; en parallèle, la plus lente seulement.
"""

import asyncio
import time
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

LENTEUR = 0.3


async def _lent_true(*_a, **_k) -> bool:
    await asyncio.sleep(LENTEUR)
    return True


async def _lent_ok(*_a, **_k) -> str:
    await asyncio.sleep(LENTEUR)
    return "ok"


@pytest.mark.asyncio
async def test_les_sondes_de_services_partent_en_parallele():
    from main import app

    with patch("routers.system.TikaService.check_health", _lent_true), \
         patch("routers.system._etat_service", _lent_ok), \
         patch("services.clamav_service.check_health", _lent_true), \
         patch("services.bookstack_service.BookStackService.configured", True), \
         patch("services.bookstack_service.BookStackService.check_health", _lent_true), \
         patch("services.transcription_service.is_enabled", lambda: True), \
         patch("services.transcription_service.check_health", _lent_true):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            debut = time.perf_counter()
            r = await c.get("/api/system/services")
            duree = time.perf_counter() - debut

    assert r.status_code == 200
    corps = r.json()
    assert all(corps[s]["ok"] for s in ("tika", "ollama", "n8n", "clamav", "bookstack", "transcription"))
    assert corps["ollama"]["etat"] == "ok"
    # Six sondes de 0,3 s : 1,8 s en série. En parallèle, ~0,3 s (marge pour une CI lente).
    assert duree < 3 * LENTEUR, f"sondes enchaînées ? {duree:.2f} s"


@pytest.mark.asyncio
async def test_chaque_reponse_porte_sa_duree_serveur():
    """Étape 6 : Server-Timing, pour lire la part serveur dans le navigateur (onglet Timing)."""
    import re

    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/version")
    assert re.fullmatch(r"app;dur=\d+\.\d", r.headers["Server-Timing"])


@pytest.mark.asyncio
@pytest.mark.parametrize("jours, restants", [("0", 3), ("", 3), ("abc", 3), ("30", 2)])
async def test_conservation_du_journal_d_audit(db_session, test_engine, monkeypatch, jours, restants):
    """Étape 7 : 0 (défaut) garde TOUT ; N supprime ce qui a plus de N jours, et seulement ça."""
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from models.audit import AuditEvent
    from services import job_worker, runtime_config

    maintenant = datetime.now(timezone.utc)
    for age in (1, 29, 45):
        db_session.add(AuditEvent(acteur="worker", action="enrich", statut="success",
                                  created_at=maintenant - timedelta(days=age)))
    await db_session.commit()

    monkeypatch.setitem(runtime_config._overrides, "audit_retention_jours", jours)
    with patch("services.job_worker.AsyncSessionLocal",
               async_sessionmaker(test_engine, expire_on_commit=False)):
        supprimes = await job_worker._purger_audit_ancien()

    reste = (await db_session.execute(select(func.count()).select_from(AuditEvent))).scalar_one()
    assert reste == restants and supprimes == 3 - restants


@pytest.mark.asyncio
async def test_la_sonde_ollama_se_nomme_aupres_de_la_passerelle(monkeypatch):
    """Sans `X-AI-Project`, l'AIGUILLEUR comptait 518 sondes anonymes par nuit (29/09/2026)."""
    import httpx

    from routers.system import _etat_service
    from services.ollama_service import entetes_projet

    monkeypatch.delenv("AI_PROJECT", raising=False)
    recues: list[httpx.Request] = []

    def repondre(requete: httpx.Request) -> httpx.Response:
        recues.append(requete)
        return httpx.Response(200, json={"models": []})

    vrai_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: vrai_client(transport=httpx.MockTransport(repondre), **kw))
    assert await _etat_service("http://passerelle:21450", "/api/tags", headers=entetes_projet()) == "ok"
    assert recues[0].headers["X-AI-Project"] == "ged-local"
