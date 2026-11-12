"""
Plan lots IA par modèle, étape 5 — « Reprises sans tempête » : AUCUN repli de modèle sur un échec passager.
===========================================================================================
Le 12/11, pendant une longue série de vision, le modèle d'embedding n'était plus en mémoire : le paquet
attendait plus de 300 s (HTTP 504), Matothèque le rejouait, puis basculait sur le modèle de repli, qui
attendait à son tour — chaque repli chargeait un modèle de plus sur une carte déjà pleine. Ici :

- un échec PASSAGER (délai dépassé, 504, connexion…) ne déclenche AUCUN appel à un autre modèle :
  enrichissement, lecture d'images, embeddings — il lève `EchecPassager`, que le worker reporte ;
- un modèle ABSENT (404 « model … not found ») est le seul motif de repli (enrichissement, vision) ;
- embeddings : jamais de vecteurs de deux modèles pour un document, et jamais de repli (la base ne
  stocke que du 4096 dimensions et la recherche compare à des vecteurs du modèle principal) ;
- `generate`/`embed`/`embed_many` ne rejouent plus un appel qui a déjà attendu 300 s.

Aucun appel réseau (httpx bouchonné ou service simulé), documents et textes fictifs.
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from tenacity import wait_none

from models.document import Document
from services import embedding_service, runtime_config
from services.classement_echecs import EchecPassager, ModeleAbsent
from services.embedding_service import EmbeddingService
from services.extraction import ExtractionService
from services.ollama_service import OllamaService

REQ = httpx.Request("POST", "http://passerelle.test/api/x")


def _http(code: int, corps: dict | str = "") -> httpx.HTTPStatusError:
    contenu = json.dumps(corps, ensure_ascii=False) if isinstance(corps, dict) else corps
    return httpx.HTTPStatusError(f"HTTP {code}", request=REQ,
                                 response=httpx.Response(code, content=contenu.encode(), request=REQ))


ABSENT = lambda m="modele-a": _http(404, {"error": f'model "{m}" not found, try pulling it first'})  # noqa: E731
DELAI = lambda: httpx.ReadTimeout("délai dépassé (fictif)", request=REQ)  # noqa: E731


@pytest.fixture(autouse=True)
def _sans_enregistrement_d_echec(monkeypatch):
    from services import ia_echecs

    async def rien(*a, **k):
        return None

    monkeypatch.setattr(ia_echecs, "noter", rien)


@pytest.fixture
def candidats(monkeypatch):
    etat = {"modeles": ["modele-a", "modele-b"]}

    async def liste(usage):
        return list(etat["modeles"])

    monkeypatch.setattr(runtime_config, "model_candidates", liste)
    return etat


# ─── Enrichissement (`ExtractionService._enrich`) ──────────────────────────────────────────

REPONSE_OK = json.dumps({"categorie": "facture", "tags": ["fictif"], "resume": "Un résumé fictif."})


def _service_llm(*effets):
    ollama = MagicMock()
    ollama.generate = AsyncMock(side_effect=list(effets))
    return ExtractionService(None, ollama, None), ollama.generate


def _doc() -> Document:
    return Document(id=uuid.uuid4(), chemin="/fictif/a.pdf", nom="a.pdf", extension="pdf", hash_sha256="h")


def _db_sans_fiche() -> MagicMock:
    db = MagicMock()
    db.flush = AsyncMock()
    resultat = MagicMock()
    resultat.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=resultat)
    return db


def modeles_appeles(generate: AsyncMock) -> list[str]:
    return [c.kwargs["model"] for c in generate.await_args_list]


class TestEnrichissementSansRepliSurPassager:
    @pytest.mark.parametrize("incident", [DELAI(), _http(504, {"error": "timeout"}), _http(503), _http(429),
                                          _http(500), httpx.ConnectError("refusé", request=REQ)])
    @pytest.mark.asyncio
    async def test_un_incident_passager_leve_sans_appeler_un_autre_modele(self, candidats, incident):
        svc, generate = _service_llm(incident, REPONSE_OK, REPONSE_OK)
        with pytest.raises(EchecPassager):
            await svc._enrich(_doc(), "texte fictif", _db_sans_fiche(), lever_passager=True)
        assert modeles_appeles(generate) == ["modele-a"]        # un seul appel, un seul modèle

    @pytest.mark.asyncio
    async def test_le_message_dit_pourquoi(self, candidats):
        svc, _ = _service_llm(_http(504, {"error": "timeout"}))
        with pytest.raises(EchecPassager) as info:
            await svc._enrich(_doc(), "texte fictif", _db_sans_fiche(), lever_passager=True)
        assert "délai dépassé à la passerelle" in info.value.resume

    @pytest.mark.asyncio
    async def test_hors_chaine_un_incident_passager_ne_change_pas_l_ancien_contrat(self, candidats):
        """process_file / process_zip : l'enrichissement raté rend False (statut `extracted`) — sans repli."""
        svc, generate = _service_llm(DELAI(), REPONSE_OK)
        assert await svc._enrich(_doc(), "texte fictif", _db_sans_fiche()) is False
        assert modeles_appeles(generate) == ["modele-a"]

    @pytest.mark.asyncio
    async def test_un_modele_absent_bascule_sur_le_suivant(self, candidats):
        svc, generate = _service_llm(ABSENT("modele-a"), REPONSE_OK)
        assert await svc._enrich(_doc(), "texte fictif", _db_sans_fiche(), lever_passager=True) is True
        assert modeles_appeles(generate) == ["modele-a", "modele-b"]

    @pytest.mark.asyncio
    async def test_modele_absent_sous_l_enveloppe_tenacity_bascule_aussi(self, candidats):
        from tenacity import RetryError

        class _T:
            def exception(self):
                return ABSENT("modele-a")

        svc, generate = _service_llm(RetryError(_T()), REPONSE_OK)  # type: ignore[arg-type]
        assert await svc._enrich(_doc(), "texte fictif", _db_sans_fiche(), lever_passager=True) is True
        assert modeles_appeles(generate) == ["modele-a", "modele-b"]

    @pytest.mark.asyncio
    async def test_erreur_definitive_essaie_le_modele_suivant_comme_avant(self, candidats):
        """I5 : seul l'échec PASSAGER interdit un autre modèle ; une erreur définitive (HTTP 400…) garde
        le comportement d'avant l'étape 5."""
        svc, generate = _service_llm(RuntimeError("boum"), REPONSE_OK)
        assert await svc._enrich(_doc(), "texte fictif", _db_sans_fiche(), lever_passager=True) is True
        assert modeles_appeles(generate) == ["modele-a", "modele-b"]

    @pytest.mark.asyncio
    async def test_erreur_definitive_partout_rend_false_sans_lever(self, candidats):
        svc, generate = _service_llm(RuntimeError("boum"), RuntimeError("encore"))
        assert await svc._enrich(_doc(), "texte fictif", _db_sans_fiche(), lever_passager=True) is False
        assert modeles_appeles(generate) == ["modele-a", "modele-b"]

    @pytest.mark.asyncio
    async def test_les_appels_ne_sont_pas_rejoues_apres_une_longue_attente(self, candidats):
        """I4 : seule la chaîne IA désactive le rejeu interne de `generate`."""
        svc, generate = _service_llm(REPONSE_OK)
        await svc._enrich(_doc(), "texte fictif", _db_sans_fiche(), lever_passager=True)
        assert generate.await_args.kwargs["rejouer_apres_attente"] is False

    @pytest.mark.asyncio
    async def test_reponse_sans_categorie_garde_l_ancien_contrat_deux_essais_puis_modele_suivant(self, candidats):
        """Une réponse inexploitable n'est pas une exception : le comportement de CLAUDE.md est conservé."""
        svc, generate = _service_llm("{}", "{}", REPONSE_OK)
        assert await svc._enrich(_doc(), "texte fictif", _db_sans_fiche(), lever_passager=True) is True
        assert modeles_appeles(generate) == ["modele-a", "modele-a", "modele-b"]


