"""
Plan lots IA par modèle, étape 5 — classement des échecs d'un appel IA (fonction pure).
=====================================================================================
PASSAGER (carte saturée, passerelle qui coupe, réseau) : on reporte, on ne change ni de modèle ni de
job. MODÈLE ABSENT : seul cas où un repli de modèle a un sens. DÉFINITIF : tout le reste.

Exceptions fabriquées à la main (httpx / tenacity) : aucun appel réseau, aucune donnée réelle.
"""
import asyncio
import json

import httpx
import pytest
from tenacity import RetryError

from services import classement_echecs as ce
from services.classement_echecs import (DEFINITIF, MODELE_ABSENT, PASSAGER, EchecPassager, ModeleAbsent,
                                        classer_echec, decrire_echec)

REQ = httpx.Request("POST", "http://passerelle.test/api/generate")


def http(code: int, corps=None) -> httpx.HTTPStatusError:
    if isinstance(corps, dict):
        reponse = httpx.Response(code, content=json.dumps(corps, ensure_ascii=False).encode(), request=REQ)
    else:
        reponse = httpx.Response(code, content=(corps or "").encode(), request=REQ)
    return httpx.HTTPStatusError(f"HTTP {code}", request=REQ, response=reponse)


def enveloppe(exc: BaseException) -> RetryError:
    """Ce que tenacity lève quand `generate`/`embed` épuisent leurs essais (pas de reraise)."""
    class _Tentative:
        def exception(self):
            return exc

    return RetryError(_Tentative())  # type: ignore[arg-type]


class TestPassager:
    @pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
    def test_codes_http_passagers(self, code):
        assert classer_echec(http(code, {"error": "boum"})) == PASSAGER

    @pytest.mark.parametrize("exc", [
        httpx.ReadTimeout("délai", request=REQ),
        httpx.ConnectTimeout("délai", request=REQ),
        httpx.PoolTimeout("délai", request=REQ),
        httpx.ConnectError("refusé", request=REQ),
        httpx.ReadError("coupé", request=REQ),
        httpx.RemoteProtocolError("protocole", request=REQ),
        asyncio.TimeoutError(),
        ConnectionResetError("reset"),
    ])
    def test_erreurs_de_delai_de_connexion_et_de_protocole(self, exc):
        assert classer_echec(exc) == PASSAGER

    @pytest.mark.parametrize("corps", ["Réessaie plus tard", "reessaie plus tard", "Please retry later",
                                       "try again later"])
    def test_reessaie_plus_tard_de_la_passerelle_sur_un_code_d_incident(self, corps):
        # M2 : le motif ne vaut que pour un code >= 429 (réponse de la passerelle), sinon un corps de page
        # d'erreur quelconque ferait passer une erreur définitive pour un incident passager.
        assert classer_echec(http(503, {"error": corps})) == PASSAGER
        assert classer_echec(http(429, {"error": corps})) == PASSAGER
        assert classer_echec(http(599, {"error": corps})) == PASSAGER

    @pytest.mark.parametrize("code", [400, 401, 403, 404, 409, 422])
    def test_le_motif_ne_s_applique_pas_sous_429(self, code):
        assert classer_echec(http(code, {"error": "réessaie plus tard"})) == DEFINITIF

    def test_deballe_l_enveloppe_tenacity(self):
        assert classer_echec(enveloppe(httpx.ReadTimeout("délai", request=REQ))) == PASSAGER
        assert classer_echec(enveloppe(http(504))) == PASSAGER

    def test_l_echec_passager_type_reste_passager(self):
        assert classer_echec(EchecPassager("délai dépassé")) == PASSAGER

    def test_l_echec_passager_separe_la_cause_du_contexte(self):
        # M3 : `resume` = la cause seule ; le message complet nomme l'étape.
        exc = EchecPassager("délai dépassé", "les embeddings")
        assert exc.resume == "délai dépassé"
        assert str(exc) == "IA indisponible pour les embeddings : délai dépassé"
        assert decrire_echec(exc) == "délai dépassé"
        assert str(EchecPassager("délai dépassé")) == "délai dépassé"


class TestModeleAbsent:
    def test_404_model_not_found(self):
        exc = http(404, {"error": 'model "llama3.1:latest" not found, try pulling it first'})
        assert classer_echec(exc) == MODELE_ABSENT

    def test_404_sous_enveloppe_tenacity(self):
        exc = http(404, {"error": "model 'x' not found"})
        assert classer_echec(enveloppe(exc)) == MODELE_ABSENT

    def test_404_sans_motif_modele_est_definitif(self):
        # « 404 page not found » = route inconnue, pas un modèle absent : repli de modèle inutile.
        assert classer_echec(http(404, "404 page not found")) == DEFINITIF

    def test_le_modele_absent_type(self):
        assert classer_echec(ModeleAbsent("m", "absent")) == MODELE_ABSENT


class TestDefinitif:
    @pytest.mark.parametrize("exc", [
        ValueError("réponse inexploitable"),
        RuntimeError("embedding vide"),
        json.JSONDecodeError("x", "y", 0),
        FileNotFoundError("illisible"),
        KeyError("x"),
        http(400, {"error": "bad request"}),
        http(401),
        http(404, "404 page not found"),
        httpx.UnsupportedProtocol("schéma inconnu", request=REQ),
        None,
    ])
    def test_tout_le_reste(self, exc):
        assert classer_echec(exc) == DEFINITIF


class TestDescription:
    def test_delai(self):
        assert "délai dépassé" in decrire_echec(httpx.ReadTimeout("", request=REQ))

    def test_504_est_un_delai_de_la_passerelle(self):
        assert "délai dépassé à la passerelle" in decrire_echec(http(504))

    def test_codes_http(self):
        assert "HTTP 503" in decrire_echec(http(503))
        assert "HTTP 429" in decrire_echec(http(429))

    def test_connexion(self):
        assert "injoignable" in decrire_echec(httpx.ConnectError("x", request=REQ))

    def test_enveloppe_deballee(self):
        assert "délai dépassé" in decrire_echec(enveloppe(httpx.ReadTimeout("", request=REQ)))

    def test_jamais_vide(self):
        assert decrire_echec(ValueError()) == "ValueError"


class TestCauseReelle:
    def test_sans_enveloppe_rend_l_exception_telle_quelle(self):
        exc = ValueError("x")
        assert ce.cause_reelle(exc) is exc

    def test_deballe(self):
        interne = http(500)
        assert ce.cause_reelle(enveloppe(interne)) is interne
