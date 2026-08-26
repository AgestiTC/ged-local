"""
Tests du parsing du connecteur reMarkable (`services.connectors.remarkable`).

`parse_docs` (contenu d'un dossier) et `collect_documents` (parcours récursif → documents)
sont PURES : elles transforment la liste **plate** renvoyée par le cloud reMarkable (chaque
entrée porte son `Parent`) en arborescence. C'est le cœur testable du connecteur (l'auth et le
téléchargement dépendent d'un compte réel, validés en session guidée).
"""

from services.connectors.remarkable import collect_documents, parse_docs

# Arbre : racine ├─ Facture.pdf (doc)  └─ Dossier A ├─ Note (doc)  └─ Sous-dossier ─ Livre (doc)
_ITEMS = [
    {"ID": "d1", "VissibleName": "Facture", "Type": "DocumentType", "Parent": ""},
    {"ID": "f1", "VissibleName": "Dossier A", "Type": "CollectionType", "Parent": ""},
    {"ID": "d2", "VissibleName": "Note", "Type": "DocumentType", "Parent": "f1"},
    {"ID": "f2", "VissibleName": "Sous-dossier", "Type": "CollectionType", "Parent": "f1"},
    {"ID": "d3", "VissibleName": "Livre", "Type": "DocumentType", "Parent": "f2"},
    {"ID": "d4", "VissibleName": "Corbeille doc", "Type": "DocumentType", "Parent": "trash"},
]


def test_parse_docs_racine():
    entrees = parse_docs(_ITEMS, "/")
    noms = [e["nom"] for e in entrees]
    # Racine : le dossier d'abord (tri), puis le document. La corbeille est exclue.
    assert noms == ["Dossier A", "Facture"]
    assert entrees[0]["dossier"] is True and entrees[0]["chemin"] == "f1"
    assert entrees[1]["dossier"] is False


def test_parse_docs_sous_dossier():
    entrees = parse_docs(_ITEMS, "f1")
    noms = {e["nom"] for e in entrees}
    assert noms == {"Sous-dossier", "Note"}


def test_collect_documents_recursif():
    docs = collect_documents(_ITEMS, "")
    rels = sorted(d["rel"] for d in docs)
    # Tous les documents (hors corbeille), rel = /{id}/{nom}.zip
    assert rels == ["/d1/Facture.zip", "/d2/Note.zip", "/d3/Livre.zip"]


def test_collect_documents_depuis_sous_dossier():
    docs = collect_documents(_ITEMS, "f1")
    rels = sorted(d["rel"] for d in docs)
    assert rels == ["/d2/Note.zip", "/d3/Livre.zip"]


def test_collect_documents_nom_avec_slash_echappe():
    items = [{"ID": "x", "VissibleName": "A/B", "Type": "DocumentType", "Parent": ""}]
    assert collect_documents(items, "")[0]["rel"] == "/x/A_B.zip"
