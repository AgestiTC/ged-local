"""
Plan lots IA par modèle, étape 5 — reprise DIFFÉRÉE d'un job en échec passager (`job_worker`).
=========================================================================================
Un job de la chaîne IA (ia_contenu, ia_enrich, ia_embed et leurs alias) dont le handler échoue sur un
incident PASSAGER (délai dépassé, 504, passerelle indisponible…) n'est pas marqué `failed` : il retourne
en attente avec un « pas avant » croissant (2, 5, 15, 30, 60 min) et un compteur d'essais borné. Au-delà :
`failed`, avec un message lisible. Un job reporté ne bloque jamais la file collante par étape.

Jobs 100 % fictifs, handlers simulés, horloge pilotée, aucun appel réseau. SQLite ignore les verrous :
la concurrence est vérifiée à part sur PostgreSQL.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from models.document import Document
from models.file_ia_etat import FileIAEtat
from models.job import Job
from services import file_ia, job_handlers, job_worker as jw
from services.classement_echecs import EchecPassager

T0 = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
REQ = httpx.Request("POST", "http://passerelle.test/api/embed")
DELAI = lambda: httpx.ReadTimeout("délai dépassé (fictif)", request=REQ)  # noqa: E731


def PASSAGER_FICTIF() -> EchecPassager:  # noqa: N802 — l'exception typée que lèvent les points d'appel de l'IA
    return EchecPassager("délai dépassé à la passerelle (HTTP 504)", "les embeddings")


def _504() -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError("HTTP 504", request=REQ,
                                 response=httpx.Response(504, json={"error": "timeout"}, request=REQ))


# ─── 1. Fonctions pures ──────────────────────────────────────────────────────

class TestDelaiDeReport:
    def test_la_progression_demandee(self):
        assert jw.REPORTS_MIN == (2, 5, 15, 30, 60)
        assert [jw.delai_de_report(i) for i in range(1, 6)] == [
            timedelta(minutes=m) for m in (2, 5, 15, 30, 60)]

    def test_croissant(self):
        delais = [jw.delai_de_report(i) for i in range(1, jw.ESSAIS_MAX + 1)]
        assert delais == sorted(delais) and len(set(delais)) == len(delais)

    def test_bornes_essai_nul_ou_negatif_et_au_dela_du_maximum(self):
        assert jw.delai_de_report(0) == timedelta(minutes=2)
        assert jw.delai_de_report(-3) == timedelta(minutes=2)
        assert jw.delai_de_report(99) == timedelta(minutes=60)

    def test_cinq_essais_au_plus(self):
        assert jw.ESSAIS_MAX == 5 == len(jw.REPORTS_MIN)


class TestPerimetre:
    @pytest.mark.parametrize("type_job", ["ia_contenu", "ia_enrich", "ia_embed", "analyze", "enrich", "reprise_texte"])
    def test_les_trois_etapes_et_leurs_alias_sont_reportables(self, type_job):
        assert jw.reprise_differee_possible(type_job, forcee=False)

    @pytest.mark.parametrize("type_job", ["rapport", "comparatif", "comparatif_reparer", "presentation",
                                          "fill_template", "analyse_regroupement", "musique", "video",
                                          "index_wiki", "sync_source", "indexation", "scan_finaliser", "demo"])
    def test_les_autres_types_gardent_leur_comportement(self, type_job):
        assert not jw.reprise_differee_possible(type_job, forcee=False)

    def test_une_priorite_forcee_echoue_tout_de_suite(self):
        assert not jw.reprise_differee_possible("ia_embed", forcee=True)

    def test_aucun_type_reportable_n_est_interactif(self):
        assert not (jw.TYPES_REPRISE_DIFFEREE & jw.INTERACTIF_TYPES)
        assert jw.TYPES_REPRISE_DIFFEREE == {t for ts in jw.TYPES_ETAPE.values() for t in ts}


class TestMessages:
    def test_message_de_reprise(self):
        quand = datetime(2026, 11, 12, 13, 35, tzinfo=timezone.utc)
        texte = jw.message_reprise(quand, 2, "délai dépassé à la passerelle (HTTP 504)")
        assert "Reprise prévue à" in texte and "essai 2/5" in texte and "délai dépassé" in texte
        assert texte.count("IA indisponible") == 1

    def test_heure_locale_europe_paris_ou_repli_utc(self):
        h = jw.heure_locale(datetime(2026, 11, 12, 13, 35, tzinfo=timezone.utc))
        assert h in ("14:35", "13:35 UTC")          # selon que le fuseau est installé dans l'image
        assert jw.heure_locale(datetime(2026, 11, 12, 13, 35)) in ("14:35", "13:35 UTC")   # SQLite : naïf = UTC

    def test_message_d_abandon(self):
        texte = jw.message_abandon("délai dépassé à la passerelle (HTTP 504)")
        assert texte == ("IA indisponible après 5 reprises "
                         "(dernier : délai dépassé à la passerelle (HTTP 504))")


# ─── Outillage base ──────────────────────────────────────────────────────────

TOUS = ["ia_contenu", "ia_enrich", "ia_embed", "analyze", "enrich", "reprise_texte",
        "comparatif", "rapport", "index_wiki", "sync_source"]


class Horloge:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def avance(self, **kw):
        self.t = self.t + timedelta(**kw)


@pytest.fixture
def horloge():
    h = Horloge(T0)
    with patch.object(jw, "_now", h):
        yield h


@pytest_asyncio.fixture
async def fabrique(test_engine):
    f = async_sessionmaker(test_engine, expire_on_commit=False)
    with patch.object(jw, "AsyncSessionLocal", f), patch.object(job_handlers, "AsyncSessionLocal", f), \
         patch.object(jw, "_HANDLERS", {t: object() for t in TOUS}):
        yield f


_n = {"n": 0}


async def ajouter(f, type_job, n=1, **champs) -> list[str]:
    ids = []
    async with f() as db:
        for _ in range(n):
            _n["n"] += 1
            jid = uuid.uuid4()
            champs_job = dict(parametres={}, created_at=T0 - timedelta(hours=5) + timedelta(seconds=_n["n"]))
            champs_job.update(champs)
            db.add(Job(id=jid, type=type_job, statut="pending", **champs_job))
            ids.append(str(jid))
        await db.commit()
    return ids


async def lire(f, jid) -> Job:
    async with f() as db:
        return await db.get(Job, uuid.UUID(jid))


def leve(exc_ou_fabrique):
    async def handler(ctx):
        raise (exc_ou_fabrique() if callable(exc_ou_fabrique) else exc_ou_fabrique)
    return handler


async def executer(f, jid, handler, type_job):
    """Prend le job (`running`) comme le worker, puis l'exécute avec ce handler."""
    async with f() as db:
        j = await db.get(Job, uuid.UUID(jid))
        j.statut = "running"
        await db.commit()
    with patch.dict(jw._HANDLERS, {type_job: handler}):
        await jw._run(jid)


