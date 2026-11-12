"""
Plan lots IA par modèle, étape 3 — file COLLANTE par étape (`job_worker._claim`).
================================================================================
Un document passe par trois jobs chaînés (contenu → enrich → embed), chacun limité à UN modèle IA.
Pour les lots GPU, `_claim` reste sur la même étape tant qu'il en reste en attente, et ne change
qu'à l'étape vide ou après un délai maximal. L'état « étape courante » est en base (`file_ia_etat`),
jamais en mémoire (uvicorn --workers 2).

Aucune donnée réelle : documents et jobs fictifs, handlers simulés, aucun appel réseau.
"""
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from models.document import Document
from models.file_ia_etat import FileIAEtat
from models.job import Job
from services import job_handlers, job_worker as jw

T0 = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
DELAI = timedelta(minutes=20)


# ─── 1. Fonctions pures ──────────────────────────────────────────────────────

class TestTypesEtEtapes:
    def test_etape_de(self):
        assert jw.etape_de("ia_contenu") == "contenu"
        assert jw.etape_de("analyze") == "contenu"          # ancien type : même étape
        assert jw.etape_de("reprise_texte") == "contenu"
        assert jw.etape_de("ia_enrich") == "enrich" and jw.etape_de("enrich") == "enrich"
        assert jw.etape_de("ia_embed") == "embed"
        assert jw.etape_de("rapport") is None and jw.etape_de("index_wiki") is None

    def test_ordre_du_cycle(self):
        assert jw.ETAPES == ("contenu", "enrich", "embed")

    def test_nouveaux_types_sont_des_lots_gpu(self):
        for t in ("ia_contenu", "ia_enrich", "ia_embed"):
            assert jw.classe_tache(t) == "gpu"
            assert t not in jw.INTERACTIF_TYPES
            assert jw.priorite(t) == 1

    def test_chaque_type_d_etape_est_gpu(self):
        for ts in jw.TYPES_ETAPE.values():
            assert ts <= jw.GPU_TYPES


class TestChoisirEtape:
    def choisir(self, courante, en_attente, ecoule=timedelta(minutes=1)):
        return jw.choisir_etape(courante, T0 - ecoule if ecoule is not None else None,
                                en_attente, T0, DELAI)

    def test_rien_en_attente_garde_la_courante(self):
        assert self.choisir("enrich", {}) == "enrich"

    def test_rien_en_attente_et_pas_de_courante(self):
        assert self.choisir(None, {}) is None
        assert self.choisir("n'importe quoi", {}) is None

    @pytest.mark.parametrize("courante", [None, "", "inconnue"])
    def test_courante_vide_ou_invalide_prend_la_premiere_du_cycle(self, courante):
        assert self.choisir(courante, {"embed": 4, "enrich": 2}) == "enrich"
        assert self.choisir(courante, {"embed": 4, "enrich": 2, "contenu": 1}) == "contenu"

    def test_courante_avec_jobs_et_delai_non_depasse_reste(self):
        assert self.choisir("embed", {"contenu": 9, "enrich": 9, "embed": 1}) == "embed"

    def test_courante_vide_passe_a_la_suivante_du_cycle(self):
        assert self.choisir("contenu", {"embed": 3}) == "embed"
        assert self.choisir("contenu", {"enrich": 3, "embed": 3}) == "enrich"
        assert self.choisir("enrich", {"contenu": 3, "embed": 3}) == "embed"
        assert self.choisir("embed", {"contenu": 3, "enrich": 3}) == "contenu"   # boucle

    def test_delai_depasse_change_si_une_autre_a_des_jobs(self):
        assert self.choisir("contenu", {"contenu": 9, "embed": 1}, ecoule=DELAI) == "embed"
        assert self.choisir("contenu", {"contenu": 9, "enrich": 1}, ecoule=DELAI + timedelta(hours=1)) == "enrich"

    def test_delai_depasse_sans_autre_etape_garde_la_courante(self):
        assert self.choisir("contenu", {"contenu": 9}, ecoule=DELAI * 3) == "contenu"

    def test_juste_avant_le_delai_reste(self):
        assert self.choisir("contenu", {"contenu": 9, "enrich": 1}, ecoule=DELAI - timedelta(seconds=1)) == "contenu"

    def test_depuis_inconnu_est_traite_comme_expire(self):
        # Pas de date de début : mieux vaut tourner que laisser une étape attendre indéfiniment.
        assert self.choisir("contenu", {"contenu": 9, "enrich": 1}, ecoule=None) == "enrich"


