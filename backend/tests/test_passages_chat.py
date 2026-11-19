"""
Chat de la GED : passages proches de la question au lieu du début des documents (plan RAG, B1).
Textes fictifs.
"""
from unittest.mock import AsyncMock, patch

import pytest

from services import passages


class TestExtraitPour:
    def test_document_court_envoye_en_entier(self):
        assert passages.extrait_pour("Note fictive courte.", [(3, "autre")], 1500) == "Note fictive courte."

    def test_document_long_sans_passage_garde_son_debut(self):
        texte = "début " + "x" * 3000
        assert passages.extrait_pour(texte, None, 1500) == texte[:1500]

    def test_document_long_rend_le_passage_proche(self):
        texte = "début " + "x" * 3000
        assert passages.extrait_pour(texte, [(7, "La réponse fictive.")], 1500) == "[…] La réponse fictive. […]"

    def test_plusieurs_passages_dans_l_ordre_du_document(self):
        extrait = passages.extrait_pour("y" * 5000, [(9, "neuf"), (2, "deux")], 1500)
        assert extrait.index("deux") < extrait.index("neuf")


@pytest.mark.asyncio
async def test_meilleurs_passages_rien_hors_postgres():
    # Base de test SQLite : pas de pgvector → {} et le chat garde le début du texte.
    assert await passages.meilleurs_passages("question fictive", ["00000000-0000-0000-0000-000000000001"]) == {}


@pytest.mark.asyncio
async def test_le_chat_envoie_le_passage_proche_d_un_document_long():
    from routers import generate

    long_doc = {"id": "d-long", "nom": "manuel-fictif.pdf", "texte": "Sommaire. " + "z" * 5000, "meta_texte": ""}
    court = {"id": "d-court", "nom": "note-fictive.txt", "texte": "Note fictive.", "meta_texte": ""}
    proches = AsyncMock(return_value={"d-long": [(42, "Chapitre fictif qui répond.")]})
    with patch("services.qa_service.comprendre", AsyncMock(return_value={"intent": "recherche", "types": ["manuel"]})), \
         patch("routers.generate._recherche_mots_cles", AsyncMock(return_value=[long_doc, court])), \
         patch("services.passages.meilleurs_passages", proches), \
         patch("services.runtime_config.model_for", lambda _u: "modele-fictif"):
        ctx = await generate._contexte_ged("Que dit le manuel fictif ?")

    assert "Chapitre fictif qui répond." in ctx.contexte and "Sommaire." not in ctx.contexte
    assert "Note fictive." in ctx.contexte
    assert proches.await_args.args[1] == ["d-long"]          # seuls les documents longs sont cherchés
