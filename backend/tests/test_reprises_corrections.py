"""
Étape 5 — corrections après relecture : colonnes garanties (C1), « Relancer l'IA » face aux jobs reportés
(I3), IA immédiate d'un scan sur incident passager (I6), textes du modèle d'embedding de repli (M1),
`file_ia` (M4).

Données fictives, aucun appel réseau.
"""
import inspect
import re
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

import database
from models.document import Document
from models.job import Job
from services.classement_echecs import EchecPassager
from services.extraction import ExtractionService


# ─── C1 : jobs.essais / jobs.pas_avant sont GARANTIS, pas « reportables » ─────────────────

class _Res:
    def __init__(self, valeur=None, lignes=()):
        self._v, self._l = valeur, list(lignes)

    def scalar(self):
        return self._v

    def __iter__(self):
        return iter(self._l)


class _Moteur:
    """Faux moteur PostgreSQL : enregistre le SQL, fait échouer les `n_echecs` premiers ALTER (verrou)."""

    def __init__(self, presentes=(), n_echecs=0):
        self.dialect = SimpleNamespace(name="postgresql")
        self.sql: list[str] = []
        self.presentes, self.n_echecs = set(presentes), n_echecs

    def _ctx(self):
        moteur = self

        class Conn:
            async def execute(self, stmt, params=None):
                texte = str(stmt)
                moteur.sql.append(texte)
                if "information_schema" in texte:
                    return _Res(lignes=[(c,) for c in moteur.presentes])
                if texte.startswith("ALTER") and moteur.n_echecs > 0:
                    moteur.n_echecs -= 1
                    raise RuntimeError("lock timeout (fictif)")
                return _Res()

        class Ctx:
            async def __aenter__(self):
                return Conn()

            async def __aexit__(self, *a):
                return False

        return Ctx()

    def connect(self):
        return self._ctx()

    def begin(self):
        return self._ctx()


class TestColonnesGaranties:
    @pytest.mark.asyncio
    async def test_un_seul_alter_pour_les_deux_colonnes(self, monkeypatch):
        moteur = _Moteur()
        monkeypatch.setattr(database, "engine", moteur)
        await database.garantir_colonnes("jobs", {"essais": "INTEGER NOT NULL DEFAULT 0", "pas_avant": "TIMESTAMPTZ"},
                                         pause=0)
        alters = [s for s in moteur.sql if s.startswith("ALTER")]
        assert len(alters) == 1
        assert "ADD COLUMN IF NOT EXISTS essais INTEGER NOT NULL DEFAULT 0" in alters[0]
        assert "ADD COLUMN IF NOT EXISTS pas_avant TIMESTAMPTZ" in alters[0]

    @pytest.mark.asyncio
    async def test_insiste_quand_le_verrou_n_est_pas_obtenu(self, monkeypatch):
        moteur = _Moteur(n_echecs=3)
        monkeypatch.setattr(database, "engine", moteur)
        await database.garantir_colonnes("jobs", {"essais": "INTEGER NOT NULL DEFAULT 0"}, pause=0)
        assert len([s for s in moteur.sql if s.startswith("ALTER")]) == 4     # 3 échecs puis le succès

    @pytest.mark.asyncio
    async def test_ne_fait_rien_si_les_colonnes_sont_deja_la(self, monkeypatch):
        moteur = _Moteur(presentes={"essais", "pas_avant"})
        monkeypatch.setattr(database, "engine", moteur)
        await database.garantir_colonnes("jobs", {"essais": "INTEGER", "pas_avant": "TIMESTAMPTZ"}, pause=0)
        assert not [s for s in moteur.sql if s.startswith("ALTER")]          # aucun verrou exclusif

    @pytest.mark.asyncio
    async def test_n_ajoute_que_ce_qui_manque(self, monkeypatch):
        moteur = _Moteur(presentes={"essais"})
        monkeypatch.setattr(database, "engine", moteur)
        await database.garantir_colonnes("jobs", {"essais": "INTEGER", "pas_avant": "TIMESTAMPTZ"}, pause=0)
        (alter,) = [s for s in moteur.sql if s.startswith("ALTER")]
        assert "pas_avant" in alter and "essais" not in alter

    @pytest.mark.asyncio
    async def test_abandon_bruyant_apres_les_essais(self, monkeypatch):
        moteur = _Moteur(n_echecs=99)
        monkeypatch.setattr(database, "engine", moteur)
        await database.garantir_colonnes("jobs", {"essais": "INTEGER"}, pause=0, essais=3)
        assert len([s for s in moteur.sql if s.startswith("ALTER")]) == 3

    def test_init_db_garantit_les_deux_colonnes_et_ne_les_laisse_plus_a_migration(self):
        source = inspect.getsource(database.init_db)
        assert re.search(r'_colonnes?_garanties?\(\s*"jobs"', source) or "garantir_colonnes(" in source
        assert "jobs" in source and "pas_avant" in source and "essais" in source
        # plus de « ALTER TABLE jobs ADD COLUMN … essais » dans la liste des migrations reportables
        assert "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS essais" not in source
        assert "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS pas_avant" not in source

    def test_nullabilite_alignee_modele_migration_et_script_sql(self):
        from models.job import Job as JobModele
        assert JobModele.__table__.c.essais.nullable is False
        assert JobModele.__table__.c.pas_avant.nullable is True
        source = inspect.getsource(database.init_db)
        assert "essais" in source and "NOT NULL DEFAULT 0" in source