class TestDelaiReglable:
    def test_defaut_vingt_minutes(self):
        assert jw.delai_etape() == timedelta(minutes=20)

    @pytest.mark.parametrize("valeur,attendu", [("5", 5), ("0", 20), ("-3", 1), ("9999", 240), ("abc", 20), ("1", 1)])
    def test_borne_et_valeurs_invalides(self, monkeypatch, valeur, attendu):
        from services import runtime_config
        monkeypatch.setitem(runtime_config._overrides, "lots_ia_etape_delai_min", valeur)
        assert jw.delai_etape() == timedelta(minutes=attendu)


# ─── Outillage base ──────────────────────────────────────────────────────────

TOUS = ["ia_contenu", "ia_enrich", "ia_embed", "analyze", "enrich", "reprise_texte",
        "comparatif", "rapport", "index_wiki", "sync_source"]


@pytest_asyncio.fixture
async def fabrique(test_engine):
    f = async_sessionmaker(test_engine, expire_on_commit=False)
    with patch.object(jw, "AsyncSessionLocal", f), \
         patch.object(jw, "_HANDLERS", {t: object() for t in TOUS}):
        yield f


_compteur = {"n": 0}


async def ajouter(f, type_job, n=1, **champs):
    """Insère n jobs pending, créés dans l'ordre (horloge fictive croissante). Renvoie leurs ids."""
    ids = []
    async with f() as db:
        for _ in range(n):
            _compteur["n"] += 1
            jid = uuid.uuid4()
            db.add(Job(id=jid, type=type_job, statut="pending", parametres={},
                       created_at=T0 - timedelta(hours=5) + timedelta(seconds=_compteur["n"]), **champs))
            ids.append(str(jid))
        await db.commit()
    return ids


async def types_de(f, ids):
    async with f() as db:
        rows = (await db.execute(select(Job.id, Job.type))).all()
    par_id = {str(i): t for i, t in rows}
    return [par_id[i] for i in ids]


async def etat(f):
    async with f() as db:
        return (await db.execute(select(FileIAEtat).where(FileIAEtat.cle == "gpu"))).scalar_one_or_none()


async def poser_etat(f, etape, depuis, bascules=0):
    async with f() as db:
        db.add(FileIAEtat(cle="gpu", etape=etape, depuis=depuis, nb_bascules=bascules))
        await db.commit()


# ─── 2. _claim collant ───────────────────────────────────────────────────────