# ─── 2. Le handler échoue sur un incident passager ───────────────────────────

class TestReportApresIncidentPassager:
    @pytest.mark.asyncio
    async def test_le_job_retourne_en_attente_avec_un_pas_avant(self, fabrique, horloge):
        (jid,) = await ajouter(fabrique, "ia_embed")
        await executer(fabrique, jid, leve(PASSAGER_FICTIF), "ia_embed")
        j = await lire(fabrique, jid)
        assert j.statut == "pending"
        assert j.essais == 1
        assert jw._en_utc(j.pas_avant) == T0 + timedelta(minutes=2)
        assert j.started_at is None and j.completed_at is None and j.progress == 0
        assert "Reprise prévue à" in j.progress_message and "essai 1/5" in j.progress_message

    @pytest.mark.parametrize("type_job", ["ia_contenu", "ia_enrich", "ia_embed", "analyze", "enrich", "reprise_texte"])
    @pytest.mark.asyncio
    async def test_les_trois_etapes_et_leurs_alias(self, fabrique, horloge, type_job):
        (jid,) = await ajouter(fabrique, type_job)
        await executer(fabrique, jid, leve(PASSAGER_FICTIF), type_job)
        assert (await lire(fabrique, jid)).statut == "pending"

    @pytest.mark.asyncio
    async def test_le_report_grandit_a_chaque_incident(self, fabrique, horloge):
        (jid,) = await ajouter(fabrique, "ia_embed")
        attendu = []
        for _ in range(jw.ESSAIS_MAX):
            await executer(fabrique, jid, leve(PASSAGER_FICTIF), "ia_embed")
            j = await lire(fabrique, jid)
            attendu.append(jw._en_utc(j.pas_avant) - horloge.t)
            horloge.avance(hours=2)
        assert attendu == [timedelta(minutes=m) for m in (2, 5, 15, 30, 60)]

    @pytest.mark.asyncio
    async def test_audit_et_journal_ne_perdent_pas_le_job(self, fabrique, horloge):
        (jid,) = await ajouter(fabrique, "ia_enrich", parametres={"document_id": str(uuid.uuid4()), "embed": True})
        await executer(fabrique, jid, leve(PASSAGER_FICTIF), "ia_enrich")
        j = await lire(fabrique, jid)
        assert j.parametres["embed"] is True              # les paramètres du job survivent au report


