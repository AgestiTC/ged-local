"""
Tableau comparatif — tâche durable et échecs de l'IA visibles (audit du 18/09/2026).

1. L'état vit en base : suivi, résultat et téléchargement marchent quel que soit le process
   uvicorn (avant : dict en mémoire par process, `--workers 2` → « Job introuvable » une fois sur deux).
2. Une réponse IA inexploitable n'est plus déguisée en « N/A » (même classe que le bug du 16/09).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from models.job import Job
from routers import compare
from services import compare_jobs

COLONNES = ["Prix", "Délai"]


# ─── Extraction IA ───────────────────────────────────────────────────────────

def _ollama(reponse: str) -> MagicMock:
    o = MagicMock()
    o.generate = AsyncMock(return_value=reponse)
    return o


class TestAnalyserGroupe:
    @pytest.mark.asyncio
    async def test_json_exploitable(self):
        valeurs, ok = await compare._analyser_groupe(
            "A", [], COLONNES, None, "m", _ollama('{"Prix": "10 €", "Délai": "N/A"}'))
        assert ok is True
        assert valeurs == {"Prix": "10 €", "Délai": "N/A"}   # « N/A » légitime conservé

    @pytest.mark.asyncio
    @pytest.mark.parametrize("reponse", ["Désolé, je ne peux pas.", "{}", '{"autre": "x"}', "{pas du json}"])
    async def test_reponse_inexploitable_est_un_echec_pas_un_na(self, reponse):
        valeurs, ok = await compare._analyser_groupe("A", [], COLONNES, None, "m", _ollama(reponse))
        assert ok is False
        assert set(valeurs.values()) == {compare.VALEUR_ECHEC_IA}

    @pytest.mark.asyncio
    async def test_appel_ia_en_erreur(self):
        o = MagicMock()
        o.generate = AsyncMock(side_effect=RuntimeError("Ollama injoignable"))
        _, ok = await compare._analyser_groupe("A", [], COLONNES, None, "m", o)
        assert ok is False


    @pytest.mark.asyncio
    async def test_json_impose_et_second_essai(self):
        """02/11/2026 : MLB en « Échec de l'IA » deux passes sur trois — réponse illisible d'un tirage."""
        o = MagicMock()
        o.generate = AsyncMock(side_effect=['{"Prix": "10', '{"Prix": "10 €", "Délai": "3 j"}'])
        valeurs, ok = await compare._analyser_groupe("A", [], COLONNES, None, "m", o)
        assert ok is True and valeurs["Délai"] == "3 j"
        assert o.generate.await_count == 2
        assert all(c.kwargs["format"] == "json" for c in o.generate.await_args_list)

    @pytest.mark.asyncio
    async def test_abandon_apres_deux_essais(self):
        o = _ollama("Désolé.")
        _, ok = await compare._analyser_groupe("A", [], COLONNES, None, "m", o)
        assert ok is False and o.generate.await_count == compare.ESSAIS_ANALYSE

    def test_retour_a_la_ligne_brut_et_valeur_en_liste(self):
        valeurs = compare._lire_valeurs('{"Prix": "10 €\nTTC", "Délai": ["3 j", "5 j"]}', COLONNES)
        assert valeurs == {"Prix": "10 €\nTTC", "Délai": "3 j ; 5 j"}


class TestDeduireColonnes:
    @pytest.mark.asyncio
    async def test_liste_exploitable(self):
        colonnes, par_defaut = await compare._deduire_colonnes([], None, "m", _ollama('["Prix", "Garanties"]'))
        assert colonnes == ["Prix", "Garanties"] and par_defaut is False

    @pytest.mark.asyncio
    async def test_repli_signale(self):
        colonnes, par_defaut = await compare._deduire_colonnes([], None, "m", _ollama("aucune idée"))
        assert colonnes == compare.COLONNES_FALLBACK and par_defaut is True

    @pytest.mark.asyncio
    async def test_consigne_longue_en_tete_et_objet_json(self):
        """02/11/2026 : un prompt structuré de 3 000 car. collé après le format faisait tomber
        la déduction sur les critères génériques — que l'analyse ne savait plus remplir."""
        o = MagicMock()
        o.generate = AsyncMock(side_effect=["Rôle : analyste…", '{"criteres": ["Hospitalisation", "Optique"]}'])
        consigne = "Rôle : analyste.\nFormat attendu : un tableau Markdown."
        colonnes, par_defaut = await compare._deduire_colonnes([], consigne, "m", o)
        assert colonnes == ["Hospitalisation", "Optique"] and par_defaut is False
        prompt = o.generate.await_args.args[0]
        assert prompt.index(consigne) < prompt.index("=== TA TÂCHE ===")   # consigne avant la tâche
        assert prompt.rstrip().endswith('{"criteres": ["Critère 1", "Critère 2", "Critère 3"]}')
        assert all(c.kwargs["format"] == "json" for c in o.generate.await_args_list)


