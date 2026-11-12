"""
Tests — origine des modèles (MATO / GECO) et refus côté serveur
================================================================
Plan docs/plan-liste-modeles.md, étape 1 :
  - `GET /api/system/models` : chaque modèle Ollama porte `origine: "MATO"` + `selectionnable: true` ;
    la liste GECO (lecture seule, `modeles_externes_url`) est rendue À PART (`externes`) ;
  - une liste GECO illisible ne fait jamais échouer la route ;
  - toute génération avec un modèle EXPLICITE absent d'Ollama (ou connu de GECO) → HTTP 400,
    sans qu'Ollama génère quoi que ce soit.

Aucun appel réseau réel : Ollama et la liste GECO sont simulés. Données fictives.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

URL_GECO = "http://geco.test/v1/models"
INSTALLES = ["llama3.1:latest", "ministral-3:14b"]


# ─── Outils de simulation ─────────────────────────────────────────────────────

def _faux_client_httpx(reponse=None, exception=None, appels=None, attente: float = 0.0):
    """Remplace `httpx.AsyncClient` du service : un vrai client sur un transport simulé."""
    vrai = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        if appels is not None:
            appels.append(request)
        if exception:
            raise exception
        return reponse

    async def handler_lent(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(attente)
        return handler(request)

    def fabrique(*args, **kwargs):
        kwargs.pop("transport", None)
        transport = httpx.MockTransport(handler_lent if attente else handler)
        return vrai(*args, transport=transport, **kwargs)

    return patch("services.modeles_externes.httpx.AsyncClient", side_effect=fabrique)


def _json(data, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


def _regler_url(url: str = URL_GECO) -> None:
    from services import runtime_config
    runtime_config._overrides["modeles_externes_url"] = url


def _ollama_fictif(installes=None, panne: bool = False) -> MagicMock:
    instance = MagicMock()
    if panne:
        instance.list_models = AsyncMock(side_effect=ConnectionError("Ollama down"))
    else:
        instance.list_models = AsyncMock(return_value=list(installes or INSTALLES))
    return instance


async def _exiger(demande):
    """Résolution interactive (mode local, sans confirmation) : lève si le modèle est refusé."""
    from services import modeles_externes
    return await modeles_externes.resoudre_modele_interactif(demande, "rapport")


@pytest_asyncio.fixture
async def client(db_session):
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


# ─── Service : lecture de la liste GECO ───────────────────────────────────────

class TestLireExternes:
    @pytest.mark.asyncio
    async def test_url_vide_aucun_appel_sortant(self):
        from services import modeles_externes
        appels: list = []
        with _faux_client_httpx(_json({"data": [{"id": "x"}]}), appels=appels) as fabrique:
            etat, liste = await modeles_externes.lire_externes()
        assert (etat, liste) == ("non_configure", [])
        assert appels == []
        fabrique.assert_not_called()   # le client HTTP n'est même pas construit

    @pytest.mark.asyncio
    async def test_liste_lue_triee_sans_donnee_matotheque(self):
        from services import modeles_externes
        _regler_url()
        appels: list = []
        reponse = _json({"data": [{"id": "zeta-1"}, {"id": "Alpha-2"}, {"id": "beta-3"}]})
        with _faux_client_httpx(reponse, appels=appels):
            etat, liste = await modeles_externes.lire_externes()
        assert etat == "disponible"
        assert [m["name"] for m in liste] == ["Alpha-2", "beta-3", "zeta-1"]   # insensible à la casse
        assert all(m["origine"] == "GECO" and m["selectionnable"] is False for m in liste)
        # Un seul GET, sans corps ; seuls les en-têtes de projet partent.
        assert len(appels) == 1
        assert appels[0].method == "GET" and appels[0].content == b""
        assert "X-AI-Project" in appels[0].headers

    @pytest.mark.asyncio
    async def test_liste_vide_est_disponible(self):
        from services import modeles_externes
        _regler_url()
        with _faux_client_httpx(_json({"data": []})):
            assert await modeles_externes.lire_externes() == ("disponible", [])

    @pytest.mark.asyncio
    async def test_entrees_invalides_ignorees_et_doublons_retires(self):
        from services import modeles_externes
        _regler_url()
        data = {"data": [{"id": "a"}, {"id": "a"}, {"id": 12}, {"nom": "b"}, "c", None, {"id": "  "}]}
        with _faux_client_httpx(_json(data)):
            etat, liste = await modeles_externes.lire_externes()
        assert etat == "disponible"
        assert [m["name"] for m in liste] == ["a"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("reponse", [
        httpx.Response(200, content=b"<html>pas du json</html>"),
        _json(["a", "b"]),
        _json({"data": "pas une liste"}),
        _json({"autre": []}),
        _json({"data": []}, status=500),
        _json({}, status=404),
    ])
    async def test_reponse_malformee_ou_erreur_http_injoignable(self, reponse):
        from services import modeles_externes
        _regler_url()
        with _faux_client_httpx(reponse):
            assert await modeles_externes.lire_externes() == ("injoignable", [])

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exc", [
        httpx.ConnectError("refusé"), httpx.ReadTimeout("lent"), OSError("réseau"),
    ])
    async def test_panne_reseau_injoignable(self, exc):
        from services import modeles_externes
        _regler_url()
        with _faux_client_httpx(exception=exc):
            assert await modeles_externes.lire_externes() == ("injoignable", [])

    @pytest.mark.asyncio
    async def test_delai_total_borne(self):
        """Un serveur qui répond trop tard → injoignable, sans attendre sa réponse."""
        from services import modeles_externes
        _regler_url()
        with patch.object(modeles_externes, "DELAI_S", 0.05), \
                _faux_client_httpx(_json({"data": [{"id": "x"}]}), attente=2.0):
            debut = asyncio.get_event_loop().time()
            resultat = await modeles_externes.lire_externes()
            duree = asyncio.get_event_loop().time() - debut
        assert resultat == ("injoignable", [])
        assert duree < 1.0

    @pytest.mark.asyncio
    async def test_url_sans_schema_http_refusee(self):
        from services import modeles_externes
        _regler_url("file:///etc/passwd")
        appels: list = []
        with _faux_client_httpx(_json({"data": [{"id": "x"}]}), appels=appels):
            assert await modeles_externes.lire_externes() == ("injoignable", [])
        assert appels == []

    def test_reglage_vide_par_defaut(self):
        from services import runtime_config
        assert runtime_config.effective("modeles_externes_url") == ""


# ─── GET /api/system/models ───────────────────────────────────────────────────

def _detailles(noms):
    return [{"name": n, "size": 1000, "digest": "d", "famille": "llama", "parametres": "8B"} for n in noms]


async def _lister(client, **patches):
    instance = MagicMock()
    instance.list_models_detailed = AsyncMock(return_value=_detailles(INSTALLES))
    async with client as c:
        with patch("routers.system.OllamaService", return_value=instance):
            return await c.get("/api/system/models")


class TestRouteModeles:
    @pytest.mark.asyncio
    async def test_origine_mato_et_selectionnable(self, client):
        resp = await _lister(client)
        assert resp.status_code == 200
        data = resp.json()
        assert [m["name"] for m in data["models"]] == INSTALLES
        assert all(m["origine"] == "MATO" and m["selectionnable"] is True for m in data["models"])

    @pytest.mark.asyncio
    async def test_non_configure_par_defaut(self, client):
        appels: list = []
        with _faux_client_httpx(_json({"data": [{"id": "x"}]}), appels=appels):
            data = (await _lister(client)).json()
        assert data["externes_etat"] == "non_configure"
        assert data["externes"] == []
        assert appels == []

    @pytest.mark.asyncio
    async def test_externes_separes_de_models(self, client):
        _regler_url()
        with _faux_client_httpx(_json({"data": [{"id": "gpt-geco-b"}, {"id": "gpt-geco-a"}]})):
            data = (await _lister(client)).json()
        assert data["externes_etat"] == "disponible"
        assert data["externes"] == [
            {"name": "gpt-geco-a", "origine": "GECO", "embedding": False, "selectionnable": False},
            {"name": "gpt-geco-b", "origine": "GECO", "embedding": False, "selectionnable": False},
        ]
        # Jamais mêlés aux modèles installés.
        assert [m["name"] for m in data["models"]] == INSTALLES

    @pytest.mark.asyncio
    async def test_liste_geco_injoignable_ne_fait_pas_echouer(self, client):
        _regler_url()
        with _faux_client_httpx(exception=httpx.ConnectError("refusé")):
            resp = await _lister(client)
        assert resp.status_code == 200
        data = resp.json()
        assert data["externes_etat"] == "injoignable" and data["externes"] == []
        assert len(data["models"]) == 2

    @pytest.mark.asyncio
    async def test_liste_geco_malformee_ne_fait_pas_echouer(self, client):
        _regler_url()
        with _faux_client_httpx(httpx.Response(200, content=b"{pas json")):
            resp = await _lister(client)
        assert resp.status_code == 200
        assert resp.json()["externes_etat"] == "injoignable"

    @pytest.mark.asyncio
    async def test_reglage_accepte_par_la_config(self, client):
        async with client as c:
            ok = await c.put("/api/system/config", json={"modeles_externes_url": URL_GECO})
            ko = await c.put("/api/system/config", json={"modeles_externes_url": "ftp://x/y"})
        assert ok.status_code == 200 and "modeles_externes_url" in ok.json()["mis_a_jour"]
        assert ko.status_code == 422


# ─── Garde-fou : une seule fonction ───────────────────────────────────────────

class TestGardeFou:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("vide", [None, "", "   "])
    async def test_auto_passe_sans_appel(self, vide):
        from services import modeles_externes
        with patch("services.modeles_externes.OllamaService") as ollama:
            await _exiger(vide)
        ollama.assert_not_called()

    @pytest.mark.asyncio
    async def test_modele_installe_accepte(self):
        from services import modeles_externes
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif()):
            await _exiger("ministral-3:14b")

    @pytest.mark.asyncio
    async def test_modele_inconnu_refuse_400_en_francais(self):
        from fastapi import HTTPException
        from services import modeles_externes
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif()):
            with pytest.raises(HTTPException) as exc:
                await _exiger("modele-fantome:7b")
        assert exc.value.status_code == 400
        assert "modele-fantome:7b" in exc.value.detail and "installé" in exc.value.detail

    @pytest.mark.asyncio
    async def test_mode_local_ne_lit_jamais_la_liste_geco(self):
        """Étape 5a : bouton sur LOCAL = aucun accès réseau vers la liste GECO ; un nom absent = « non installé »."""
        from fastapi import HTTPException
        _regler_url()
        appels: list = []
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif()), \
                _faux_client_httpx(_json({"data": [{"id": "gpt-geco"}]}), appels=appels):
            with pytest.raises(HTTPException) as exc:
                await _exiger("gpt-geco")
        assert exc.value.status_code == 400 and "installé" in exc.value.detail
        assert appels == []

    @pytest.mark.asyncio
    async def test_ollama_injoignable_laisse_passer_un_modele_inconnu(self):
        """Pas de faux « modèle inconnu » : l'erreur « IA injoignable » existante prendra le relais."""
        from services import modeles_externes
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif(panne=True)):
            await _exiger("modele-fantome:7b")

    @pytest.mark.asyncio
    async def test_tout_en_panne_refuse_un_nom_geco(self, monkeypatch):
        """
        Étape 5a : Ollama ET la liste GECO en panne → on ne sait rien d'un nom `geco/…` ; une sortie est
        possible, donc le doute REFUSE (503). (Avant l'étape 5a : on laissait passer.)
        """
        from fastapi import HTTPException
        from services import audit, modeles_externes
        monkeypatch.setattr(audit, "role_courant", lambda: "admin")   # l'IA GECO est réservée à l'administrateur
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif(panne=True)),                 patch("services.modeles_externes.lire_externes",
                      AsyncMock(return_value=(modeles_externes.ETAT_INJOIGNABLE, []))):
            with pytest.raises(HTTPException) as exc:
                await _exiger("geco/gpt-geco")
        assert exc.value.status_code == 400   # bouton « IA GECO » désactivé : refus, sans même lire la liste
        from services import runtime_config
        runtime_config._overrides["ia_destination"] = "geco"
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif(panne=True)),                 patch("services.modeles_externes.lire_externes",
                      AsyncMock(return_value=(modeles_externes.ETAT_INJOIGNABLE, []))):
            with pytest.raises(HTTPException) as exc:
                await _exiger("geco/gpt-geco")
        assert exc.value.status_code == 503   # bouton activé mais rien de vérifiable : le doute refuse

    @pytest.mark.asyncio
    async def test_tout_en_panne_laisse_passer_un_nom_simple_en_mode_local(self):
        """Mode local, nom sans préfixe : aucune sortie possible → l'erreur « IA injoignable » de la route prend le relais."""
        from services import modeles_externes
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif(panne=True)),                 patch("services.modeles_externes.lire_externes",
                      AsyncMock(return_value=(modeles_externes.ETAT_INJOIGNABLE, []))):
            resolu = await _exiger("modele-fantome:7b")
        assert resolu.nom == "modele-fantome:7b" and not resolu.est_geco

    @pytest.mark.parametrize("url, attendu", [
        ("http://192.168.42.105:21450/v1/models", True),
        ("https://hote/liste", True),
        ("http://u:p@hote/liste", False),
        ("http://hote/liste?key=secret", False),
        ("file:///etc/passwd", False),
        ("ftp://hote/x", False),
        ("http://", False),
        ("", False),
    ])
    def test_url_acceptable(self, url, attendu):
        from services import modeles_externes
        assert modeles_externes.url_acceptable(url) is attendu

    @pytest.mark.asyncio
    async def test_ollama_muet_ne_suspend_pas_la_generation(self, monkeypatch):
        """Ollama accepte la connexion sans répondre : le contrôle rend la main, il n'attend pas 30 min."""
        import asyncio

        from services import modeles_externes

        async def muet():
            await asyncio.sleep(30)

        instance = MagicMock()
        instance.list_models = muet
        monkeypatch.setattr(modeles_externes, "DELAI_CONTROLE_S", 0.05)
        with patch("services.modeles_externes.OllamaService", return_value=instance):
            await asyncio.wait_for(_exiger("modele-fantome:7b"), timeout=2)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("installe, demande", [
        ("llama3.1:latest", "llama3.1"),
        ("llama3.1", "llama3.1:latest"),
        ("hf.co/org/modele:latest", "hf.co/org/modele"),
    ])
    async def test_nom_sans_tag_vaut_latest(self, installe, demande):
        """Ollama sert `nom` comme `nom:latest` : le refuser serait un faux « non installé »."""
        from services import modeles_externes
        with patch("services.modeles_externes.OllamaService",
                   return_value=_ollama_fictif(installes=[installe])):
            await _exiger(demande)

    @pytest.mark.asyncio
    async def test_un_autre_tag_reste_refuse(self):
        from fastapi import HTTPException

        from services import modeles_externes
        with patch("services.modeles_externes.OllamaService",
                   return_value=_ollama_fictif(installes=["llama3.1:latest"])):
            with pytest.raises(HTTPException) as exc:
                await _exiger("llama3.1:70b")
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_ollama_injoignable_mode_local_ne_lit_pas_la_liste_geco(self):
        _regler_url()
        appels: list = []
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif(panne=True)), \
                _faux_client_httpx(_json({"data": [{"id": "gpt-geco"}]}), appels=appels):
            resolu = await _exiger("gpt-geco")
        assert not resolu.est_geco and appels == []