def _script_init_db() -> str:
    from pathlib import Path
    for parent in Path(__file__).resolve().parents:
        candidat = parent / "scripts" / "init-db.sql"
        if candidat.exists():
            return candidat.read_text(encoding="utf-8")
    return ""        # image de test sans le dossier scripts/ : le test correspondant est ignoré


def test_init_db_sql_declare_les_colonnes_de_report():
    sql = _script_init_db()
    if not sql:
        pytest.skip("scripts/init-db.sql absent de l'image de test")
    bloc = sql[sql.index("CREATE TABLE IF NOT EXISTS jobs"):]
    bloc = bloc[:bloc.index(");")]
    assert re.search(r"essais\s+INTEGER\s+NOT NULL\s+DEFAULT 0", bloc)
    assert re.search(r"pas_avant\s+TIMESTAMPTZ", bloc)


def test_aucune_lecture_des_colonnes_avant_init_db():
    """Rien ne lit `jobs.essais`/`pas_avant` avant que `init_db` (qui les garantit) soit terminé :
    le worker démarre APRÈS `init_db` dans le `lifespan`."""
    from pathlib import Path
    source = (Path(database.__file__).parent / "main.py").read_text(encoding="utf-8")
    assert source.index("await init_db()") < source.index("await job_worker.start()")


# ─── I3 : « Relancer l'IA » ne reste pas bloqué par un job reporté ───────────────────────────

async def _doc(db, nom="a.pdf", texte="Texte fictif.", extension="pdf", statut="extracted") -> Document:
    d = Document(chemin=f"/fictif/{nom}", nom=nom, extension=extension, hash_sha256=f"h-{nom}",
                 statut=statut, texte_extrait=texte)
    db.add(d)
    await db.commit()
    return d


def _futur(minutes=30) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


