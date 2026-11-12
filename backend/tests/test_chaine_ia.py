"""
Plan lots IA par modèle, étape 3 — la chaîne ia_contenu → ia_enrich → ia_embed.
===============================================================================
Chaque étape met la suivante en file en fin de succès (`enfiler_suivant`, dans la transaction qui
écrit son résultat), est rejouable sans doublon, et n'appelle qu'UN modèle IA. Les anciens types
(`analyze`, `enrich`, `reprise_texte`) restent acceptés et déroulent la même chaîne.

Documents, textes et vecteurs 100 % fictifs ; Ollama et Tika sont simulés (aucun appel réseau).
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from models.document import Document
from models.embedding import Embedding
from models.job import Job
from models.metadata import MetadonneeIA
from models.version import Version
from services import file_ia, job_handlers, job_worker as jw
from services.extraction import MARQUE_ANCIEN_RESUME, ExtractionService
from services.job_worker import JobContext

T0 = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def fabrique(test_engine):
    f = async_sessionmaker(test_engine, expire_on_commit=False)
    with patch.object(job_handlers, "AsyncSessionLocal", f), patch.object(jw, "AsyncSessionLocal", f):
        yield f


async def creer_doc(f, nom="fictif.pdf", texte="Texte fictif du document.", **champs) -> str:
    async with f() as db:
        d = Document(chemin=f"/fictif/{nom}", nom=nom, extension="pdf", hash_sha256=f"h-{uuid.uuid4().hex[:8]}",
                     statut=champs.pop("statut", "extracted"), texte_extrait=texte, **champs)
        db.add(d)
        await db.commit()
        return str(d.id)


async def jobs(f, type_job=None, statut=None) -> list[Job]:
    async with f() as db:
        q = select(Job).order_by(Job.created_at)
        if type_job:
            q = q.where(Job.type.in_([type_job] if isinstance(type_job, str) else type_job))
        if statut:
            q = q.where(Job.statut == statut)
        return list((await db.execute(q)).scalars().all())


def ctx_pour(type_job, doc_id, **params):
    return JobContext(str(uuid.uuid4()), type_job, {"document_id": doc_id, **params}, uuid.UUID(doc_id))


# ─── enfiler_suivant ─────────────────────────────────────────────────────────

class TestEnfilerSuivant:
    @pytest.mark.asyncio
    async def test_cree_le_job_avec_document_et_correlation(self, fabrique):
        doc = await creer_doc(fabrique)
        async with fabrique() as db:
            jid = await job_handlers.enfiler_suivant(
                db, "ia_enrich", doc, {"document_id": doc, "embed": True, "correlation_id": "cid-1"})
            await db.commit()
        (j,) = await jobs(fabrique, "ia_enrich")
        assert str(j.id) == jid and j.statut == "pending" and str(j.document_id) == doc
        assert j.parametres["embed"] is True and j.parametres["correlation_id"] == "cid-1"

    @pytest.mark.asyncio
    async def test_rejouer_ne_double_pas(self, fabrique):
        doc = await creer_doc(fabrique)
        async with fabrique() as db:
            premier = await job_handlers.enfiler_suivant(db, "ia_embed", doc, {"document_id": doc})
            second = await job_handlers.enfiler_suivant(db, "ia_embed", doc, {"document_id": doc})
            await db.commit()
        assert premier and second is None
        assert len(await jobs(fabrique, "ia_embed")) == 1

    @pytest.mark.asyncio
    async def test_un_job_pending_suffit(self, fabrique):
        doc = await creer_doc(fabrique)
        async with fabrique() as db:
            db.add(Job(type="ia_enrich", statut="pending", document_id=uuid.UUID(doc), parametres={}))
            await db.commit()
        async with fabrique() as db:
            assert await job_handlers.enfiler_suivant(db, "ia_enrich", doc, {"document_id": doc}) is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("type_job", ["ia_enrich", "ia_embed"])
    async def test_un_job_running_n_empeche_pas_un_nouveau_job(self, fabrique, type_job):
        """I1 : une nouvelle version arrivée PENDANT l'étape doit être retraitée, pas perdue."""
        doc = await creer_doc(fabrique)
        async with fabrique() as db:
            db.add(Job(type=type_job, statut="running", document_id=uuid.UUID(doc), parametres={}))
            await db.commit()
        async with fabrique() as db:
            assert await job_handlers.enfiler_suivant(db, type_job, doc, {"document_id": doc, "embed": True})
            await db.commit()
        assert len(await jobs(fabrique, type_job, "pending")) == 1
        assert len(await jobs(fabrique, type_job, "running")) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("statut", ["completed", "failed", "cancelled"])
    async def test_un_job_termine_n_empeche_pas_de_rejouer(self, fabrique, statut):
        doc = await creer_doc(fabrique)
        async with fabrique() as db:
            db.add(Job(type="ia_enrich", statut=statut, document_id=uuid.UUID(doc), parametres={}))
            await db.commit()
        async with fabrique() as db:
            assert await job_handlers.enfiler_suivant(db, "ia_enrich", doc, {"document_id": doc})
            await db.commit()
        assert len(await jobs(fabrique, "ia_enrich", "pending")) == 1

    @pytest.mark.asyncio
    async def test_un_ancien_type_de_la_meme_etape_compte(self, fabrique):
        doc = await creer_doc(fabrique)
        async with fabrique() as db:
            db.add(Job(type="enrich", statut="pending", document_id=uuid.UUID(doc), parametres={}))
            await db.commit()
        async with fabrique() as db:
            assert await job_handlers.enfiler_suivant(db, "ia_enrich", doc, {"document_id": doc}) is None

    @pytest.mark.asyncio
    async def test_document_disparu_pas_de_job(self, fabrique):
        async with fabrique() as db:
            absent = str(uuid.uuid4())
            assert await job_handlers.enfiler_suivant(db, "ia_enrich", absent, {"document_id": absent}) is None
        assert await jobs(fabrique) == []

    @pytest.mark.asyncio
    async def test_un_job_en_attente_recoit_embed_et_version_demandes_apres_coup(self, fabrique):
        doc = await creer_doc(fabrique)
        async with fabrique() as db:
            await job_handlers.enfiler_suivant(db, "ia_enrich", doc, {"document_id": doc, "embed": False})
            await job_handlers.enfiler_suivant(db, "ia_enrich", doc,
                                               {"document_id": doc, "embed": True, "version_id": "v-1"})
            await db.commit()
        (j,) = await jobs(fabrique, "ia_enrich")
        assert j.parametres["embed"] is True and j.parametres["version_id"] == "v-1"