class TestClaimCollant:
    @pytest.mark.asyncio
    async def test_premiere_prise_choisit_la_premiere_etape_du_cycle_avec_des_jobs(self, fabrique):
        await ajouter(fabrique, "ia_embed", 2)           # les plus anciens
        await ajouter(fabrique, "ia_enrich", 2)
        ids = await jw._claim("gpu", 2)
        assert set(await types_de(fabrique, ids)) == {"ia_enrich"}      # pas la FIFO brute
        e = await etat(fabrique)
        assert e.etape == "enrich" and e.nb_bascules == 1 and e.depuis is not None

    @pytest.mark.asyncio
    async def test_reste_sur_l_etape_courante_meme_si_une_autre_est_plus_ancienne(self, fabrique):
        await poser_etat(fabrique, "enrich", datetime.now(timezone.utc))
        await ajouter(fabrique, "ia_contenu", 3)         # plus anciens, autre étape
        await ajouter(fabrique, "ia_enrich", 3)
        ids = await jw._claim("gpu", 2)
        assert set(await types_de(fabrique, ids)) == {"ia_enrich"}
        assert (await etat(fabrique)).nb_bascules == 0

    @pytest.mark.asyncio
    async def test_les_anciens_types_suivent_leur_etape(self, fabrique):
        await poser_etat(fabrique, "contenu", datetime.now(timezone.utc))
        await ajouter(fabrique, "analyze", 1)
        await ajouter(fabrique, "reprise_texte", 1)
        await ajouter(fabrique, "ia_contenu", 1)
        await ajouter(fabrique, "enrich", 2)
        ids = await jw._claim("gpu", 3)
        assert sorted(await types_de(fabrique, ids)) == ["analyze", "ia_contenu", "reprise_texte"]

    @pytest.mark.asyncio
    async def test_etape_vide_complete_les_places_libres_avec_la_suivante_une_seule_fois(self, fabrique):
        await ajouter(fabrique, "ia_contenu", 1)
        await ajouter(fabrique, "ia_enrich", 1)
        await ajouter(fabrique, "ia_embed", 1)
        ids = await jw._claim("gpu", 3)
        # contenu (1), puis UN seul recalcul → enrich ; embed attend son tour.
        assert await types_de(fabrique, ids) == ["ia_contenu", "ia_enrich"]
        e = await etat(fabrique)
        assert e.etape == "enrich" and e.nb_bascules == 2

    @pytest.mark.asyncio
    async def test_places_libres_non_remplies_si_aucune_autre_etape(self, fabrique):
        await ajouter(fabrique, "ia_contenu", 1)
        ids = await jw._claim("gpu", 4)
        assert len(ids) == 1
        assert (await etat(fabrique)).etape == "contenu"

    @pytest.mark.asyncio
    async def test_les_lots_hors_etape_partent_en_fifo_avec_l_etape_courante(self, fabrique):
        await poser_etat(fabrique, "enrich", datetime.now(timezone.utc))
        wiki = await ajouter(fabrique, "index_wiki", 1)
        await ajouter(fabrique, "ia_contenu", 1)         # autre étape : attend
        enrich = await ajouter(fabrique, "ia_enrich", 1)
        ids = await jw._claim("gpu", 2)
        assert ids == wiki + enrich

    @pytest.mark.asyncio
    async def test_claim_marque_running(self, fabrique):
        await ajouter(fabrique, "ia_contenu", 2)
        ids = await jw._claim("gpu", 1)
        async with fabrique() as db:
            statuts = dict((str(i), s) for i, s in (await db.execute(select(Job.id, Job.statut))).all())
        assert statuts[ids[0]] == "running" and list(statuts.values()).count("pending") == 1
        assert await jw._claim("gpu", 0) == []

    @pytest.mark.asyncio
    async def test_la_classe_io_ignore_les_etapes(self, fabrique):
        await ajouter(fabrique, "sync_source", 2)
        await ajouter(fabrique, "ia_contenu", 1)
        ids = await jw._claim("io", 5)
        assert set(await types_de(fabrique, ids)) == {"sync_source"}
        assert await etat(fabrique) is None              # aucune logique d'étape côté io


# ─── 3. Priorités inchangées ─────────────────────────────────────────────────

class TestPrioritesInchangees:
    @pytest.mark.asyncio
    async def test_l_interactif_passe_devant_meme_plus_recent(self, fabrique):
        await poser_etat(fabrique, "contenu", datetime.now(timezone.utc))
        await ajouter(fabrique, "ia_contenu", 3)
        c = await ajouter(fabrique, "comparatif", 1)
        ids = await jw._claim("gpu", 1)
        assert ids == c

    @pytest.mark.asyncio
    async def test_l_interactif_part_meme_si_son_etape_n_existe_pas(self, fabrique):
        await poser_etat(fabrique, "embed", datetime.now(timezone.utc))
        r = await ajouter(fabrique, "rapport", 1)
        await ajouter(fabrique, "ia_embed", 1)
        ids = await jw._claim("gpu", 2)
        assert set(await types_de(fabrique, ids)) == {"rapport", "ia_embed"}

    @pytest.mark.asyncio
    async def test_priorite_forcee_les_lots_ne_prennent_pas_de_creneau(self, fabrique):
        await ajouter(fabrique, "ia_contenu", 3)
        forcee = await ajouter(fabrique, "comparatif", 1, priorite_forcee=True)
        ids = await jw._claim("gpu", 2)
        assert ids == forcee
        assert await etat(fabrique) is None              # la logique d'étape n'a pas été touchée

    @pytest.mark.asyncio
    async def test_pause_ia_seuls_les_interactifs_partent_sans_toucher_l_etat(self, fabrique):
        await ajouter(fabrique, "ia_contenu", 3)
        inter = await ajouter(fabrique, "comparatif", 1)
        ids = await jw._claim("gpu", 5, interactifs_seulement=True)
        assert ids == inter
        assert await etat(fabrique) is None


