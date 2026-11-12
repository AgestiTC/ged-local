"""Embeddings par paquets (plan lots IA, étape 2) : `/api/embed` au lieu d'un appel par morceau.

Aucun appel réseau : httpx est bouchonné (MockTransport), la base est simulée.
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from services import embedding_service
from services.embedding_service import TAILLE_PAQUET, EmbeddingService
from services.ollama_service import EmbedLotNonSupporte, OllamaService

DIM = 4096


def _vec(i: int, dim: int = DIM) -> list[float]:
    """Vecteur fictif reconnaissable : sa 1ʳᵉ composante porte le numéro du morceau."""
    v = [0.001] * dim
    v[0] = float(i + 1)
    return v


def _num(texte: str) -> int:
    return int(texte.rsplit(" ", 1)[1])


@pytest.fixture
def requetes(monkeypatch):
    """Requêtes RÉELLEMENT émises (le vrai `_get_client` reste en place) + réponse pilotable."""
    etat = {"vues": [], "reponse": None}

    def handler(request: httpx.Request) -> httpx.Response:
        corps = json.loads(request.content)
        etat["vues"].append({"path": request.url.path, "headers": dict(request.headers), "corps": corps})
        if etat["reponse"] is not None:
            return etat["reponse"](request, corps)
        if request.url.path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [_vec(_num(t)) for t in corps["input"]]})
        return httpx.Response(200, json={"embedding": _vec(_num(corps["prompt"]))})

    vrai = httpx.AsyncClient

    def fabrique(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return vrai(*a, **k)

    monkeypatch.setattr("services.ollama_service.httpx.AsyncClient", fabrique)
    return etat


@pytest.fixture(autouse=True)
def _sans_enregistrement_d_echec(monkeypatch):
    from services import ia_echecs

    async def rien(*a, **k):
        return None

    monkeypatch.setattr(ia_echecs, "noter", rien)


def _morceaux(monkeypatch, n: int) -> list[str]:
    textes = [f"morceau fictif {i}" for i in range(n)]
    monkeypatch.setattr(embedding_service, "chunk_text", lambda t: list(textes))
    return textes


def _base() -> MagicMock:
    db = MagicMock()                  # SQLite ne stocke pas de vecteur : session simulée
    db.flush = AsyncMock()
    return db


def _lignes(db) -> list:
    return [c.args[0] for c in db.add.call_args_list]


# ─── OllamaService.embed_many ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_embed_many_poste_api_embed_avec_input_et_keep_alive(requetes):
    svc = OllamaService(base_url="http://ollama.test")
    vecteurs = await svc.embed_many(["texte fictif 0", "texte fictif 1"], model="m-fictif")
    (req,) = requetes["vues"]
    assert req["path"] == "/api/embed"                       # jamais /v1/*
    assert req["corps"]["model"] == "m-fictif"
    assert req["corps"]["input"] == ["texte fictif 0", "texte fictif 1"]
    assert req["corps"]["keep_alive"] == svc._keep_alive_for("m-fictif")
    assert req["headers"]["x-ai-usage"] == "embeddings"
    assert [v[0] for v in vecteurs] == [1.0, 2.0]


@pytest.mark.asyncio
async def test_embed_many_liste_vide_n_appelle_rien(requetes):
    assert await OllamaService(base_url="http://ollama.test").embed_many([]) == []
    assert requetes["vues"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("statut, corps", [
    (405, "method not allowed"),
    (404, "404 page not found"),                              # route inconnue, corps non JSON
    (404, '{"error":"unknown route"}'),
])
async def test_embed_many_route_refusee_leve_sans_nouvel_essai(requetes, statut, corps):
    requetes["reponse"] = lambda r, c: httpx.Response(statut, content=corps.encode())
    svc = OllamaService(base_url="http://ollama.test")
    with pytest.raises(EmbedLotNonSupporte):
        await svc.embed_many(["texte fictif 0"], model="m")
    assert len(requetes["vues"]) == 1


@pytest.mark.asyncio
async def test_embed_many_modele_absent_n_est_pas_une_route_inconnue(requetes, monkeypatch):
    """404 « model not found » : vrai échec du modèle (repli de modèle), pas de repli unitaire."""
    requetes["reponse"] = lambda r, c: httpx.Response(
        404, json={"error": 'model "qwen3-embedding:8b" not found, try pulling it first'})

    async def sans_attente(_):
        return None

    monkeypatch.setattr(OllamaService.embed_many.retry, "sleep", sans_attente)   # pas d'attente entre essais
    svc = OllamaService(base_url="http://ollama.test")
    with pytest.raises(Exception) as info:
        await svc.embed_many(["texte fictif 0"], model="m")
    assert not isinstance(info.value, EmbedLotNonSupporte)


@pytest.mark.asyncio
async def test_embed_many_rend_tel_quel_une_reponse_incoherente(requetes):
    requetes["reponse"] = lambda r, c: httpx.Response(200, json={"embeddings": [[0.1]]})
    svc = OllamaService(base_url="http://ollama.test")
    assert await svc.embed_many(["a 0", "b 1"], model="m") == [[0.1]]   # la vérification est à l'appelant


# ─── EmbeddingService.embed_document ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cent_morceaux_font_quatre_appels_au_plus(requetes, monkeypatch):
    _morceaux(monkeypatch, 100)
    n = await EmbeddingService(OllamaService(base_url="http://ollama.test")).embed_document(
        str(uuid.uuid4()), "peu importe", _base())
    assert n == 100
    assert len(requetes["vues"]) <= 4
    assert {v["path"] for v in requetes["vues"]} == {"/api/embed"}
    assert sum(len(v["corps"]["input"]) for v in requetes["vues"]) == 100
    assert max(len(v["corps"]["input"]) for v in requetes["vues"]) <= TAILLE_PAQUET
    assert TAILLE_PAQUET == 32


@pytest.mark.asyncio
async def test_meme_resultat_en_base_qu_avec_les_appels_unitaires(requetes, monkeypatch):
    from utils.vectors import matryoshka_prefix

    textes = _morceaux(monkeypatch, 70)                      # 3 paquets : 32 + 32 + 6
    db = _base()
    doc = uuid.uuid4()
    await EmbeddingService(OllamaService(base_url="http://ollama.test")).embed_document(str(doc), "x", db)
    lignes = _lignes(db)
    assert [l.chunk_index for l in lignes] == list(range(70))           # ordre conservé
    assert [l.chunk_text for l in lignes] == textes
    assert all(l.document_id == doc for l in lignes)
    for i, l in enumerate(lignes):
        assert l.embedding == _vec(i) and len(l.embedding) == 4096       # le bon vecteur, au bon rang
        assert l.embedding_small == matryoshka_prefix(_vec(i)) and len(l.embedding_small) == 1024
        assert l.modele_embedding
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_petit_document_un_seul_appel(requetes, monkeypatch):
    _morceaux(monkeypatch, 5)
    await EmbeddingService(OllamaService(base_url="http://ollama.test")).embed_document(
        str(uuid.uuid4()), "x", _base())
    assert len(requetes["vues"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("statut", [404, 405])
async def test_repli_sur_l_appel_unitaire_si_api_embed_refuse(requetes, monkeypatch, statut):
    _morceaux(monkeypatch, 3)

    def reponse(req, corps):
        if req.url.path == "/api/embed":
            return httpx.Response(statut, content=b"404 page not found")
        return httpx.Response(200, json={"embedding": _vec(_num(corps["prompt"]))})

    requetes["reponse"] = reponse
    db = _base()
    n = await EmbeddingService(OllamaService(base_url="http://ollama.test")).embed_document(
        str(uuid.uuid4()), "x", db)
    assert n == 3
    chemins = [v["path"] for v in requetes["vues"]]
    assert chemins == ["/api/embed", "/api/embeddings", "/api/embeddings", "/api/embeddings"]
    assert [l.embedding for l in _lignes(db)] == [_vec(0), _vec(1), _vec(2)]
    assert [l.chunk_index for l in _lignes(db)] == [0, 1, 2]


def _ollama_lot(**kw):
    o = MagicMock()
    o.embed_many = AsyncMock(**kw)
    o.embed = AsyncMock(return_value=[0.5] * 8)
    return o


@pytest.mark.asyncio
@pytest.mark.parametrize("reponse", [
    [[0.1] * 8],                       # un vecteur de moins que de textes
    [[0.1] * 8] * 4,                   # un de trop
    [[0.1] * 8, [], [0.1] * 8],        # un vide au milieu
    [],                                # rien du tout
])
async def test_reponse_incoherente_est_un_echec_explicite(monkeypatch, reponse):
    _morceaux(monkeypatch, 3)
    ollama = MagicMock()
    # principal puis repli : les deux incohérents → échec explicite, rien n'est stocké
    ollama.embed_many = AsyncMock(return_value=reponse)
    db = _base()
    with pytest.raises(RuntimeError, match="Embedding vide"):
        await EmbeddingService(ollama).embed_document(str(uuid.uuid4()), "x", db)
    assert ollama.embed_many.await_count == 2        # le principal, puis le modèle de repli
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_paquet_incoherent_rattrape_par_le_modele_de_repli(monkeypatch):
    _morceaux(monkeypatch, 2)
    ollama = _ollama_lot(side_effect=[[[0.1] * 8], [[0.2] * 8, [0.3] * 8]])   # principal KO, repli OK
    db = _base()
    assert await EmbeddingService(ollama).embed_document(str(uuid.uuid4()), "x", db) == 2
    assert [l.embedding for l in _lignes(db)] == [[0.2] * 8, [0.3] * 8]
    modeles = [c.kwargs["model"] for c in ollama.embed_many.await_args_list]
    assert len(set(modeles)) == 2, "le 2ᵉ essai doit viser le modèle de repli"
    assert {l.modele_embedding for l in _lignes(db)} == {modeles[1]}


@pytest.mark.asyncio
async def test_erreur_du_paquet_bascule_le_reste_du_document_sur_le_repli(monkeypatch):
    """Même sémantique qu'avant, à la maille du paquet : après un échec, le modèle de repli sert
    jusqu'à la fin du document (les paquets déjà posés gardent le modèle principal)."""
    monkeypatch.setattr(embedding_service, "TAILLE_PAQUET", 2)
    _morceaux(monkeypatch, 5)                                    # paquets : 2 + 2 + 1
    ollama = _ollama_lot(side_effect=[
        [[1.0] * 8, [1.0] * 8],                                  # paquet 1 : principal OK
        RuntimeError("boum"),                                    # paquet 2 : principal KO
        [[2.0] * 8, [2.0] * 8],                                  #   … repli OK
        [[2.0] * 8],                                             # paquet 3 : directement le repli
    ])
    db = _base()
    await EmbeddingService(ollama).embed_document(str(uuid.uuid4()), "x", db)
    modeles = [c.kwargs["model"] for c in ollama.embed_many.await_args_list]
    assert modeles[0] == modeles[1] != modeles[2] == modeles[3]
    assert [l.chunk_index for l in _lignes(db)] == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_aucun_morceau_aucun_appel(monkeypatch):
    monkeypatch.setattr(embedding_service, "chunk_text", lambda t: [])
    ollama = _ollama_lot()
    assert await EmbeddingService(ollama).embed_document(str(uuid.uuid4()), "", _base()) == 0
    ollama.embed_many.assert_not_awaited()
    ollama.embed.assert_not_awaited()


