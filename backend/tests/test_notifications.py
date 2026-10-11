"""Cloche de l'en-tête : bilan « idées d'évolution » et routes /api/notifications (11/10/2026) — données fictives."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from models.notification import Notification
from services import idees_evolution as ie

MAINTENANT = datetime(2026, 10, 11, tzinfo=timezone.utc)


class TestPur:
    def test_extraire_consignes(self):
        prompt = f"Consigne fixe…\n\n{ie.MARQUEUR} (à respecter) :\nVérifie les pénalités.\nEt les délais."
        assert ie.extraire_consignes(prompt) == "Vérifie les pénalités.\nEt les délais."
        assert ie.extraire_consignes("rapport sans consigne") is None
        assert ie.extraire_consignes(None) is None

    @pytest.mark.parametrize("valeur, attendu", [("mensuel", 1), ("Trimestriel", 3), ("desactive", None), ("", None)])
    def test_frequence(self, valeur, attendu):
        assert ie.mois_frequence(valeur) == attendu

    def test_est_du(self):
        assert ie.est_du(None, 1, MAINTENANT)
        assert not ie.est_du(MAINTENANT - timedelta(days=10), 1, MAINTENANT)
        assert ie.est_du(MAINTENANT - timedelta(days=31), 1, MAINTENANT)
        assert not ie.est_du(MAINTENANT - timedelta(days=60), 3, MAINTENANT)

    def test_prompt_du_bilan(self):
        p = ie.construire_prompt([(MAINTENANT, "Vérifie les pénalités")], "09/2026")
        assert "[11/10] Vérifie les pénalités" in p and "💡 Idées d'évolution pour Matothèque" in p
        assert "n'invente aucun besoin" in p


class TestBilan:
    @pytest.mark.asyncio
    async def test_rien_a_analyser(self):
        with patch.object(ie, "collecter", AsyncMock(return_value=[])):
            r = await ie.generer_bilan(force=True, model="m", ollama=MagicMock())
        assert r["statut"] == "rien"

    @pytest.mark.asyncio
    async def test_bilan_enregistre(self, test_engine):
        o = MagicMock()
        o.generate = AsyncMock(return_value="# 🔔 Idées d'évolution\n- 💡 Contrôle des pénalités")
        fabrique = async_sessionmaker(test_engine, expire_on_commit=False)
        with patch.object(ie, "collecter", AsyncMock(return_value=[(MAINTENANT, "Vérifie les pénalités")])), \
             patch("database.AsyncSessionLocal", fabrique):
            r = await ie.generer_bilan(force=True, model="m", ollama=o)
        assert r["statut"] == "cree" and r["demandes"] == 1
        async with fabrique() as db:
            n = await db.get(Notification, uuid.UUID(r["notification_id"]))
        assert n.type == ie.TYPE and not n.lu and "pénalités" in n.contenu


class TestRoutes:
    @pytest.mark.asyncio
    async def test_liste_lu_suppression(self, client, db_session):
        a = Notification(type=ie.TYPE, titre="A", contenu="x")
        b = Notification(type=ie.TYPE, titre="B", contenu="y")
        db_session.add_all([a, b])
        await db_session.commit()

        r = (await client.get("/api/notifications")).json()
        assert r["non_lues"] == 2 and {n["titre"] for n in r["notifications"]} == {"A", "B"}

        assert (await client.post(f"/api/notifications/{a.id}/lu")).json()["lu"] is True
        assert (await client.get("/api/notifications")).json()["non_lues"] == 1
        await client.post("/api/notifications/lu-tout")
        assert (await client.get("/api/notifications")).json()["non_lues"] == 0

        assert (await client.delete(f"/api/notifications/{b.id}")).status_code == 200
        assert (await client.delete(f"/api/notifications/{b.id}")).status_code == 404
        assert (await client.post("/api/notifications/pas-un-uuid/lu")).status_code == 400

    @pytest.mark.asyncio
    async def test_generer_met_en_file(self, client):
        r = await client.post("/api/notifications/idees/generer")
        assert r.status_code == 202 and r.json()["job_id"]