# ─── Refus sur chaque route de génération ─────────────────────────────────────

# (nom, méthode, url, corps) — `{rid}` remplacé pour l'analyse d'un regroupement.
ROUTES = [
    ("rapport", "/api/generate/report", {"document_ids": [], "prompt": "bilan"}),
    ("template", "/api/generate/fill-template", {"document_ids": ["a"], "template_id": "t"}),
    ("chat", "/api/generate/chat", {"messages": [{"role": "user", "content": "bonjour"}]}),
    ("criteres", "/api/generate/compare/criteres", {"document_ids": ["a"]}),
    ("comparatif", "/api/generate/compare",
     {"groupes": [{"nom": "A", "document_ids": ["a"]}, {"nom": "B", "document_ids": ["b"]}],
      "colonnes": ["Prix"]}),
    ("regroupement", "/api/regroupements/{rid}/analyser", {}),
    ("assistant_pieces", "/api/assistant/pieces", {"besoin": "dossier de prêt"}),
    ("assistant_question", "/api/assistant/question", {"question": "quel est le total ?"}),
    ("relecture", "/api/prompts/relire", {"texte": "fais un résumé"}),
    ("presentation", "/api/presentations", {"document_ids": ["a", "b"]}),
]


@pytest.fixture
def espions():
    """Aucune génération ni mise en file ne doit partir quand le modèle est refusé."""
    generation = MagicMock()
    generation.generate = AsyncMock(return_value="{}")
    generation.chat_stream = MagicMock(side_effect=AssertionError("génération lancée"))
    with patch("services.job_worker.enqueue", new=AsyncMock(return_value="job-1")) as enqueue, \
            patch("routers.generate.OllamaService", return_value=generation), \
            patch("routers.compare.OllamaService", return_value=generation), \
            patch("routers.assistant.OllamaService", return_value=generation), \
            patch("services.relecture_prompt.relire_prompt", new=AsyncMock(return_value=None)) as relire, \
            patch("services.qa_service.repondre", new=AsyncMock(return_value={})) as repondre:
        yield {"enqueue": enqueue, "generation": generation, "relire": relire, "repondre": repondre}