class TestAuDelaDuMaximum:
    @pytest.mark.asyncio
    async def test_le_job_passe_failed_avec_un_message_lisible(self, fabrique, horloge):
        (jid,) = await ajouter(fabrique, "ia_embed", essais=jw.ESSAIS_MAX)
        await executer(fabrique, jid, leve(PASSAGER_FICTIF), "ia_embed")
        j = await lire(fabrique, jid)
        assert j.statut == "failed" and j.completed_at is not None
        assert j.erreur == ("IA indisponible après 5 reprises "
                            "(dernier : délai dépassé à la passerelle (HTTP 504))")
        assert j.progress_message == j.erreur              # lisible aussi dans la liste des tâches
        assert j.pas_avant is None

    @pytest.mark.asyncio
    async def test_de_bout_en_bout_cinq_reports_puis_l_abandon(self, fabrique, horloge):
        (jid,) = await ajouter(fabrique, "ia_enrich")
        statuts = []
        for _ in range(jw.ESSAIS_MAX + 1):
            await executer(fabrique, jid, leve(PASSAGER_FICTIF), "ia_enrich")
            statuts.append((await lire(fabrique, jid)).statut)
            horloge.avance(hours=2)
        assert statuts == ["pending"] * 5 + ["failed"]
        assert (await lire(fabrique, jid)).essais == 5


class TestPasDeReport:
    @pytest.mark.parametrize("exc", [RuntimeError("réponse inexploitable"), ValueError("fichier illisible"),
                                     lambda: httpx.HTTPStatusError("HTTP 400", request=REQ,
                                                                   response=httpx.Response(400, request=REQ))])
    @pytest.mark.asyncio
    async def test_un_echec_definitif_echoue_tout_de_suite(self, fabrique, horloge, exc):
        (jid,) = await ajouter(fabrique, "ia_embed")
        await executer(fabrique, jid, leve(exc), "ia_embed")
        j = await lire(fabrique, jid)
        assert j.statut == "failed" and j.essais == 0 and j.pas_avant is None

    @pytest.mark.asyncio
    async def test_un_modele_absent_echoue_tout_de_suite_avec_son_message(self, fabrique, horloge):
        from services.classement_echecs import ModeleAbsent
        (jid,) = await ajouter(fabrique, "ia_embed")
        await executer(fabrique, jid, leve(ModeleAbsent("qwen3-embedding:8b", "Modèle « qwen3-embedding:8b » absent")),
                       "ia_embed")
        j = await lire(fabrique, jid)
        assert j.statut == "failed" and "qwen3-embedding:8b" in j.erreur

    @pytest.mark.parametrize("type_job", ["comparatif", "rapport", "index_wiki", "sync_source"])
    @pytest.mark.asyncio
    async def test_les_autres_types_gardent_le_comportement_actuel(self, fabrique, horloge, type_job):
        (jid,) = await ajouter(fabrique, type_job)
        await executer(fabrique, jid, leve(PASSAGER_FICTIF), type_job)
        j = await lire(fabrique, jid)
        assert j.statut == "failed" and j.pas_avant is None and j.essais == 0

    @pytest.mark.asyncio
    async def test_une_priorite_forcee_echoue_tout_de_suite(self, fabrique, horloge):
        (jid,) = await ajouter(fabrique, "ia_embed", priorite_forcee=True)
        await executer(fabrique, jid, leve(PASSAGER_FICTIF), "ia_embed")
        assert (await lire(fabrique, jid)).statut == "failed"

    @pytest.mark.asyncio
    async def test_annulation_demandee_pendant_l_incident_annule_au_lieu_de_reporter(self, fabrique, horloge):
        (jid,) = await ajouter(fabrique, "ia_embed", annulation_demandee=True)
        jw._cancel_requested.add(jid)
        await executer(fabrique, jid, leve(PASSAGER_FICTIF), "ia_embed")
        j = await lire(fabrique, jid)
        assert j.statut == "cancelled" and j.pas_avant is None

    @pytest.mark.asyncio
    async def test_un_job_termine_normalement_reste_completed(self, fabrique, horloge):
        async def ok(ctx):
            return {"ok": True}

        (jid,) = await ajouter(fabrique, "ia_embed")
        await executer(fabrique, jid, ok, "ia_embed")
        assert (await lire(fabrique, jid)).statut == "completed"