class TestLectureValeurs:
    def test_cles_rapprochees_sans_casse_ni_accents(self):
        assert compare._lire_valeurs('{"points_d_attention": "x", "OBJET": "y"}', ["Objet", "Points d'attention"]) == {
            "Objet": "y", "Points d'attention": "x"}

    def test_reponse_enveloppee_deballee(self):
        assert compare._lire_valeurs('{"Mutuelle Fictive": {"Prix": "10 €"}}', COLONNES) == {"Prix": "10 €", "Délai": "N/A"}

    def test_cles_sans_rapport_restent_un_echec(self):
        assert compare._lire_valeurs('{"Hospitalisation": "150 %"}', COLONNES) is None


# ─── Handler du worker ───────────────────────────────────────────────────────

def _ctx(groupes: list[dict], colonnes=COLONNES) -> MagicMock:
    ctx = MagicMock()
    ctx.job_id = str(uuid.uuid4())
    # Fiches coupées : elles ont leurs tests (test_comparatif_rao.py) et appelleraient l'IA ici.
    ctx.parametres = {"groupes": groupes, "colonnes": colonnes, "model": "m", "synthese": False, "fiches": False,
                      "recommandation": False}
    ctx.cancelled = False
    ctx.report = AsyncMock()
    return ctx


GROUPES = [{"nom": "Société A", "document_ids": []}, {"nom": "Société B", "document_ids": []}]


class TestHandler:
    @pytest.mark.asyncio
    async def test_groupe_en_echec_signale_sans_bloquer(self):
        analyses = AsyncMock(side_effect=[({"Prix": "10"}, True), ({"Prix": compare.VALEUR_ECHEC_IA}, False)])
        with patch.object(compare, "_analyser_groupe", analyses), \
             patch.object(compare, "_charger_documents", AsyncMock(return_value=[])), \
             patch.object(compare_jobs, "_persister", AsyncMock()) as persister:
            etat = await compare_jobs.handler_comparatif(_ctx(GROUPES))

        assert etat["groupes_en_echec"] == ["Société B"]
        assert etat["groupes"][1]["echec_ia"] is True
        fin_b = [e for e in etat["events"] if e.get("groupe") == "Société B" and e["statut"] == "done"][0]
        assert fin_b["echec_ia"] is True
        assert persister.await_count >= 4   # chaque événement est écrit en base, pas gardé en mémoire

    @pytest.mark.asyncio
    async def test_tous_les_groupes_en_echec_fait_echouer_le_job(self):
        echec = AsyncMock(return_value=({"Prix": compare.VALEUR_ECHEC_IA}, False))
        with patch.object(compare, "_analyser_groupe", echec), \
             patch.object(compare, "_charger_documents", AsyncMock(return_value=[])), \
             patch.object(compare_jobs, "_persister", AsyncMock()):
            with pytest.raises(RuntimeError, match="aucun groupe"):
                await compare_jobs.handler_comparatif(_ctx(GROUPES))

    @pytest.mark.asyncio
    async def test_criteres_par_defaut_annonces(self):
        with patch.object(compare, "_deduire_colonnes", AsyncMock(return_value=(["Objet"], True))), \
             patch.object(compare, "_analyser_groupe", AsyncMock(return_value=({"Objet": "x"}, True))), \
             patch.object(compare, "_charger_documents", AsyncMock(return_value=[])), \
             patch.object(compare_jobs, "_persister", AsyncMock()):
            etat = await compare_jobs.handler_comparatif(_ctx(GROUPES, colonnes=[]))
        assert etat["criteres_par_defaut"] is True
        assert any("critères génériques" in (e.get("message") or "") for e in etat["events"])


