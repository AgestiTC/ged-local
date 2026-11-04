"""Cause lisible des échecs de l'IA dans le comparatif (04/11/2026) — données fictives uniquement."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from routers import compare
from services import compare_jobs, cause_echec_ia as d


def _http_500(corps: str) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://ia.test.invalid/api/generate")
    return httpx.HTTPStatusError("Server error '500'", request=req, response=httpx.Response(500, text=corps, request=req))


class TestCauses:
    def test_boucle_lue_dans_le_corps_de_la_reponse(self):
        # Ollama met son motif dans le CORPS ; str(HTTPStatusError) ne le contient pas.
        assert d.cause_erreur(_http_500('{"error":"prediction aborted, token repeat limit reached"}')) == d.BOUCLE

    @pytest.mark.parametrize("erreur, attendu", [
        (httpx.ReadTimeout("x"), d.DELAI),
        (httpx.ConnectError("x"), d.INJOIGNABLE),
    ])
    def test_erreurs_d_appel(self, erreur, attendu):
        assert d.cause_erreur(erreur) == attendu

    def test_autre_erreur_http(self):
        assert "HTTP 500" in d.cause_erreur(_http_500("boom"))

    @pytest.mark.parametrize("reponse, attendu", [
        ("", d.VIDE),
        ('{"Synthèse": "' + "x" * 5000, d.COUPEE),                 # coupée : jamais refermée
        ('{"Synthèse": "' + "x" * 5000 + '"}', d.REDIGEE),         # texte rédigé de 5 000 car.
        ('{"Autre rubrique": "court"}', d.CLES),
        ("Voici mon analyse.", d.ILLISIBLE),
    ])
    def test_forme_de_la_reponse(self, reponse, attendu):
        assert d.cause_reponse(reponse) == attendu

    def test_cause_dominante(self):
        assert d.cause_dominante([d.CLES, d.REDIGEE, d.REDIGEE]) == d.REDIGEE
        assert d.cause_dominante([]) is None


class TestAnalyseGroupe:
    @pytest.mark.asyncio
    async def test_boucle_puis_second_essai_anti_repetition(self):
        ollama = SimpleNamespace(generate=AsyncMock(side_effect=[
            _http_500('{"error":"prediction aborted, token repeat limit reached"}'),
            '{"Prix": "1 000 €"}',
        ]))
        causes: list[str] = []
        valeurs, ok = await compare._analyser_groupe("Alpha", [], ["Prix"], None, "m", ollama, causes=causes)
        assert ok and valeurs == {"Prix": "1 000 €"}
        assert causes == [d.BOUCLE]
        assert ollama.generate.await_args_list[1].kwargs["options"] == d.OPTIONS_ANTI_BOUCLE

    @pytest.mark.asyncio
    async def test_reponse_redigee_donne_sa_cause(self):
        ollama = SimpleNamespace(generate=AsyncMock(return_value='{"Analyse": "' + "x" * 5000 + '"}'))
        causes: list[str] = []
        _, ok = await compare._analyser_groupe("Alpha", [], ["Prix"], None, "m", ollama, causes=causes)
        assert not ok and causes == [d.REDIGEE, d.REDIGEE]


class TestEchecTotal:
    @pytest.mark.asyncio
    async def test_message_final_nomme_la_cause(self):
        async def echec(**kw):
            kw["causes"].append(d.REDIGEE)
            return {"Prix": compare.VALEUR_ECHEC_IA}, False

        ctx = MagicMock(job_id="j", cancelled=False, report=AsyncMock(), parametres={
            "groupes": [{"nom": "Alpha", "document_ids": []}, {"nom": "Beta", "document_ids": []}],
            "colonnes": ["Prix"], "model": "m", "synthese": False, "fiches": False, "recommandation": False})
        with patch.object(compare, "_analyser_groupe", side_effect=echec), \
             patch.object(compare, "_charger_documents", AsyncMock(return_value=[])), \
             patch.object(compare_jobs, "_persister", AsyncMock()), \
             patch("services.ollama_service.OllamaService.check_health", AsyncMock(return_value=True)):
            with pytest.raises(RuntimeError, match="rédigé une analyse"):
                await compare_jobs.handler_comparatif(ctx)