# ─── ia_contenu (et son alias analyze) ───────────────────────────────────────

def faux_service(texte="Texte fictif extrait.", infecte=False):
    async def extraire(doc, chemin, db, **_k):
        if infecte:
            doc.statut, doc.erreur = "error", "Menace détectée par l'antivirus : Eicar"
            return False
        doc.texte_extrait, doc.statut = texte, "extracted"
        return bool(texte.strip())

    service = MagicMock()
    service.extraire_contenu = AsyncMock(side_effect=extraire)
    return service


async def lancer_contenu(type_job, doc_id, service, **params):
    with patch.object(job_handlers, "_resoudre_fichier", new=AsyncMock(return_value=("/tmp/f", lambda: None))), \
         patch("routers.upload._get_extraction_service", return_value=service):
        return await jw._HANDLERS[type_job](ctx_pour(type_job, doc_id, **params))


class TestIaContenu:
    @pytest.mark.asyncio
    async def test_avec_texte_met_ia_enrich_en_file(self, fabrique):
        doc = await creer_doc(fabrique, texte="", statut="catalogued")
        r = await lancer_contenu("ia_contenu", doc, faux_service())
        (suite,) = await jobs(fabrique, "ia_enrich")
        assert r == {"ok": True, "statut": "extracted", "document_id": doc, "sans_texte": False,
                     "job_suivant": str(suite.id)}
        assert suite.parametres["embed"] is True and str(suite.document_id) == doc

    @pytest.mark.asyncio
    async def test_rejouee_ne_cree_pas_de_second_job(self, fabrique):
        doc = await creer_doc(fabrique, texte="")
        await lancer_contenu("ia_contenu", doc, faux_service())
        r = await lancer_contenu("ia_contenu", doc, faux_service())
        assert r["job_suivant"] is None
        assert len(await jobs(fabrique, "ia_enrich")) == 1

    @pytest.mark.asyncio
    async def test_sans_texte_reste_terminee_et_n_enchaine_rien(self, fabrique):
        doc = await creer_doc(fabrique, texte="")
        r = await lancer_contenu("ia_contenu", doc, faux_service(texte=""))
        assert r["sans_texte"] is True and r["job_suivant"] is None and r["ok"] is True
        assert await jobs(fabrique, "ia_enrich") == []

    @pytest.mark.asyncio
    async def test_fichier_infecte_echoue_avec_la_raison_et_commit_le_statut(self, fabrique):
        doc = await creer_doc(fabrique, texte="")
        with pytest.raises(RuntimeError, match="Eicar"):
            await lancer_contenu("ia_contenu", doc, faux_service(infecte=True))
        async with fabrique() as db:
            assert (await db.get(Document, uuid.UUID(doc))).statut == "error"
        assert await jobs(fabrique, "ia_enrich") == []

    @pytest.mark.asyncio
    async def test_document_introuvable(self, fabrique):
        with pytest.raises(ValueError, match="introuvable"):
            await lancer_contenu("ia_contenu", str(uuid.uuid4()), faux_service())

    @pytest.mark.asyncio
    async def test_aucune_ia_dans_cette_etape(self, fabrique):
        """L'étape contenu n'enrichit pas et ne vectorise pas : elle n'a que Tika (et la vision)."""
        doc = await creer_doc(fabrique, texte="")
        service = faux_service()
        await lancer_contenu("ia_contenu", doc, service)
        service._enrich.assert_not_called()
        service.embeddings.embed_document.assert_not_called()

    @pytest.mark.asyncio
    async def test_analyze_est_un_alias_qui_deroule_la_meme_chaine(self, fabrique):
        assert jw._HANDLERS["analyze"] is jw._HANDLERS["ia_contenu"]
        doc = await creer_doc(fabrique, texte="")
        r = await lancer_contenu("analyze", doc, faux_service())
        assert r["job_suivant"] and len(await jobs(fabrique, "ia_enrich")) == 1


# ─── ia_enrich (et son alias enrich) ─────────────────────────────────────────

def patch_enrich(ok=True, meta=None, erreur=None):
    """Remplace `ExtractionService._enrich` : écrit (ou non) la fiche IA, sans aucun appel Ollama."""
    async def faux(self, doc, texte, db):
        if erreur:
            raise erreur
        if ok:
            champs = meta or {"categorie": "rapport", "tags": ["pdf", "ia"], "resume": "Résumé fictif.",
                              "langue": "fr"}
            fiche = (await db.execute(select(MetadonneeIA).where(MetadonneeIA.document_id == doc.id))).scalar_one_or_none()
            if fiche is None:
                db.add(MetadonneeIA(document_id=doc.id, **champs))
            else:
                for cle, valeur in champs.items():
                    setattr(fiche, cle, valeur)
            await db.flush()
        return ok
    return patch("services.extraction.ExtractionService._enrich", new=faux), \
        patch("services.ollama_service.OllamaService", MagicMock())


async def lancer_enrich(type_job, doc_id, ok=True, meta=None, erreur=None, **params):
    p1, p2 = patch_enrich(ok, meta, erreur)
    with p1, p2:
        return await jw._HANDLERS[type_job](ctx_pour(type_job, doc_id, **params))


async def statut_de(f, doc_id):
    async with f() as db:
        return (await db.get(Document, uuid.UUID(doc_id))).statut


