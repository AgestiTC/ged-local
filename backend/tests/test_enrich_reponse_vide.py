"""
Enrichissement « réussi » mais vide — régression du 16/09/2026.

1 220 documents longs restaient bloqués dans « Relancer l'IA » : Ollama (contexte 4096 par
défaut) tronquait le DÉBUT du prompt, donc les consignes ; le modèle renvoyait un JSON valide
mais sans catégorie, accepté tel quel. Le doc passait « enrichi » à vide, la tâche « completed »,
et le compteur « Restant » ne bougeait jamais.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.document import Document
from services import job_handlers
from services.extraction import ExtractionService, _enrichissement_exploitable
from services.ollama_service import OllamaService, settings

JSON_OK = '{"categorie": "rapport", "tags": ["formation"], "resume": "Un rapport."}'


class TestEnrichissementExploitable:
    @pytest.mark.parametrize("data", [
        {}, {"categorie": None}, {"categorie": ""}, {"categorie": "   "},
        {"document": "…"}, {"categorie": 3}, [], "rapport", None,
    ])
    def test_vide_ou_inutilisable_refuse(self, data):
        assert _enrichissement_exploitable(data) is False

    def test_avec_categorie_accepte(self):
        assert _enrichissement_exploitable({"categorie": "rapport"}) is True


@pytest.fixture(autouse=True)
def _candidats():
    with patch("services.runtime_config.model_candidates",
               new=AsyncMock(return_value=["modele-a", "modele-b"])):
        yield


def _doc() -> Document:
    return Document(id=uuid.uuid4(), nom="long.pdf", extension="pdf", chemin="/x/long.pdf",
                    hash_sha256="h", texte_extrait="texte")


def _db_sans_meta() -> MagicMock:
    db = MagicMock()
    resultat = MagicMock()
    resultat.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=resultat)
    db.flush = AsyncMock()
    return db


class TestEnrichRefuseLeVide:
    @pytest.mark.asyncio
    async def test_json_vide_partout_echoue_sans_rien_ecrire(self):
        ollama = MagicMock()
        ollama.generate = AsyncMock(return_value="{}")
        db = _db_sans_meta()

        ok = await ExtractionService(None, ollama, None)._enrich(_doc(), "texte", db)

        assert ok is False
        db.add.assert_not_called()            # plus de fiche « enrichie » à vide
        assert ollama.generate.await_count == 4   # 2 tentatives × 2 modèles

    @pytest.mark.asyncio
    async def test_json_vide_puis_valide_reessaie(self):
        ollama = MagicMock()
        ollama.generate = AsyncMock(side_effect=["{}", JSON_OK])
        db = _db_sans_meta()

        ok = await ExtractionService(None, ollama, None)._enrich(_doc(), "texte", db)

        assert ok is True
        meta = db.add.call_args.args[0]
        assert meta.categorie == "rapport"
        assert meta.modele_utilise == "modele-a"

    @pytest.mark.asyncio
    async def test_bascule_sur_le_modele_suivant(self):
        ollama = MagicMock()
        ollama.generate = AsyncMock(side_effect=["{}", '{"categorie": ""}', JSON_OK])
        db = _db_sans_meta()

        ok = await ExtractionService(None, ollama, None)._enrich(_doc(), "texte", db)

        assert ok is True
        assert db.add.call_args.args[0].modele_utilise == "modele-b"


class TestJobEnrichEchoueVisiblement:
    @pytest.mark.asyncio
    async def test_enrichissement_vide_leve_une_erreur(self):
        """Le worker transforme l'exception en tâche « failed », visible dans « Tâches »."""
        doc = _doc()
        session = MagicMock()
        session.get = AsyncMock(return_value=doc)
        session.commit = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=0)))
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)
        ctx = MagicMock()
        ctx.parametres = {"document_id": str(doc.id)}
        ctx.report = AsyncMock()

        with patch.object(job_handlers, "AsyncSessionLocal", return_value=cm), \
             patch("services.ollama_service.OllamaService"), \
             patch("services.extraction.ExtractionService._enrich", new=AsyncMock(return_value=False)):
            with pytest.raises(RuntimeError, match="catégorie"):
                await job_handlers.handler_enrich(ctx)

        assert doc.statut == "extracted"       # le doc redevient candidat à la relance
        session.commit.assert_awaited()


class TestNumCtx:
    def test_num_ctx_envoye(self, monkeypatch):
        monkeypatch.setattr(settings, "ollama_num_ctx", 16384, raising=False)
        assert OllamaService._options() == {"num_ctx": 16384}
        assert OllamaService._options(num_predict=0) == {"num_predict": 0, "num_ctx": 16384}

    def test_zero_laisse_le_defaut_serveur(self, monkeypatch):
        monkeypatch.setattr(settings, "ollama_num_ctx", 0, raising=False)
        assert OllamaService._options() == {}

    @pytest.mark.asyncio
    async def test_generate_transmet_num_ctx(self, monkeypatch):
        monkeypatch.setattr(settings, "ollama_num_ctx", 16384, raising=False)
        reponse = MagicMock()
        reponse.json.return_value = {"response": "ok"}
        client = MagicMock()
        client.post = AsyncMock(return_value=reponse)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=False)

        service = OllamaService(base_url="http://ollama.test")
        with patch.object(service, "_get_client", return_value=cm):
            await service.generate("prompt", model="modele-a", format="json")

        payload = client.post.call_args.kwargs["json"]
        assert payload["options"]["num_ctx"] == 16384