# ─── 3. Un job reporté ne repart pas avant son délai, et repart après ────────

class TestPasAvant:
    @pytest.mark.asyncio
    async def test_ne_repart_pas_avant_son_delai_et_repart_apres(self, fabrique, horloge):
        (jid,) = await ajouter(fabrique, "ia_embed")
        await executer(fabrique, jid, leve(PASSAGER_FICTIF), "ia_embed")
        assert await jw._claim("gpu", 2) == []                            # tout de suite : rien
        horloge.avance(minutes=1, seconds=59)
        assert await jw._claim("gpu", 2) == []                            # une seconde trop tôt : rien
        horloge.avance(seconds=1)
        assert await jw._claim("gpu", 2) == [jid]                         # pile à l'heure : il repart
        j = await lire(fabrique, jid)
        assert j.statut == "running" and j.pas_avant is None and j.essais == 1   # le compteur, lui, reste

    @pytest.mark.asyncio
    async def test_un_pas_avant_passe_ou_nul_est_eligible(self, fabrique, horloge):
        passe = await ajouter(fabrique, "ia_embed", pas_avant=T0 - timedelta(minutes=1))
        nul = await ajouter(fabrique, "ia_embed")
        assert set(await jw._claim("gpu", 5)) == set(passe + nul)

    @pytest.mark.asyncio
    async def test_le_report_n_est_pas_borne_a_la_classe_gpu_les_io_non_concernes(self, fabrique, horloge):
        (jid,) = await ajouter(fabrique, "sync_source")
        assert await jw._claim("io", 1) == [jid]


# ─── 4. Pas de famine : une étape de jobs reportés ne bloque pas la file collante ─────

async def poser_etat(f, etape, depuis):
    async with f() as db:
        db.add(FileIAEtat(cle="gpu", etape=etape, depuis=depuis, nb_bascules=0))
        await db.commit()


class TestPasDeFamine:
    @pytest.mark.asyncio
    async def test_une_etape_qui_ne_contient_que_des_reportes_laisse_passer_les_autres(self, fabrique, horloge):
        await poser_etat(fabrique, "embed", T0 - timedelta(minutes=1))    # étape courante : embed, délai non écoulé
        await ajouter(fabrique, "ia_embed", 3, pas_avant=T0 + timedelta(minutes=30))   # que des reportés
        enrich = await ajouter(fabrique, "ia_enrich", 2)
        ids = await jw._claim("gpu", 2)
        assert set(ids) == set(enrich)                                    # l'étape embed ne retient pas la file
        async with fabrique() as db:
            e = (await db.execute(select(FileIAEtat))).scalar_one()
        assert e.etape == "enrich" and e.nb_bascules == 1

    @pytest.mark.asyncio
    async def test_seuls_des_reportes_en_attente_aucune_prise_et_etat_intact(self, fabrique, horloge):
        await poser_etat(fabrique, "embed", T0 - timedelta(minutes=1))
        await ajouter(fabrique, "ia_embed", 2, pas_avant=T0 + timedelta(minutes=30))
        await ajouter(fabrique, "ia_enrich", 1, pas_avant=T0 + timedelta(minutes=5))
        assert await jw._claim("gpu", 2) == []
        async with fabrique() as db:
            e = (await db.execute(select(FileIAEtat))).scalar_one()
        assert e.etape == "embed" and e.nb_bascules == 0                  # sortie anticipée : aucune écriture

    @pytest.mark.asyncio
    async def test_pending_par_etape_ne_compte_que_les_eligibles(self, fabrique, horloge):
        await ajouter(fabrique, "ia_embed", 2, pas_avant=T0 + timedelta(minutes=30))
        await ajouter(fabrique, "ia_enrich", 1)
        async with fabrique() as db:
            compte = await jw._pending_par_etape(db, ["ia_embed", "ia_enrich"])
        assert compte == {"enrich": 1}

    @pytest.mark.asyncio
    async def test_places_libres_completees_apres_un_changement_d_etape_sans_les_reportes(self, fabrique, horloge):
        await ajouter(fabrique, "ia_contenu", 1)
        await ajouter(fabrique, "ia_enrich", 1, pas_avant=T0 + timedelta(minutes=30))   # reporté : invisible
        emb = await ajouter(fabrique, "ia_embed", 1)
        ids = await jw._claim("gpu", 3)
        assert len(ids) == 2 and emb[0] in ids                            # contenu puis embed, jamais enrich

    @pytest.mark.asyncio
    async def test_un_reporte_redevient_eligible_et_compte_a_nouveau(self, fabrique, horloge):
        (jid,) = await ajouter(fabrique, "ia_embed", pas_avant=T0 + timedelta(minutes=5))
        assert await jw._claim("gpu", 1) == []
        horloge.avance(minutes=5)
        assert await jw._claim("gpu", 1) == [jid]

    @pytest.mark.asyncio
    async def test_une_tache_forcee_reportee_ne_bloque_pas_les_lots(self, fabrique, horloge):
        await ajouter(fabrique, "comparatif", 1, priorite_forcee=True, pas_avant=T0 + timedelta(minutes=30))
        lot = await ajouter(fabrique, "ia_contenu", 1)
        assert await jw._claim("gpu", 2) == lot

    @pytest.mark.asyncio
    async def test_les_interactifs_sont_inchanges(self, fabrique, horloge):
        await ajouter(fabrique, "ia_contenu", 3)
        c = await ajouter(fabrique, "comparatif", 1)
        assert await jw._claim("gpu", 1) == c