# ─── Priorité dans la file du worker ─────────────────────────────────────────

class TestPriorite:
    def test_comparatif_passe_devant_les_lots(self):
        from services import job_worker as jw
        assert jw.priorite("comparatif") < jw.priorite("analyze")
        assert jw.priorite("comparatif") < jw.priorite("enrich")
        assert jw.classe_tache("comparatif") == "gpu"   # même budget VRAM que les lots

    @pytest.mark.asyncio
    async def test_claim_sert_l_interactif_avant_un_lot_plus_ancien(self, db_session, test_engine):
        from datetime import datetime, timedelta, timezone

        from services import job_worker as jw
        vieux = datetime.now(tz=timezone.utc) - timedelta(hours=2)
        lot = Job(type="analyze", statut="pending", created_at=vieux)
        interactif = Job(type="comparatif", statut="pending")
        db_session.add_all([lot, interactif])
        await db_session.commit()

        handlers = {"analyze": object(), "comparatif": object()}
        with patch.object(jw, "_HANDLERS", handlers), \
             patch.object(jw, "AsyncSessionLocal", async_sessionmaker(test_engine, expire_on_commit=False)):
            ids = await jw._claim("gpu", 1)
        assert ids == [str(interactif.id)]

    @pytest.mark.asyncio
    async def test_en_pause_creer_passe_les_lots_attendent(self, db_session, test_engine):
        """Décision 2 (02/11/2026) : une pause oubliée retenait deux comparatifs depuis deux jours."""
        from services import job_worker as jw
        lot = Job(type="analyze", statut="pending")
        interactif = Job(type="comparatif", statut="pending")
        db_session.add_all([lot, interactif])
        await db_session.commit()

        handlers = {"analyze": object(), "comparatif": object()}
        with patch.object(jw, "_HANDLERS", handlers), \
             patch.object(jw, "AsyncSessionLocal", async_sessionmaker(test_engine, expire_on_commit=False)):
            ids = await jw._claim("gpu", 5, interactifs_seulement=True)
        assert ids == [str(interactif.id)]   # l'analyse en lot reste en attente

    def test_creer_est_interactif(self):
        from services import job_worker as jw
        assert {"comparatif", "rapport", "musique", "video"} <= jw.INTERACTIF_TYPES
        assert "analyze" not in jw.INTERACTIF_TYPES and "enrich" not in jw.INTERACTIF_TYPES


# ─── Endpoints : tout est relu en base ───────────────────────────────────────

RESULTAT = {"events": [{"statut": "criteres", "colonnes": COLONNES}],
            "colonnes": COLONNES, "synthese": None, "criteres_par_defaut": False,
            "groupes": [{"nom": "A", "valeurs": {"Prix": "10", "Délai": "2 j"}},
                        {"nom": "B", "valeurs": {"Prix": "12", "Délai": "N/A"}}],
            "groupes_en_echec": []}


async def _job(db_session, statut: str, resultat=None, erreur=None) -> str:
    job = Job(type="comparatif", statut=statut, parametres={"template_id": None},
              resultat=resultat, erreur=erreur)
    db_session.add(job)
    await db_session.commit()
    return str(job.id)


