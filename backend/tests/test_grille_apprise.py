"""Grille apprise par l'IA locale (04/11/2026) — classeurs et candidats FICTIFS, IA simulée."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import openpyxl
import pytest

from services import grille_analyse as ga, grille_apprise as gp


def _grille_inedite(chemin, titre="MA99999 - Rapport d'analyse", noms=("ALPHA SARL", "BETA SAS")):
    """Forme qu'aucune règle ne connaît : ni « Avis/Note », ni « Candidats », ni « Critère »."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Analyse"
    ws.append([titre])
    ws.append([None, "Point examiné", None, *noms])                       # L2 : noms en D, E
    ws.append([None, "Qualité de l'équipe proposée", None, None, None])   # L3
    ws.append([None, "Planning d'exécution", None, None, None])           # L4
    ws.append([None, "Total", None, "=SUM(D3:D4)", "=SUM(E3:E4)"])        # L5 : formules
    wb.save(chemin)
    return chemin


BONNE = {"ligne_noms": 2, "candidats": [{"col_avis": 4, "col_note": None}, {"col_avis": 5, "col_note": None}],
         "criteres": [{"ligne": 3, "colonne_libelle": 2, "ligne_note": None, "note_max": None},
                      {"ligne": 4, "colonne_libelle": 2, "ligne_note": None, "note_max": None}]}
FAUSSE = {**BONNE, "criteres": [{"ligne": 5, "colonne_libelle": 2}]}       # la ligne des totaux


def _ia(*reponses):
    return SimpleNamespace(generate=AsyncMock(side_effect=[json.dumps(r) for r in reponses]))


class TestPlanEtValidation:
    def test_aucune_regle_ne_la_reconnait(self, tmp_path):
        chemin = _grille_inedite(tmp_path / "g.xlsx")
        assert ga.detecter_grille(chemin) is None
        assert ga.apercu_classeur(chemin)["type"] == "inconnu"

    def test_plan_masque_nombres_et_formules(self, tmp_path):
        ws = openpyxl.load_workbook(_grille_inedite(tmp_path / "g.xlsx")).active
        plan = gp.plan_classeur(ws)
        assert 'L3: B="Qualité de l\'équipe proposée"' in plan and "L5:" in plan and "D=<formule>" in plan
        assert "SUM" not in plan

    def test_une_case_a_remplir_doit_etre_vide(self, tmp_path):
        ws = openpyxl.load_workbook(_grille_inedite(tmp_path / "g.xlsx")).active
        with pytest.raises(ValueError, match="total"):
            gp.valider(ws, FAUSSE)                     # rien de valide : refus, avec le motif
        g = gp.valider(ws, {**BONNE, "criteres": BONNE["criteres"] + FAUSSE["criteres"]})
        assert [c.ligne for c in g.criteres] == [3, 4]  # la ligne des totaux est écartée, le reste gardé
        g = gp.valider(ws, {**BONNE, "ligne_noms": None})
        assert [b.nom for b in g.blocs] == ["ALPHA SARL", "BETA SAS"]   # ligne des noms retrouvée seule
        g = gp.valider(ws, BONNE)
        assert [c.titre for c in g.criteres] == ["Qualité de l'équipe proposée", "Planning d'exécution"]
        assert [b.nom for b in g.blocs] == ["ALPHA SARL", "BETA SAS"]


class TestErreursMesureesDeLIA:
    """Réponses RÉELLES de ministral-3:14b sur la forme « en sections » (04/11/2026), rejouées."""

    def test_ligne_de_note_prise_pour_un_critere_est_rattachee(self, tmp_path):
        from test_comparatif_rao import _grille_en_sections
        ws = openpyxl.load_workbook(_grille_en_sections(tmp_path / "s.xlsx")).active
        reponse = {"ligne_noms": 9, "candidats": [{"col_avis": c, "col_note": c} for c in (2, 3, 4)],
                   "criteres": [{"ligne": 10, "colonne_libelle": 1, "ligne_note": None, "note_max": None},
                                {"ligne": 11, "colonne_libelle": 1, "ligne_note": 11, "note_max": 10},   # faux
                                {"ligne": 16, "colonne_libelle": 1, "ligne_note": 17, "note_max": 25},
                                {"ligne": 18, "colonne_libelle": 1, "ligne_note": 19, "note_max": 50},
                                {"ligne": 20, "colonne_libelle": 1, "ligne_note": None, "note_max": 75},  # formules
                                {"ligne": 6, "colonne_libelle": 1, "ligne_note": None, "note_max": 40}]}  # formules
        g = gp.valider(ws, reponse)
        assert [(c.ligne, c.ligne_note, c.note_max) for c in g.criteres] == [(10, 11, 10.0), (16, 17, 25.0), (18, 19, 50.0)]


class TestApprentissage:
    @pytest.mark.asyncio
    async def test_second_essai_avec_le_motif_puis_memorise_sans_nom(self, tmp_path, db_session):
        chemin = _grille_inedite(tmp_path / "g.xlsx")
        ia = _ia(FAUSSE, BONNE)
        grille, _ = await gp.apprendre(chemin, ia, "m", db=db_session)
        assert grille is not None and len(grille.criteres) == 2
        assert "FAUSSE" in ia.generate.await_args_list[1].args[0]          # le motif est renvoyé à l'IA
        apprises = await gp.charger(db_session)
        assert len(apprises) == 1
        assert "ALPHA" not in json.dumps(apprises) and "BETA" not in json.dumps(apprises)   # coordonnées seulement

    @pytest.mark.asyncio
    async def test_marche_suivant_de_meme_forme_reconnu_sans_ia(self, tmp_path, db_session):
        await gp.apprendre(_grille_inedite(tmp_path / "a.xlsx"), _ia(BONNE), "m", db=db_session)
        suivant = _grille_inedite(tmp_path / "b.xlsx", titre="MA99998 - Rapport d'analyse",
                                  noms=("GAMMA", "DELTA"))
        apercu = ga.apercu_classeur(suivant, await gp.charger(db_session))
        assert apercu["type"] == "grille" and apercu["apprise"] is True and len(apercu["criteres"]) == 2
        g = gp.reconnaitre(suivant, await gp.charger(db_session))
        assert [b.nom for b in g.blocs] == ["GAMMA", "DELTA"]                # noms lus dans CE classeur

    @pytest.mark.asyncio
    async def test_deux_reponses_invalides_echec_explicite(self, tmp_path, db_session):
        grille, motif = await gp.apprendre(_grille_inedite(tmp_path / "g.xlsx"), _ia(FAUSSE, FAUSSE), "m",
                                           db=db_session)
        assert grille is None and "total" in motif
        assert await gp.charger(db_session) == []                           # rien de faux n'est retenu

    @pytest.mark.asyncio
    async def test_grille_apprise_remplie(self, tmp_path):
        from io import BytesIO
        chemin = _grille_inedite(tmp_path / "g.xlsx")
        grille, _ = await gp.apprendre(chemin, _ia(BONNE), "m")
        groupes = [{"nom": "BETA", "evaluations": {"3": {"avis": "Équipe solide.", "note": 8}}}]
        ws = openpyxl.load_workbook(BytesIO(ga.remplir_grille(chemin, grille, groupes))).active
        assert ws["E3"].value == "Équipe solide." and ws["D3"].value is None and ws["E5"].value == "=SUM(E3:E4)"
