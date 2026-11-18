"""
Liste fermée des catégories (plan prompts + RAG, étape A3 — liste validée le 18/11/2026).
=========================================================================================
Correspondance des catégories inventées par l'IA, regroupement des fiches existantes (simulé, appliqué,
annulé), catégories des règles de classement et corrections à la main préservées. Données fictives.
"""
import uuid

import pytest
from sqlalchemy import select

from models.document import Document
from models.metadata import MetadonneeIA
from models.regle_classement import RegleClassement
from services import categories as cat


class TestRamener:
    @pytest.mark.parametrize("brute, attendue", [
        # variantes relevées en production le 13 et le 18/11/2026
        ("livre_audio", "livre audio"), ("Livre-Audio", "livre audio"), ("livre audio", "livre audio"),
        ("presentation", "présentation"), ("Présentation", "présentation"), ("diaporama", "présentation"),
        ("photographie", "image"), ("document photographique", "image"), ("document visuel", "image"),
        ("album photo automatique", "image"), ("album", "musique"), ("piste_audio", "musique"),
        ("document sonore", "audio"), ("son", "audio"),
        ("manuel d'utilisation", "documentation technique"), ("manuel utilisateur", "documentation technique"),
        ("roman policier", "livre"), ("policier", "livre"), ("biographie", "livre"),
        ("compte-rendu", "rapport"), ("procès-verbal", "rapport"), ("compte", "finances"),
        ("avis d'impôt", "finances"), ("quittance", "finances"),
        ("CV", "candidature"), ("lettre de motivation", "candidature"), ("curriculum-vitae", "candidature"),
        ("lettre", "correspondance"), ("courrier", "correspondance"), ("article", "publication"),
        ("attestation", "administratif"), ("document_administratif", "administratif"),
        ("ordonnance", "santé"), ("film", "vidéo"), ("code source", "informatique"),
        ("document", "autre"), ("fichier", "autre"), ("autre", "autre"),
        # ambigus, envoyés en « autre » par décision de Thomas (18/11/2026)
        ("contrôle", "autre"), ("document multimédia", "autre"), ("contenu multimedia", "autre"),
        ("conte", "livre"), ("contes de fées", "livre"), ("contexte", "autre"), ("contestation", "autre"),
    ])
    def test_correspondances(self, brute, attendue):
        assert cat.ramener(brute) == attendue

    def test_vide_reste_vide(self):
        assert cat.ramener(None) is None and cat.ramener("  ") is None

    def test_toute_reponse_tombe_dans_la_liste(self):
        for brute in ("zzz", "document de randonnée", "Quelque chose d'inédit"):
            assert cat.ramener(brute) in cat.LISTE

    def test_categorie_d_une_regle_de_classement_gardee_telle_quelle(self):
        assert cat.ramener("Documentation applications", {"Documentation applications"}) == "Documentation applications"

    def test_la_liste_est_close_et_sans_doublon(self):
        assert len(cat.LISTE) == 25 and len({cat.cle(c) for c in cat.LISTE}) == 25 and cat.LISTE[-1] == "autre"
        for c in cat.LISTE:
            assert cat.ramener(c) == c


async def _fiche(db, categorie, **champs) -> MetadonneeIA:
    d = Document(chemin=f"/fictif/{uuid.uuid4().hex}.pdf", nom="f.pdf", extension="pdf",
                 hash_sha256=uuid.uuid4().hex, statut="enriched", texte_extrait="Texte fictif.")
    db.add(d)
    await db.flush()
    m = MetadonneeIA(document_id=d.id, categorie=categorie, entites={}, **champs)
    db.add(m)
    await db.flush()
    return m


