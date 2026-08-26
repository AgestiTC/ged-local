"""
Tests de la logique PURE de la passerelle wiki (Lot 1) — sans base ni réseau.
`rapprocher` compare un manifeste à l'état publié et produit le plan d'action.
"""
from datetime import datetime, timezone

from services import publication_service as ps


def _page(cle, markdown, livre="Guide", chapitre=None, genere_le=None):
    return {"cle": cle, "livre": livre, "chapitre": chapitre, "titre": cle,
            "markdown": markdown, "genere_le": genere_le}


class TestHashContenu:
    def test_deterministe(self):
        assert ps.hash_contenu("abc") == ps.hash_contenu("abc")

    def test_sensible_au_contenu(self):
        assert ps.hash_contenu("abc") != ps.hash_contenu("abd")

    def test_vide(self):
        assert len(ps.hash_contenu("")) == 64   # sha256 hex


class TestRapprocher:
    def test_page_nouvelle_a_creer(self):
        plan = ps.rapprocher([_page("intro", "Bonjour")], existantes={})
        assert [p["cle"] for p in plan["creer"]] == ["intro"]
        assert plan["creer"][0]["hash"] == ps.hash_contenu("Bonjour")
        assert plan["mettre_a_jour"] == [] and plan["retraits_candidats"] == []

    def test_page_inchangee(self):
        h = ps.hash_contenu("Bonjour")
        plan = ps.rapprocher([_page("intro", "Bonjour")], {"intro": {"contenu_hash": h, "genere_le": None}})
        assert plan["inchangees"] == ["intro"]
        assert plan["creer"] == [] and plan["mettre_a_jour"] == []

    def test_page_modifiee(self):
        vieux = ps.hash_contenu("Bonjour")
        plan = ps.rapprocher([_page("intro", "Bonjour v2")], {"intro": {"contenu_hash": vieux, "genere_le": None}})
        assert [p["cle"] for p in plan["mettre_a_jour"]] == ["intro"]
        assert plan["mettre_a_jour"][0]["hash"] == ps.hash_contenu("Bonjour v2")

    def test_retrait_candidat(self):
        # « ancienne » est publiée mais absente du manifeste → signalée, pas supprimée.
        plan = ps.rapprocher([_page("intro", "x")], {"ancienne": {"contenu_hash": "zzz", "genere_le": None}})
        assert plan["retraits_candidats"] == ["ancienne"]

    def test_avertissement_version_plus_ancienne(self):
        publie_le = datetime(2026, 8, 1, tzinfo=timezone.utc)
        pousse_le = datetime(2026, 7, 1, tzinfo=timezone.utc)   # plus ancien
        plan = ps.rapprocher(
            [_page("intro", "Bonjour v2", genere_le=pousse_le)],
            {"intro": {"contenu_hash": ps.hash_contenu("Bonjour v1"), "genere_le": publie_le}},
        )
        assert plan["mettre_a_jour"] and len(plan["avertissements"]) == 1
        assert "plus ancienne" in plan["avertissements"][0]

    def test_pas_d_avertissement_si_plus_recent(self):
        publie_le = datetime(2026, 7, 1, tzinfo=timezone.utc)
        pousse_le = datetime(2026, 8, 1, tzinfo=timezone.utc)   # plus récent
        plan = ps.rapprocher(
            [_page("intro", "v2", genere_le=pousse_le)],
            {"intro": {"contenu_hash": ps.hash_contenu("v1"), "genere_le": publie_le}},
        )
        assert plan["avertissements"] == []

    def test_manifeste_mixte(self):
        existantes = {
            "a": {"contenu_hash": ps.hash_contenu("A"), "genere_le": None},   # inchangée
            "b": {"contenu_hash": ps.hash_contenu("vieux"), "genere_le": None},  # modifiée
            "c": {"contenu_hash": "zzz", "genere_le": None},                  # retrait
        }
        pages = [_page("a", "A"), _page("b", "B nouveau"), _page("d", "D")]
        plan = ps.rapprocher(pages, existantes)
        assert plan["inchangees"] == ["a"]
        assert [p["cle"] for p in plan["mettre_a_jour"]] == ["b"]
        assert [p["cle"] for p in plan["creer"]] == ["d"]
        assert plan["retraits_candidats"] == ["c"]
