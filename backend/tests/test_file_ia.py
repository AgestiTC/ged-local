"""File IA lisible et pilotable (plan docs/plan-file-ia-priorites.md, étapes 2-4, 02/11/2026).
Tâches 100 % FICTIVES."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from models.job import Job
from services import file_ia, job_worker, runtime_config
from test_auth_protection import SYNC, auth_on, client, cookie, creer_session  # noqa: F401 — fixtures

T0 = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


def _j(id_, type_, minutes, statut="pending", prioritaire=False, started=None):
    return {"id": id_, "type": type_, "statut": statut, "created_at": T0 + timedelta(minutes=minutes),
            "started_at": started, "progress": 0, "prioritaire": prioritaire}


class TestOrdre:
    def test_forcee_puis_creer_puis_lots(self):
        cible = _j("c", "comparatif", 5)
        attente = [_j("l", "analyze", 0), _j("r", "rapport", 1), _j("f", "comparatif", 9, prioritaire=True), cible]
        assert [j["id"] for j in file_ia.devant(cible, attente, pause=False)] == ["f", "r"]

    def test_lot_derriere_tous_les_creer(self):
        cible = _j("l2", "analyze", 3)
        attente = [_j("l1", "analyze", 0), _j("r", "rapport", 9), cible]
        assert [j["id"] for j in file_ia.devant(cible, attente, pause=False)] == ["r", "l1"]

    def test_en_pause_les_lots_ne_comptent_pas_devant(self):
        cible = _j("l2", "analyze", 3)
        attente = [_j("l1", "analyze", 0), _j("r", "rapport", 9), cible]
        assert [j["id"] for j in file_ia.devant(cible, attente, pause=True)] == ["r"]


class TestRaisonEtEstimation:
    def test_pause_retient_un_lot_pas_un_creer(self):
        assert file_ia.raison(_j("l", "analyze", 0), True, 0, 2, 0) == "pause_ia"
        assert file_ia.raison(_j("c", "comparatif", 0), True, 0, 2, 0) == "demarrage"

    def test_gpu_occupe_et_taches_devant(self):
        assert file_ia.raison(_j("c", "comparatif", 0), False, 2, 2, 0) == "gpu_occupe"
        assert file_ia.raison(_j("c", "comparatif", 0), False, 2, 2, 1) == "taches_devant"

    def test_estimation_simule_les_creneaux(self):
        maintenant = T0 + timedelta(minutes=10)
        en_cours = [_j("a", "comparatif", 0, "running", started=T0 + timedelta(minutes=8)),    # reste 3 min
                    _j("b", "comparatif", 0, "running", started=T0 + timedelta(minutes=6))]    # reste 1 min
        avant = [_j("r", "rapport", 1)]                                                        # 3 min
        durees = {"comparatif": 300.0, "rapport": 180.0}
        # créneaux libres à +60 s et +180 s ; le rapport prend le premier (60+180=240) → nous : 180 s.
        assert file_ia.estimer_debut_s(en_cours, avant, 2, durees, maintenant) == 180.0

    def test_estimation_jamais_negative_et_bornee(self):
        maintenant = T0 + timedelta(hours=5)
        en_cours = [_j("a", "comparatif", 0, "running", started=T0)]   # déjà au-delà de sa durée
        assert file_ia.estimer_debut_s(en_cours, [], 1, {}, maintenant) == 0.0
        longs = [_j(str(i), "video", i) for i in range(500)]
        assert file_ia.estimer_debut_s([], longs, 1, {}, maintenant) == file_ia.HORIZON_MAX_S


async def _ajouter(db, *jobs):
    db.add_all(jobs)
    await db.commit()
    return jobs


class TestRoutes:
    @pytest.mark.asyncio
    async def test_file_sans_parametres_des_autres_taches(self, client, db_session):
        autre = Job(type="comparatif", statut="running", started_at=datetime.now(timezone.utc),
                    parametres={"groupes": [{"nom": "Candidat Secret"}]})
        moi = Job(type="comparatif", statut="pending")
        await _ajouter(db_session, autre, moi)
        r = await client.get(f"/api/jobs/{moi.id}/file")
        assert r.status_code == 200, r.text
        corps = r.json()
        assert "Candidat Secret" not in r.text
        assert corps["en_cours"][0]["libelle"] == "Tableau comparatif" and corps["position"] == 1
        assert corps["peut_prioriser"] is True and corps["estimation"]["minutes"] >= 0

    @pytest.mark.asyncio
    async def test_pause_dite_pour_un_lot(self, client, db_session):
        (lot,) = await _ajouter(db_session, Job(type="analyze", statut="pending"))
        with patch.object(runtime_config, "ia_en_pause", return_value=True):
            corps = (await client.get(f"/api/jobs/{lot.id}/file")).json()
        assert corps["raison"] == "pause_ia" and corps["estimation"] is None

    @pytest.mark.asyncio
    async def test_prioriser_creer_ok_lot_ou_termine_409(self, client, db_session):
        creer, lot, fini = await _ajouter(db_session, Job(type="comparatif", statut="pending"),
                                          Job(type="analyze", statut="pending"),
                                          Job(type="comparatif", statut="completed"))
        assert (await client.post(f"/api/jobs/{creer.id}/prioriser")).status_code == 200
        assert (await client.post(f"/api/jobs/{creer.id}/prioriser")).status_code == 200   # idempotent
        await db_session.refresh(creer)
        assert creer.priorite_forcee is True
        assert (await client.post(f"/api/jobs/{lot.id}/prioriser")).status_code == 409
        assert (await client.post(f"/api/jobs/{fini.id}/prioriser")).status_code == 409

    @pytest.mark.asyncio
    async def test_utilisateur_annule_un_creer_pas_un_lot(self, client, auth_on, db_session):
        jeton = await creer_session(db_session, "utilisateur")
        creer, lot = await _ajouter(db_session, Job(type="comparatif", statut="pending"),
                                    Job(type="analyze", statut="pending"))
        r = await client.post(f"/api/jobs/{creer.id}/cancel", headers={**cookie(jeton), **SYNC})
        assert r.status_code == 200, r.text
        r = await client.post(f"/api/jobs/{lot.id}/cancel", headers={**cookie(jeton), **SYNC})
        assert r.status_code == 403


class TestWorker:
    @pytest.mark.asyncio
    async def test_forcee_part_devant_et_bloque_les_lots(self, db_session, test_engine):
        vieux = datetime.now(timezone.utc) - timedelta(hours=1)
        lot, premier, force = await _ajouter(
            db_session, Job(type="analyze", statut="pending", created_at=vieux),
            Job(type="rapport", statut="pending", created_at=vieux),
            Job(type="comparatif", statut="pending", priorite_forcee=True))
        handlers = {"analyze": object(), "rapport": object(), "comparatif": object()}
        with patch.object(job_worker, "_HANDLERS", handlers), \
             patch.object(job_worker, "AsyncSessionLocal", async_sessionmaker(test_engine, expire_on_commit=False)):
            ids = await job_worker._claim("gpu", 3)
        assert ids[0] == str(force.id) and str(lot.id) not in ids   # aucun lot tant qu'une forcée attend


class TestPrioriteDeclaree:
    def test_entete_selon_le_contexte(self):
        import contextvars
        from services.ollama_service import entetes_projet, priorite_ia

        def avec(valeur):
            priorite_ia(valeur)
            return entetes_projet()["X-AI-Priority"]

        assert contextvars.copy_context().run(entetes_projet)["X-AI-Priority"] == "batch"   # hors contexte
        assert contextvars.copy_context().run(avec, "interactif") == "interactif"
        assert contextvars.copy_context().run(avec, "n'importe quoi") == "batch"
        assert entetes_projet()["X-AI-Project"]