# ─── 5. Démarrage, annulation, nettoyage, garde anti-doublon ─────────────────

class TestCasQuiChangent:
    @pytest.mark.asyncio
    async def test_annuler_un_job_reporte(self, fabrique, horloge):
        (jid,) = await ajouter(fabrique, "ia_embed", pas_avant=T0 + timedelta(minutes=30), essais=2)
        async with fabrique() as db:
            assert await jw.request_cancel(db, jid) == "cancelled"
        j = await lire(fabrique, jid)
        assert j.statut == "cancelled" and j.completed_at is not None
        assert await jw._claim("gpu", 1) == []

    @pytest.mark.asyncio
    async def test_le_nettoyage_des_pending_fantomes_ne_touche_pas_un_reporte(self, fabrique, horloge):
        """Le nettoyage vise les types SANS handler ; un job de la chaîne reporté, même vieux, reste."""
        (jid,) = await ajouter(fabrique, "ia_embed", pas_avant=T0 + timedelta(minutes=30),
                               created_at=datetime.now(timezone.utc) - timedelta(days=2))
        fantome = await ajouter(fabrique, "type_sans_handler", created_at=datetime.now(timezone.utc) - timedelta(days=2))
        await jw._purger_pending_fantomes()
        assert (await lire(fabrique, jid)).statut == "pending"
        assert (await lire(fabrique, fantome[0])).statut == "cancelled"

    @pytest.mark.asyncio
    async def test_la_garde_anti_doublon_voit_un_job_reporte_et_ne_cree_rien(self, fabrique, horloge):
        async with fabrique() as db:
            d = Document(chemin="/fictif/a.pdf", nom="a.pdf", extension="pdf", hash_sha256="h-fictif",
                         statut="extracted", texte_extrait="Texte fictif.")
            db.add(d)
            await db.commit()
            doc_id = str(d.id)
        (jid,) = await ajouter(fabrique, "ia_enrich", pas_avant=T0 + timedelta(minutes=30), essais=2,
                               document_id=uuid.UUID(doc_id), parametres={"document_id": doc_id})
        async with fabrique() as db:
            suivant = await job_handlers.enfiler_suivant(db, "ia_enrich", doc_id,
                                                         {"document_id": doc_id, "embed": True})
            await db.commit()
        assert suivant is None                                            # pas de second job pour le même document
        async with fabrique() as db:
            nb = (await db.execute(select(func.count()).select_from(Job).where(Job.type == "ia_enrich"))).scalar()
        assert nb == 1
        j = await lire(fabrique, jid)
        assert j.parametres["embed"] is True                              # la demande est fusionnée dans le job reporté
        assert j.essais == 2 and jw._en_utc(j.pas_avant) == T0 + timedelta(minutes=30)   # son report est intact

    @pytest.mark.asyncio
    async def test_la_reprise_des_orphelins_ne_touche_que_les_running(self, fabrique, horloge):
        """`start()` ne remet en attente que les jobs `running` (verrou d'avis PostgreSQL : testé par lecture,
        la requête ne filtre que sur le statut). Un job reporté est `pending` : son report survit au redémarrage."""
        import inspect
        source = inspect.getsource(jw.start)
        assert source.count('Job.statut == "running"') == 2 and "pas_avant" not in source

    @pytest.mark.asyncio
    async def test_prendre_un_job_reporte_remet_son_pas_avant_a_zero_mais_garde_le_compteur(self, fabrique, horloge):
        (jid,) = await ajouter(fabrique, "ia_embed", pas_avant=T0 - timedelta(seconds=1), essais=3)
        assert await jw._claim("gpu", 1) == [jid]
        j = await lire(fabrique, jid)
        assert j.pas_avant is None and j.essais == 3


