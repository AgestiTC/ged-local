"""
Tests du raisonnement temporel Q&R (E8) — fonctions pures, sans IA ni base.
"""
from datetime import date

from services import qa_temporal as qt


class TestMoisEtNormalisation:
    def test_mois_fr(self):
        assert qt.mois_fr("juillet") == 7
        assert qt.mois_fr("Juillet") == 7
        assert qt.mois_fr("juil") == 7
        assert qt.mois_fr("décembre") == 12
        assert qt.mois_fr("decembre") == 12
        assert qt.mois_fr("inconnu") is None

    def test_normaliser_periode_mois(self):
        assert qt.normaliser_periode(2018, 7) == (date(2018, 7, 1), date(2018, 7, 31))
        # février bissextile
        assert qt.normaliser_periode(2020, 2) == (date(2020, 2, 1), date(2020, 2, 29))

    def test_normaliser_periode_annee(self):
        assert qt.normaliser_periode(2018) == (date(2018, 1, 1), date(2018, 12, 31))

    def test_parse_date_iso(self):
        assert qt.parse_date_iso("2018") == date(2018, 1, 1)
        assert qt.parse_date_iso("2018-07") == date(2018, 7, 1)
        assert qt.parse_date_iso("2018-07-15") == date(2018, 7, 15)
        assert qt.parse_date_iso("pas une date") is None
        assert qt.parse_date_iso("2018-13") is None   # mois invalide


class TestPeriodeDepuisTexte:
    def test_mois_annee_francais(self):
        assert qt.periode_depuis_texte("Où travaillait Thomas en juillet 2018 ?") == \
            (date(2018, 7, 1), date(2018, 7, 31))

    def test_mm_aaaa_et_aaaa_mm(self):
        assert qt.periode_depuis_texte("paie 07/2018") == (date(2018, 7, 1), date(2018, 7, 31))
        assert qt.periode_depuis_texte("période 2018-07") == (date(2018, 7, 1), date(2018, 7, 31))

    def test_annee_seule(self):
        assert qt.periode_depuis_texte("rapport 2018") == (date(2018, 1, 1), date(2018, 12, 31))

    def test_priorite_mois_sur_annee(self):
        # le mois nommé prime sur l'année seule quand les deux sont présents
        assert qt.periode_depuis_texte("bilan de mars 2019 vs 2018")[0] == date(2019, 3, 1)

    def test_aucune_date(self):
        assert qt.periode_depuis_texte("où travaillait Thomas ?") is None


class TestPeriodeFichier:
    def test_nom_avec_mois_annee(self):
        assert qt.periode_fichier("bulletin 07-2018.pdf") == (date(2018, 7, 1), date(2018, 7, 31))

    def test_nom_mois_nomme_sans_annee(self):
        # « 7-Juillet » sans année → année neutre 1900 (tri relatif, pas filtre absolu)
        deb, fin = qt.periode_fichier("TC-Fiche paie 7-Juillet.pdf")
        assert (deb.month, fin.month) == (7, 7)
        assert deb.year == 1900

    def test_nom_sans_date(self):
        assert qt.periode_fichier("archive.zip") is None


class TestCouvre:
    def test_date_dans_periode(self):
        p = (date(2018, 7, 1), date(2018, 7, 31))
        assert qt.couvre(p, date(2018, 7, 15)) is True
        assert qt.couvre(p, date(2018, 8, 1)) is False

    def test_chevauchement_de_plages(self):
        paie = (date(2018, 7, 1), date(2018, 7, 31))
        assert qt.couvre(paie, (date(2018, 7, 1), date(2018, 7, 31))) is True
        assert qt.couvre(paie, (date(2018, 1, 1), date(2018, 12, 31))) is True   # « en 2018 »
        assert qt.couvre(paie, (date(2019, 1, 1), date(2019, 12, 31))) is False


class TestDureeEtAgregation:
    def test_agreger_periodes(self):
        ps = [(date(2018, 7, 1), date(2018, 7, 31)),
              (date(2018, 11, 1), date(2018, 11, 30)),
              (date(2018, 9, 1), date(2018, 9, 30))]
        assert qt.agreger_periodes(ps) == (date(2018, 7, 1), date(2018, 11, 30))
        assert qt.agreger_periodes([]) is None

    def test_nb_mois_inclusif(self):
        assert qt.nb_mois_inclusif(date(2018, 7, 1), date(2018, 11, 30)) == 5
        assert qt.nb_mois_inclusif(date(2018, 7, 1), date(2018, 7, 31)) == 1
        assert qt.nb_mois_inclusif(date(2018, 1, 1), date(2019, 2, 28)) == 14
        assert qt.nb_mois_inclusif(date(2019, 1, 1), date(2018, 1, 1)) == 0   # fin < debut

    def test_duree_humaine(self):
        assert qt.duree_humaine(date(2018, 7, 1), date(2018, 11, 30)) == "5 mois"
        assert qt.duree_humaine(date(2018, 1, 1), date(2019, 5, 31)) == "1 an et 5 mois"
        assert qt.duree_humaine(date(2018, 1, 1), date(2019, 12, 31)) == "2 ans"

    def test_libelle_periode(self):
        assert qt.libelle_periode(date(2018, 7, 1), date(2018, 7, 31)) == "juillet 2018"
        assert qt.libelle_periode(date(2018, 7, 1), date(2018, 11, 30)) == "07/2018 → 11/2018"
        assert qt.libelle_periode(date(2018, 1, 1), date(2018, 12, 31)) == "2018"   # année entière
