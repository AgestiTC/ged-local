"""Indicateurs de mesure de la récupération (plan prompts/RAG, étape B0)."""
from utils.mesure_rag import mesurer, rangs

R = [{"id": "a", "nom": "Facture EDF.pdf"}, {"id": "b", "nom": "Bail.pdf"}, {"id": "c", "nom": "Note.docx"}]


def test_rangs_par_nom_sans_casse_et_par_id():
    assert rangs(R, ["facture edf.pdf", {"id": "c"}, "absent.pdf"]) == [1, 3, None]


def test_indicateurs():
    cas = [
        {"id": "q1", "resultats": R, "attendus": ["Bail.pdf"]},                 # rang 2
        {"id": "q2", "resultats": R, "attendus": [{"id": "c"}, "absent.pdf"]},  # rang 3, 1 manquant
        {"id": "q3", "resultats": R, "attendus": ["introuvable.pdf"]},          # rien
    ]
    m = mesurer(cas, ks=(1, 3))["indicateurs"]
    assert m["questions"] == 3
    assert m["rappel@1"] == 0.0
    assert m["rappel@3"] == round(2 / 3, 4)
    assert m["couverture@3"] == 0.5          # 2 attendus trouvés sur 4
    assert m["mrr"] == round((1 / 2 + 1 / 3) / 3, 4)


def test_jeu_vide():
    assert mesurer([])["indicateurs"] == {"questions": 0}