# ─── 6. L'écran « File IA » dit pourquoi le job attend ───────────────────────

class TestFileIAReprisePrevue:
    @pytest.mark.asyncio
    async def test_motif_reprise_prevue_avec_l_heure(self, db_session):
        quand = datetime.now(timezone.utc) + timedelta(minutes=15)
        j = Job(type="ia_embed", statut="pending", essais=2, pas_avant=quand, progress=0)
        db_session.add(j)
        await db_session.commit()
        etat = await file_ia.etat_file(db_session, j)
        assert etat["raison"] == "reprise_prevue"
        assert etat["position"] is None            # M4 : pas de rang dans la file tant que le report court
        assert "Reprise prévue à" in etat["message"] and "essai 2/5" in etat["message"]
        assert jw.heure_locale(quand) in etat["message"]

    @pytest.mark.asyncio
    async def test_un_reporte_n_est_pas_devant_les_autres_et_ne_decale_pas_l_etape(self, db_session):
        quand = datetime.now(timezone.utc) + timedelta(minutes=15)
        vieux = datetime.now(timezone.utc) - timedelta(hours=1)
        reporte = Job(type="ia_embed", statut="pending", pas_avant=quand, created_at=vieux, progress=0)
        autre = Job(type="ia_embed", statut="pending", progress=0)
        db_session.add_all([reporte, autre])
        await db_session.commit()
        etat = await file_ia.etat_file(db_session, autre)
        assert etat["nb_devant"] == 0 and etat["position"] == 1
        assert etat["raison"] != "reprise_prevue"

    @pytest.mark.asyncio
    async def test_un_pas_avant_echu_n_est_plus_un_report(self, db_session):
        j = Job(type="ia_embed", statut="pending", pas_avant=datetime.now(timezone.utc) - timedelta(minutes=1),
                progress=0)
        db_session.add(j)
        await db_session.commit()
        assert (await file_ia.etat_file(db_session, j))["raison"] != "reprise_prevue"

    def test_le_motif_est_documente(self):
        assert "reprise_prevue" in file_ia.MESSAGES


# ─── 7. Avec les VRAIS handlers de la chaîne ─────────────────────────────────