class TestIaEnrich:
    @pytest.mark.asyncio
    async def test_succes_statut_enriched_et_embed_demande(self, fabrique):
        doc = await creer_doc(fabrique)
        r = await lancer_enrich("ia_enrich", doc, embed=True, correlation_id="cid-9")
        assert r["ok"] is True and r["statut"] == "enriched" and r["job_suivant"]
        assert await statut_de(fabrique, doc) == "enriched"
        (suite,) = await jobs(fabrique, "ia_embed")
        assert suite.parametres["correlation_id"] == "cid-9"

    @pytest.mark.asyncio
    async def test_embed_faux_mais_aucun_embedding_enchaine_quand_meme(self, fabrique):
        doc = await creer_doc(fabrique)
        await lancer_enrich("ia_enrich", doc, embed=False)
        assert len(await jobs(fabrique, "ia_embed")) == 1

    @pytest.mark.asyncio
    async def test_embed_faux_et_deja_des_embeddings_pas_de_suite(self, fabrique):
        doc = await creer_doc(fabrique)
        async with fabrique() as db:
            db.add(Embedding(document_id=uuid.UUID(doc), chunk_index=0, chunk_text="x", embedding="[0.1]",
                             modele_embedding="m"))
            await db.commit()
        r = await lancer_enrich("ia_enrich", doc, embed=False)
        assert r["job_suivant"] is None and await jobs(fabrique, "ia_embed") == []

    @pytest.mark.asyncio
    async def test_rejouee_pas_de_doublon(self, fabrique):
        doc = await creer_doc(fabrique)
        await lancer_enrich("ia_enrich", doc, embed=True)
        await lancer_enrich("ia_enrich", doc, embed=True)
        assert len(await jobs(fabrique, "ia_embed")) == 1
        async with fabrique() as db:
            n = (await db.execute(select(func.count()).select_from(MetadonneeIA).where(
                MetadonneeIA.document_id == uuid.UUID(doc)))).scalar()
        assert n >= 1   # la fiche est écrite à chaque passage ; l'unicité de la fiche est celle du vrai _enrich

    @pytest.mark.asyncio
    async def test_reponse_inexploitable_commit_statut_et_suite_puis_leve(self, fabrique):
        doc = await creer_doc(fabrique)
        with pytest.raises(RuntimeError, match="catégorie"):
            await lancer_enrich("ia_enrich", doc, ok=False, embed=True)
        assert await statut_de(fabrique, doc) == "extracted"
        assert len(await jobs(fabrique, "ia_embed")) == 1       # le texte est là : on le vectorise quand même

    @pytest.mark.asyncio
    async def test_exception_technique_pas_de_suite(self, fabrique):
        doc = await creer_doc(fabrique)
        with pytest.raises(ConnectionError):
            await lancer_enrich("ia_enrich", doc, erreur=ConnectionError("Ollama injoignable"), embed=True)
        assert await jobs(fabrique, "ia_embed") == []

    @pytest.mark.asyncio
    async def test_sans_texte_leve_et_ne_chaine_rien(self, fabrique):
        doc = await creer_doc(fabrique, texte="  ")
        with pytest.raises(ValueError, match="Aucun texte"):
            await lancer_enrich("ia_enrich", doc, embed=True)
        assert await jobs(fabrique, "ia_embed") == []

    @pytest.mark.asyncio
    async def test_une_copie_n_est_jamais_vectorisee(self, fabrique):
        original = await creer_doc(fabrique, nom="original.pdf")
        copie = await creer_doc(fabrique, nom="copie.pdf", doublon_de=uuid.UUID(original))
        r = await lancer_enrich("ia_enrich", copie, embed=True)
        assert r["job_suivant"] is None and await jobs(fabrique, "ia_embed") == []

    @pytest.mark.asyncio
    async def test_une_copie_qui_a_deja_une_fiche_n_est_jamais_touchee(self, fabrique):
        """I5 : ni déclassement silencieux (« restreint » → « normal »), ni corrections manuelles écrasées."""
        original = await creer_doc(fabrique, nom="original.pdf")
        copie = await creer_doc(fabrique, nom="copie.pdf", doublon_de=uuid.UUID(original), statut="extracted")
        async with fabrique() as db:
            db.add(MetadonneeIA(document_id=uuid.UUID(copie), categorie="corrigée à la main", tags=["dossier-A"],
                                resume="Résumé corrigé.", niveau_confidentialite="restreint"))
            await db.commit()
        await lancer_enrich("ia_enrich", original, embed=False)
        async with fabrique() as db:
            m = (await db.execute(select(MetadonneeIA).where(MetadonneeIA.document_id == uuid.UUID(copie)))).scalar_one()
            assert (m.categorie, m.tags, m.resume, m.niveau_confidentialite) == (
                "corrigée à la main", ["dossier-A"], "Résumé corrigé.", "restreint")
            assert (await db.get(Document, uuid.UUID(copie))).statut == "extracted"

    @pytest.mark.asyncio
    async def test_une_copie_sans_fiche_en_recoit_une(self, fabrique):
        original = await creer_doc(fabrique, nom="original.pdf")
        c1 = await creer_doc(fabrique, nom="copie1.pdf", doublon_de=uuid.UUID(original), statut="extracted")
        c2 = await creer_doc(fabrique, nom="copie2.pdf", doublon_de=uuid.UUID(original), statut="extracted")
        await lancer_enrich("ia_enrich", original, embed=False)
        async with fabrique() as db:
            for c in (c1, c2):
                m = (await db.execute(select(MetadonneeIA).where(MetadonneeIA.document_id == uuid.UUID(c)))).scalar_one()
                assert m.categorie == "rapport" and m.niveau_confidentialite == "normal"
                assert m.tags == ["pdf", "ia"] and m.resume == "Résumé fictif."
                assert (await db.get(Document, uuid.UUID(c))).statut == "enriched"

    @pytest.mark.asyncio
    async def test_enrich_est_un_alias(self, fabrique):
        assert jw._HANDLERS["enrich"] is jw._HANDLERS["ia_enrich"]
        doc = await creer_doc(fabrique)
        r = await lancer_enrich("enrich", doc, embed=True)
        assert r["statut"] == "enriched" and len(await jobs(fabrique, "ia_embed")) == 1

    @pytest.mark.asyncio
    async def test_resume_des_changements_de_version_s_execute_ici(self, fabrique):
        doc = await creer_doc(fabrique)
        async with fabrique() as db:
            v = Version(document_id=uuid.UUID(doc), numero_version=1, hash_sha256="h",
                        diff_resume=MARQUE_ANCIEN_RESUME + "Ancien résumé fictif.")
            db.add(v)
            await db.commit()
            vid = str(v.id)
        diff = AsyncMock()
        with patch("services.extraction.ExtractionService._generate_diff_resume", new=diff):
            await lancer_enrich("ia_enrich", doc, version_id=vid, embed=True)
        diff.assert_awaited_once()
        assert diff.await_args.args[1] == "Ancien résumé fictif."      # marque retirée, texte intact
        async with fabrique() as db:   # le diff n'a rien écrit (simulé) : la marque ne doit pas rester
            assert (await db.get(Version, uuid.UUID(vid))).diff_resume is None

    @pytest.mark.asyncio
    async def test_un_bon_resume_deja_ecrit_n_est_pas_ecrase_au_rejeu(self, fabrique):
        """M1 : rejeu après plantage → le diff déjà produit est conservé."""
        doc = await creer_doc(fabrique)
        async with fabrique() as db:
            v = Version(document_id=uuid.UUID(doc), numero_version=1, hash_sha256="h", diff_resume="Changements déjà résumés.")
            db.add(v)
            await db.commit()
            vid = str(v.id)
        diff = AsyncMock()
        with patch("services.extraction.ExtractionService._generate_diff_resume", new=diff):
            await lancer_enrich("ia_enrich", doc, version_id=vid, embed=False)
        diff.assert_not_awaited()
        async with fabrique() as db:
            assert (await db.get(Version, uuid.UUID(vid))).diff_resume == "Changements déjà résumés."

    @pytest.mark.asyncio
    async def test_pas_de_resume_des_changements_si_l_enrichissement_a_echoue(self, fabrique):
        doc = await creer_doc(fabrique)
        async with fabrique() as db:
            v = Version(document_id=uuid.UUID(doc), numero_version=1, hash_sha256="h",
                        diff_resume=MARQUE_ANCIEN_RESUME + "Ancien.")
            db.add(v)
            await db.commit()
            vid = str(v.id)
        diff = AsyncMock()
        with patch("services.extraction.ExtractionService._generate_diff_resume", new=diff), \
             pytest.raises(RuntimeError):
            await lancer_enrich("ia_enrich", doc, ok=False, version_id=vid, embed=False)
        diff.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_texte_change_pendant_l_enrichissement_pas_de_enriched_sur_l_ancien_texte(self, fabrique):
        """I1 (suite) : la fiche calculée sur l'ancien texte ne vaut pas « enriched » ; la suite est
        laissée à l'`ia_enrich` mis en file par la nouvelle version."""
        doc = await creer_doc(fabrique, texte="Ancien texte fictif.")

        async def faux(self, d, texte, db):
            async with fabrique() as autre:     # la nouvelle version arrive pendant l'appel IA
                d2 = await autre.get(Document, d.id)
                d2.texte_extrait = "Nouveau texte fictif."
                await autre.commit()
            db.add(MetadonneeIA(document_id=d.id, categorie="rapport", tags=[]))
            await db.flush()
            return True

        with patch("services.extraction.ExtractionService._enrich", new=faux), \
             patch("services.ollama_service.OllamaService", MagicMock()):
            r_ = await jw._HANDLERS["ia_enrich"](ctx_pour("ia_enrich", doc, embed=True))
        assert r_["statut"] == "extracted" and r_.get("texte_modifie") is True
        assert await statut_de(fabrique, doc) == "extracted"
        assert await jobs(fabrique, "ia_embed") == []

    @pytest.mark.asyncio
    async def test_version_inconnue_n_empeche_pas_l_enrichissement(self, fabrique):
        doc = await creer_doc(fabrique)
        r = await lancer_enrich("ia_enrich", doc, version_id=str(uuid.uuid4()), embed=False)
        assert r["statut"] == "enriched"


