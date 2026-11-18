"""
Rattrapage de nuit (remplace le workflow n8n « réindexation », 18/11/2026).
============================================================================
Quand passer (une fois par nuit, dans la fenêtre), quoi reprendre (erreurs, analyse IA, vecteurs),
dans quelle limite (plafond par volet, rien de retenté depuis moins de 7 jours) et les réglages.
Documents 100 % fictifs ; aucun appel réseau (les tâches sont seulement mises en file).
"""
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from models.document import Document
from models.embedding import Embedding
from models.job import Job
from models.metadata import MetadonneeIA
from services import rattrapage_nuit as rn

PARIS = ZoneInfo("Europe/Paris")
DEUX_H = 2 * 60


def paris(jour: int, heure: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, jour, heure, minute, tzinfo=PARIS)


class TestPassageDu:
    def test_coupe_sans_heure(self):
        assert not rn.passage_du(paris(18, 2, 30), None, None)

    def test_avant_l_heure_rien(self):
        assert not rn.passage_du(paris(18, 1, 59), DEUX_H, paris(17, 2, 0))

    def test_dans_la_fenetre_une_seule_fois(self):
        assert rn.passage_du(paris(18, 2, 5), DEUX_H, paris(17, 2, 0))
        assert not rn.passage_du(paris(18, 2, 10), DEUX_H, paris(18, 2, 5))   # déjà passé cette nuit

    def test_jamais_passe(self):
        assert rn.passage_du(paris(18, 3, 0), DEUX_H, None)

    def test_hors_fenetre_pas_en_pleine_journee(self):
        # Worker redémarré à 10 h sans passage de la nuit : on attend la nuit suivante.
        assert not rn.passage_du(paris(18, 10, 0), DEUX_H, paris(17, 2, 0))

    def test_fenetre_a_cheval_sur_minuit(self):
        # Heure réglée à 23:00 : à 1 h du matin on est encore dans la fenêtre de la veille.
        assert rn.passage_du(paris(18, 1, 0), 23 * 60, paris(16, 23, 0))
        assert not rn.passage_du(paris(18, 1, 0), 23 * 60, paris(17, 23, 5))


class TestPlafond:
    @pytest.mark.parametrize("valeur, attendu", [
        (None, 100), ("", 100), ("abc", 100), ("0", 0), ("50", 50), ("-3", 0), ("99999", rn.PLAFOND_MAX),
    ])
    def test_lire_plafond(self, valeur, attendu):
        assert rn.lire_plafond(valeur) == attendu


async def _doc(db, nom, statut, texte="", **champs) -> Document:
    d = Document(chemin=f"/fictif/{nom}", nom=nom, extension="pdf", hash_sha256=f"h-{uuid.uuid4().hex[:8]}",
                 statut=statut, texte_extrait=texte, **champs)
    db.add(d)
    await db.flush()
    return d


class TestExecuter:
    @pytest.mark.asyncio
    async def test_trois_volets_et_exclusions(self, db_session):
        db = db_session
        erreur = await _doc(db, "erreur.pdf", "error")
        sans_ia = await _doc(db, "sans-ia.pdf", "extracted", "Texte fictif.")
        sans_vecteurs = await _doc(db, "sans-vecteurs.pdf", "enriched", "Texte fictif.")
        db.add(MetadonneeIA(document_id=sans_vecteurs.id, categorie="Fictif", entites={}))
        complet = await _doc(db, "complet.pdf", "enriched", "Texte fictif.")
        db.add(MetadonneeIA(document_id=complet.id, categorie="Fictif", entites={}))
        db.add(Embedding(document_id=complet.id, chunk_index=0, chunk_text="x", embedding="[0.1]",
                         modele_embedding="m"))
        sans_texte = await _doc(db, "scan-muet.pdf", "extracted")   # rien à enrichir : jamais repris
        # Erreur déjà retentée il y a 2 jours : écartée (pas chaque nuit le même fichier illisible).
        retentee = await _doc(db, "retentee.pdf", "error")
        db.add(Job(type="ia_contenu", statut="failed", document_id=retentee.id, parametres={},
                   created_at=datetime.now(timezone.utc) - timedelta(days=2)))
        # Erreur retentée il y a 10 jours : reprise.
        ancienne = await _doc(db, "ancienne.pdf", "error")
        db.add(Job(type="ia_contenu", statut="failed", document_id=ancienne.id, parametres={},
                   created_at=datetime.now(timezone.utc) - timedelta(days=10)))
        await db.commit()

        bilan = await rn.executer(db, plafond=100)
        await db.commit()

        # `sans_ia` n'a pas non plus de vecteurs : il compte dans les deux volets.
        assert bilan == {"erreurs": 2, "analyse_ia": 1, "vecteurs": 2}
        enfiles = {(j.type, j.document_id) for j in (await db.execute(
            select(Job).where(Job.statut == "pending"))).scalars().all()}
        assert enfiles == {("ia_contenu", erreur.id), ("ia_contenu", ancienne.id), ("ia_enrich", sans_ia.id),
                           ("ia_embed", sans_ia.id), ("ia_embed", sans_vecteurs.id)}
        assert {d for _, d in enfiles}.isdisjoint({complet.id, sans_texte.id, retentee.id})

    @pytest.mark.asyncio
    async def test_second_passage_ne_double_rien(self, db_session):
        await _doc(db_session, "erreur.pdf", "error")
        await db_session.commit()
        assert (await rn.executer(db_session, plafond=100))["erreurs"] == 1
        await db_session.commit()
        assert (await rn.executer(db_session, plafond=100))["erreurs"] == 0

    @pytest.mark.asyncio
    async def test_plafond_par_volet_et_zero_coupe(self, db_session):
        for i in range(5):
            await _doc(db_session, f"erreur-{i}.pdf", "error")
        await db_session.commit()
        assert (await rn.executer(db_session, plafond=0)) == {"erreurs": 0, "analyse_ia": 0, "vecteurs": 0}
        assert (await rn.executer(db_session, plafond=3))["erreurs"] == 3


class TestReglages:
    @pytest.mark.asyncio
    async def test_heure_et_plafond_valides(self, client):
        r = await client.put("/api/system/config", json={"rattrapage_nuit_heure": "03:30",
                                                         "rattrapage_nuit_plafond": "50"})
        assert r.status_code == 200
        etat = (await client.get("/api/system/rattrapage-nuit")).json()
        assert etat["heure"] == "03:30" and etat["plafond"] == 50 and etat["dernier"] is None

    @pytest.mark.parametrize("champ, valeur", [
        ("rattrapage_nuit_heure", "25:00"), ("rattrapage_nuit_heure", "2h"),
        ("rattrapage_nuit_plafond", "-1"), ("rattrapage_nuit_plafond", "beaucoup"),
        ("rattrapage_nuit_plafond", str(rn.PLAFOND_MAX + 1)),
    ])
    @pytest.mark.asyncio
    async def test_valeurs_refusees(self, client, champ, valeur):
        assert (await client.put("/api/system/config", json={champ: valeur})).status_code == 422

    @pytest.mark.asyncio
    async def test_n8n_n_existe_plus(self, client):
        services = (await client.get("/api/system/services")).json()
        assert "n8n" not in services
        assert (await client.post("/api/system/test/n8n")).status_code == 400