async def _appeler(client, db_session, url: str, corps: dict, modele: str | None):
    if "{rid}" in url:
        from models.regroupement import Regroupement
        rg = Regroupement(nom="Groupe fictif", document_ids=["doc-fictif"])
        db_session.add(rg)
        await db_session.commit()
        url = url.replace("{rid}", str(rg.id))
    corps = dict(corps)
    if modele is not None:
        corps["model"] = modele
    async with client as c:
        return await c.post(url, json=corps)


def _aucune_generation(espions) -> None:
    espions["enqueue"].assert_not_called()
    espions["generation"].generate.assert_not_called()
    espions["generation"].chat_stream.assert_not_called()
    espions["relire"].assert_not_called()
    espions["repondre"].assert_not_called()


class TestRefusParRoute:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("nom,url,corps", ROUTES, ids=[r[0] for r in ROUTES])
    async def test_modele_geco_refuse(self, client, db_session, espions, nom, url, corps):
        _regler_url()
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif()), \
                _faux_client_httpx(_json({"data": [{"id": "gpt-geco"}]})):
            resp = await _appeler(client, db_session, url, corps, "gpt-geco")
        assert resp.status_code == 400, resp.text
        assert "gpt-geco" in resp.json()["detail"]
        _aucune_generation(espions)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nom,url,corps", ROUTES, ids=[r[0] for r in ROUTES])
    async def test_modele_inconnu_refuse(self, client, db_session, espions, nom, url, corps):
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif()):
            resp = await _appeler(client, db_session, url, corps, "modele-fantome:7b")
        assert resp.status_code == 400, resp.text
        assert "modele-fantome:7b" in resp.json()["detail"]
        _aucune_generation(espions)

    @pytest.mark.asyncio
    async def test_modele_installe_non_refuse(self, client, db_session, espions):
        """Contrôle de non-régression : un modèle installé passe le garde-fou (ici : mise en file)."""
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif()), \
                patch("routers.generate._resoudre_modele", new=AsyncMock(return_value="ministral-3:14b")):
            resp = await _appeler(client, db_session, "/api/presentations",
                                  {"document_ids": ["a", "b"]}, "ministral-3:14b")
        assert resp.status_code == 200
        espions["enqueue"].assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_inchange_sans_appel_au_garde_fou(self, client, db_session, espions):
        """Modèle vide = « Auto » : le contrôle ne touche pas Ollama."""
        with patch("services.modeles_externes.OllamaService") as ollama:
            resp = await _appeler(client, db_session, "/api/presentations", {"document_ids": ["a", "b"]}, None)
        assert resp.status_code == 200
        ollama.assert_not_called()