# ─── ia_embed ────────────────────────────────────────────────────────────────

class FauxEmbeddings:
    """Vecteurs fictifs en texte (SQLite ne stocke pas de vecteur) ; compte les calculs."""
    def __init__(self, n=3, echec=None):
        self.n, self.echec, self.calculs = n, echec, 0

    async def calculer(self, texte):
        self.calculs += 1
        if self.echec:
            raise self.echec
        return [(i, f"morceau {i}", f"[{i}.0]", f"[{i}.0]", "modele-fictif") for i in range(self.n)]

    async def remplacer(self, document_id, lignes, db):
        from services.embedding_service import EmbeddingService
        return await EmbeddingService(None).remplacer(document_id, lignes, db)


async def lancer_embed(doc_id, faux, type_job="ia_embed"):
    with patch.object(job_handlers, "_service_embeddings", return_value=faux):
        return await jw._HANDLERS[type_job](ctx_pour(type_job, doc_id))


async def nb_embeddings(f, doc_id):
    async with f() as db:
        return (await db.execute(select(func.count()).select_from(Embedding).where(
            Embedding.document_id == uuid.UUID(doc_id)))).scalar()


class TestIaEmbed:
    @pytest.mark.asyncio
    async def test_calcule_et_stocke_sans_ecrire_de_statut(self, fabrique):
        doc = await creer_doc(fabrique, statut="enriched")
        r = await lancer_embed(doc, FauxEmbeddings(3))
        assert r["nb_chunks"] == 3 and await nb_embeddings(fabrique, doc) == 3
        assert await statut_de(fabrique, doc) == "enriched"

    @pytest.mark.asyncio
    async def test_rejouer_remplace_au_lieu_d_empiler(self, fabrique):
        doc = await creer_doc(fabrique)
        await lancer_embed(doc, FauxEmbeddings(3))
        await lancer_embed(doc, FauxEmbeddings(3))
        await lancer_embed(doc, FauxEmbeddings(2))
        assert await nb_embeddings(fabrique, doc) == 2

    @pytest.mark.asyncio
    async def test_un_calcul_en_echec_garde_les_anciens_vecteurs(self, fabrique):
        doc = await creer_doc(fabrique)
        await lancer_embed(doc, FauxEmbeddings(3))
        with pytest.raises(RuntimeError, match="Ollama KO"):
            await lancer_embed(doc, FauxEmbeddings(echec=RuntimeError("Ollama KO")))
        assert await nb_embeddings(fabrique, doc) == 3

    @pytest.mark.asyncio
    async def test_une_copie_est_ignoree(self, fabrique):
        original = await creer_doc(fabrique)
        copie = await creer_doc(fabrique, nom="copie.pdf", doublon_de=uuid.UUID(original))
        faux = FauxEmbeddings()
        r = await lancer_embed(copie, faux)
        assert r == {"ok": True, "document_id": copie, "ignore": "copie"}
        assert faux.calculs == 0 and await nb_embeddings(fabrique, copie) == 0

    @pytest.mark.asyncio
    async def test_sans_texte_rien_a_faire(self, fabrique):
        doc = await creer_doc(fabrique, texte="")
        faux = FauxEmbeddings()
        r = await lancer_embed(doc, faux)
        assert r.get("ignore") == "sans_texte" and faux.calculs == 0

    @pytest.mark.asyncio
    async def test_document_introuvable(self, fabrique):
        with pytest.raises(ValueError, match="introuvable"):
            await lancer_embed(str(uuid.uuid4()), FauxEmbeddings())

    @pytest.mark.asyncio
    async def test_document_disparu_sous_verrou_rien_inserer_sans_lever(self, fabrique):
        """M2 : le document a été supprimé pendant le calcul → 0, ni insertion ni exception."""
        from services.embedding_service import EmbeddingService
        absent = str(uuid.uuid4())
        async with fabrique() as db:
            assert await EmbeddingService(None).remplacer(absent, [(0, "a", "[1.0]", "[1.0]", "m")], db) == 0
            await db.commit()
        assert await nb_embeddings(fabrique, absent) == 0

    @pytest.mark.asyncio
    async def test_embed_document_supprime_puis_insere_pour_tous_les_appelants(self, fabrique):
        """`embed_document` garde sa signature mais ne duplique plus : un 2ᵉ appel REMPLACE."""
        from services.embedding_service import EmbeddingService
        doc = await creer_doc(fabrique)
        ollama = MagicMock()
        ollama.embed_many = AsyncMock(side_effect=lambda paquet, model=None: [[0.5] * 8 for _ in paquet])
        service = EmbeddingService(ollama)
        lignes = [(0, "a", "[1.0]", "[1.0]", "m"), (1, "b", "[2.0]", "[2.0]", "m")]
        async with fabrique() as db:
            await service.remplacer(doc, lignes, db)
            await service.remplacer(doc, lignes, db)
            await db.commit()
        assert await nb_embeddings(fabrique, doc) == 2


