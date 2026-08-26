"""
Tests de la logique PURE d'authentification des projets publieurs (Lot 2) — sans base.
"""
from services import publieur_auth as pa


class TestExclusionMisGeco:
    def test_projets_exclus(self):
        assert pa.est_projet_exclu("mis") is True
        assert pa.est_projet_exclu("MIS-facturation") is True
        assert pa.est_projet_exclu("geco") is True
        assert pa.est_projet_exclu("geco_caisse") is True
        assert pa.est_projet_exclu("Geco Caisse") is True

    def test_projets_autorises(self):
        assert pa.est_projet_exclu("sapyn") is False
        assert pa.est_projet_exclu("matotheque") is False
        assert pa.est_projet_exclu("netsight") is False
        assert pa.est_projet_exclu("") is False

    def test_pas_de_faux_positif(self):
        # « mission » commence par « mis » mais n'est PAS le segment « mis ».
        assert pa.est_projet_exclu("mission") is False
        assert pa.est_projet_exclu("gecko") is False


class TestJeton:
    def test_generer_aleatoire_et_long(self):
        a, b = pa.generer_jeton(), pa.generer_jeton()
        assert a != b
        assert len(a) >= 32   # token_urlsafe(32) → ~43 caractères

    def test_hash_deterministe_et_hex(self):
        h = pa.hash_jeton("secret")
        assert h == pa.hash_jeton("secret")
        assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)

    def test_hash_sensible(self):
        assert pa.hash_jeton("a") != pa.hash_jeton("b")

    def test_hash_vide(self):
        assert len(pa.hash_jeton("")) == 64
