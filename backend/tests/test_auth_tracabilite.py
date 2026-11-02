"""Authentification, étape 5 : l'auteur de chaque action au journal, un propriétaire par tâche
(plan docs/plan-authentification.md). Personnes, jetons et tâches 100 % FICTIFS."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from models.audit import AuditEvent
from models.job import Job
from services import acces, audit, job_worker
from test_auth_protection import SYNC, auth_on, client, cookie, creer_session  # noqa: F401 — fixtures


@pytest.fixture
def journal(monkeypatch):
    """Événements émis, avec l'auteur tel que `emit` le verrait (explicite, sinon celui du contexte)."""
    liste = []

    async def faux_emit(action, statut, **kw):
        liste.append({**kw, "action": action, "statut": statut, "auteur": kw.get("auteur") or audit.auteur_courant()})

    monkeypatch.setattr(audit, "emit", faux_emit)
    return liste


def _ecritures(journal):
    return [e for e in journal if e["action"] == "ecriture"]


class TestJournalDesEcritures:
    @pytest.mark.asyncio
    async def test_creation_suppression_reglage_export_avec_auteur(self, client, auth_on, db_session, journal):
        jeton = await creer_session(db_session, "admin", identifiant="tclement-fictif")
        h = {**cookie(jeton), **SYNC}
        r = await client.post("/api/prompts", json={"nom": "Essai", "prompt_text": "Résume."}, headers=h)
        assert r.status_code in (200, 201), r.text
        pid = r.json()["id"]
        assert (await client.delete(f"/api/prompts/{pid}", headers=h)).status_code in (200, 204)
        assert (await client.put("/api/system/config", json={"tika_url": "http://tika-fictif:9998"},
                                 headers=h)).status_code == 200
        assert (await client.post("/api/export/docx", json={"content": "# Titre", "title": "Essai"},
                                  headers=h)).status_code == 200

        lignes = {e["message"]: e for e in _ecritures(journal)}
        for attendu in ("POST /api/prompts", "DELETE /api/prompts/{prompt_id}",
                        "PUT /api/system/config", "POST /api/export/docx"):
            assert attendu in lignes, f"{attendu} absent du journal : {list(lignes)}"
            assert lignes[attendu]["auteur"] == "tclement-fictif"
        assert lignes["DELETE /api/prompts/{prompt_id}"]["cible"] == f"/api/prompts/{pid}"

    @pytest.mark.asyncio
    async def test_echec_non_trace(self, client, auth_on, db_session, journal):
        jeton = await creer_session(db_session, "admin")
        r = await client.delete("/api/prompts/00000000-0000-0000-0000-000000000000",
                                headers={**cookie(jeton), **SYNC})
        assert r.status_code == 404
        assert _ecritures(journal) == []

    @pytest.mark.asyncio
    async def test_auth_eteinte_ni_ligne_ni_auteur(self, client, db_session, journal):
        r = await client.post("/api/prompts", json={"nom": "Essai", "prompt_text": "Résume."})
        assert r.status_code in (200, 201)
        assert _ecritures(journal) == []

    def test_quoi_tracer(self):
        assert acces.a_tracer("DELETE", "/api/documents/{document_id}")
        assert acces.a_tracer("PUT", "/api/system/config")
        assert acces.a_tracer("GET", "/api/system/backups/{fichier}")          # export
        assert not acces.a_tracer("GET", "/api/documents")                     # simple lecture
        assert not acces.a_tracer("POST", "/api/assistant/question")           # ne modifie rien
        assert not acces.a_tracer("POST", "/api/auth/utilisateurs/{uid}/bloquer")  # journalisé à part
        assert not acces.a_tracer("POST", None)                                # route inconnue


class TestEmit:
    @pytest.mark.asyncio
    async def test_auteur_du_contexte_ecrit_en_base(self, db_session, monkeypatch):
        monkeypatch.setattr(audit, "AsyncSessionLocal", async_sessionmaker(db_session.bind, expire_on_commit=False))
        audit.definir_auteur("mlb-fictif")
        try:
            await audit.emit("ecriture", "success", cible="/api/x")
            await audit.emit("ecriture", "success", cible="/api/y", auteur="jeton:n8n-fictif")
        finally:
            audit.definir_auteur(None)
        auteurs = {e.cible: e.auteur for e in (await db_session.execute(select(AuditEvent))).scalars()}
        assert auteurs == {"/api/x": "mlb-fictif", "/api/y": "jeton:n8n-fictif"}


class TestProprietaire:
    @pytest.mark.asyncio
    async def test_enqueue_note_le_proprietaire(self, db_session, journal):
        audit.definir_auteur("mlb-fictif")
        try:
            jid = await job_worker.enqueue(db_session, "rapport", {"prompt": "x"})
        finally:
            audit.definir_auteur(None)
        job = await db_session.get(Job, uuid.UUID(jid))
        assert job.parametres["proprietaire"] == "mlb-fictif"

    @pytest.mark.asyncio
    async def test_enqueue_sans_auteur_sans_proprietaire(self, db_session, journal):
        jid = await job_worker.enqueue(db_session, "rapport", {"prompt": "x"})
        job = await db_session.get(Job, uuid.UUID(jid))
        assert "proprietaire" not in job.parametres

    @pytest.mark.asyncio
    async def test_utilisateur_pilote_sa_tache_pas_celle_des_autres(self, client, auth_on, db_session, journal):
        moi = await creer_session(db_session, "utilisateur", identifiant="mlb-fictif", sub="sub-mlb")
        autre = await creer_session(db_session, "utilisateur", identifiant="autre-fictif", sub="sub-autre")
        admin = await creer_session(db_session, "admin", identifiant="admin-fictif", sub="sub-admin")
        a_moi = Job(type="rapport", statut="pending", parametres={"proprietaire": "mlb-fictif"})
        orpheline = Job(type="rapport", statut="pending", parametres={})
        db_session.add_all([a_moi, orpheline])
        await db_session.commit()

        r = await client.get(f"/api/jobs/{a_moi.id}/file", headers=cookie(autre))
        assert r.json()["peut_agir"] is False and r.json()["peut_prioriser"] is False
        r = await client.post(f"/api/jobs/{a_moi.id}/cancel", headers={**cookie(autre), **SYNC})
        assert r.status_code == 403 and "quelqu'un d'autre" in r.json()["detail"]
        r = await client.post(f"/api/jobs/{a_moi.id}/prioriser", headers={**cookie(autre), **SYNC})
        assert r.status_code == 403
        r = await client.post(f"/api/jobs/{orpheline.id}/cancel", headers={**cookie(moi), **SYNC})
        assert r.status_code == 403                                   # sans propriétaire : aux admins

        assert (await client.get(f"/api/jobs/{a_moi.id}/file", headers=cookie(moi))).json()["peut_agir"] is True
        r = await client.post(f"/api/jobs/{a_moi.id}/cancel", headers={**cookie(moi), **SYNC})
        assert r.status_code == 200, r.text
        r = await client.post(f"/api/jobs/{orpheline.id}/cancel", headers={**cookie(admin), **SYNC})
        assert r.status_code == 200, r.text
        annulations = [e for e in journal if e["action"] == "job_annuler"]
        assert [e["auteur"] for e in annulations] == ["mlb-fictif", "admin-fictif"]
