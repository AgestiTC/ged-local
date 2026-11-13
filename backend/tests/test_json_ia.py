"""
Lecture tolérante du JSON des modèles (plan docs/plan-prompts-et-rag-apprenant.md, étape A2).

Reprend les cas de l'ancien `TestExtraireJson` (extraction) et ceux que couvraient, chacun à
sa façon, les cinq autres parseurs remplacés.
"""
from utils.json_ia import lire_objet


def test_json_direct():
    data = lire_objet('{"categorie": "rapport", "tags": ["a", "b"]}')
    assert data == {"categorie": "rapport", "tags": ["a", "b"]}


def test_json_dans_bloc_markdown():
    reponse = 'Voici le JSON :\n```json\n{"categorie": "contrat", "resume": "Test"}\n```\n'
    assert lire_objet(reponse)["categorie"] == "contrat"


def test_bloc_sans_mot_json():
    assert lire_objet('```\n{"a": 1}\n```') == {"a": 1}


def test_objet_entoure_de_texte():
    assert lire_objet('Réponse : {"categorie": "facture", "tags": []} et voilà.')["categorie"] == "facture"


def test_objet_imbrique():
    reponse = 'Résultat :\n```json\n{"entites": {"personnes": ["A"]}, "x": 1}\n```'
    assert lire_objet(reponse) == {"entites": {"personnes": ["A"]}, "x": 1}


def test_champs_null():
    data = lire_objet('{"categorie": "note", "sous_categorie": null}')
    assert data["sous_categorie"] is None


def test_liste_autour_de_l_objet():
    # La grille apprise cherchait directement le premier objet : une liste autour ne doit pas
    # faire échouer la lecture.
    assert lire_objet('[{"feuille": "Notes", "lignes": [3, 4]}]') == {"feuille": "Notes", "lignes": [3, 4]}


def test_rien_de_lisible_rend_none():
    for texte in ("Aucun JSON ici du tout", "", None, "   ", "{pas du json}", "[1, 2]", '"chaîne"'):
        assert lire_objet(texte) is None, texte


def test_caracteres_de_controle_selon_strict():
    reponse = '{"avis": "ligne 1\nligne 2"}'   # saut de ligne BRUT dans la chaîne
    assert lire_objet(reponse) is None
    assert lire_objet(reponse, strict=False) == {"avis": "ligne 1\nligne 2"}