class TestPriseSansDoublon:
    @pytest.mark.asyncio
    async def test_un_job_hors_chaine_n_est_jamais_rendu_deux_fois(self, fabrique):
        """C1 : `rapport` pris avec l'étape courante, puis le recalcul vers l'étape suivante le
        rendait encore (il restait `pending` dans la même transaction) → deux `_run` pour un job."""
        await poser_etat(fabrique, "contenu", datetime.now(timezone.utc))
        await ajouter(fabrique, "rapport", 1)
        await ajouter(fabrique, "ia_enrich", 1)
        await ajouter(fabrique, "ia_embed", 1)
        ids = await jw._claim("gpu", 4)
        assert len(ids) == len(set(ids)) == 3
        assert sorted(await types_de(fabrique, ids)) == ["ia_embed", "ia_enrich", "rapport"]

    @pytest.mark.asyncio
    async def test_idem_avec_un_lot_hors_etape(self, fabrique):
        await ajouter(fabrique, "index_wiki", 1)
        await ajouter(fabrique, "ia_contenu", 1)
        await ajouter(fabrique, "ia_enrich", 1)
        ids = await jw._claim("gpu", 5)
        assert len(ids) == len(set(ids)) == 3


class TestSortieAnticipee:
    @pytest.mark.asyncio
    async def test_file_vide_ni_verrou_ni_ecriture(self, fabrique):
        """I3 : à vide, `_claim` ne crée ni ne verrouille la ligne d'état (appelé toutes les 0,3-1 s)."""
        assert await jw._claim("gpu", 2) == []
        assert await etat(fabrique) is None

    @pytest.mark.asyncio
    async def test_rien_d_eligible_ne_touche_a_l_etat_existant(self, fabrique):
        await poser_etat(fabrique, "enrich", datetime.now(timezone.utc), bascules=4)
        await ajouter(fabrique, "sync_source", 2)       # classe io : pas éligible côté gpu
        assert await jw._claim("gpu", 2) == []
        e = await etat(fabrique)
        assert e.etape == "enrich" and e.nb_bascules == 4


# ─── 4. Délai maximal ────────────────────────────────────────────────────────

class TestDelaiMaximal:
    @pytest.mark.asyncio
    async def test_delai_depasse_force_le_changement(self, fabrique):
        await poser_etat(fabrique, "contenu", T0 - timedelta(minutes=21), bascules=7)
        await ajouter(fabrique, "ia_contenu", 5)
        await ajouter(fabrique, "ia_enrich", 2)
        with patch.object(jw, "_now", return_value=T0):
            ids = await jw._claim("gpu", 2)
        assert set(await types_de(fabrique, ids)) == {"ia_enrich"}
        e = await etat(fabrique)
        assert e.etape == "enrich" and e.nb_bascules == 8

    @pytest.mark.asyncio
    async def test_delai_non_atteint_ne_change_pas(self, fabrique):
        await poser_etat(fabrique, "contenu", T0 - timedelta(minutes=19))
        await ajouter(fabrique, "ia_contenu", 5)
        await ajouter(fabrique, "ia_enrich", 2)
        with patch.object(jw, "_now", return_value=T0):
            ids = await jw._claim("gpu", 2)
        assert set(await types_de(fabrique, ids)) == {"ia_contenu"}

    @pytest.mark.asyncio
    async def test_delai_depasse_sans_autre_etape_ne_touche_pas_a_depuis(self, fabrique):
        depuis = T0 - timedelta(hours=2)
        await poser_etat(fabrique, "contenu", depuis)
        await ajouter(fabrique, "ia_contenu", 3)
        with patch.object(jw, "_now", return_value=T0):
            ids = await jw._claim("gpu", 1)
        assert len(ids) == 1
        e = await etat(fabrique)
        assert e.etape == "contenu" and e.nb_bascules == 0
        assert e.depuis.replace(tzinfo=timezone.utc) == depuis

    @pytest.mark.asyncio
    async def test_le_delai_se_regle_en_base(self, fabrique, monkeypatch):
        from services import runtime_config
        monkeypatch.setitem(runtime_config._overrides, "lots_ia_etape_delai_min", "60")
        await poser_etat(fabrique, "contenu", T0 - timedelta(minutes=30))
        await ajouter(fabrique, "ia_contenu", 2)
        await ajouter(fabrique, "ia_enrich", 2)
        with patch.object(jw, "_now", return_value=T0):
            ids = await jw._claim("gpu", 1)
        assert set(await types_de(fabrique, ids)) == {"ia_contenu"}