class TestVraisHandlers:
    @pytest.mark.asyncio
    async def test_ia_embed_incident_passager_reporte_le_job_sans_toucher_aux_vecteurs(self, fabrique, horloge):
        from unittest.mock import MagicMock, AsyncMock

        async with fabrique() as db:
            d = Document(chemin="/fictif/b.pdf", nom="b.pdf", extension="pdf", hash_sha256="h-b",
                         statut="enriched", texte_extrait="Texte fictif.")
            db.add(d)
            await db.commit()
            doc_id = str(d.id)
        (jid,) = await ajouter(fabrique, "ia_embed", document_id=uuid.UUID(doc_id),
                               parametres={"document_id": doc_id})
        faux = MagicMock()
        faux.calculer = AsyncMock(side_effect=EchecPassager("IA indisponible pour les embeddings : délai dépassé"))
        faux.remplacer = AsyncMock()
        async with fabrique() as db:
            j = await db.get(Job, uuid.UUID(jid))
            j.statut = "running"
            await db.commit()
        with patch.object(job_handlers, "_service_embeddings", return_value=faux), \
             patch.dict(jw._HANDLERS, {"ia_embed": job_handlers.handler_ia_embed}):
            await jw._run(jid)
        j = await lire(fabrique, jid)
        assert j.statut == "pending" and j.essais == 1 and "délai dépassé" in j.progress_message
        faux.remplacer.assert_not_awaited()                      # rien n'est écrit, les anciens vecteurs restent

    @pytest.mark.asyncio
    async def test_ia_enrich_demande_a_enrich_de_lever_l_incident_passager(self, fabrique, horloge):
        async with fabrique() as db:
            d = Document(chemin="/fictif/c.pdf", nom="c.pdf", extension="pdf", hash_sha256="h-c",
                         statut="extracted", texte_extrait="Texte fictif.")
            db.add(d)
            await db.commit()
            doc_id = str(d.id)
        (jid,) = await ajouter(fabrique, "ia_enrich", document_id=uuid.UUID(doc_id),
                               parametres={"document_id": doc_id, "embed": True})
        vus = {}

        async def enrich_en_incident(self, doc, texte, db, **options):
            vus.update(options)
            raise EchecPassager("IA indisponible pour l'enrichissement : délai dépassé")

        async with fabrique() as db:
            j = await db.get(Job, uuid.UUID(jid))
            j.statut = "running"
            await db.commit()
        with patch("services.extraction.ExtractionService._enrich", new=enrich_en_incident), \
             patch.dict(jw._HANDLERS, {"ia_enrich": job_handlers.handler_ia_enrich}):
            await jw._run(jid)
        assert vus == {"lever_passager": True}
        j = await lire(fabrique, jid)
        assert j.statut == "pending" and j.essais == 1
        async with fabrique() as db:                              # aucune suite mise en file, document inchangé
            assert (await db.execute(select(func.count()).select_from(Job).where(Job.type == "ia_embed"))).scalar() == 0
            assert (await db.get(Document, uuid.UUID(doc_id))).statut == "extracted"


class TestOrdreApresReport:
    @pytest.mark.asyncio
    async def test_un_job_reporte_repart_derriere_ceux_qui_attendaient_deja(self, fabrique, horloge):
        """« Fin de son étape » : malgré sa date de création ancienne, il passe après les jobs déjà en attente."""
        reporte = await ajouter(fabrique, "ia_embed", pas_avant=T0 - timedelta(minutes=1))   # report échu
        autres = await ajouter(fabrique, "ia_embed", 2)                                      # créés après lui, avant son report
        ids = await jw._claim("gpu", 2)
        assert ids == autres and reporte[0] not in ids


# ─── 8. I1 : seule l'exception TYPÉE `EchecPassager` est reportée ────────────

class TestSeulLIaEstReportee:
    @pytest.mark.parametrize("brute", [DELAI, _504, lambda: httpx.ConnectError("refusé", request=REQ)])
    @pytest.mark.asyncio
    async def test_une_erreur_httpx_brute_echoue_tout_de_suite(self, fabrique, horloge, brute):
        """Un délai ou un 500 de Tika, une erreur du NAS… ne sont pas « IA indisponible »."""
        (jid,) = await ajouter(fabrique, "ia_contenu")
        await executer(fabrique, jid, leve(brute), "ia_contenu")
        j = await lire(fabrique, jid)
        assert j.statut == "failed" and j.essais == 0 and j.pas_avant is None
        assert "IA indisponible" not in (j.erreur or "")

    @pytest.mark.parametrize("tika_en_panne", [
        lambda: httpx.HTTPStatusError("HTTP 500", request=REQ, response=httpx.Response(500, request=REQ)),
        lambda: httpx.ReadTimeout("délai Tika (fictif)", request=REQ),
        lambda: httpx.ConnectError("Tika injoignable", request=REQ),
    ])
    @pytest.mark.asyncio
    async def test_ia_contenu_tika_en_panne_echoue_tout_de_suite(self, fabrique, horloge, tmp_path, tika_en_panne):
        """Vraie `extraire_contenu` : l'erreur vient de Tika, avant tout appel IA → aucun report."""
        from unittest.mock import AsyncMock, MagicMock
        from pathlib import Path
        from services import clamav_service
        from services.extraction import ExtractionService

        fichier = tmp_path / "fictif.pdf"
        fichier.write_bytes(b"%PDF fictif")
        async with fabrique() as db:
            d = Document(chemin=str(fichier), nom="fictif.pdf", extension="pdf", hash_sha256="h-t",
                         statut="catalogued", texte_extrait="")
            db.add(d)
            await db.commit()
            doc_id = str(d.id)
        (jid,) = await ajouter(fabrique, "ia_contenu", document_id=uuid.UUID(doc_id),
                               parametres={"document_id": doc_id})
        tika = MagicMock()
        tika.extract_metadata = AsyncMock(side_effect=tika_en_panne())

        async def sain(_):
            return True, "", "clean"

        service = ExtractionService(tika, MagicMock(), None)
        with patch.object(clamav_service, "scan_file", sain), \
             patch("routers.upload._get_extraction_service", return_value=service), \
             patch.object(job_handlers, "_resoudre_fichier", AsyncMock(return_value=(Path(fichier), lambda: None))):
            await executer(fabrique, jid, job_handlers.handler_ia_contenu, "ia_contenu")
        j = await lire(fabrique, jid)
        assert j.statut == "failed" and j.essais == 0 and j.pas_avant is None
        tika.extract_metadata.assert_awaited_once()                  # le fichier n'est pas repassé à Tika

    @pytest.mark.asyncio
    async def test_le_message_ne_dit_pas_ia_indisponible_deux_fois(self, fabrique, horloge):
        (jid,) = await ajouter(fabrique, "ia_embed", essais=jw.ESSAIS_MAX)
        await executer(fabrique, jid, leve(PASSAGER_FICTIF), "ia_embed")
        j = await lire(fabrique, jid)
        assert j.erreur.count("IA indisponible") == 1                # M3
        (jid2,) = await ajouter(fabrique, "ia_embed")
        await executer(fabrique, jid2, leve(PASSAGER_FICTIF), "ia_embed")
        assert (await lire(fabrique, jid2)).progress_message.count("IA indisponible") == 1