# ─── reprise_texte ───────────────────────────────────────────────────────────

class TestRepriseTexte:
    @pytest.mark.asyncio
    async def test_reprend_le_texte_sans_ia_puis_chaine_l_enrichissement(self, fabrique, mock_tika, mock_ollama,
                                                                           mock_embedding_service):
        doc = await creer_doc(fabrique, texte="", tika_metadata={"tk:content": "Texte dormant fictif."})
        service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
        with patch("routers.upload._get_extraction_service", return_value=service):
            r = await jw._HANDLERS["reprise_texte"](ctx_pour("reprise_texte", doc))
        assert r["ok"] is True and r["job_suivant"]
        mock_ollama.generate.assert_not_awaited()                  # aucune IA dans cette étape
        mock_embedding_service.embed_document.assert_not_awaited()
        mock_tika.extract_metadata.assert_not_awaited()
        (suite,) = await jobs(fabrique, "ia_enrich")
        assert suite.parametres["embed"] is True
        async with fabrique() as db:
            assert (await db.get(Document, uuid.UUID(doc))).texte_extrait == "Texte dormant fictif."

    @pytest.mark.asyncio
    async def test_rien_a_reprendre(self, fabrique, mock_tika, mock_ollama, mock_embedding_service):
        doc = await creer_doc(fabrique, texte="déjà là", tika_metadata={"tk:content": "autre"})
        service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
        with patch("routers.upload._get_extraction_service", return_value=service):
            r = await jw._HANDLERS["reprise_texte"](ctx_pour("reprise_texte", doc))
        assert r["rien_a_reprendre"] is True and await jobs(fabrique, "ia_enrich") == []


# ─── process_file / process_zip : l'IA est différée ──────────────────────────

@pytest.fixture
def fichier(tmp_path):
    f = tmp_path / "rapport_fictif.pdf"
    f.write_bytes(b"%PDF-1.4 contenu fictif numero un")
    return f


