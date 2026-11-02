"""Candidat recommandé en page 1 des exports du comparatif (02/11/2026). Données 100 % FICTIVES."""

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest

from routers import compare
from services import recommandation_comparatif as rc

NOMS = ["Mutuelle Alpha", "Mutuelle Béta"]
RECO = {"candidat": "Mutuelle Alpha", "pourquoi": "Meilleure hospitalisation (200 % BR).",
        "atouts": ["Hospitalisation 200 % BR"], "vigilance": ["Carence de 3 mois"], "alternative": ""}
GROUPES = [{"nom": "Mutuelle Alpha", "valeurs": {"Prix": "10 €"}},
           {"nom": "Mutuelle Béta", "valeurs": {"Prix": "12 €"}}]


class TestLecture:
    def test_candidat_rapproche_sans_casse_ni_accents(self):
        reco = rc.lire_recommandation('{"candidat": "mutuelle beta", "pourquoi": "Moins chère.", '
                                      '"atouts": "- Prix bas\\n- Réseau", "vigilance": []}', NOMS)
        assert reco["candidat"] == "Mutuelle Béta" and reco["atouts"] == ["Prix bas", "Réseau"]

    def test_gras_markdown_retire(self):
        """Essai réel du 02/11 : « **200 % BR** » s'affichait tel quel dans Word et Excel."""
        reco = rc.lire_recommandation('{"candidat": "Mutuelle Alpha", "pourquoi": "Rembourse **200 % BR**.", '
                                      '"atouts": ["**Hospitalisation** forte"], "alternative": "__Béta__ si budget"}', NOMS)
        assert reco["pourquoi"] == "Rembourse 200 % BR." and reco["atouts"] == ["Hospitalisation forte"]
        assert reco["alternative"] == "Béta si budget"

    @pytest.mark.parametrize("reponse", [
        '{"candidat": "Mutuelle Inventée", "pourquoi": "x"}',   # hors de la liste : jamais inventé
        '{"candidat": "Mutuelle Alpha", "pourquoi": ""}',        # sans justification
        "pas de JSON",
    ])
    def test_inexploitable(self, reponse):
        assert rc.lire_recommandation(reponse, NOMS) is None


class TestRecommander:
    @pytest.mark.asyncio
    async def test_json_impose_et_candidat_en_echec_exclu(self):
        o = MagicMock()
        o.generate = AsyncMock(return_value='{"candidat": "Mutuelle Alpha", "pourquoi": "p"}')
        groupes = GROUPES + [{"nom": "Mutuelle Gamma", "echec_ia": True}]
        reco = await rc.recommander("| tableau |", groupes, None, None, None, "m", o)
        assert reco["candidat"] == "Mutuelle Alpha"
        assert o.generate.await_args.kwargs["format"] == "json"
        assert '"Mutuelle Gamma"' not in o.generate.await_args.args[0]   # pas proposé au choix

    @pytest.mark.asyncio
    async def test_moins_de_deux_candidats_exploitables(self):
        o = MagicMock()
        o.generate = AsyncMock()
        groupes = [GROUPES[0], {"nom": "Mutuelle Béta", "echec_ia": True}]
        assert await rc.recommander("t", groupes, None, None, None, "m", o) is None
        o.generate.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_second_essai_puis_abandon(self):
        o = MagicMock()
        o.generate = AsyncMock(return_value="désolé")
        assert await rc.recommander("t", GROUPES, None, None, None, "m", o) is None
        assert o.generate.await_count == rc.ESSAIS


class TestPageUne:
    def test_markdown_recommandation_avant_le_tableau_et_saut_de_page(self):
        md = compare._construire_markdown(["Prix"], GROUPES, None, titre=None, recommandation=RECO, saut_de_page=True)
        assert md.index("Candidat recommandé") < md.index(rc.SAUT_DE_PAGE_HTML) < md.index("| Critère |")
        assert rc.AVERTISSEMENT in md

    def test_sans_recommandation_rendu_inchange(self):
        assert "Candidat recommandé" not in compare._construire_markdown(["Prix"], GROUPES, None)

    def test_word_recommandation_puis_saut_de_page_puis_tableau(self):
        from docx import Document
        doc = Document(BytesIO(compare._generer_docx(["Prix"], GROUPES, None, "Tableau comparatif",
                                                     recommandation=RECO)))
        textes = [p.text for p in doc.paragraphs]
        assert textes.index("Candidat recommandé") < textes.index("Tableau comparatif détaillé")
        assert "Mutuelle Alpha" in textes and doc.tables   # le tableau suit

    def test_excel_feuille_recommandation_en_premier_et_active(self):
        import openpyxl
        brut = compare._generer_xlsx(None, GROUPES, ["Prix"], None)
        wb = openpyxl.load_workbook(BytesIO(compare._xlsx_avec_recommandation(brut, RECO)))
        assert wb.sheetnames[0] == "Recommandation" and wb.active.title == "Recommandation"
        assert wb["Recommandation"]["A2"].value == "Mutuelle Alpha"
        assert "Comparatif" in wb.sheetnames

    def test_excel_sans_recommandation_identique(self):
        brut = compare._generer_xlsx(None, GROUPES, ["Prix"], None)
        assert compare._xlsx_avec_recommandation(brut, None) is brut

    def test_pdf_rendu_avec_recommandation(self):
        md = compare._construire_markdown(["Prix"], GROUPES, None, titre=None, recommandation=RECO, saut_de_page=True)
        assert compare._generer_pdf(md, "Tableau comparatif")[:4] == b"%PDF"
