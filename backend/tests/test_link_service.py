"""
Tests du service Liens documentaires (`services.link_service`).

Fonctions PURES (aucune I/O) : extraction de références FR, détection du type
documentaire, et appariement des documents partageant une référence. C'est le
cœur métier de la détection BC ↔ facture — une régression ici produirait de
faux liens (ou en manquerait).
"""

from services import link_service as ls


# ── Extraction de références ────────────────────────────────────────────────────

def test_extrait_bon_de_commande():
    refs = ls.extract_references("Bon de commande N° BC-2024-1234 du 01/07")
    assert "BC-2024-1234" in refs


def test_extrait_facture_et_commande_referencee():
    refs = ls.extract_references("Facture n°FA2024-001 relative à la commande BC-2024-1234")
    assert refs == {"FA2024-001", "BC-2024-1234"}


def test_ignore_annee_nue_et_mots_bruit():
    # « 2024 » (année nue) et « total 1500 » ne sont pas des références.
    assert ls.extract_references("Rapport annuel 2024 — total 1500") == set()


def test_reference_exige_un_chiffre():
    # Un token sans chiffre n'est jamais une référence (évite « facture acquittée »).
    assert ls.extract_references("Facture acquittée définitivement") == set()


def test_texte_vide():
    assert ls.extract_references(None) == set()
    assert ls.extract_references("") == set()


# ── Détection du type documentaire ──────────────────────────────────────────────

def test_detect_kind_bc_et_facture_et_devis():
    assert ls.detect_kind("Bon de commande fournisseur", "cmd.pdf") == "bc"
    assert ls.detect_kind("FACTURE acquittée", "f.pdf") == "facture"
    assert ls.detect_kind("Devis proforma", "d.pdf") == "devis"
    assert ls.detect_kind("Note interne sans type", "note.pdf") is None


# ── Appariement (find_link_suggestions) ─────────────────────────────────────────

_A = "11111111-1111-1111-1111-111111111111"
_B = "22222222-2222-2222-2222-222222222222"
_C = "33333333-3333-3333-3333-333333333333"


def test_lien_bc_facture_haute_confiance():
    docs = [
        {"id": _A, "nom": "bc.pdf", "texte": "Bon de commande N° BC-2024-1234"},
        {"id": _B, "nom": "facture.pdf", "texte": "Facture n° FA-9 pour la commande BC-2024-1234"},
        {"id": _C, "nom": "autre.pdf", "texte": "Devis DV-777 sans rapport"},
    ]
    liens = ls.find_link_suggestions(docs)
    assert len(liens) == 1
    lien = liens[0]
    assert lien["type_lien"] == "bc_facture"
    assert lien["score"] >= 0.9
    assert lien["reference"] == "BC-2024-1234"
    # Paire normalisée (source = plus petit id).
    assert (lien["source_document_id"], lien["cible_document_id"]) == (_A, _B)


def test_paire_normalisee_sans_doublon_ab_ba():
    # Deux références partagées par la même paire → une seule suggestion.
    docs = [
        {"id": _B, "nom": "x", "texte": "Commande BC-100 et facture FA-100"},
        {"id": _A, "nom": "y", "texte": "Réf BC-100 puis FA-100"},
    ]
    liens = ls.find_link_suggestions(docs)
    assert len(liens) == 1
    assert (liens[0]["source_document_id"], liens[0]["cible_document_id"]) == (_A, _B)


def test_reference_trop_partagee_ignoree():
    # Une référence présente dans trop de documents = bruit (en-tête récurrent) → ignorée.
    docs = [{"id": f"{i:08d}-0000-0000-0000-000000000000", "nom": "d",
             "texte": "Commande BC-9999"} for i in range(10)]
    assert ls.find_link_suggestions(docs, max_par_reference=8) == []


def test_aucun_lien_si_references_disjointes():
    docs = [
        {"id": _A, "nom": "a", "texte": "Facture n° FA-1"},
        {"id": _B, "nom": "b", "texte": "Facture n° FA-2"},
    ]
    assert ls.find_link_suggestions(docs) == []