class TestProcessFileDiffere:
    @pytest.mark.asyncio
    async def test_aucun_appel_ollama_et_ia_enrich_en_file(self, db_session, mock_tika, mock_ollama,
                                                            mock_embedding_service, fichier):
        service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
        doc_id = await service.process_file(fichier, source="upload", db=db_session)
        await db_session.commit()

        mock_ollama.generate.assert_not_awaited()
        mock_embedding_service.embed_document.assert_not_awaited()
        doc = await db_session.get(Document, uuid.UUID(doc_id))
        assert doc.statut == "extracted" and doc.texte_extrait
        (j,) = (await db_session.execute(select(Job))).scalars().all()
        assert j.type == "ia_enrich" and j.statut == "pending" and str(j.document_id) == doc_id
        assert j.parametres["embed"] is True and j.parametres["document_id"] == doc_id
        assert "version_id" not in j.parametres

    @pytest.mark.asyncio
    async def test_differer_ia_faux_garde_le_comportement_immediat(self, db_session, mock_tika, mock_ollama,
                                                                    mock_embedding_service, fichier):
        service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
        doc_id = await service.process_file(fichier, source="upload", db=db_session, differer_ia=False)
        doc = await db_session.get(Document, uuid.UUID(doc_id))
        assert doc.statut == "enriched"
        mock_embedding_service.embed_document.assert_awaited_once()
        assert (await db_session.execute(select(Job))).scalars().all() == []

    @pytest.mark.asyncio
    async def test_texte_vide_rien_a_enchainer(self, db_session, mock_tika, mock_ollama, mock_embedding_service,
                                               fichier):
        mock_tika.extract_metadata = AsyncMock(side_effect=lambda *_a, **_k: [{"Content-Type": "image/jpeg"}])
        service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
        await service.process_file(fichier, source="upload", db=db_session)
        assert (await db_session.execute(select(Job))).scalars().all() == []

    @pytest.mark.asyncio
    async def test_fichier_inchange_ou_copie_pas_de_nouveau_job(self, db_session, mock_tika, mock_ollama,
                                                                mock_embedding_service, fichier, tmp_path):
        service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
        await service.process_file(fichier, source="watch", db=db_session)
        await service.process_file(fichier, source="watch", db=db_session)            # inchangé
        copie = tmp_path / "copie.pdf"
        copie.write_bytes(fichier.read_bytes())
        await service.process_file(copie, source="watch", db=db_session)               # copie
        assert len((await db_session.execute(select(Job))).scalars().all()) == 1

    @pytest.mark.asyncio
    async def test_nouvelle_version_garde_l_ancien_resume_dans_la_version(self, db_session, mock_tika, mock_ollama,
                                                                           mock_embedding_service, fichier):
        service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
        doc_id = await service.process_file(fichier, source="upload", db=db_session)
        db_session.add(MetadonneeIA(document_id=uuid.UUID(doc_id), categorie="rapport", tags=[],
                                    resume="Ancien résumé fictif."))
        for j in (await db_session.execute(select(Job))).scalars().all():
            j.statut = "completed"
        await db_session.commit()

        fichier.write_bytes(b"%PDF-1.4 contenu fictif numero deux")
        assert await service.process_file(fichier, source="upload", db=db_session) == doc_id
        await db_session.commit()

        (v,) = (await db_session.execute(select(Version))).scalars().all()
        assert v.diff_resume == MARQUE_ANCIEN_RESUME + "Ancien résumé fictif."
        suite = (await db_session.execute(select(Job).where(Job.statut == "pending"))).scalars().all()
        assert len(suite) == 1 and suite[0].type == "ia_enrich"
        assert suite[0].parametres["version_id"] == str(v.id)
        assert (await db_session.execute(select(MetadonneeIA))).scalars().all() == []   # fiche obsolète retirée
        mock_ollama.generate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_une_erreur_de_mise_en_file_n_invalide_pas_la_transaction_de_l_appelant(
            self, db_session, mock_tika, mock_ollama, mock_embedding_service, fichier, tmp_path):
        """I4 : `enfiler_suivant` dans un savepoint. Sa panne laisse le document `extracted` (rattrapable
        par « Relancer l'IA »), pas `error`, et le lot continue avec la même session."""
        service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
        with patch("services.job_handlers.enfiler_suivant", new=AsyncMock(side_effect=RuntimeError("file KO"))):
            doc_id = await service.process_file(fichier, source="upload", db=db_session)
        doc = await db_session.get(Document, uuid.UUID(doc_id))
        assert doc.statut == "extracted" and doc.erreur is None

        autre = tmp_path / "suivant.pdf"
        autre.write_bytes(b"%PDF-1.4 un autre contenu fictif")
        id2 = await service.process_file(autre, source="upload", db=db_session)      # même session : toujours saine
        await db_session.commit()
        assert id2 != doc_id and len((await db_session.execute(select(Job))).scalars().all()) == 1

    def test_le_verrou_du_document_est_for_no_key_update(self):
        """I4 : FOR NO KEY UPDATE (pas FOR UPDATE) — ne bloque pas les clés étrangères qui visent le document."""
        from sqlalchemy.dialects import postgresql
        sql = str(job_handlers._verrou_document(uuid.uuid4()).compile(dialect=postgresql.dialect()))
        assert "FOR NO KEY UPDATE" in sql and "FOR UPDATE" not in sql.replace("FOR NO KEY UPDATE", "")

    @pytest.mark.asyncio
    async def test_zip_sous_documents_differes(self, db_session, mock_tika, mock_ollama, mock_embedding_service,
                                               tmp_path):
        mock_tika.extract_metadata = AsyncMock(side_effect=lambda *_a, **_k: [
            {"X-TIKA:content": "Premier texte fictif.", "resourceName": "a.txt", "Content-Type": "text/plain"},
            {"X-TIKA:content": "Second texte fictif.", "resourceName": "b.txt", "Content-Type": "text/plain"},
            {"Content-Type": "image/png", "resourceName": "c.png"}])
        z = tmp_path / "lot.zip"
        z.write_bytes(b"PK fictif")
        service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
        ids = await service.process_zip(z, source="upload", db=db_session)
        await db_session.commit()
        assert len(ids) == 3
        mock_ollama.generate.assert_not_awaited()
        mock_embedding_service.embed_document.assert_not_awaited()
        types = [(j.type, j.parametres["embed"]) for j in (await db_session.execute(select(Job))).scalars().all()]
        assert types == [("ia_enrich", True)] * 2        # le sous-document sans texte n'enchaîne rien


class TestChaineDeBoutEnBout:
    @pytest.mark.asyncio
    async def test_process_file_puis_les_jobs_d_etape_menent_a_enriched_avec_embeddings(
            self, fabrique, db_session, mock_tika, mock_ollama, mock_embedding_service, fichier):
        """Bout en bout, vrais handlers + vrai `_enrich` (Ollama simulé) : extracted → enriched,
        fiche IA écrite, vecteurs remplacés, chaque job exécuté une seule fois par étape."""
        service = ExtractionService(mock_tika, mock_ollama, mock_embedding_service)
        doc_id = await service.process_file(fichier, source="upload", db=db_session)
        await db_session.commit()

        faux = FauxEmbeddings(3)
        with patch("services.ollama_service.OllamaService", return_value=mock_ollama),              patch("services.runtime_config.model_candidates", new=AsyncMock(return_value=["modele-fictif"])),              patch.object(job_handlers, "_service_embeddings", return_value=faux):
            for _ in range(5):
                ids = await jw._claim("gpu", 5)
                if not ids:
                    break
                for jid in ids:
                    await jw._run(jid)

        statuts = [(j.type, j.statut) for j in await jobs(fabrique)]
        assert statuts == [("ia_enrich", "completed"), ("ia_embed", "completed")]
        async with fabrique() as db:
            doc = await db.get(Document, uuid.UUID(doc_id))
            assert doc.statut == "enriched"
            meta = (await db.execute(select(MetadonneeIA).where(MetadonneeIA.document_id == doc.id))).scalar_one()
            assert meta.categorie == "rapport"
        assert await nb_embeddings(fabrique, doc_id) == 3 and faux.calculs == 1
        assert mock_ollama.generate.await_count == 1            # un seul appel LLM pour tout le document


# ─── Routes : nouveaux types, valeurs de `route` conservées ──────────────────

async def doc_api(db_session, nom, texte="Texte fictif.", extension="pdf", statut="extracted"):
    d = Document(chemin=f"/fictif/{nom}", nom=nom, extension=extension, hash_sha256=f"h-{nom}",
                 statut=statut, texte_extrait=texte)
    db_session.add(d)
    await db_session.commit()
    return d