# ─── 9. I2 : le report est atomique ──────────────────────────────────────────

class TestReportAtomique:
    @pytest.mark.parametrize("statut", ["pending", "cancelled", "completed", "failed"])
    @pytest.mark.asyncio
    async def test_un_job_qui_n_est_plus_running_n_est_pas_touche(self, fabrique, horloge, statut):
        """Job repris, annulé ou terminé entre l'incident et le report : on n'écrit rien."""
        (jid,) = await ajouter(fabrique, "ia_embed", essais=2)
        async with fabrique() as db:
            j = await db.get(Job, uuid.UUID(jid))
            j.statut = statut
            await db.commit()
        for annule in (False, True):
            assert await jw._gerer_incident_passager(jid, "ia_embed", PASSAGER_FICTIF(), annule) == "ignore"
        j = await lire(fabrique, jid)
        assert j.statut == statut and j.essais == 2 and j.pas_avant is None and j.progress_message is None

    @pytest.mark.asyncio
    async def test_un_job_annule_pendant_l_incident_reste_annule_et_n_est_pas_failed(self, fabrique, horloge):
        (jid,) = await ajouter(fabrique, "ia_embed")

        async def annule_puis_leve(ctx):
            async with fabrique() as db:           # « Annuler » sur un job en attente, ou une reprise concurrente
                j = await db.get(Job, uuid.UUID(jid))
                j.statut = "cancelled"
                await db.commit()
            raise PASSAGER_FICTIF()

        await executer(fabrique, jid, annule_puis_leve, "ia_embed")
        j = await lire(fabrique, jid)
        assert j.statut == "cancelled" and j.essais == 0

    @pytest.mark.asyncio
    async def test_le_compteur_s_incremente_dans_la_requete(self, fabrique, horloge):
        """`essais = coalesce(essais, 0) + 1` dans le SET : un NULL hérité d'avant la migration compte pour 0."""
        (jid,) = await ajouter(fabrique, "ia_embed")
        async with fabrique() as db:
            j = await db.get(Job, uuid.UUID(jid))
            j.statut = "running"
            await db.commit()
        assert await jw._gerer_incident_passager(jid, "ia_embed", PASSAGER_FICTIF(), False) == "reporte"
        j = await lire(fabrique, jid)
        assert j.statut == "pending" and j.essais == 1

    @pytest.mark.asyncio
    async def test_la_branche_abandon_est_gardee_aussi(self, fabrique, horloge):
        (jid,) = await ajouter(fabrique, "ia_embed", essais=jw.ESSAIS_MAX)
        async with fabrique() as db:
            j = await db.get(Job, uuid.UUID(jid))
            j.statut = "cancelled"
            await db.commit()
        assert await jw._gerer_incident_passager(jid, "ia_embed", PASSAGER_FICTIF(), False) == "ignore"
        assert (await lire(fabrique, jid)).statut == "cancelled"