# ─── Lecture d'images (`_ocr_fallback_sans_usage`) ─────────────────────────────────────────

@pytest.fixture
def image(tmp_path):
    f = tmp_path / "photo-fictive.png"
    f.write_bytes(b"PNG fictif")
    return f


class TestVisionSansRepliSurPassager:
    @pytest.mark.parametrize("incident", [DELAI(), _http(504, {"error": "timeout"}), _http(503),
                                          httpx.ConnectError("refusé", request=REQ)])
    @pytest.mark.asyncio
    async def test_un_incident_passager_leve_sans_appeler_un_autre_modele(self, candidats, image, incident):
        svc, generate = _service_llm(incident, "Texte lu")
        with pytest.raises(EchecPassager):
            await svc._ocr_fallback_sans_usage(image, "png")
        assert modeles_appeles(generate) == ["modele-a"]

    @pytest.mark.asyncio
    async def test_passager_a_mi_parcours_d_un_pdf_arrete_tout(self, candidats, tmp_path, monkeypatch):
        from services import extraction
        monkeypatch.setattr(extraction, "_rasteriser_pdf", lambda c, m: [b"p1", b"p2", b"p3"])
        pdf = tmp_path / "scan-fictif.pdf"
        pdf.write_bytes(b"%PDF fictif")
        svc, generate = _service_llm("page 1", DELAI(), "page 3")
        with pytest.raises(EchecPassager):
            await svc._ocr_fallback_sans_usage(pdf, "pdf")
        assert modeles_appeles(generate) == ["modele-a", "modele-a"]      # ni page 3, ni modèle B

    @pytest.mark.asyncio
    async def test_un_modele_absent_bascule_sur_le_suivant(self, candidats, image):
        svc, generate = _service_llm(ABSENT("modele-a"), "Texte lu")
        assert await svc._ocr_fallback_sans_usage(image, "png") == "Texte lu"
        assert modeles_appeles(generate) == ["modele-a", "modele-b"]

    @pytest.mark.asyncio
    async def test_erreur_definitive_essaie_le_modele_suivant_comme_avant(self, candidats, image):
        """I5 : seul l'échec PASSAGER interdit un autre modèle."""
        svc, generate = _service_llm(RuntimeError("boum"), "Texte lu")
        assert await svc._ocr_fallback_sans_usage(image, "png") == "Texte lu"
        assert modeles_appeles(generate) == ["modele-a", "modele-b"]

    @pytest.mark.asyncio
    async def test_erreur_definitive_partout_rend_vide(self, candidats, image):
        svc, generate = _service_llm(RuntimeError("boum"), RuntimeError("encore"))
        assert await svc._ocr_fallback_sans_usage(image, "png") == ""
        assert modeles_appeles(generate) == ["modele-a", "modele-b"]

    @pytest.mark.asyncio
    async def test_les_appels_ne_sont_pas_rejoues_apres_une_longue_attente(self, candidats, image):
        svc, generate = _service_llm("Texte lu")
        await svc._ocr_fallback_sans_usage(image, "png")
        assert generate.await_args.kwargs["rejouer_apres_attente"] is False

    @pytest.mark.asyncio
    async def test_reponse_vide_garde_son_second_avis(self, candidats, image):
        """Le cas « réponse vide » (modèle non-vision) est CONSERVÉ : un autre modèle, un seul."""
        svc, generate = _service_llm("", "Texte lu")
        assert await svc._ocr_fallback_sans_usage(image, "png") == "Texte lu"
        assert modeles_appeles(generate) == ["modele-a", "modele-b"]

    @pytest.mark.asyncio
    async def test_extraire_contenu_laisse_remonter_l_incident_passager(self, candidats, image, monkeypatch):
        """Le texte est vide ET la vision est indisponible : ce n'est pas « pas de texte », c'est « plus tard »."""
        from services import clamav_service

        async def sain(_):
            return True, "", "clean"

        monkeypatch.setattr(clamav_service, "scan_file", sain)
        tika = MagicMock()
        tika.extract_metadata = AsyncMock(return_value=[{}])
        svc = ExtractionService(tika, MagicMock(generate=AsyncMock(side_effect=DELAI())), None)
        db = MagicMock()
        db.flush = AsyncMock()
        with pytest.raises(EchecPassager):
            await svc.extraire_contenu(_doc_png(), image, db, recompute_hash=False)