class TestRoutes:
    @pytest.mark.asyncio
    async def test_relance_avec_texte_ia_enrich_et_route_enrich(self, client, db_session):
        d = await doc_api(db_session, "a.pdf")
        r = (await client.post(f"/api/documents/{d.id}/enrich")).json()
        assert r["route"] == "enrich" and r["deja"] is False
        (j,) = (await db_session.execute(select(Job))).scalars().all()
        assert j.type == "ia_enrich" and j.parametres["embed"] is False and j.document_id == d.id

    @pytest.mark.asyncio
    async def test_relance_sans_texte_ia_contenu_et_route_analyze(self, client, db_session):
        d = await doc_api(db_session, "scan.pdf", texte="")
        r = (await client.post(f"/api/documents/{d.id}/enrich")).json()
        assert r["route"] == "analyze"
        (j,) = (await db_session.execute(select(Job))).scalars().all()
        assert j.type == "ia_contenu"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("existant", ["ia_enrich", "ia_contenu", "enrich", "analyze"])
    async def test_garde_anti_double_clic_couvre_anciens_et_nouveaux_types(self, client, db_session, existant):
        d = await doc_api(db_session, "a.pdf")
        db_session.add(Job(type=existant, statut="pending", document_id=d.id, parametres={}))
        await db_session.commit()
        assert (await client.post(f"/api/documents/{d.id}/enrich")).json()["deja"] is True
        assert (await client.post(f"/api/documents/{d.id}/analyze")).json()["deja"] is True
        assert len((await db_session.execute(select(Job))).scalars().all()) == 1

    @pytest.mark.asyncio
    async def test_lot_de_reenrichissement_ia_enrich_sans_embed(self, client, db_session):
        a = await doc_api(db_session, "a.pdf")
        b = await doc_api(db_session, "b.pdf")
        db_session.add(Job(type="ia_enrich", statut="pending", document_id=b.id, parametres={}))
        await db_session.commit()
        r = (await client.post("/api/documents/reenrich-batch")).json()
        assert r["enqueued"] == 1
        nouveaux = [j for j in (await db_session.execute(select(Job))).scalars().all() if j.document_id == a.id]
        assert [(j.type, j.parametres["embed"]) for j in nouveaux] == [("ia_enrich", False)]

    @pytest.mark.asyncio
    async def test_echecs_repetes_comptent_les_deux_noms_d_etape(self, client, db_session):
        d = await doc_api(db_session, "chronique.pdf")
        for t in ("enrich", "ia_enrich", "ia_enrich"):
            db_session.add(Job(type=t, statut="failed", document_id=d.id, parametres={}))
        await db_session.commit()
        assert (await client.post("/api/documents/reenrich-batch")).json()["enqueued"] == 0

    @pytest.mark.asyncio
    async def test_analyse_unitaire_et_en_lot_ia_contenu(self, client, db_session):
        d = await doc_api(db_session, "photo.jpg", texte="", extension="jpg", statut="catalogued")
        e = await doc_api(db_session, "photo2.jpg", texte="", extension="jpg", statut="catalogued")
        assert (await client.post(f"/api/documents/{d.id}/analyze")).json()["deja"] is False
        r = (await client.post("/api/documents/analyze-batch", params={"scope": "media"})).json()
        assert r["enqueued"] == 1                                  # d est déjà en file
        types = sorted((j.type, str(j.document_id)) for j in (await db_session.execute(select(Job))).scalars().all())
        assert types == sorted([("ia_contenu", str(d.id)), ("ia_contenu", str(e.id))])

    @pytest.mark.asyncio
    async def test_originaux_sans_vecteurs_comptes_puis_mis_en_file(self, client, db_session):
        """I2 : un `ia_embed` en échec laisse un document `enriched` sans vecteurs ; ce lot le rattrape."""
        sans = await doc_api(db_session, "sans-vecteurs.pdf", statut="enriched")
        avec = await doc_api(db_session, "avec-vecteurs.pdf", statut="enriched")
        actif = await doc_api(db_session, "deja-en-file.pdf", statut="enriched")
        vide = await doc_api(db_session, "vide.pdf", texte="")
        copie = await doc_api(db_session, "copie.pdf", statut="enriched")
        copie.doublon_de = sans.id
        db_session.add(Embedding(document_id=avec.id, chunk_index=0, chunk_text="x", embedding="[0.1]",
                                 modele_embedding="m"))
        db_session.add(Job(type="ia_embed", statut="pending", document_id=actif.id, parametres={}))
        await db_session.commit()

        c = (await client.get("/api/documents/maintenance/counts")).json()
        assert c["sans_embeddings"] == 1
        r_ = (await client.post("/api/documents/embed-batch")).json()
        assert r_["enqueued"] == 1
        nouveaux = [j for j in (await db_session.execute(select(Job))).scalars().all() if j.document_id == sans.id]
        assert [(j.type, j.statut) for j in nouveaux] == [("ia_embed", "pending")]
        assert (await client.post("/api/documents/embed-batch")).json()["enqueued"] == 0    # un 2ᵉ clic ne double rien
        assert (await client.get("/api/documents/maintenance/counts")).json()["sans_embeddings"] == 0
        assert vide.id and copie.id

    @pytest.mark.asyncio
    async def test_reprise_de_texte_garde_son_type(self, client, db_session):
        db_session.add(Document(chemin="/fictif/d.pdf", nom="d.pdf", extension="pdf", hash_sha256="hd",
                                statut="extracted", texte_extrait="", tika_metadata={"tk:content": "Texte"}))
        await db_session.commit()
        assert (await client.post("/api/documents/maintenance/reprise-texte")).json()["enqueued"] == 1
        assert [j.type for j in (await db_session.execute(select(Job))).scalars().all()] == ["reprise_texte"]

    @pytest.mark.asyncio
    async def test_compteurs_de_file_regroupent_anciens_et_nouveaux_types(self, client, db_session):
        d = await doc_api(db_session, "a.pdf")
        for t in ("enrich", "ia_enrich", "ia_embed", "analyze", "ia_contenu"):
            db_session.add(Job(type=t, statut="pending", document_id=d.id, parametres={}))
        await db_session.commit()
        c = (await client.get("/api/documents/maintenance/counts")).json()
        assert c["jobs_enrich"] == 2 and c["jobs_analyze"] == 2

    @pytest.mark.asyncio
    async def test_la_marque_provisoire_n_apparait_pas_dans_l_historique_des_versions(self, client, db_session):
        d = await doc_api(db_session, "v.pdf")
        db_session.add_all([
            Version(document_id=d.id, numero_version=1, hash_sha256="a", diff_resume=MARQUE_ANCIEN_RESUME + "Secret provisoire"),
            Version(document_id=d.id, numero_version=2, hash_sha256="b", diff_resume="Changements réels.")])
        await db_session.commit()
        v = (await client.get(f"/api/documents/{d.id}/versions")).json()["versions"]
        assert sorted((x["numero_version"], x["diff_resume"]) for x in v) == [(1, None), (2, "Changements réels.")]