class TestRelancerLiberLesReportes:
    @pytest.mark.parametrize("route", ["enrich", "analyze"])
    @pytest.mark.asyncio
    async def test_garde_anti_double_clic_remet_pas_avant_a_null_et_le_dit(self, client, db_session, route):
        d = await _doc(db_session)
        db_session.add(Job(type="ia_enrich", statut="pending", document_id=d.id, parametres={},
                           essais=3, pas_avant=_futur()))
        await db_session.commit()
        r = (await client.post(f"/api/documents/{d.id}/{route}")).json()
        assert r["deja"] is True and r["reprise_immediate"] is True          # champ AJOUTÉ, contrat inchangé
        assert {"job_id", "statut", "deja"} <= set(r)
        (j,) = (await db_session.execute(select(Job))).scalars().all()
        await db_session.refresh(j)
        assert j.pas_avant is None and j.essais == 3 and j.statut == "pending"   # le compteur n'est pas remis à 0

    @pytest.mark.asyncio
    async def test_un_job_deja_pret_ne_declenche_pas_le_champ(self, client, db_session):
        d = await _doc(db_session)
        db_session.add(Job(type="ia_enrich", statut="pending", document_id=d.id, parametres={}))
        await db_session.commit()
        r = (await client.post(f"/api/documents/{d.id}/enrich")).json()
        assert r["deja"] is True and not r.get("reprise_immediate")

    @pytest.mark.asyncio
    async def test_un_job_running_n_est_pas_touche(self, client, db_session):
        d = await _doc(db_session)
        db_session.add(Job(type="ia_enrich", statut="running", document_id=d.id, parametres={}))
        await db_session.commit()
        r = (await client.post(f"/api/documents/{d.id}/enrich")).json()
        assert r["deja"] is True and not r.get("reprise_immediate")

    @pytest.mark.asyncio
    async def test_lots_liberent_les_jobs_reportes_et_comptent(self, client, db_session):
        a = await _doc(db_session, "a.pdf")
        db_session.add(Job(type="ia_enrich", statut="pending", document_id=a.id, parametres={}, pas_avant=_futur()))
        s = await _doc(db_session, "scan.jpg", texte="", extension="jpg", statut="catalogued")
        db_session.add(Job(type="ia_contenu", statut="pending", document_id=s.id, parametres={}, pas_avant=_futur()))
        v = await _doc(db_session, "v.pdf", statut="enriched")
        db_session.add(Job(type="ia_embed", statut="pending", document_id=v.id, parametres={}, pas_avant=_futur()))
        await db_session.commit()
        r1 = (await client.post("/api/documents/reenrich-batch")).json()
        r2 = (await client.post("/api/documents/analyze-batch", params={"scope": "media"})).json()
        r3 = (await client.post("/api/documents/embed-batch")).json()
        # « Relancer l'IA » libère tous les jobs IA actifs (enrich + contenu) ; l'analyse en lot, qui passe
        # ensuite, ne trouve plus rien à libérer ; l'indexation sémantique libère son `ia_embed`.
        assert (r1["reportes_liberes"], r2["reportes_liberes"], r3["reportes_liberes"]) == (2, 0, 1)
        for j in (await db_session.execute(select(Job))).scalars().all():
            await db_session.refresh(j)
            assert j.pas_avant is None


# ─── I6 : IA immédiate (finalisation d'un scan) sur incident passager ────────────────────────

@pytest.fixture
def fichier(tmp_path):
    f = tmp_path / "rapport_fictif.pdf"
    f.write_bytes(b"%PDF-1.4 contenu fictif numero deux")
    return f


async def _jobs(db):
    return [(j.type, j.statut, j.parametres) for j in (await db.execute(select(Job))).scalars().all()]


