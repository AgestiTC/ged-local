"""Notes « 15/20 », réponses mal rangées, fiches robustes, réparation sans tout relancer (11/10/2026).
Données 100 % FICTIVES."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from models.job import Job
from services import compare_jobs, fiches_candidats as fc
from services import grille_analyse as ga


class TestNotes:
    @pytest.mark.parametrize("valeur, attendu", [
        (15, 15.0), ("15", 15.0), ("15/20", 15.0), ("15 / 20", 15.0), ("15,5 sur 20", 15.5),
        ("Note : 15", 15.0), ("8/10", 16.0), (25, 20.0), ("abc", None), (None, None), (True, None)])
    def test_note_sur_20(self, valeur, attendu):
        assert ga._note(valeur, 20) == attendu

    def test_note_en_tete_d_avis(self):
        assert ga._note_depuis_avis("15/20 — Délais garantis.", 20) == 15.0
        assert ga._note_depuis_avis("Délais garantis, 15/20.", 20) is None   # seulement en tête

    def test_reponse_rangee_sous_le_nom_du_critere(self):
        assert ga._lire_reponse('{"Délais d\'urgence": "15/20 — Délais garantis."}', 20) == (
            "15/20 — Délais garantis.", 15.0)

    def test_note_texte_dans_le_json(self):
        assert ga._lire_reponse('{"note": "12/20", "avis": "Moyens corrects."}', 20) == ("Moyens corrects.", 12.0)


class TestFiches:
    def test_repli_markdown(self):
        fiche = fc.lire_fiche("## Résumé\nOffre solide.\n## Points forts\n- Délais tenus\n- Équipe dédiée\n"
                              "**Points faibles :**\n- Pas d'exemple de rapport\n")
        assert fiche == {"resume": "Offre solide.", "points_forts": ["Délais tenus", "Équipe dédiée"],
                         "points_faibles": ["Pas d'exemple de rapport"], "vigilance": []}

    @pytest.mark.asyncio
    async def test_second_essai(self):
        o = MagicMock()
        o.generate = AsyncMock(side_effect=["{coupé", '{"resume": "r", "points_forts": ["p"]}'])
        fiche = await fc.rediger_fiche("A", {"Prix": "10"}, None, "m", o)
        assert fiche["points_forts"] == ["p"] and o.generate.await_count == 2


def _grille():
    return ga.Grille(feuille="F", ligne_entete=2, note_max=20.0,
                     blocs=[ga.Bloc("C1", 3, 4), ga.Bloc("E1", 5, 6)],
                     criteres=[ga.Critere(3, "Délais", "", 20.0), ga.Critere(4, "Moyens", "", 20.0)])


class TestReparation:
    @pytest.mark.asyncio
    async def test_notes_criteres_et_fiches(self, test_engine):
        fabrique = async_sessionmaker(test_engine, expire_on_commit=False)
        groupes = [
            {"nom": "Alpha", "valeurs": {}, "fiche": None, "evaluations": {
                "3": {"avis": "15/20 — Délais garantis.", "note": None},
                "4": {"avis": "Équipe dédiée.", "note": 14}}},
            {"nom": "Beta", "valeurs": {}, "fiche": None, "echec_ia": True, "evaluations": {
                "3": {"avis": ga.AVIS_ECHEC_IA, "note": None}, "4": {"avis": ga.AVIS_ECHEC_IA, "note": None}}},
        ]
        async with fabrique() as db:
            cible = Job(type="comparatif", statut="completed",
                        parametres={"grille": _grille().to_dict(), "model": "m", "fiches": True,
                                    "groupes": [{"nom": "Alpha", "document_ids": []}, {"nom": "Beta", "document_ids": []}]},
                        resultat={"groupes": groupes, "groupes_en_echec": ["Beta"], "colonnes": ["Délais", "Moyens"]})
            db.add(cible)
            await db.commit()
            cible_id = str(cible.id)

        ctx = MagicMock()
        ctx.parametres, ctx.cancelled, ctx.report = {"job_id": cible_id}, False, AsyncMock()
        fiche = {"resume": "r", "points_forts": ["p"], "points_faibles": [], "vigilance": []}
        with patch.object(compare_jobs, "AsyncSessionLocal", fabrique), \
             patch("routers.compare._charger_documents", AsyncMock(return_value=[])), \
             patch.object(ga, "passages_pertinents", AsyncMock(return_value="OFFRE")), \
             patch.object(ga, "exigences_marche", AsyncMock(return_value=None)), \
             patch.object(ga, "evaluer_critere", AsyncMock(return_value=("Réévalué.", 11.0, True))), \
             patch.object(fc, "rediger_fiche", AsyncMock(return_value=fiche)):
            bilan = await compare_jobs.handler_comparatif_reparer(ctx)

        assert bilan == {"notes_recuperees": 1, "criteres_reevalues": 2, "fiches_redigees": 2}
        async with fabrique() as db:
            etat = (await db.get(Job, uuid.UUID(cible_id))).resultat
        alpha, beta = etat["groupes"]
        assert alpha["evaluations"]["3"]["note"] == 15.0 and alpha["valeurs"]["Délais"].startswith("15/20")
        assert "echec_ia" not in beta and beta["evaluations"]["4"]["note"] == 11.0
        assert alpha["fiche"] == fiche and etat["groupes_en_echec"] == [] and etat["rev"] == 1

    @pytest.mark.asyncio
    async def test_route_refuse_une_comparaison_non_terminee(self, client, db_session):
        j = Job(type="comparatif", statut="running", parametres={}, resultat=None)
        db_session.add(j)
        await db_session.commit()
        assert (await client.post(f"/api/generate/compare/reparer/{j.id}")).status_code == 400


def test_pdf_paysage():
    """Comparatif en paysage (une colonne par candidat) ; rapports : au choix (12/10/2026)."""
    from services.export_service import _html_document
    assert "size: A4 landscape;" in _html_document("T", "<p>x</p>", paysage=True)
    assert "size: A4;" in _html_document("T", "<p>x</p>") and "landscape" not in _html_document("T", "<p>x</p>")