# ─── charge sous échec : un paquet rejoué coûte 32 textes d'un coup ─────────────────────

@pytest.fixture
def sans_attente(monkeypatch):
    from tenacity import wait_none
    monkeypatch.setattr(OllamaService.embed_many.retry, "wait", wait_none())


@pytest.mark.asyncio
async def test_embed_many_erreur_serveur_deux_essais_au_plus(requetes, sans_attente):
    requetes["reponse"] = lambda request, corps: httpx.Response(500, json={"error": "boum"})
    with pytest.raises(Exception):
        await OllamaService(base_url="http://ollama.test").embed_many(["morceau fictif 0"], model="m")
    assert [v["path"] for v in requetes["vues"]] == ["/api/embed"] * 2


@pytest.mark.asyncio
async def test_embed_many_delai_depasse_aucun_nouvel_essai(requetes, sans_attente):
    """Délai dépassé = carte saturée : rejouer le paquet aggraverait la saturation."""
    def trop_long(request, corps):
        raise httpx.ReadTimeout("délai dépassé (fictif)", request=request)

    requetes["reponse"] = trop_long
    with pytest.raises(httpx.TimeoutException):
        await OllamaService(base_url="http://ollama.test").embed_many(["morceau fictif 0"], model="m")
    assert len(requetes["vues"]) == 1


@pytest.mark.asyncio
async def test_refus_de_api_embed_en_cours_de_document_ni_trou_ni_doublon(requetes, monkeypatch):
    """1ᵉʳ paquet accepté, 2ᵉ refusé : le reste part en unitaire, chaque morceau une seule fois."""
    n = TAILLE_PAQUET + 5
    _morceaux(monkeypatch, n)
    etat = {"lots": 0}

    def reponse(request, corps):
        if request.url.path == "/api/embed":
            etat["lots"] += 1
            if etat["lots"] > 1:
                return httpx.Response(405)
            return httpx.Response(200, json={"embeddings": [_vec(_num(t)) for t in corps["input"]]})
        return httpx.Response(200, json={"embedding": _vec(_num(corps["prompt"]))})

    requetes["reponse"] = reponse
    db = _base()
    svc = EmbeddingService(OllamaService(base_url="http://ollama.test"))
    assert await svc.embed_document(str(uuid.uuid4()), "texte fictif", db) == n
    lignes = [a.args[0] for a in db.add.call_args_list]
    assert [l.chunk_index for l in lignes] == list(range(n))
    assert [l.embedding[0] for l in lignes] == [float(i + 1) for i in range(n)]