# ─── 5. 50 documents : un modèle à la fois ───────────────────────────────────

MODELE = {"ia_contenu": "vision", "ia_enrich": "llm", "ia_embed": "embedding"}
SUITE = {"ia_contenu": "ia_enrich", "ia_enrich": "ia_embed", "ia_embed": None}


class Horloge:
    """Horloge fictive strictement croissante : sur SQLite, `now()` a la seconde pour résolution et
    les jobs chaînés seraient à égalité de date — l'ordre FIFO ne voudrait plus rien dire."""
    def __init__(self, debut):
        self.t = debut

    def suivant(self):
        self.t += timedelta(seconds=1)
        return self.t


def faux_handlers(horloge, echec=None):
    """Un faux handler par type, qui fait ce que fait le vrai côté file : chaîner la suite, avec
    une date de création explicite."""
    def fabrique_handler(type_job):
        async def h(ctx):
            doc_id = ctx.parametres["document_id"]
            if echec == (type_job, doc_id):
                raise RuntimeError("panne simulée")
            if SUITE[type_job]:
                async with jw.AsyncSessionLocal() as db:
                    jid = await job_handlers.enfiler_suivant(db, SUITE[type_job], doc_id,
                                                             {"document_id": doc_id})
                    if jid:
                        await db.execute(update(Job).where(Job.id == uuid.UUID(jid))
                                         .values(created_at=horloge.suivant()))
                    await db.commit()
            return {"ok": True}
        return h
    return {t: fabrique_handler(t) for t in MODELE}


async def creer_documents(f, n, prefixe="doc"):
    docs = []
    async with f() as db:
        for i in range(n):
            d = Document(chemin=f"/fictif/{prefixe}-{i}.pdf", nom=f"{prefixe}-{i}.pdf", extension="pdf",
                         hash_sha256=f"{prefixe}{i:03d}", statut="extracted", texte_extrait=f"texte fictif {i}")
            db.add(d)
            docs.append(d)
        await db.flush()
        for i, d in enumerate(docs):
            db.add(Job(type="ia_contenu", statut="pending", document_id=d.id,
                       parametres={"document_id": str(d.id)},
                       created_at=T0 - timedelta(hours=1) + timedelta(seconds=i)))
        await db.commit()
        return [str(d.id) for d in docs]


async def injecter_pendant_embed(f):
    """Pendant que l'étape embed tourne, de nouveaux documents arrivent — et leurs ia_contenu sont
    datés ENTRE les ia_embed restants : c'est le cas où une FIFO brute alterne les modèles."""
    async with f() as db:
        embeds = (await db.execute(select(Job).where(Job.type == "ia_embed", Job.statut == "pending")
                                   .order_by(Job.created_at))).scalars().all()
        for i, e in enumerate(embeds):
            d = Document(chemin=f"/fictif/nouveau-{i}.pdf", nom=f"nouveau-{i}.pdf", extension="pdf",
                         hash_sha256=f"nouveau{i:03d}", statut="extracted", texte_extrait=f"nouveau texte {i}")
            db.add(d)
            await db.flush()
            db.add(Job(type="ia_contenu", statut="pending", document_id=d.id,
                       parametres={"document_id": str(d.id)}, created_at=e.created_at + timedelta(milliseconds=500)))
        await db.commit()
        return len(embeds)


async def simuler(f, libres, handlers, injection=None, mode="etape"):
    """Boucle du worker : réclame jusqu'à `libres` places, termine le plus ancien, recommence.
    `mode="fifo"` : témoin, réclame le plus ancien `pending` sans tenir compte des étapes.
    Renvoie la suite des modèles dans l'ordre où les jobs ont DÉMARRÉ."""
    demarres, en_vol, injecte = [], deque(), False
    with patch.dict(jw._HANDLERS, handlers):
        for _ in range(3000):
            if mode == "fifo":
                ids = []
                async with f() as db:
                    for j in (await db.execute(select(Job).where(Job.statut == "pending")
                                               .order_by(Job.created_at, Job.id).limit(libres - len(en_vol)))).scalars():
                        j.statut = "running"
                        ids.append(str(j.id))
                    await db.commit()
            else:
                ids = await jw._claim("gpu", libres - len(en_vol))
            for jid, t in zip(ids, await types_de(f, ids)):
                demarres.append(MODELE[t])
                en_vol.append(jid)
            if injection and not injecte and "embedding" in demarres:
                injecte = True
                await injection(f)
            if not en_vol:
                break
            await jw._run(en_vol.popleft())
        else:
            raise AssertionError("la simulation ne converge pas")
    return demarres


