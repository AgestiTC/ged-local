"""
Tests — libellés de l'arborescence GED
======================================
L'arbre des documents affiche des **chemins techniques** : `gdrive://<uuid>/…`,
`smb://<ip>/…`. Ce qu'il doit montrer, c'est le nom que l'utilisateur a donné à sa source.

Le cas qui manquait jusqu'ici est celui de la **source supprimée** : ses documents restent
indexés, plus aucun libellé ne les nomme, et l'arbre retombait sur l'UUID brut — illisible, et
muet sur la raison. Un nœud dont on ne comprend pas la présence ne se range pas.
"""

from routers.documents import _label_noeud, _racine_chemin


def test_source_connue_prend_son_libelle():
    """Le nom donné par l'utilisateur, pas l'identifiant interne."""
    uid = "a1618c1a-3e14-4953-b3e6-445e428f65c1"
    nom = _label_noeud(f"gdrive://{uid}", "", {uid: "Google Drive (frclementt@gmail.com)"})
    assert nom == "Google Drive (frclementt@gmail.com)"


def test_source_supprimee_est_nommee_et_expliquee():
    """
    Le défaut constaté en production : un `fca9af54-…` seul en tête d'arbre. L'utilisateur ne
    peut ni le lire, ni décider quoi en faire. Le libellé doit dire le service **et** que la
    source n'existe plus — c'est ce qui permet de trancher entre réindexer et purger.
    """
    nom = _label_noeud("gdrive://fca9af54-25ca-4e05-9577-1a3c137300d0", "", {})
    assert nom == "Google Drive (source supprimée)"


def test_schema_inconnu_ne_fabrique_pas_un_faux_nom():
    """Mieux vaut le schéma tel quel qu'un nom de service inventé."""
    nom = _label_noeud("truc://fca9af54-25ca-4e05-9577-1a3c137300d0", "", {})
    assert nom == "truc (source supprimée)"


def test_hote_smb_reste_lisible_sans_libelle():
    """Une IP renseigne encore ; la remplacer par « source supprimée » perdrait l'information."""
    assert _label_noeud("smb://192.168.42.200", "", {}) == "192.168.42.200"


def test_wiki_garde_son_nom():
    assert _label_noeud("wiki://", "") == "Wiki"


def test_dossier_ordinaire_prend_son_dernier_segment():
    """Plus bas dans l'arbre, les segments sont déjà des noms : pas de traduction."""
    assert _label_noeud("gdrive://abc/Scans_Epson", "gdrive://abc") == "Scans_Epson"


def test_racine_regroupe_par_source():
    """Tous les documents d'une source doivent tomber sous le même nœud racine."""
    uid = "fca9af54-25ca-4e05-9577-1a3c137300d0"
    assert _racine_chemin(f"gdrive://{uid}/Scans_Epson/Contrats/2026/x.pdf") == f"gdrive://{uid}"
    assert _racine_chemin("wiki://42") == "wiki://"
    assert _racine_chemin("/app/documents/a/b.pdf") == "/app"  # 1er segment absolu
