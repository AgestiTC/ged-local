"""
Tests de l'agrégation Q&R (E8) — logique métier PURE (sans IA ni base).
Couvre : construction des requêtes-signaux, employeur-à-une-date, durée d'emploi, gabarit de réponse.
"""
from datetime import date

from services import qa_service as qa
from services import qa_temporal as qt


def _fait(did, employeur, deb, fin=None, est_paie=True, nom="paie.pdf"):
    """Fabrique un fait extrait (comme le renverrait l'extraction LLM)."""
    per = None
    if deb:
        d = qt.parse_date_iso(deb)
        f = qt.parse_date_iso(fin or deb)
        per = (qt.normaliser_periode(d.year, d.month)[0], qt.normaliser_periode(f.year, f.month)[1])
    return {"id": did, "nom": nom, "extension": "pdf", "categorie": "paie",
            "score": 1.0, "est_paie": est_paie, "employeur": employeur,
            "salarie": "Thomas", "periode": per}


class TestRequetesRecherche:
    def test_construit_par_signaux_pas_la_question(self):
        intent = {"type_piece": ["fiche de paie"], "personnes": ["Thomas"], "organisations": []}
        reqs = qa.requetes_recherche(intent)
        assert "fiche de paie Thomas" in reqs
        # jamais la question brute
        assert all("où travaillait" not in r.lower() for r in reqs)

    def test_defaut_si_pas_de_type(self):
        reqs = qa.requetes_recherche({"type_piece": [], "personnes": [], "organisations": []})
        assert reqs and "paie" in reqs[0].lower()

    def test_inclut_organisation(self):
        intent = {"type_piece": ["fiche de paie"], "personnes": [], "organisations": ["LApp Muller"]}
        assert any("LApp Muller" in r for r in qa.requetes_recherche(intent))


class TestMatchOrg:
    def test_inclusion_souple(self):
        assert qa._match_org("SARL LApp Muller", "lapp muller") is True
        assert qa._match_org("LApp Muller", "muller") is True
        assert qa._match_org("Autre Entreprise", "muller") is False
        assert qa._match_org(None, "muller") is False


class TestEmployeurADate:
    def test_paie_couvrant_la_date(self):
        intent = {"intent": "employeur_a_date", "personnes": ["Thomas"]}
        faits = [_fait("1", "LApp Muller", "2018-07"),
                 _fait("2", "Autre SA", "2019-01")]
        cible = qt.normaliser_periode(2018, 7)   # juillet 2018
        agg = qa.agreger(intent, faits, cible)
        assert agg["type"] == "employeur_a_date"
        assert agg["employeurs"] == ["LApp Muller"]
        assert len(agg["documents"]) == 1

    def test_aucune_paie_sur_la_periode(self):
        intent = {"intent": "employeur_a_date", "personnes": ["Thomas"]}
        faits = [_fait("1", "LApp Muller", "2020-07")]
        agg = qa.agreger(intent, faits, qt.normaliser_periode(2018, 7))
        assert agg["employeurs"] == []

    def test_reponse_gabarit_elevee(self):
        intent = {"intent": "employeur_a_date", "personnes": ["Thomas"]}
        faits = [_fait("1", "LApp Muller", "2018-07")]
        agg = qa.agreger(intent, faits, qt.normaliser_periode(2018, 7))
        texte, conf = qa.composer(intent, agg)
        assert "LApp Muller" in texte and "juillet 2018" in texte
        assert conf == "Élevée"

    def test_employeurs_multiples_ambigu(self):
        intent = {"intent": "employeur_a_date", "personnes": ["Thomas"]}
        faits = [_fait("1", "LApp Muller", "2018-07"), _fait("2", "Autre SA", "2018-07")]
        agg = qa.agreger(intent, faits, qt.normaliser_periode(2018, 7))
        texte, conf = qa.composer(intent, agg)
        assert conf == "Moyenne" and "plusieurs employeurs" in texte


class TestDureeEmploi:
    def test_min_max_des_paies(self):
        intent = {"intent": "duree_emploi", "organisations": ["LApp Muller"]}
        faits = [_fait("1", "LApp Muller", "2018-07"),
                 _fait("2", "LApp Muller", "2018-11"),
                 _fait("3", "LApp Muller", "2018-09"),
                 _fait("4", "Autre SA", "2020-01")]   # doit être ignoré (autre employeur)
        agg = qa.agreger(intent, faits, None)
        assert agg["enveloppe"] == (date(2018, 7, 1), date(2018, 11, 30))
        assert agg["duree"] == "5 mois"
        assert len(agg["documents"]) == 3

    def test_reponse_gabarit(self):
        intent = {"intent": "duree_emploi", "personnes": ["Thomas"], "organisations": ["LApp Muller"]}
        faits = [_fait("1", "LApp Muller", "2018-07"), _fait("2", "LApp Muller", "2018-11")]
        agg = qa.agreger(intent, faits, None)
        texte, conf = qa.composer(intent, agg)
        assert "LApp Muller" in texte and "5 mois" in texte
        assert conf == "Élevée"

    def test_aucune_paie_confiance_faible(self):
        intent = {"intent": "duree_emploi", "organisations": ["Inconnue"]}
        agg = qa.agreger(intent, [], None)
        texte, conf = qa.composer(intent, agg)
        assert texte == "" and conf == "Faible"