def segments(suite):
    return 1 + sum(1 for a, b in zip(suite, suite[1:]) if a != b)


def blocs(suite):
    return [m for i, m in enumerate(suite) if i == 0 or m != suite[i - 1]]


@pytest.mark.parametrize("libres", [2, 1])
@pytest.mark.asyncio
async def test_cinquante_documents_un_modele_a_la_fois(fabrique, libres):
    docs = await creer_documents(fabrique, 50)
    demarres = await simuler(fabrique, libres, faux_handlers(Horloge(T0)))

    assert len(demarres) == 150
    assert demarres.count("vision") == demarres.count("llm") == demarres.count("embedding") == 50
    # Au plus un changement de modèle par étape : trois blocs, dans l'ordre du cycle.
    assert blocs(demarres) == ["vision", "llm", "embedding"]
    e = await etat(fabrique)
    assert e.nb_bascules <= 3
    async with fabrique() as db:
        termines = (await db.execute(
            select(func.count()).select_from(Job).where(Job.type == "ia_embed", Job.statut == "completed")
        )).scalar()
        assert termines == 50
        assert (await db.execute(select(func.count()).select_from(Job).where(Job.statut != "completed"))).scalar() == 0
    assert len(docs) == 50


@pytest.mark.parametrize("libres", [2, 1])
@pytest.mark.asyncio
async def test_de_nouveaux_documents_pendant_l_etape_embed_n_interrompent_pas_l_etape(fabrique, libres):
    """I7 : le worker reste sur embed jusqu'à ce qu'elle soit vide, PUIS traite les nouveaux arrivants."""
    await creer_documents(fabrique, 50)
    demarres = await simuler(fabrique, libres, faux_handlers(Horloge(T0)), injection=injecter_pendant_embed)

    assert blocs(demarres) == ["vision", "llm", "embedding", "vision", "llm", "embedding"]
    assert demarres.count("embedding") == demarres.count("vision") == demarres.count("llm")
    assert (await etat(fabrique)).nb_bascules <= 6
    async with fabrique() as db:
        assert (await db.execute(select(func.count()).select_from(Job).where(Job.statut != "completed"))).scalar() == 0


@pytest.mark.asyncio
async def test_temoin_une_fifo_brute_alterne_sur_le_meme_scenario(fabrique):
    """Même scénario, réclamé en FIFO pure (dates explicites, donc déterministe) : les modèles
    alternent — c'est exactement ce que la file collante supprime."""
    await creer_documents(fabrique, 50)
    fifo = await simuler(fabrique, 1, faux_handlers(Horloge(T0)), injection=injecter_pendant_embed, mode="fifo")
    assert segments(fifo) > 6
    assert segments(fifo) >= 20       # alternance franche, pas un hasard à un ou deux changements


# ─── 6. Un échec n'arrête pas les autres ─────────────────────────────────────

@pytest.mark.parametrize("etape_en_panne", ["ia_contenu", "ia_enrich", "ia_embed"])
@pytest.mark.asyncio
async def test_un_echec_ne_bloque_pas_les_autres_documents(fabrique, etape_en_panne):
    docs = await creer_documents(fabrique, 50)
    malade = docs[17]
    demarres = await simuler(fabrique, 2, faux_handlers(Horloge(T0), echec=(etape_en_panne, malade)))

    assert blocs(demarres) == ["vision", "llm", "embedding"]
    async with fabrique() as db:
        echecs = (await db.execute(select(Job).where(Job.statut == "failed"))).scalars().all()
        assert len(echecs) == 1
        assert echecs[0].type == etape_en_panne and str(echecs[0].document_id) == malade
        assert "panne simulée" in echecs[0].erreur
        embeds_ok = (await db.execute(
            select(func.count()).select_from(Job).where(Job.type == "ia_embed", Job.statut == "completed")
        )).scalar()
        # Les 49 autres vont jusqu'au bout ; le malade s'arrête à son étape.
        assert embeds_ok == 49
        assert (await db.execute(select(func.count()).select_from(Job).where(Job.statut.in_(("pending", "running"))))).scalar() == 0