class TestRegroupement:
    @pytest.mark.asyncio
    async def test_simuler_regrouper_annuler(self, db_session):
        db = db_session
        await _fiche(db, "livre_audio")
        await _fiche(db, "livre-audio")
        await _fiche(db, "contrat")                       # déjà dans la liste : intact
        await _fiche(db, "photographie perso", categorie_manuelle=True)
        await _fiche(db, "Documentation applications")
        db.add(RegleClassement(libelle="Docs fictives", prefixe_chemin="smb://nas/docs/",
                               categorie="Documentation applications", classement="fixe"))
        await db.commit()

        sim = await cat.simuler(db)
        assert sim["fiches_changees"] == 2 and sim["categories_changees"] == 2
        assert sim["manuelles_ignorees"] == 1
        assert {e["ancienne"]: e["nouvelle"] for e in sim["exemples"]} == {
            "livre_audio": "livre audio", "livre-audio": "livre audio"}
        # La simulation n'a rien écrit.
        assert (await db.execute(select(MetadonneeIA.categorie).where(
            MetadonneeIA.categorie == "livre_audio"))).scalar() == "livre_audio"

        assert (await cat.regrouper(db))["fiches_changees"] == 2
        db.expire_all()
        lignes = {(m.categorie, m.categorie_origine) for m in (await db.execute(select(MetadonneeIA))).scalars()}
        assert ("livre audio", "livre_audio") in lignes and ("livre audio", "livre-audio") in lignes
        assert ("contrat", None) in lignes
        assert ("photographie perso", None) in lignes                      # corrigée à la main : intacte
        assert ("Documentation applications", None) in lignes              # règle de classement : intacte
        # Relancer ne fait rien de plus et ne perd pas l'origine.
        assert (await cat.regrouper(db))["fiches_changees"] == 0

        assert (await cat.annuler(db))["fiches_restaurees"] == 2
        db.expire_all()
        restes = sorted(c for (c,) in (await db.execute(select(MetadonneeIA.categorie))).all())
        assert restes == sorted(["livre_audio", "livre-audio", "contrat", "photographie perso",
                                 "Documentation applications"])


class TestRoutesEtCorrection:
    @pytest.mark.asyncio
    async def test_routes(self, client, db_session):
        await _fiche(db_session, "photo")
        await db_session.commit()
        sim = (await client.get("/api/system/categories/simulation")).json()
        assert sim["liste"][-1] == "autre" and sim["fiches_changees"] == 1
        assert (await client.post("/api/system/categories/regrouper")).json()["fiches_changees"] == 1
        assert (await client.post("/api/system/categories/annuler")).json()["fiches_restaurees"] == 1

    @pytest.mark.asyncio
    async def test_une_correction_a_la_main_est_marquee(self, client, db_session):
        m = await _fiche(db_session, "photo")
        meta_id, doc_id = m.id, m.document_id
        await db_session.commit()
        r = await client.patch(f"/api/documents/{doc_id}/metadata", json={"categorie": "Vacances 2026"})
        assert r.status_code == 200
        db_session.expire_all()
        m = (await db_session.execute(select(MetadonneeIA).where(MetadonneeIA.id == meta_id))).scalar_one()
        assert m.categorie == "Vacances 2026" and m.categorie_manuelle is True
        assert (await cat.simuler(db_session))["fiches_changees"] == 0


class TestEnrichissement:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("reponse, categorie, origine", [
        ('{"categorie": "livre_audio", "resume": "Fictif."}', "livre audio", "livre_audio"),
        ('{"categorie": "contrat", "resume": "Fictif."}', "contrat", None),
        ('{"categorie": "document", "resume": "Fictif."}', "autre", "document"),
    ])
    async def test_la_reponse_de_l_ia_est_ramenee_a_la_liste(self, reponse, categorie, origine):
        from unittest.mock import AsyncMock, MagicMock, patch
        from services.extraction import ExtractionService

        ollama = MagicMock()
        ollama.generate = AsyncMock(return_value=reponse)
        db = MagicMock()
        resultat = MagicMock()
        resultat.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=resultat)
        db.flush = AsyncMock()
        doc = Document(id=uuid.uuid4(), nom="f.pdf", extension="pdf", chemin="/fictif/f.pdf", hash_sha256="h",
                       texte_extrait="texte")
        with patch("services.runtime_config.model_candidates", new=AsyncMock(return_value=["modele-a"])):
            assert await ExtractionService(None, ollama, None)._enrich(doc, "texte", db) is True
        meta = db.add.call_args.args[0]
        assert (meta.categorie, meta.categorie_origine) == (categorie, origine)
        # Le prompt envoyé donne bien la liste fermée.
        assert "UNE SEULE valeur parmi : contrat, musique" in ollama.generate.await_args.args[0]