def _doc_png() -> Document:
    return Document(id=uuid.uuid4(), chemin="/fictif/p.png", nom="p.png", extension="png", hash_sha256="h")


# ─── Embeddings (`EmbeddingService`) ───────────────────────────────────────────────────────

def _morceaux(monkeypatch, n: int) -> list[str]:
    textes = [f"morceau fictif {i}" for i in range(n)]
    monkeypatch.setattr(embedding_service, "chunk_text", lambda t: list(textes))
    return textes


def _base() -> MagicMock:
    db = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=(1,))))   # verrou du document obtenu
    return db


def _ollama(**kw) -> MagicMock:
    o = MagicMock()
    o.embed_many = AsyncMock(**kw)
    o.embed = AsyncMock(return_value=[0.5] * 8)
    return o


def modeles_lot(ollama) -> list[str]:
    return [c.kwargs["model"] for c in ollama.embed_many.await_args_list]


class TestEmbeddingsSansRepli:
    @pytest.mark.parametrize("incident", [DELAI(), _http(504, {"error": "timeout"}), _http(503),
                                          httpx.ConnectError("refusé", request=REQ)])
    @pytest.mark.asyncio
    async def test_incident_passager_sur_le_premier_paquet_aucun_autre_modele(self, monkeypatch, incident):
        _morceaux(monkeypatch, 3)
        ollama = _ollama(side_effect=incident)
        db = _base()
        with pytest.raises(EchecPassager):
            await EmbeddingService(ollama).embed_document(str(uuid.uuid4()), "x", db)
        assert len(modeles_lot(ollama)) == 1                       # un seul appel, un seul modèle
        db.add.assert_not_called()                                 # rien n'est écrit
        db.execute.assert_not_awaited()                            # et les anciens vecteurs ne sont pas supprimés
        ollama.embed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_incident_au_deuxieme_paquet_fait_echouer_le_calcul_entier(self, monkeypatch):
        monkeypatch.setattr(embedding_service, "TAILLE_PAQUET", 2)
        _morceaux(monkeypatch, 5)                                  # paquets : 2 + 2 + 1
        ollama = _ollama(side_effect=[[[1.0] * 8] * 2, DELAI(), [[2.0] * 8] * 2])
        db = _base()
        with pytest.raises(EchecPassager):
            await EmbeddingService(ollama).embed_document(str(uuid.uuid4()), "x", db)
        modeles = modeles_lot(ollama)
        assert len(modeles) == 2 and len(set(modeles)) == 1        # jamais le modèle de repli
        db.add.assert_not_called()                                 # pas de demi-document

    @pytest.mark.asyncio
    async def test_un_document_n_a_qu_un_seul_modele_embedding(self, monkeypatch):
        monkeypatch.setattr(embedding_service, "TAILLE_PAQUET", 2)
        _morceaux(monkeypatch, 5)
        ollama = _ollama(side_effect=[[[1.0] * 8] * 2, [[1.0] * 8] * 2, [[1.0] * 8]])
        db = _base()
        await EmbeddingService(ollama).embed_document(str(uuid.uuid4()), "x", db)
        lignes = [c.args[0] for c in db.add.call_args_list]
        assert len(lignes) == 5
        assert len({l.modele_embedding for l in lignes}) == 1
        assert len(set(modeles_lot(ollama))) == 1

    @pytest.mark.asyncio
    async def test_modele_absent_pas_de_repli_message_lisible(self, monkeypatch):
        """Principal absent : le modèle de repli (nomic, 768 dimensions) ne peut pas être stocké dans
        `halfvec(4096)` et ses vecteurs ne se comparent pas à ceux de la recherche → échec définitif."""
        _morceaux(monkeypatch, 3)
        ollama = _ollama(side_effect=ABSENT("qwen3-embedding:8b"))
        db = _base()
        monkeypatch.setattr(runtime_config, "usage_model", lambda u: "qwen3-embedding:8b")
        with pytest.raises(ModeleAbsent) as info:
            await EmbeddingService(ollama).embed_document(str(uuid.uuid4()), "x", db)
        message = str(info.value)
        assert "qwen3-embedding:8b" in message and "4096" in message
        assert modeles_lot(ollama) == ["qwen3-embedding:8b"]       # AUCUN appel au modèle de repli
        ollama.embed.assert_not_awaited()
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_reponse_incoherente_est_un_echec_definitif_sans_repli(self, monkeypatch):
        _morceaux(monkeypatch, 3)
        ollama = _ollama(return_value=[[0.1] * 8])                 # un vecteur pour trois textes
        db = _base()
        with pytest.raises(RuntimeError, match="Embedding vide ou incohérent"):
            await EmbeddingService(ollama).embed_document(str(uuid.uuid4()), "x", db)
        assert len(modeles_lot(ollama)) == 1
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_chemin_unitaire_passager_aucun_autre_modele(self, monkeypatch):
        from services.ollama_service import EmbedLotNonSupporte
        _morceaux(monkeypatch, 3)
        ollama = _ollama(side_effect=EmbedLotNonSupporte())
        ollama.embed = AsyncMock(side_effect=[[0.1] * 8, DELAI(), [0.3] * 8])
        db = _base()
        with pytest.raises(EchecPassager):
            await EmbeddingService(ollama).embed_document(str(uuid.uuid4()), "x", db)
        assert [c.kwargs["model"] for c in ollama.embed.await_args_list].count(
            ollama.embed.await_args_list[0].kwargs["model"]) == 2
        assert len({c.kwargs["model"] for c in ollama.embed.await_args_list}) == 1
        db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_aucun_appel_n_est_rejoue_apres_une_longue_attente(self, monkeypatch):
        """I4 : EmbeddingService désactive le rejeu interne, par paquet comme en unitaire."""
        from services.ollama_service import EmbedLotNonSupporte
        _morceaux(monkeypatch, 2)
        ollama = _ollama(return_value=[[0.1] * 8] * 2)
        await EmbeddingService(ollama).embed_document(str(uuid.uuid4()), "x", _base())
        assert ollama.embed_many.await_args.kwargs["rejouer_apres_attente"] is False
        ollama = _ollama(side_effect=EmbedLotNonSupporte())
        ollama.embed = AsyncMock(return_value=[0.1] * 8)
        await EmbeddingService(ollama).embed_document(str(uuid.uuid4()), "x", _base())
        assert ollama.embed.await_args.kwargs["rejouer_apres_attente"] is False

    @pytest.mark.asyncio
    async def test_chemin_unitaire_vecteur_vide_echec_definitif_sans_repli(self, monkeypatch):
        from services.ollama_service import EmbedLotNonSupporte
        _morceaux(monkeypatch, 2)
        ollama = _ollama(side_effect=EmbedLotNonSupporte())
        ollama.embed = AsyncMock(return_value=[])
        with pytest.raises(RuntimeError, match="Embedding vide"):
            await EmbeddingService(ollama).embed_document(str(uuid.uuid4()), "x", _base())
        assert ollama.embed.await_count == 1

    @pytest.mark.asyncio
    async def test_chemin_unitaire_modele_absent_pas_de_repli(self, monkeypatch):
        from services.ollama_service import EmbedLotNonSupporte
        _morceaux(monkeypatch, 2)
        ollama = _ollama(side_effect=EmbedLotNonSupporte())
        ollama.embed = AsyncMock(side_effect=ABSENT())
        with pytest.raises(ModeleAbsent):
            await EmbeddingService(ollama).embed_document(str(uuid.uuid4()), "x", _base())
        assert ollama.embed.await_count == 1


