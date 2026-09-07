"""
Tests — proposition d'événement à partir d'un texte libre
=========================================================
Seul `normaliser()` est testé, et c'est volontaire : l'appel à Ollama n'est qu'un transport,
alors que la normalisation est la barrière qui protège l'agenda. C'est elle qui décide qu'une
catégorie inventée retombe sur « préparation », qu'une heure sans jour est jetée, et qu'une
date écrite « 25/09 » se résout à l'année la plus proche.

Un modèle local rend n'importe quoi de temps en temps : ces tests décrivent ce qui arrive
alors, plutôt que d'espérer que ça n'arrive pas.
"""

from datetime import date

from services.jalon_ia import normaliser

AUJ = date(2026, 9, 7)
PHRASE = "Entretien prénatal avec la maternité le vendredi 25 septembre de 13h à 14h"


class TestNormalisation:
    def test_proposition_complete(self):
        p = normaliser({"titre": "Entretien prénatal à la maternité", "categorie": "medical",
                        "date": "2026-09-25", "heure_debut": "13:00", "heure_fin": "14:00",
                        "detail": "À la maternité", "obligatoire": False}, PHRASE, AUJ)

        assert p["titre"] == "Entretien prénatal à la maternité"
        assert p["categorie"] == "medical"
        assert p["date_reelle"] == "2026-09-25"
        assert (p["heure_debut"], p["heure_fin"]) == ("13:00", "14:00")

    def test_categorie_inventee_retombe_sur_preparation(self):
        """Le modèle propose parfois « rendez-vous » ou « santé » : ce ne sont pas des
        catégories du planning, et une catégorie inconnue casserait filtres et couleurs."""
        p = normaliser({"titre": "X", "categorie": "santé"}, "X", AUJ)
        assert p["categorie"] == "preparation"

    def test_date_inventee_par_le_modele_est_rejetee(self):
        """« vendredi prochain » n'est pas une date : on ne la stocke pas comme telle."""
        p = normaliser({"titre": "X", "date": "vendredi prochain"}, "X sans date", AUJ)
        assert p["date_reelle"] is None

    def test_repechage_de_la_date_et_du_creneau_quand_le_modele_les_oublie(self):
        """Les petits modèles lisent l'intention et ratent souvent le second horaire."""
        p = normaliser({"titre": "Entretien prénatal"}, PHRASE, AUJ)
        assert p["date_reelle"] == "2026-09-25"
        assert (p["heure_debut"], p["heure_fin"]) == ("13:00", "14:00")

    def test_repechage_date_numerique_annee_la_plus_proche(self):
        """Un planning contient du passé autant que du futur : forcer l'année suivante
        daterait un rendez-vous d'hier dans onze mois."""
        assert normaliser({"titre": "X"}, "rdv le 25/09", AUJ)["date_reelle"] == "2026-09-25"
        assert normaliser({"titre": "X"}, "rdv le 3 mars", AUJ)["date_reelle"] == "2027-03-03"
        assert normaliser({"titre": "X"}, "rdv le 3 décembre", AUJ)["date_reelle"] == "2026-12-03"
        assert normaliser({"titre": "X"}, "rdv le 25/09/2027", AUJ)["date_reelle"] == "2027-09-25"

    def test_une_heure_sans_jour_est_jetee(self):
        """Elle laisserait croire à un créneau réservé sur un événement posé au petit
        bonheur dans son mois."""
        p = normaliser({"titre": "X", "heure_debut": "13:00"}, "rendez-vous à 13h", AUJ)
        assert p["date_reelle"] is None
        assert p["heure_debut"] is None and p["heure_fin"] is None

    def test_heure_de_fin_anterieure_au_debut_est_ignoree(self):
        p = normaliser({"titre": "X", "date": "2026-09-25",
                        "heure_debut": "14:00", "heure_fin": "13:00"}, "X", AUJ)
        assert p["heure_debut"] == "14:00" and p["heure_fin"] is None

    def test_formats_d_heure_toleres(self):
        p = normaliser({"titre": "X", "date": "2026-09-25",
                        "heure_debut": "9h30", "heure_fin": "10h"}, "X", AUJ)
        assert (p["heure_debut"], p["heure_fin"]) == ("09:30", "10:00")

    def test_heure_hors_bornes_rejetee(self):
        p = normaliser({"titre": "X", "date": "2026-09-25", "heure_debut": "25:00"}, "X", AUJ)
        assert p["heure_debut"] is None

    def test_titre_manquant_retombe_sur_le_texte(self):
        """Échouer pour un titre absent gâcherait le reste de l'analyse, qui garde sa valeur."""
        p = normaliser({"categorie": "medical", "date": "2026-09-25"}, PHRASE, AUJ)
        assert p["titre"].startswith("Entretien prénatal")

    def test_obligatoire_ne_s_invente_pas(self):
        assert normaliser({"titre": "X"}, "X", AUJ)["obligatoire"] is False
        assert normaliser({"titre": "X", "obligatoire": True}, "X", AUJ)["obligatoire"] is True