class TestEndpoints:
    @pytest.mark.asyncio
    async def test_lancement_met_en_file_une_tache_durable(self, client):
        with patch("services.job_worker.enqueue", new=AsyncMock(return_value=str(uuid.uuid4()))) as enqueue:
            r = await client.post("/api/generate/compare", json={
                "groupes": [{"nom": "A", "document_ids": [str(uuid.uuid4())]},
                            {"nom": "B", "document_ids": [str(uuid.uuid4())]}],
                "colonnes": COLONNES, "model": "m"})
        assert r.status_code == 202
        assert enqueue.await_args.args[1] == "comparatif"
        assert [g["nom"] for g in enqueue.await_args.args[2]["groupes"]] == ["A", "B"]

    @pytest.mark.asyncio
    async def test_resultat_lu_en_base(self, client, db_session):
        job_id = await _job(db_session, "completed", RESULTAT)
        r = await client.get(f"/api/generate/compare/resultat/{job_id}")
        assert r.status_code == 200
        assert r.json()["groupes"][0]["valeurs"]["Prix"] == "10"

    @pytest.mark.asyncio
    async def test_resultat_pas_encore_termine(self, client, db_session):
        job_id = await _job(db_session, "running", {"events": []})
        r = await client.get(f"/api/generate/compare/resultat/{job_id}")
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_telechargement_markdown(self, client, db_session):
        job_id = await _job(db_session, "completed", RESULTAT)
        r = await client.get(f"/api/generate/compare/download/{job_id}", params={"format": "md"})
        assert r.status_code == 200
        assert "Prix" in r.text

    @pytest.mark.asyncio
    async def test_flux_rejoue_les_evenements_puis_termine(self, client, db_session, test_engine):
        job_id = await _job(db_session, "completed", RESULTAT)
        with patch("database.AsyncSessionLocal", async_sessionmaker(test_engine, expire_on_commit=False)):
            r = await client.get(f"/api/generate/compare/stream/{job_id}")
        lignes = [l for l in r.text.splitlines() if l.startswith("data: ")]
        assert '"criteres"' in lignes[0]
        assert '"complete"' in lignes[-1]

    @pytest.mark.asyncio
    async def test_flux_job_en_echec(self, client, db_session, test_engine):
        job_id = await _job(db_session, "failed", {"events": []}, erreur="L'IA n'a rien pu extraire")
        with patch("database.AsyncSessionLocal", async_sessionmaker(test_engine, expire_on_commit=False)):
            r = await client.get(f"/api/generate/compare/stream/{job_id}")
        assert "rien pu extraire" in r.text


class TestMotifAttente:
    """02/11/2026 : une pause IA oubliée retenait le comparatif, le message accusait « d'autres tâches »."""

    def test_message_selon_la_pause(self):
        assert "en pause pour les tâches de fond" in compare.message_attente(True)
        assert "passe devant" in compare.message_attente(True)
        assert "pause" not in compare.message_attente(False)

    @pytest.mark.asyncio
    async def test_flux_dit_la_pause_puis_sa_levee(self, client, db_session, test_engine):
        from models.config import Config
        db_session.add(Config(cle="ia_pause", valeur="1"))
        job_id = await _job(db_session, "pending", {"events": []})
        fabrique = async_sessionmaker(test_engine, expire_on_commit=False)
        tours = []

        async def tour_suivant(_secondes):
            # 1er tour : l'utilisateur lève la pause ; 2e tour : il annule la tâche.
            tours.append(1)
            async with fabrique() as db:
                if len(tours) == 1:
                    (await db.get(Config, "ia_pause")).valeur = "0"
                else:
                    (await db.get(Job, uuid.UUID(job_id))).statut = "cancelled"
                await db.commit()

        with patch("database.AsyncSessionLocal", fabrique), \
                patch("routers.compare.asyncio.sleep", new=tour_suivant):
            r = await client.get(f"/api/generate/compare/stream/{job_id}")
        lignes = [l for l in r.text.splitlines() if l.startswith("data: ")]
        assert "en pause pour les t" in lignes[0]   # JSON échappe les accents
        assert "En attente de d" in lignes[1] and "pause" not in lignes[1]
        assert '"failed"' in lignes[-1] and len(lignes) == 3