# ─── Les rejeux internes à OllamaService ne doublent plus une attente de 300 s ─────────────

@pytest.fixture
def requetes(monkeypatch):
    etat = {"vues": [], "reponse": None}

    def handler(request: httpx.Request) -> httpx.Response:
        etat["vues"].append(request.url.path)
        return etat["reponse"](request)

    vrai = httpx.AsyncClient

    def fabrique(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return vrai(*a, **k)

    monkeypatch.setattr("services.ollama_service.httpx.AsyncClient", fabrique)
    monkeypatch.setattr(OllamaService.generate.retry, "wait", wait_none())
    monkeypatch.setattr(OllamaService.embed.retry, "wait", wait_none())
    monkeypatch.setattr(OllamaService.embed_many.retry, "wait", wait_none())
    return etat


def _svc() -> OllamaService:
    return OllamaService(base_url="http://ollama.test")


def _trop_long(request):
    raise httpx.ReadTimeout("délai dépassé (fictif)", request=request)


class TestRejeuInterne:
    """I4 : par défaut (rapports, comparatifs, assistant…) l'ancien comportement est conservé — un second
    essai après un délai dépassé ou un 504 ; la chaîne IA le désactive avec `rejouer_apres_attente=False`."""

    @pytest.mark.asyncio
    async def test_generate_par_defaut_rejoue_un_504_et_un_delai(self, requetes):
        requetes["reponse"] = lambda r: httpx.Response(504, json={"error": "timeout"})
        with pytest.raises(Exception):
            await _svc().generate("prompt fictif", model="m")
        requetes["reponse"] = _trop_long
        with pytest.raises(Exception):
            await _svc().generate("prompt fictif", model="m")
        assert requetes["vues"] == ["/api/generate"] * 4            # 2 + 2

    @pytest.mark.asyncio
    async def test_generate_sans_rejeu_un_seul_appel(self, requetes):
        from services.classement_echecs import PASSAGER, classer_echec
        requetes["reponse"] = lambda r: httpx.Response(504, json={"error": "timeout"})
        with pytest.raises(Exception) as info:
            await _svc().generate("prompt fictif", model="m", rejouer_apres_attente=False)
        assert classer_echec(info.value) == PASSAGER
        requetes["reponse"] = _trop_long
        with pytest.raises(httpx.TimeoutException):
            await _svc().generate("prompt fictif", model="m", rejouer_apres_attente=False)
        assert requetes["vues"] == ["/api/generate"] * 2            # un par appel

    @pytest.mark.asyncio
    async def test_generate_503_garde_ses_deux_essais_meme_sans_rejeu_apres_attente(self, requetes):
        requetes["reponse"] = lambda r: httpx.Response(503, json={"error": "indisponible"})
        with pytest.raises(Exception):
            await _svc().generate("prompt fictif", model="m", rejouer_apres_attente=False)
        assert requetes["vues"] == ["/api/generate"] * 2

    @pytest.mark.asyncio
    async def test_embed_par_defaut_trois_essais_sans_rejeu_un_seul(self, requetes):
        requetes["reponse"] = lambda r: httpx.Response(504, json={"error": "timeout"})
        with pytest.raises(Exception):
            await _svc().embed("texte fictif", model="m")
        assert requetes["vues"] == ["/api/embeddings"] * 3          # 3 essais, comme avant
        requetes["vues"].clear()
        with pytest.raises(Exception):
            await _svc().embed("texte fictif", model="m", rejouer_apres_attente=False)
        assert requetes["vues"] == ["/api/embeddings"]

    @pytest.mark.asyncio
    async def test_embed_many_504_par_defaut_deux_essais_sans_rejeu_un(self, requetes):
        requetes["reponse"] = lambda r: httpx.Response(504, json={"error": "timeout"})
        with pytest.raises(Exception):               # RetryError (tenacity) : essais épuisés
            await _svc().embed_many(["a 0", "b 1"], model="m")
        assert requetes["vues"] == ["/api/embed"] * 2
        requetes["vues"].clear()
        with pytest.raises(httpx.HTTPStatusError):
            await _svc().embed_many(["a 0", "b 1"], model="m", rejouer_apres_attente=False)
        assert requetes["vues"] == ["/api/embed"]

    @pytest.mark.asyncio
    async def test_embed_many_delai_depasse_jamais_rejoue_comme_a_l_etape_2(self, requetes):
        requetes["reponse"] = _trop_long
        with pytest.raises(httpx.TimeoutException):
            await _svc().embed_many(["a 0"], model="m")
        assert requetes["vues"] == ["/api/embed"]

    @pytest.mark.asyncio
    async def test_embed_many_500_garde_ses_deux_essais(self, requetes):
        requetes["reponse"] = lambda r: httpx.Response(500, json={"error": "boum"})
        with pytest.raises(Exception):
            await _svc().embed_many(["a 0"], model="m", rejouer_apres_attente=False)
        assert requetes["vues"] == ["/api/embed"] * 2


# ─── C2 : l'annulation n'est jamais « rejouée » ────────────────────────────────────────────

@pytest.fixture
def requetes_lentes(monkeypatch):
    """Serveur fictif qui met 1 s à répondre : de quoi annuler l'appel en cours."""
    import asyncio
    vues: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        vues.append(request.url.path)
        await asyncio.sleep(1.0)
        return httpx.Response(200, json={"response": "x", "embedding": [0.1], "embeddings": [[0.1]]})

    vrai = httpx.AsyncClient

    def fabrique(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return vrai(*a, **k)

    monkeypatch.setattr("services.ollama_service.httpx.AsyncClient", fabrique)
    monkeypatch.setattr(OllamaService.generate.retry, "wait", wait_none())
    monkeypatch.setattr(OllamaService.embed.retry, "wait", wait_none())
    monkeypatch.setattr(OllamaService.embed_many.retry, "wait", wait_none())
    return vues


class TestAnnulationJamaisRejouee:
    @pytest.mark.parametrize("appel,chemin", [
        (lambda s: s.generate("prompt fictif", model="m"), "/api/generate"),
        (lambda s: s.generate("prompt fictif", model="m", rejouer_apres_attente=False), "/api/generate"),
        (lambda s: s.embed("texte fictif", model="m"), "/api/embeddings"),
        (lambda s: s.embed("texte fictif", model="m", rejouer_apres_attente=False), "/api/embeddings"),
        (lambda s: s.embed_many(["texte fictif"], model="m"), "/api/embed"),
        (lambda s: s.embed_many(["texte fictif"], model="m", rejouer_apres_attente=False), "/api/embed"),
    ])
    @pytest.mark.asyncio
    async def test_wait_for_court_un_seul_appel(self, requetes_lentes, appel, chemin):
        """Comme `asyncio.wait_for(embed(...), 10)` de routers/search.py : le délai coupe l'appel UNE fois."""
        import asyncio
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(appel(_svc()), 0.2)
        assert requetes_lentes == [chemin]

    @pytest.mark.asyncio
    async def test_une_tache_annulee_n_est_pas_rejouee(self, requetes_lentes):
        import asyncio
        tache = asyncio.create_task(_svc().generate("prompt fictif", model="m"))
        await asyncio.sleep(0.2)
        tache.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tache
        assert requetes_lentes == ["/api/generate"]

    def test_les_predicats_ignorent_ce_qui_n_est_pas_une_exception(self):
        import asyncio
        from services import ollama_service as o
        for pred in (o._rejouable, o._rejouable_par_paquet):
            assert pred(asyncio.CancelledError()) is False
            assert pred(KeyboardInterrupt()) is False