class TestIaImmediateSurIncidentPassager:
    @pytest.mark.asyncio
    async def test_enrichissement_passager_document_extracted_et_ia_enrich_en_file(
            self, db_session, mock_tika, mock_ollama, mock_embedding_service, fichier, monkeypatch):
        async def incident(self, doc, texte, db, **kw):
            raise EchecPassager("délai dépassé", "l'enrichissement")

        monkeypatch.setattr(ExtractionService, "_enrich", incident)
        service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
        doc_id = await service.process_file(fichier, source="upload", db=db_session, differer_ia=False)
        await db_session.commit()
        doc = await db_session.get(Document, uuid.UUID(doc_id))
        assert doc.statut == "extracted" and doc.erreur is None
        (type_job, statut, params), = await _jobs(db_session)
        assert (type_job, statut) == ("ia_enrich", "pending") and params["embed"] is True
        mock_embedding_service.embed_document.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_embeddings_passagers_enrichi_et_ia_embed_en_file(
            self, db_session, mock_tika, mock_ollama, mock_embedding_service, fichier, monkeypatch):
        async def enrich_ok(self, doc, texte, db, **kw):
            return True

        monkeypatch.setattr(ExtractionService, "_enrich", enrich_ok)
        mock_embedding_service.embed_document = AsyncMock(side_effect=EchecPassager("délai dépassé", "les embeddings"))
        service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
        doc_id = await service.process_file(fichier, source="upload", db=db_session, differer_ia=False)
        await db_session.commit()
        doc = await db_session.get(Document, uuid.UUID(doc_id))
        assert doc.statut == "enriched" and doc.erreur is None
        (type_job, statut, _), = await _jobs(db_session)
        assert (type_job, statut) == ("ia_embed", "pending")          # l'enrichissement n'est pas refait

    @pytest.mark.asyncio
    async def test_une_erreur_definitive_reste_une_erreur(
            self, db_session, mock_tika, mock_ollama, mock_embedding_service, fichier):
        mock_embedding_service.embed_document = AsyncMock(side_effect=RuntimeError("boum"))
        service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
        doc_id = await service.process_file(fichier, source="upload", db=db_session, differer_ia=False)
        doc = await db_session.get(Document, uuid.UUID(doc_id))
        assert doc.statut == "error" and "boum" in doc.erreur
        assert await _jobs(db_session) == []

    @pytest.mark.asyncio
    async def test_zip_enrichissement_passager_laisse_extracted_et_met_en_file(
            self, db_session, mock_tika, mock_ollama, mock_embedding_service, tmp_path, monkeypatch):
        async def incident(self, doc, texte, db, **kw):
            raise EchecPassager("délai dépassé", "l'enrichissement")

        monkeypatch.setattr(ExtractionService, "_enrich", incident)
        mock_tika.extract_metadata = AsyncMock(return_value=[
            {"X-TIKA:content": "Contenu fictif du premier fichier.", "resourceName": "un.txt"},
            {"X-TIKA:content": "Contenu fictif du second fichier.", "resourceName": "deux.txt"}])
        z = tmp_path / "lot.zip"
        with zipfile.ZipFile(z, "w") as f:
            f.writestr("un.txt", "x")
        service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
        ids = await service.process_zip(z, source="upload", db=db_session, differer_ia=False)
        await db_session.commit()
        assert len(ids) == 2
        for doc_id in ids:
            doc = await db_session.get(Document, uuid.UUID(doc_id))
            assert doc.statut == "extracted" and doc.erreur is None
        assert sorted(t for t, _, _ in await _jobs(db_session)) == ["ia_enrich", "ia_enrich"]


# ─── M1 : le modèle d'embedding de repli n'est plus utilisé à l'indexation ───────────────────

class TestTextesDuRepli:
    def test_le_catalogue_ne_pretend_plus_que_le_repli_est_utilise(self):
        from services import model_catalog
        source = inspect.getsource(model_catalog)
        assert "il est bien utilisé" not in source
        ligne = next(l for l in source.splitlines() if "nomic-embed" in l or "REPLI des embeddings" in l)
        bloc = source[source.index('("nomic-embed"'):source.index('("embed"')]
        assert "plus utilisé à l'indexation" in bloc or "dormant" in bloc
        assert "ne pas supprimer" in bloc.lower() or "protégé" in bloc.lower()
        assert ligne

    def test_le_commentaire_du_diagnostic_dit_la_verite(self):
        from routers import system
        source = inspect.getsource(system)
        assert "appelé quand le principal échoue" not in source
        assert "dormant" in source.lower()

    def test_la_protection_contre_la_suppression_est_conservee(self):
        from routers import system
        assert 'usages["embeddings_repli"] = settings.ollama_model_embedding_fallback' in inspect.getsource(system)


# ─── M4 : un job reporté n'a pas de rang dans la file ────────────────────────────────────────

@pytest.mark.asyncio
async def test_position_nulle_pour_un_job_reporte(db_session):
    from services import file_ia
    j = Job(type="ia_embed", statut="pending", pas_avant=_futur(15), essais=1, progress=0)
    db_session.add(j)
    await db_session.commit()
    etat = await file_ia.etat_file(db_session, j)
    assert etat["position"] is None and etat["nb_devant"] == 0 and etat["raison"] == "reprise_prevue"