# ─── File IA lisible ─────────────────────────────────────────────────────────

def _j(id_, type_, minutes, statut="pending"):
    return {"id": id_, "type": type_, "statut": statut, "created_at": T0 + timedelta(minutes=minutes),
            "started_at": None, "progress": 0, "prioritaire": False}


class TestFileIaEtapes:
    def test_libelles(self):
        assert file_ia.libelle("ia_contenu") == "Lecture du contenu"
        assert file_ia.libelle("ia_enrich") == "Enrichissement IA"
        assert file_ia.libelle("ia_embed") == "Indexation sémantique"

    def test_l_ordre_suit_l_etape_courante(self):
        # L'embedding est le plus ancien, mais l'étape courante est « contenu » : il passe en dernier.
        cible = _j("e", "ia_embed", 0)
        attente = [cible, _j("c1", "ia_contenu", 5), _j("c2", "ia_contenu", 6), _j("w", "index_wiki", 9)]
        devant = file_ia.devant(cible, attente, pause=False, etape="contenu")
        assert [j["id"] for j in devant] == ["c1", "c2", "w"]

    def test_sans_etape_l_ordre_est_la_fifo_d_avant(self):
        cible = _j("e", "ia_embed", 5)
        assert [j["id"] for j in file_ia.devant(cible, [_j("c", "ia_contenu", 0), cible], pause=False)] == ["c"]

    def test_un_job_de_l_etape_courante_ne_voit_pas_les_autres_devant_lui(self):
        cible = _j("c9", "ia_contenu", 9)
        attente = [_j("e", "ia_embed", 0), cible]
        assert file_ia.devant(cible, attente, pause=False, etape="contenu") == []

    def test_raison_autre_etape(self):
        assert file_ia.raison(_j("e", "ia_embed", 0), False, 0, 2, 0, autre_etape=True) == "autre_etape"
        # La pause garde la priorité sur le motif d'étape ; un « Créer » n'a pas d'étape.
        assert file_ia.raison(_j("e", "ia_embed", 0), True, 0, 2, 0, autre_etape=True) == "pause_ia"
        assert file_ia.raison(_j("c", "comparatif", 0), False, 0, 2, 0) == "demarrage"

    def test_message_autre_etape(self):
        msg = file_ia.message("autre_etape", minutes=12)
        assert msg == ("Les documents sont traités par étape, un modèle IA à la fois : celle-ci démarre "
                       "après l'étape en cours (au plus tard dans 12 min).")

    def test_etape_effective_suit_la_regle_du_worker(self):
        d = timedelta(minutes=20)
        assert file_ia.etape_effective(None, None, {"enrich": 3, "embed": 1}, T0, d) == "enrich"
        assert file_ia.etape_effective("enrich", T0, {"enrich": 3, "embed": 1}, T0, d) == "enrich"
        # Courante vide : le worker passera à la suivante qui a des jobs.
        assert file_ia.etape_effective("embed", T0, {"enrich": 3}, T0, d) == "enrich"

    @pytest.mark.asyncio
    async def test_etat_file_expose_etape_courante_et_motif(self, db_session):
        from models.file_ia_etat import FileIAEtat
        db_session.add(FileIAEtat(cle="gpu", etape="contenu", depuis=datetime.now(timezone.utc), nb_bascules=1))
        a = Job(type="ia_contenu", statut="pending", parametres={})
        b = Job(type="ia_embed", statut="pending", parametres={})
        db_session.add_all([a, b])
        await db_session.commit()

        etat_b = await file_ia.etat_file(db_session, b)
        assert etat_b["etape_courante"] == "contenu" and etat_b["depuis"]
        assert etat_b["raison"] == "autre_etape"
        assert "au plus tard dans" in etat_b["message"] and "{" not in etat_b["message"]
        assert etat_b["libelle"] == "Indexation sémantique"

        etat_a = await file_ia.etat_file(db_session, a)
        assert etat_a["raison"] != "autre_etape" and etat_a["etape_courante"] == "contenu"


# ─── Transcription : une à la fois par processus ─────────────────────────────

@pytest.mark.asyncio
async def test_la_transcription_est_bornee_a_une_a_la_fois(monkeypatch, tmp_path):
    """I6 : `indexation` est en classe io (3 slots) mais `process_file` transcrit encore l'audio sur
    la carte partagée → jusqu'à 3 transcriptions simultanées hors budget. Plafond : une."""
    import asyncio

    import httpx

    from services import runtime_config, transcription_service

    monkeypatch.setitem(runtime_config._overrides, "transcription_url", "http://transcription.test")
    etat = {"en_cours": 0, "max": 0}

    async def handler(request):
        etat["en_cours"] += 1
        etat["max"] = max(etat["max"], etat["en_cours"])
        await asyncio.sleep(0.05)
        etat["en_cours"] -= 1
        return httpx.Response(200, json={"text": "Parole fictive."})

    vrai = httpx.AsyncClient
    monkeypatch.setattr("services.transcription_service.httpx.AsyncClient",
                        lambda *a, **k: vrai(*a, **{**k, "transport": httpx.MockTransport(handler)}))
    audio = tmp_path / "memo.mp3"
    audio.write_bytes(b"audio fictif")

    textes = await asyncio.gather(*(transcription_service.transcribe(audio) for _ in range(4)))
    assert textes == ["Parole fictive."] * 4
    assert etat["max"] == 1
