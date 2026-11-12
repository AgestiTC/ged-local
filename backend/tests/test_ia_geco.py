"""
Tests — IA GECO (étape 5a du plan docs/plan-liste-modeles.md), BACKEND
=======================================================================
Règle d'or : AUCUN envoi vers GECO sans que TOUT soit vrai, à chaque envoi — acteur administrateur
(session, authentification active), bouton « IA GECO » sur `geco` EN BASE, marque d'envoi ouverte par
une route interactive / le worker, plafond respecté, ligne de journal écrite AVANT l'envoi.

Couvre : résolution du modèle, envoi `/v1/chat/completions` (SSE, erreurs, délais), barrières, journal
fail-closed, réglages (422/403), recontrôle du worker, routes de lecture, et des tests de BOUT EN BOUT
(vraie route FastAPI -> vrai `OllamaService` -> espion de TRANSPORT httpx, sans mock du service).

AUCUN appel réseau réel. Données fictives.
"""

import ast
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

URL_LISTE = "http://aiguilleur.test/modeles/externes"
BASE_AIGUILLEUR = "http://aiguilleur.test:21450"
GECO = "geco/modele-fictif"
EMBED = "geco/text-embedding-nomic-embed-text-v1.5"
INSTALLES = ["llama3.1:latest", "ministral-3:14b"]
SECRET = "texte-secret-fictif-a-ne-jamais-journaliser"
CHEMIN_GECO = "/v1/chat/completions"


# ─── Outils ───────────────────────────────────────────────────────────────────

def _json(data, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


def _liste_geco(*noms: str) -> httpx.Response:
    return _json({"object": "list", "data": [{"id": n, "origine": "GECO"} for n in noms]})


def _regler(**reglages: str) -> None:
    from services import runtime_config
    runtime_config._overrides.update(reglages)


def _faux_client(handler):
    """Remplace `httpx.AsyncClient` (global) par un client sur transport simulé ; `handler(request) -> Response`."""
    vrai = httpx.AsyncClient

    def fabrique(*args, **kwargs):
        kwargs.pop("transport", None)
        return vrai(*args, transport=httpx.MockTransport(handler), **kwargs)

    return patch("services.ollama_service.httpx.AsyncClient", side_effect=fabrique)


def _faux_liste(reponse=None, exception=None):
    def handler(request):
        if exception:
            raise exception
        return reponse
    return _faux_client(handler)


def _ollama_fictif(installes=None, panne: bool = False) -> MagicMock:
    instance = MagicMock()
    if panne:
        instance.list_models = AsyncMock(side_effect=ConnectionError("Ollama down"))
    else:
        instance.list_models = AsyncMock(return_value=list(installes or INSTALLES))
    return instance


async def _morceaux(*parts: bytes, pause: float = 0.0):
    import asyncio
    for p in parts:
        if pause:
            await asyncio.sleep(pause)
        yield p


def _sse_octets(*parts: bytes) -> httpx.Response:
    return httpx.Response(200, content=_morceaux(*parts), headers={"content-type": "text/event-stream"})


def _ligne(texte=None, **extra) -> bytes:
    choix = {"delta": ({"content": texte} if texte is not None else {})}
    choix.update(extra)
    return ("data: " + json.dumps({"choices": [choix]}, ensure_ascii=False) + "\n\n").encode()


def _reponse_chat(texte="Bonjour") -> httpx.Response:
    return _json({"choices": [{"message": {"role": "assistant", "content": texte}}]})


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def acteur_admin(monkeypatch):
    from services import audit
    monkeypatch.setattr(audit, "role_courant", lambda: "admin")
    monkeypatch.setattr(audit, "auteur_courant", lambda: "admin-fictif")


@pytest.fixture
def acteur_utilisateur(monkeypatch):
    from services import audit
    monkeypatch.setattr(audit, "role_courant", lambda: "utilisateur")
    monkeypatch.setattr(audit, "auteur_courant", lambda: "marie-fictive")


@pytest.fixture
def acteur_jeton(monkeypatch):
    from services import audit
    monkeypatch.setattr(audit, "role_courant", lambda: "jeton")
    monkeypatch.setattr(audit, "auteur_courant", lambda: "jeton:n8n-fictif")


@pytest.fixture
def liste_ok():
    """Liste GECO disponible : deux modèles de texte, un nom SANS préfixe, un modèle d'embeddings."""
    _regler(modeles_externes_url=URL_LISTE)
    with _faux_liste(_liste_geco(GECO, "geco/autre", "sans-prefixe", EMBED)):
        yield


@pytest.fixture
def mode_geco(monkeypatch, acteur_admin):
    """Bouton « IA GECO » activé (cache ET base simulée), administrateur, `geco_modele` choisi."""
    _regler(ia_destination="geco", geco_modele=GECO)
    monkeypatch.setattr("services.ollama_service.destination_en_base", AsyncMock(return_value="geco"))
    # Authentification active et non suspendue, relue en base par les deux barrières (envoi, worker).
    monkeypatch.setattr("services.ollama_service.authentification_en_base", AsyncMock(return_value=True))
    monkeypatch.setattr("services.modeles_externes.authentification_en_base", AsyncMock(return_value=True))


@pytest.fixture
def journal(monkeypatch):
    """Remplace `audit.emit` ET `audit.emit_strict` : enregistre sans toucher la base."""
    from services import audit
    evenements: list[dict] = []

    async def faux(action, statut, **kw):
        evenements.append({"action": action, "statut": statut, **kw})

    monkeypatch.setattr(audit, "emit", faux)
    monkeypatch.setattr(audit, "emit_strict", faux)
    return evenements


@pytest_asyncio.fixture
async def appli(db_session):
    """Branche la base de test sur l'application ; les appels se font par `_post` / `_put` (client neuf)."""
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield app
    app.dependency_overrides.clear()


async def _post(appli, url, **corps):
    async with AsyncClient(transport=ASGITransport(app=appli), base_url="http://test") as c:
        return await c.post(url, json=corps)


async def _put(appli, **corps):
    async with AsyncClient(transport=ASGITransport(app=appli), base_url="http://test") as c:
        return await c.put("/api/system/config", json=corps)


async def _get(appli, url):
    async with AsyncClient(transport=ASGITransport(app=appli), base_url="http://test") as c:
        return await c.get(url)


@pytest.fixture
def ecriture_geco_ok(monkeypatch):
    """Simule « authentification active + session administrateur » pour l'écriture des réglages GECO."""
    monkeypatch.setattr("routers.system._ecriture_geco_autorisee", lambda request: True)


class Reseau:
    """Espion de TRANSPORT : enregistre chaque requête sortante (Ollama, liste GECO, AIGUILLEUR) et répond."""

    def __init__(self):
        self.requetes: list[httpx.Request] = []
        self.surcharge = None      # fonction(request) -> Response | None, consultée en premier

    @property
    def geco(self) -> list[httpx.Request]:
        return [r for r in self.requetes if r.url.path == CHEMIN_GECO]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requetes.append(request)
        if self.surcharge is not None and (reponse := self.surcharge(request)) is not None:
            return reponse
        chemin = request.url.path
        if chemin == "/modeles/externes":
            return _liste_geco(GECO, "geco/autre", EMBED)
        if chemin == "/api/tags":
            return _json({"models": [{"name": n, "size": 1, "details": {}} for n in INSTALLES]})
        if chemin == "/api/generate":
            corps = json.loads(request.content or b"{}")
            if corps.get("stream"):
                return httpx.Response(200, content=_morceaux(b'{"response": "{}", "done": true}\n'))
            return _json({"response": "{}"})
        if chemin == "/api/chat":
            return httpx.Response(200, content=_morceaux(
                b'{"message": {"content": "local"}, "done": false}\n{"done": true}\n'))
        if chemin == CHEMIN_GECO:
            if json.loads(request.content).get("stream"):
                return _sse_octets(_ligne("Réponse GECO"), b"data: [DONE]\n\n")
            return _reponse_chat("{}")
        return _json({}, 404)


@pytest.fixture
def reseau():
    espion = Reseau()
    _regler(modeles_externes_url=URL_LISTE)
    with _faux_client(espion.handler):
        yield espion


@pytest_asyncio.fixture
async def base_geco(db_session, monkeypatch):
    """
    Base de test réelle : `ia_destination` et réglages GECO ÉCRITS EN BASE (c'est là que la barrière lit),
    journal réel (table `audit_events`). Rend `ecrire(destination)` et `evenements()`.
    """
    from models.audit import AuditEvent
    from models.config import Config

    fabrique = async_sessionmaker(db_session.bind, expire_on_commit=False)
    for cible in ("services.ollama_service.AsyncSessionLocal", "services.audit.AsyncSessionLocal",
                  "services.job_worker.AsyncSessionLocal", "services.rapport_jobs.AsyncSessionLocal",
                  "services.compare_jobs.AsyncSessionLocal", "services.regroupement_jobs.AsyncSessionLocal"):
        monkeypatch.setattr(cible, fabrique)

    async def ecrire(destination: str, auth: str | None = "true", suspension: str | None = None):
        """`auth` : valeur de `auth_active` en base (None = ligne absente) ; `suspension` : échéance ISO."""
        from services.acces import CLE_SUSPENSION
        async with fabrique() as db:
            for cle, valeur in (("ia_destination", destination), ("geco_modele", GECO),
                                ("modeles_externes_url", URL_LISTE), ("auth_active", auth),
                                (CLE_SUSPENSION, suspension)):
                ligne = await db.get(Config, cle)
                if valeur is None:
                    if ligne is not None:
                        await db.delete(ligne)
                elif ligne is None:
                    db.add(Config(cle=cle, valeur=valeur))
                else:
                    ligne.valeur = valeur
            await db.commit()
        _regler(ia_destination=destination, geco_modele=GECO, modeles_externes_url=URL_LISTE)

    async def evenements(action="sortie_geco"):
        async with fabrique() as db:
            return list((await db.execute(select(AuditEvent).where(AuditEvent.action == action))).scalars())

    return SimpleNamespace(ecrire=ecrire, evenements=evenements, fabrique=fabrique)


async def _resoudre(demande, usage="rapport"):
    from services import modeles_externes
    return await modeles_externes.resoudre_modele_interactif(demande, usage)


async def _generer(prompt="Q", modele=GECO, origine="/api/test", base=BASE_AIGUILLEUR, **kw):
    from services.ollama_service import OllamaService, sortie_geco_autorisee
    with sortie_geco_autorisee(origine):
        return await OllamaService(base_url=base).generate(prompt, model=modele, **kw)


async def _flux(methode="generate_stream", modele=GECO, origine="/api/test", **kw):
    from services.ollama_service import OllamaService, sortie_geco_autorisee
    service = OllamaService(base_url=BASE_AIGUILLEUR)
    with sortie_geco_autorisee(origine):
        if methode == "chat_stream":
            return [m async for m in service.chat_stream([{"role": "user", "content": "Q"}], model=modele, **kw)]
        return [m async for m in service.generate_stream("Q", model=modele, **kw)]


# ─── Résolution : « Auto » ────────────────────────────────────────────────────

class TestResolutionAuto:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("vide", [None, "", "   "])
    async def test_auto_local_routage_habituel_sans_appel(self, vide):
        from services import runtime_config
        _regler(usage_models=json.dumps({"rapport": "ministral-3:14b"}))
        with patch("services.modeles_externes.OllamaService") as ollama, \
                patch("services.modeles_externes.lire_externes", new=AsyncMock()) as liste:
            r = await _resoudre(vide, "rapport")
        assert (r.nom, r.origine, r.explicite) == (runtime_config.model_for("rapport"), "MATO", False)
        ollama.assert_not_called()
        liste.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_mode_geco_prend_geco_modele(self, liste_ok, mode_geco):
        r = await _resoudre(None)
        assert (r.nom, r.origine, r.explicite) == (GECO, "GECO", False)

    @pytest.mark.asyncio
    async def test_auto_mode_geco_sans_modele_choisi_503(self, liste_ok, mode_geco):
        _regler(geco_modele="")
        from services import runtime_config
        runtime_config._overrides.pop("geco_modele", None)
        with pytest.raises(HTTPException) as exc:
            await _resoudre("")
        assert exc.value.status_code == 503 and "aucun modèle GECO" in exc.value.detail

    @pytest.mark.asyncio
    async def test_auto_mode_geco_liste_muette_503(self, mode_geco):
        from services import modeles_externes
        with patch("services.modeles_externes.lire_externes",
                   AsyncMock(return_value=(modeles_externes.ETAT_INJOIGNABLE, []))):
            with pytest.raises(HTTPException) as exc:
                await _resoudre(None)
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    @pytest.mark.parametrize("choisi", ["geco/disparu", EMBED])
    async def test_auto_mode_geco_modele_inutilisable_503(self, liste_ok, mode_geco, choisi):
        _regler(geco_modele=choisi)
        with pytest.raises(HTTPException) as exc:
            await _resoudre(None)
        assert exc.value.status_code == 503 and "n'est plus utilisable" in exc.value.detail

    @pytest.mark.asyncio
    async def test_auto_mode_local_ne_sort_jamais_meme_avec_geco_modele(self, liste_ok, acteur_admin):
        _regler(geco_modele=GECO)
        r = await _resoudre(None)
        assert r.origine == "MATO" and not r.nom.startswith("geco/")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("reglage", [{"default_model": GECO}, {"usage_models": json.dumps({"rapport": GECO})}])
    async def test_auto_local_modele_geco_force_par_la_configuration_refuse_400(self, reglage):
        """Ligne `default_model` / `usage_models` écrite directement en base : « Auto » ne part jamais vers GECO."""
        _regler(**reglage)
        with pytest.raises(HTTPException) as exc:
            await _resoudre(None, "rapport")
        assert exc.value.status_code == 400 and "modèle GECO" in exc.value.detail

    @pytest.mark.parametrize("valeur", ["", "local", "LOCAL", "n'importe quoi", "geco "])
    def test_destination_autre_que_geco_vaut_local(self, valeur):
        from services import modeles_externes
        if valeur:
            _regler(ia_destination=valeur)
        assert modeles_externes.destination_ia() == ("geco" if valeur.strip().lower() == "geco" else "local")


# ─── Résolution : modèle explicite ────────────────────────────────────────────

class TestResolutionExplicite:
    @pytest.mark.asyncio
    async def test_local_installe(self):
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif()):
            r = await _resoudre("ministral-3:14b")
        assert (r.nom, r.origine, r.explicite) == ("ministral-3:14b", "MATO", True)

    @pytest.mark.asyncio
    async def test_geco_explicite_refuse_en_mode_local_sans_rien_lire(self, liste_ok, acteur_admin):
        with patch("services.modeles_externes.lire_externes", new=AsyncMock()) as liste, \
                patch("services.modeles_externes.OllamaService") as ollama:
            with pytest.raises(HTTPException) as exc:
                await _resoudre(GECO)
        assert exc.value.status_code == 400
        assert "Les modèles GECO ne sont utilisables que lorsque le bouton « IA GECO » est activé" in exc.value.detail
        liste.assert_not_called()
        ollama.assert_not_called()

    @pytest.mark.asyncio
    async def test_geco_explicite_accepte_en_mode_geco(self, liste_ok, mode_geco):
        r = await _resoudre("geco/autre")
        assert (r.nom, r.origine, r.est_geco, r.explicite) == ("geco/autre", "GECO", True, True)

    @pytest.mark.asyncio
    async def test_geco_explicite_n_interroge_pas_ollama(self, liste_ok, mode_geco):
        with patch("services.modeles_externes.OllamaService") as ollama:
            await _resoudre(GECO)
        ollama.assert_not_called()

    @pytest.mark.asyncio
    async def test_geco_embeddings_refuse_400(self, liste_ok, mode_geco):
        with pytest.raises(HTTPException) as exc:
            await _resoudre(EMBED)
        assert exc.value.status_code == 400 and "embeddings" in exc.value.detail

    @pytest.mark.asyncio
    async def test_mode_geco_modele_local_explicite_reste_local(self, liste_ok, mode_geco):
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif()):
            r = await _resoudre("llama3.1")
        assert (r.nom, r.origine) == ("llama3.1", "MATO")

    @pytest.mark.asyncio
    async def test_mode_geco_lit_ollama_et_la_liste_geco_en_parallele(self, mode_geco):
        """Les deux lectures sont lancées ensemble (asyncio.gather), pas l'une après l'autre."""
        import asyncio
        ordre: list[str] = []

        async def installes():
            ordre.append("ollama-debut")
            await asyncio.sleep(0.05)
            ordre.append("ollama-fin")
            return INSTALLES

        async def externes():
            ordre.append("liste-debut")
            await asyncio.sleep(0.05)
            ordre.append("liste-fin")
            return "disponible", []

        with patch("services.modeles_externes._installes", installes), \
                patch("services.modeles_externes.lire_externes", externes):
            await _resoudre("llama3.1")
        assert ordre[:2] == ["ollama-debut", "liste-debut"]

    @pytest.mark.asyncio
    async def test_nom_inconnu_400(self, liste_ok):
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif()):
            with pytest.raises(HTTPException) as exc:
                await _resoudre("modele-fantome:7b")
        assert exc.value.status_code == 400 and "n'est pas installé" in exc.value.detail

    @pytest.mark.asyncio
    async def test_nom_geco_absent_de_la_liste_message_dedie_400(self, liste_ok, mode_geco):
        with pytest.raises(HTTPException) as exc:
            await _resoudre("geco/inconnu")
        assert exc.value.status_code == 400 and "n'est pas dans la liste des modèles GECO" in exc.value.detail
        assert "installé sur Ollama" not in exc.value.detail

    @pytest.mark.asyncio
    async def test_prefixe_reserve_meme_si_installe_sur_ollama(self, liste_ok, mode_geco):
        with patch("services.modeles_externes.OllamaService",
                   return_value=_ollama_fictif(installes=["geco/trompeur:latest"])):
            with pytest.raises(HTTPException) as exc:
                await _resoudre("geco/trompeur:latest")
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nom", ["GECO/modele-fictif", " geco/modele-fictif", "ＧＥＣＯ/modele-fictif"])
    async def test_prefixe_normalise_unicode_et_casse_refuse_en_mode_local(self, nom, acteur_admin):
        with pytest.raises(HTTPException) as exc:
            await _resoudre(nom)
        assert exc.value.status_code == 400 and "bouton « IA GECO »" in exc.value.detail

    @pytest.mark.asyncio
    async def test_nom_de_la_liste_sans_prefixe_en_mode_geco_400(self, liste_ok, mode_geco):
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif()):
            with pytest.raises(HTTPException) as exc:
                await _resoudre("sans-prefixe")
        assert exc.value.status_code == 400 and "préfixe" in exc.value.detail

    @pytest.mark.asyncio
    async def test_mode_local_ne_lit_jamais_la_liste_geco(self, acteur_admin):
        """Bouton sur LOCAL : aucun accès à `modeles_externes_url`. Un nom absent = « non installé »."""
        _regler(modeles_externes_url=URL_LISTE)
        appels: list = []
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif()), \
                _faux_client(lambda r: (appels.append(r), _liste_geco("sans-prefixe"))[1]):
            with pytest.raises(HTTPException) as exc:
                await _resoudre("sans-prefixe")
        assert exc.value.status_code == 400 and "n'est pas installé" in exc.value.detail
        assert appels == []


# ─── Résolution : le doute refuse ─────────────────────────────────────────────

class TestResolutionDoute:
    @pytest.mark.asyncio
    async def test_liste_geco_injoignable_nom_geco_503(self, mode_geco):
        _regler(modeles_externes_url=URL_LISTE)
        with _faux_liste(exception=httpx.ConnectError("refusé")):
            with pytest.raises(HTTPException) as exc:
                await _resoudre(GECO)
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_liste_geco_non_configuree_nom_geco_400(self, mode_geco):
        with pytest.raises(HTTPException) as exc:
            await _resoudre(GECO)
        assert exc.value.status_code == 400 and "pas configurée" in exc.value.detail

    @pytest.mark.asyncio
    async def test_ollama_muet_nom_geco_passe_car_ollama_inutile(self, liste_ok, mode_geco):
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif(panne=True)):
            assert (await _resoudre(GECO)).est_geco

    @pytest.mark.asyncio
    async def test_ollama_muet_mode_geco_nom_simple_503(self, liste_ok, mode_geco):
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif(panne=True)):
            with pytest.raises(HTTPException) as exc:
                await _resoudre("llama3.1")
        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_ollama_muet_mode_local_nom_simple_laisse_passer(self, acteur_admin):
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif(panne=True)):
            r = await _resoudre("llama3.1")
        assert (r.nom, r.origine) == ("llama3.1", "MATO")

    @pytest.mark.asyncio
    async def test_les_deux_muets_mode_geco_503_pour_chaque_demande(self, mode_geco):
        from services import modeles_externes
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif(panne=True)), \
                patch("services.modeles_externes.lire_externes",
                      AsyncMock(return_value=(modeles_externes.ETAT_INJOIGNABLE, []))):
            for demande in (GECO, "gpt-quelconque", None):
                with pytest.raises(HTTPException) as exc:
                    await _resoudre(demande)
                assert exc.value.status_code == 503, demande


# ─── IA GECO réservée aux sessions administrateur ─────────────────────────────

class TestReserveeAdministrateur:
    @pytest.fixture(autouse=True)
    def _bouton_actif(self, liste_ok):
        _regler(ia_destination="geco", geco_modele=GECO)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("acteur, message", [
        ("acteur_utilisateur", "réservée à l'administrateur"),
        ("acteur_jeton", "Les automates n'utilisent pas l'IA GECO"),
    ])
    async def test_geco_explicite_403(self, request, acteur, message):
        request.getfixturevalue(acteur)
        with pytest.raises(HTTPException) as exc:
            await _resoudre(GECO)
        assert exc.value.status_code == 403 and message in exc.value.detail

    @pytest.mark.asyncio
    async def test_authentification_inactive_acteur_indetermine_403(self):
        """Aucune session (authentification inactive ou suspendue) : le doute refuse."""
        with pytest.raises(HTTPException) as exc:
            await _resoudre(GECO)
        assert exc.value.status_code == 403 and "réservée à l'administrateur" in exc.value.detail

    @pytest.mark.asyncio
    @pytest.mark.parametrize("acteur", ["acteur_utilisateur", "acteur_jeton", None])
    async def test_auto_reste_local_en_mode_geco(self, request, acteur):
        if acteur:
            request.getfixturevalue(acteur)
        with patch("services.modeles_externes.lire_externes", new=AsyncMock()) as liste:
            r = await _resoudre(None)
        assert (r.origine, r.explicite) == ("MATO", False) and not r.nom.startswith("geco/")
        liste.assert_not_called()

    @pytest.mark.asyncio
    async def test_modele_local_explicite_reste_servi_en_local(self, acteur_utilisateur):
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif()):
            r = await _resoudre("llama3.1")
        assert (r.nom, r.origine) == ("llama3.1", "MATO")

    def test_acteur_administrateur(self, monkeypatch):
        from services import audit, modeles_externes
        assert modeles_externes.acteur_administrateur() is False              # rien posé
        monkeypatch.setattr(audit, "role_courant", lambda: "admin")
        monkeypatch.setattr(audit, "auteur_courant", lambda: "jeton:n8n")     # « admin » mais jeton : non
        assert modeles_externes.acteur_administrateur() is False
        monkeypatch.setattr(audit, "auteur_courant", lambda: "root")
        assert modeles_externes.acteur_administrateur() is True

    def test_role_pose_par_le_middleware_et_le_worker(self):
        from services import audit
        assert audit.role_courant() is None
        audit.definir_role("admin")
        try:
            assert audit.role_courant() == "admin"
        finally:
            audit.definir_role(None)


# ─── Envoi : /v1/chat/completions ─────────────────────────────────────────────

class TestEnvoiGeco:
    pytestmark = pytest.mark.usefixtures("mode_geco", "journal")

    @pytest.mark.asyncio
    async def test_generate_corps_exact_octets_postes_et_entetes(self):
        from services.ollama_service import usage_ia
        vues: list[httpx.Request] = []

        def handler(request):
            vues.append(request)
            return _reponse_chat("Réponse GECO")

        with _faux_client(handler), usage_ia("rapport"):
            texte = await _generer("Question é ?", system="Consigne", num_predict=50,
                                   options={"temperature": 0.1}, keep_alive=-1, format="json")
        assert texte == "Réponse GECO" and len(vues) == 1
        req = vues[0]
        assert (req.method, req.url.path) == ("POST", CHEMIN_GECO)
        corps = json.loads(req.content)
        assert corps == {"model": GECO, "stream": False, "max_tokens": 50,
                         "messages": [{"role": "system", "content": "Consigne"},
                                      {"role": "user", "content": "Question é ?"}]}
        for interdit in ("options", "keep_alive", "num_ctx", "think", "prompt", "format", "images"):
            assert interdit not in corps
        assert req.content == json.dumps(corps, ensure_ascii=False).encode("utf-8")   # corps sérialisé UNE fois
        assert req.headers["content-type"] == "application/json"
        assert req.headers["X-AI-Project"] and req.headers["X-AI-Usage"] == "rapport"

    @pytest.mark.asyncio
    async def test_en_tete_x_ai_sortie_sur_l_envoi_geco_seulement(self):
        from services.ollama_service import OllamaService, entetes_projet
        vues: list[httpx.Request] = []

        def handler(request):
            vues.append(request)
            if request.url.path == CHEMIN_GECO:
                return _reponse_chat()
            return _json({"response": "local", "models": []})

        with _faux_client(handler):
            await _generer("Q")
            service = OllamaService(base_url=BASE_AIGUILLEUR)
            await service.generate("Q", model="llama3.1:latest")
            await service.list_models()
        geco, locales = vues[0], vues[1:]
        assert geco.headers["X-AI-Sortie"] == "geco"
        assert locales and all("x-ai-sortie" not in r.headers for r in locales)
        assert all(r.url.path.startswith("/api/") for r in locales)
        assert "X-AI-Sortie" not in entetes_projet()

    @pytest.mark.asyncio
    async def test_generate_sans_systeme_un_seul_message_user(self):
        vues = []
        with _faux_client(lambda r: (vues.append(r), _reponse_chat())[1]):
            await _generer("Salut")
        corps = json.loads(vues[0].content)
        assert corps["messages"] == [{"role": "user", "content": "Salut"}] and "max_tokens" not in corps

    @pytest.mark.asyncio
    async def test_aucune_redirection_suivie(self):
        vues = []

        def handler(request):
            vues.append(request)
            return httpx.Response(302, headers={"location": "http://ailleurs.test/x"})

        from services.ollama_service import ErreurGeco
        with _faux_client(handler):
            with pytest.raises(ErreurGeco) as e1:
                await _generer("Q")
            with pytest.raises(ErreurGeco) as e2:
                await _flux()
        assert len(vues) == 2 and all(r.url.host == "aiguilleur.test" for r in vues)
        assert "redirection" in str(e1.value) and e2.value.status_code == 502

    @pytest.mark.asyncio
    async def test_flux_sse_ignore_commentaire_ligne_illisible_et_apres_done(self):
        flux = [b": commentaire\n\n", _ligne(None, role="assistant"), _ligne("Bon"), _ligne("jour"),
                b"data: pas-du-json\n\n", b"data: [1, 2]\n\n", b'data: {"choices": ["x"]}\n\n',
                _ligne(" monde"), b"data: [DONE]\n\n", _ligne("APRES-DONE")]
        vues = []
        with _faux_client(lambda r: (vues.append(r), _sse_octets(*flux))[1]):
            morceaux = await _flux(system=None) if False else await _flux()
        assert morceaux == ["Bon", "jour", " monde"]
        assert json.loads(vues[0].content) == {"model": GECO, "stream": True,
                                               "messages": [{"role": "user", "content": "Q"}]}

    @pytest.mark.asyncio
    async def test_u2028_reste_dans_le_texte(self):
        """`aiter_lines()` coupait sur U+2028 : la découpe se fait sur `\\n` SEULEMENT."""
        with _faux_client(lambda r: _sse_octets(_ligne("avant après"), b"data: [DONE]\n\n")):
            assert await _flux() == ["avant après"]

    @pytest.mark.asyncio
    async def test_caractere_multi_octets_coupe_entre_deux_morceaux(self):
        brut = _ligne("é€😀") + b"data: [DONE]\n\n"
        i = brut.index("€".encode()) + 1          # au milieu de l'euro (3 octets)
        with _faux_client(lambda r: _sse_octets(brut[:i], brut[i:])):
            assert await _flux() == ["é€😀"]

    @pytest.mark.asyncio
    async def test_json_coupe_entre_deux_morceaux_et_octet_par_octet(self):
        brut = _ligne("Bonjour") + _ligne(" tout le monde") + b"data: [DONE]\n\n"
        with _faux_client(lambda r: _sse_octets(brut[:25], brut[25:60], brut[60:])):
            assert await _flux() == ["Bonjour", " tout le monde"]
        with _faux_client(lambda r: _sse_octets(*[brut[i:i + 1] for i in range(len(brut))])):
            assert await _flux() == ["Bonjour", " tout le monde"]

    @pytest.mark.asyncio
    async def test_fin_de_flux_sans_done_derniere_ligne_sans_saut(self):
        with _faux_client(lambda r: _sse_octets(_ligne("un"), _ligne("deux").rstrip())):
            assert await _flux() == ["un", "deux"]

    @pytest.mark.asyncio
    async def test_flux_vide_erreur_502(self):
        from services.ollama_service import ErreurGeco
        for parties in ((b"data: [DONE]\n\n",), (_ligne(None, role="assistant"), b"data: [DONE]\n\n"),
                        (_ligne(None, delta=None), b"")):
            with _faux_client(lambda r, p=parties: _sse_octets(*p)):
                with pytest.raises(ErreurGeco) as exc:
                    await _flux()
            assert exc.value.status_code == 502 and "Réponse vide de GECO" in str(exc.value)

    @pytest.mark.asyncio
    async def test_contenu_null_tolere(self):
        brut = b'data: {"choices": [{"delta": {"content": null}}]}\n\n' + _ligne("ok") + b"data: [DONE]\n\n"
        with _faux_client(lambda r: _sse_octets(brut)):
            assert await _flux() == ["ok"]

    @pytest.mark.asyncio
    async def test_ligne_error_dans_le_flux_502(self):
        from services.ollama_service import ErreurGeco
        brut = _ligne("début") + ('data: {"error": {"message": "' + SECRET + '"}}\n\n').encode()
        with _faux_client(lambda r: _sse_octets(brut)):
            with pytest.raises(ErreurGeco) as exc:
                await _flux()
        assert exc.value.status_code == 502 and SECRET not in str(exc.value)

    @pytest.mark.asyncio
    async def test_finish_reason_length_garde_le_texte_et_avertit(self):
        with _faux_client(lambda r: _sse_octets(_ligne("coupé", finish_reason="length"), b"data: [DONE]\n\n")):
            with patch("services.ollama_service.log") as log:
                assert await _flux() == ["coupé"]
        log.warning.assert_any_call("Réponse GECO tronquée ou filtrée", finish_reason="length")

    @pytest.mark.asyncio
    async def test_content_type_non_flux_lu_comme_reponse_complete(self):
        with _faux_client(lambda r: _reponse_chat("Réponse d'un coup")):
            assert await _flux() == ["Réponse d'un coup"]

    @pytest.mark.asyncio
    async def test_non_flux_avec_cle_error_ou_vide_502(self):
        from services.ollama_service import ErreurGeco
        for reponse in (_json({"error": {"message": SECRET}}), _json({"choices": []}), _json({"autre": 1}),
                        _reponse_chat(""), httpx.Response(200, content=b"<html>")):
            with _faux_client(lambda r, rep=reponse: rep):
                with pytest.raises(ErreurGeco) as e1:
                    await _flux()
                with pytest.raises(ErreurGeco) as e2:
                    await _generer("Q")
            assert e1.value.status_code == e2.value.status_code == 502
            assert SECRET not in str(e1.value) + str(e2.value)

    @pytest.mark.asyncio
    async def test_chat_stream_messages_et_usage_chat(self):
        vues = []
        messages = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
                    {"role": "user", "content": "c"}]
        from services.ollama_service import OllamaService, sortie_geco_autorisee
        with _faux_client(lambda r: (vues.append(r), _sse_octets(_ligne("ok"), b"data: [DONE]\n\n"))[1]):
            with sortie_geco_autorisee("/api/generate/chat"):
                morceaux = [m async for m in OllamaService(base_url=BASE_AIGUILLEUR).chat_stream(
                    messages, model=GECO, think=False)]
        assert morceaux == ["ok"]
        corps = json.loads(vues[0].content)
        assert corps["messages"] == messages and "keep_alive" not in corps and "options" not in corps
        assert vues[0].headers["X-AI-Usage"] == "chat" and vues[0].headers["X-AI-Sortie"] == "geco"

    @pytest.mark.asyncio
    async def test_modele_local_inchange(self):
        """Non-régression : un modèle local part vers /api/generate, avec ses options, sans signal de sortie."""
        from services.ollama_service import OllamaService
        vues = []
        with _faux_client(lambda r: (vues.append(r), _json({"response": "local"}))[1]):
            texte = await OllamaService(base_url=BASE_AIGUILLEUR).generate("Q", model="llama3.1:latest")
        assert texte == "local" and vues[0].url.path == "/api/generate"
        corps = json.loads(vues[0].content)
        assert "keep_alive" in corps and "options" in corps and "x-ai-sortie" not in vues[0].headers

    @pytest.mark.asyncio
    async def test_images_refusees(self):
        from services.ollama_service import ErreurGeco
        appels = []
        with _faux_client(lambda r: (appels.append(r), _reponse_chat())[1]):
            with pytest.raises(ErreurGeco) as exc:
                await _generer("Q", images=["aaa"])
        assert "texte" in str(exc.value) and appels == []


# ─── Délais, plafonds de lecture, erreurs réseau ──────────────────────────────

class TestDelaisEtReseau:
    pytestmark = pytest.mark.usefixtures("mode_geco", "journal")

    @pytest.mark.asyncio
    async def test_delai_total_du_flux_504(self):
        from services.ollama_service import ErreurGeco, OllamaService
        lent = httpx.Response(200, content=_morceaux(_ligne("a"), _ligne("b"), pause=0.2),
                              headers={"content-type": "text/event-stream"})
        with patch.object(OllamaService, "_delai_geco", staticmethod(lambda: 0.05)), \
                _faux_client(lambda r: lent):
            with pytest.raises(ErreurGeco) as exc:
                await _flux()
        assert exc.value.status_code == 504

    @pytest.mark.asyncio
    async def test_delai_total_non_flux_504(self):
        import asyncio
        from services.ollama_service import ErreurGeco, OllamaService

        async def lent(request):
            await asyncio.sleep(0.5)
            return _reponse_chat()

        with patch.object(OllamaService, "_delai_geco", staticmethod(lambda: 0.05)), _faux_client(lent):
            with pytest.raises(ErreurGeco) as exc:
                await _generer("Q")
        assert exc.value.status_code == 504

    @pytest.mark.asyncio
    @pytest.mark.parametrize("exc_reseau, code", [
        (httpx.ReadTimeout("lent"), 504), (httpx.ConnectTimeout("lent"), 504), (httpx.PoolTimeout("plein"), 504),
        (httpx.ConnectError("refusé vers http://aiguilleur.test:21450"), 503),
        (httpx.ReadError("coupé"), 503), (httpx.RemoteProtocolError("x"), 503), (httpx.InvalidURL("x"), 503),
        (httpx.StreamError("x"), 503),
    ])
    async def test_erreurs_reseau(self, exc_reseau, code):
        from services.ollama_service import ErreurGeco

        def handler(request):
            raise exc_reseau

        with _faux_client(handler):
            with pytest.raises(ErreurGeco) as e1:
                await _generer("Q")
            with pytest.raises(ErreurGeco) as e2:
                await _flux()
        assert e1.value.status_code == e2.value.status_code == code
        assert "aiguilleur.test" not in str(e1.value)

    @pytest.mark.asyncio
    async def test_plafond_de_lecture_8_mio(self):
        from services.ollama_service import ErreurGeco
        enorme = _ligne("x" * 400)
        with patch("services.ollama_service.PLAFOND_LECTURE_OCTETS", 1000), \
                _faux_client(lambda r: _sse_octets(*[enorme] * 5)):
            with pytest.raises(ErreurGeco) as exc:
                await _flux()
        assert exc.value.status_code == 502 and "volumineuse" in str(exc.value)
        with patch("services.ollama_service.PLAFOND_LECTURE_OCTETS", 100), \
                _faux_client(lambda r: _reponse_chat("y" * 500)):
            with pytest.raises(ErreurGeco):
                await _generer("Q")

    @pytest.mark.asyncio
    async def test_delai_reglable(self):
        from services.ollama_service import OllamaService
        assert OllamaService._delai_geco() == 300.0
        _regler(geco_timeout_s="42")
        assert OllamaService._delai_geco() == 42.0
        _regler(geco_timeout_s="1")
        assert OllamaService._delai_geco() == 10.0       # borné [10, 3600]
        _regler(geco_timeout_s="pas-un-nombre")
        assert OllamaService._delai_geco() == 300.0

    @pytest.mark.asyncio
    async def test_flux_ferme_quand_le_consommateur_sort(self):
        from services.ollama_service import OllamaService, sortie_geco_autorisee
        with _faux_client(lambda r: _sse_octets(_ligne("un"), _ligne("deux"), b"data: [DONE]\n\n")):
            with sortie_geco_autorisee("/api/test"):
                flux = OllamaService(base_url=BASE_AIGUILLEUR).generate_stream("Q", model=GECO)
                premier = await flux.__anext__()
                await flux.aclose()
        assert premier == "un"

    @pytest.mark.asyncio
    async def test_echecs_geco_notes_dans_ia_echecs_sans_contenu(self):
        from services.ollama_service import ErreurGeco
        with patch("services.ollama_service.ia_echecs.noter", new=AsyncMock()) as noter, \
                _faux_client(lambda r: httpx.Response(500, json={"error": SECRET})):
            with pytest.raises(ErreurGeco):
                await _generer("Q")
        modele, operation = noter.call_args.args[:2]
        assert (modele, operation) == (GECO, "generate")
        assert SECRET not in json.dumps(noter.call_args.kwargs, default=str)
        assert noter.call_args.kwargs["nature"] == "http"


# ─── Erreurs de l'AIGUILLEUR (A2) ─────────────────────────────────────────────

class TestErreursAiguilleur:
    pytestmark = pytest.mark.usefixtures("mode_geco", "journal")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("statut, corps, code, fragment", [
        (403, {"code": "projet_non_autorise"}, 403, "n'est pas autorisée à sortir vers GECO"),
        (403, {"error": {"code": "projet_non_autorise"}}, 403, "administration de l'AIGUILLEUR"),
        (403, {}, 403, "n'est pas autorisée à sortir vers GECO"),
        (403, {"code": "code-inconnu"}, 403, "n'est pas autorisée à sortir vers GECO"),
        (403, {"code": "sortie_non_demandee"}, 500, "sans le signal du bouton « IA GECO ». Rien n'est sorti. À signaler."),
        (403, {"error": {"code": "sortie_non_demandee"}}, 500, "Défaut de Matothèque"),
        (400, {"code": "surface_non_permise"}, 500, "un modèle GECO a été envoyé par un chemin non prévu. Rien n'est sorti. À signaler."),
        (400, {}, 400, "refusé la requête GECO (HTTP 400)"),
        (429, {}, 429, "HTTP 429"),
        (408, {}, 504, "HTTP 408"),
        (504, {}, 504, "HTTP 504"),
        (500, {}, 502, "GECO a répondu par une erreur (HTTP 500)"),
        (503, {}, 502, "HTTP 503"),
        (404, {}, 502, "HTTP 404"),
    ])
    async def test_traduction(self, statut, corps, code, fragment):
        from services.ollama_service import ErreurGeco
        appels = []

        def handler(request):
            appels.append(request)
            return httpx.Response(statut, json={**corps, "detail": "interne-" + SECRET})

        with _faux_client(handler):
            with pytest.raises(ErreurGeco) as exc:
                await _generer("Q")
            with pytest.raises(ErreurGeco) as exc2:
                await _flux()
            with pytest.raises(ErreurGeco) as exc3:
                await _flux("chat_stream")
        assert exc.value.status_code == exc2.value.status_code == exc3.value.status_code == code
        assert fragment in str(exc.value) and SECRET not in str(exc.value)    # le reste du corps n'est jamais relayé
        assert len(appels) == 3                                               # `generate` ne rejoue pas

    @pytest.mark.asyncio
    async def test_defauts_de_matotheque_journalises_en_erreur(self):
        from services.ollama_service import ErreurGeco
        with patch("services.ollama_service.log") as log, \
                _faux_client(lambda r: httpx.Response(403, json={"code": "sortie_non_demandee"})):
            with pytest.raises(ErreurGeco):
                await _generer("Q")
        assert log.error.called

    @pytest.mark.asyncio
    async def test_corps_non_json_ou_code_non_chaine(self):
        from services.ollama_service import ErreurGeco
        for corps in (b"<html>", b'{"code": 12}', b'{"error": "texte"}', b"[1]"):
            with _faux_client(lambda r, c=corps: httpx.Response(403, content=c)):
                with pytest.raises(ErreurGeco) as exc:
                    await _generer("Q")
            assert exc.value.status_code == 403 and "n'est pas autorisée" in str(exc.value)

    @pytest.mark.asyncio
    async def test_gestionnaire_global_rend_le_message_et_le_code(self, appli, liste_ok):
        from services.ollama_service import erreur_http_geco
        with patch("services.modeles_externes.OllamaService", return_value=_ollama_fictif()), \
                patch("services.relecture_prompt.relire_prompt", new=AsyncMock(side_effect=erreur_http_geco(403))):
            resp = await _post(appli, "/api/prompts/relire", texte="fais un résumé", model=GECO)
        assert resp.status_code == 403
        assert "n'est pas autorisée à sortir vers GECO" in resp.json()["detail"]


# ─── Barrières (liste blanche, bouton en base, usage, plafond, journal) ───────

class TestBarrieres:
    @pytest.mark.asyncio
    async def test_sans_marque_aucun_envoi_meme_bouton_sur_geco(self, mode_geco, journal):
        """Liste blanche, défaut REFUS : un appel hors route interactive / job marqué ne part jamais."""
        from services.ollama_service import ErreurGeco, OllamaService
        appels = []
        service = OllamaService(base_url=BASE_AIGUILLEUR)
        with _faux_client(lambda r: (appels.append(r), _reponse_chat())[1]):
            with pytest.raises(ErreurGeco) as exc:
                await service.generate("Q", model=GECO)
            with pytest.raises(ErreurGeco):
                [m async for m in service.generate_stream("Q", model=GECO)]
            with pytest.raises(ErreurGeco):
                [m async for m in service.chat_stream([{"role": "user", "content": "Q"}], model=GECO)]
        assert exc.value.status_code == 403 and "traitement" in str(exc.value)
        assert appels == [] and journal == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("usage", ["enrichissement", "embeddings", "vision", "rapport", "chat", "autre"])
    async def test_marque_absente_refus_quel_que_soit_l_usage(self, mode_geco, usage):
        from services.ollama_service import ErreurGeco, OllamaService, usage_ia
        appels = []
        with _faux_client(lambda r: (appels.append(r), _reponse_chat())[1]), usage_ia(usage):
            with pytest.raises(ErreurGeco):
                await OllamaService(base_url=BASE_AIGUILLEUR).generate("Q", model=GECO)
        assert appels == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("usage", ["enrichissement", "embeddings", "vision"])
    async def test_usage_de_fond_refuse_meme_avec_marque(self, mode_geco, journal, usage):
        from services.ollama_service import ErreurGeco, usage_ia
        appels = []
        with _faux_client(lambda r: (appels.append(r), _reponse_chat())[1]), usage_ia(usage):
            with pytest.raises(ErreurGeco) as exc:
                await _generer("Q")
            with pytest.raises(ErreurGeco):
                await _flux()
        assert usage in str(exc.value) and appels == [] and journal == []

    def test_resume_modele_retire_de_la_liste_des_usages_de_fond(self):
        from services.ollama_service import USAGES_DE_FOND
        assert "resume_modele" not in USAGES_DE_FOND

    @pytest.mark.asyncio
    async def test_la_marque_ne_sort_pas_du_bloc_et_se_referme(self):
        from services.ollama_service import _SORTIE_GECO, sortie_geco_autorisee
        assert _SORTIE_GECO.get() is None
        with sortie_geco_autorisee("/api/x"):
            assert _SORTIE_GECO.get() == "/api/x"
            with pytest.raises(RuntimeError):
                raise RuntimeError("x")
        assert _SORTIE_GECO.get() is None

    @pytest.mark.asyncio
    async def test_la_marque_est_copiee_dans_les_taches_creees(self, mode_geco, journal):
        import asyncio
        from services.ollama_service import OllamaService, sortie_geco_autorisee
        vues = []
        service = OllamaService(base_url=BASE_AIGUILLEUR)
        with _faux_client(lambda r: (vues.append(r), _reponse_chat())[1]):
            with sortie_geco_autorisee("/api/assistant/question"):
                await asyncio.gather(*(service.generate(f"Q{i}", model=GECO) for i in range(3)))
            nombre = len(vues)
        assert nombre == 3

    @pytest.mark.asyncio
    async def test_embeddings_vision_prechauffage_refusent_geco(self, mode_geco):
        from services.ollama_service import ErreurGeco, OllamaService
        appels = []
        service = OllamaService(base_url=BASE_AIGUILLEUR)
        with _faux_client(lambda r: (appels.append(r), _json({}))[1]):
            with pytest.raises(ErreurGeco):
                await service.embed("texte", model=GECO)
            with pytest.raises(ErreurGeco):
                await service.embed_many(["texte"], model=GECO)
            with pytest.raises(ErreurGeco):
                await service.warm(GECO)
        assert appels == []

    @pytest.mark.asyncio
    async def test_cache_du_processus_sur_geco_mais_base_sur_local_aucune_requete(self, base_geco, acteur_admin,
                                                                                   journal):
        """Rémanence du cache : un autre processus a repassé sur LOCAL, celui-ci croit encore « geco »."""
        from services import runtime_config
        from services.ollama_service import ErreurGeco
        await base_geco.ecrire("local")
        runtime_config._overrides["ia_destination"] = "geco"       # cache périmé de CE processus
        appels = []
        with _faux_client(lambda r: (appels.append(r), _reponse_chat())[1]):
            with pytest.raises(ErreurGeco) as exc:
                await _generer("Q")
        assert exc.value.status_code == 403 and "bouton « IA GECO »" in str(exc.value)
        assert appels == [] and journal == []

    @pytest.mark.asyncio
    async def test_base_geco_le_cache_n_est_pas_consulte(self, base_geco, acteur_admin, journal):
        from services import runtime_config
        await base_geco.ecrire("geco")
        runtime_config._overrides["ia_destination"] = "local"      # cache périmé dans l'autre sens
        with _faux_client(lambda r: _reponse_chat("ok")):
            assert await _generer("Q") == "ok"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("etat", ["absente", "vide", "autre", "illisible"])
    async def test_base_injoignable_ou_valeur_absente_aucune_requete(self, base_geco, acteur_admin, journal,
                                                                     monkeypatch, etat):
        from services.ollama_service import ErreurGeco
        if etat == "illisible":
            def casse():
                raise ConnectionError("base injoignable")
            monkeypatch.setattr("services.ollama_service.AsyncSessionLocal", casse)
        else:
            await base_geco.ecrire("local")
            from models.config import Config
            async with base_geco.fabrique() as db:
                ligne = await db.get(Config, "ia_destination")
                if etat == "absente":
                    await db.delete(ligne)
                else:
                    ligne.valeur = "" if etat == "vide" else "internet"
                await db.commit()
        appels = []
        with _faux_client(lambda r: (appels.append(r), _reponse_chat())[1]):
            with pytest.raises(ErreurGeco):
                await _generer("Q")
        assert appels == []

    @pytest.mark.asyncio
    async def test_plafond_32_mio_avant_envoi_et_octets_mesures(self, mode_geco, journal):
        from services.ollama_service import ErreurGeco
        appels = []
        enorme = "é" * (16 * 1024 * 1024 + 1)         # 2 octets par caractère : 32 Mio + 2 octets, 16 Mi caractères
        with _faux_client(lambda r: (appels.append(r), _reponse_chat())[1]):
            with pytest.raises(ErreurGeco) as exc:
                await _generer(enorme)
        assert exc.value.status_code == 413 and appels == [] and journal == []

    def test_plafond_route_413(self):
        from services import modeles_externes
        modeles_externes.exiger_taille(32 * 1024 * 1024)
        with pytest.raises(HTTPException) as exc:
            modeles_externes.exiger_taille(32 * 1024 * 1024 + 1)
        assert exc.value.status_code == 413

    @pytest.mark.parametrize("nom, attendu", [
        ("geco/x", True), (" geco/x", True), ("GECO/x", True), ("Geco/x", True), ("ＧＥＣＯ/x", True),
        ("llama3.1", False), ("hf.co/geco/x", False), ("gecko/x", False), ("", False), (None, False),
    ])
    def test_est_geco_normalise(self, nom, attendu):
        from services.ollama_service import est_geco
        assert est_geco(nom) is attendu


# ─── Journal PAR ENVOI, fail-closed (B4) ──────────────────────────────────────

class TestJournalParEnvoi:
    @pytest.mark.asyncio
    async def test_une_entree_par_envoi_avant_l_envoi_sans_contenu(self, mode_geco, journal):
        ordre: list[str] = []
        from services import audit

        async def emit(action, statut, **kw):
            ordre.append("journal")
            journal.append({"action": action, "statut": statut, **kw})

        def handler(request):
            ordre.append("envoi")
            return _reponse_chat("ok")

        with patch.object(audit, "emit_strict", emit), _faux_client(handler):
            await _generer(SECRET, origine="/api/generate/report", system="consigne-" + SECRET)
            await _generer("deux", origine="job:rapport")
        assert ordre == ["journal", "envoi", "journal", "envoi"]
        premiere, seconde = journal
        assert premiere["action"] == "sortie_geco" and premiere["cible"] == "/api/generate/report"
        d = premiere["detail"]
        assert set(d) == {"origine", "modele", "usage", "nb_messages", "nb_caracteres", "nb_octets"}
        assert d["modele"] == GECO and d["nb_messages"] == 2 and d["nb_octets"] >= d["nb_caracteres"] > len(SECRET)
        assert SECRET not in json.dumps(premiere, default=str)
        assert seconde["acteur"] == "worker" and seconde["detail"]["origine"] == "job:rapport"

    @pytest.mark.asyncio
    async def test_journal_indisponible_aucun_envoi(self, mode_geco, monkeypatch):
        from services import audit
        from services.ollama_service import ErreurGeco
        monkeypatch.setattr(audit, "emit_strict", AsyncMock(side_effect=RuntimeError("base KO")))
        appels = []
        with _faux_client(lambda r: (appels.append(r), _reponse_chat())[1]):
            with pytest.raises(ErreurGeco) as exc:
                await _generer("Q")
            with pytest.raises(ErreurGeco):
                await _flux()
        assert exc.value.status_code == 503 and "journal" in str(exc.value).lower() and appels == []

    @pytest.mark.asyncio
    async def test_emit_strict_leve_emit_avale(self, monkeypatch):
        from services import audit

        def casse():
            raise RuntimeError("base KO")

        monkeypatch.setattr(audit, "AsyncSessionLocal", casse)
        await audit.emit("x", "info")                       # n'a jamais levé : comportement inchangé
        with pytest.raises(RuntimeError):
            await audit.emit_strict("x", "info")

    @pytest.mark.asyncio
    async def test_journal_reel_auteur_du_contexte(self, base_geco, acteur_admin):
        from services import audit
        await base_geco.ecrire("geco")
        audit.definir_auteur("admin-fictif")
        try:
            with _faux_client(lambda r: _reponse_chat("ok")):
                await _generer("Q", origine="/api/prompts/relire")
        finally:
            audit.definir_auteur(None)
        (ligne,) = await base_geco.evenements()
        assert ligne.auteur == "admin-fictif" and ligne.cible == "/api/prompts/relire"
        assert ligne.detail["modele"] == GECO

    @pytest.mark.asyncio
    async def test_bascule_journalisee(self, appli, liste_ok, ecriture_geco_ok, journal):
        resp = await _put(appli, ia_destination="geco", geco_modele=GECO)
        assert resp.status_code == 200, resp.text
        resp = await _put(appli, ia_destination="local")
        assert resp.status_code == 200
        bascules = [e for e in journal if e["action"] == "ia_destination"]
        assert [(b["detail"]["ancienne"], b["detail"]["nouvelle"]) for b in bascules] == [
            ("local", "geco"), ("geco", "local")]


# ─── BOUT EN BOUT : routes interactives (vraie route -> vrai OllamaService -> espion de transport) ───

def _doc(texte="texte fictif"):
    from models.document import Document
    return Document(chemin="/fictif/a.txt", nom="a.txt", extension="txt", hash_sha256="h", texte_extrait=texte)


ROUTES = [
    ("chat", "/api/generate/chat", {"messages": [{"role": "user", "content": "bonjour"}], "ged_mode": "jamais"}),
    ("rapport", "/api/generate/report", {"document_ids": [], "prompt": "bilan"}),
    ("template", "/api/generate/fill-template", {"document_ids": ["a"], "template_id": "t"}),
    ("criteres", "/api/generate/compare/criteres", {"document_ids": ["a"]}),
    ("comparatif", "/api/generate/compare",
     {"groupes": [{"nom": "A", "document_ids": ["a"]}, {"nom": "B", "document_ids": ["b"]}], "colonnes": ["Prix"]}),
    ("regroupement", "/api/regroupements/{rid}/analyser", {}),
    ("assistant_pieces", "/api/assistant/pieces", {"besoin": "dossier de prêt"}),
    ("assistant_question", "/api/assistant/question", {"question": "quel est le total ?"}),
    ("relecture", "/api/prompts/relire", {"texte": "fais un résumé"}),
    ("presentation", "/api/presentations", {"document_ids": ["a", "b"]}),
]
ROUTES_ENQUEUE = {"rapport", "template", "comparatif", "regroupement", "presentation"}
ROUTES_DIRECTES = {"chat", "criteres", "assistant_pieces", "assistant_question", "relecture"}


@pytest.fixture
def faux_travail(base_geco):
    """Neutralise ce qui n'est pas l'objet : mise en file, chargement de documents, recherche GED."""
    with patch("services.job_worker.enqueue", new=AsyncMock(return_value="job-1")) as enqueue, \
            patch("routers.compare._charger_documents", new=AsyncMock(return_value=[_doc()])), \
            patch("routers.generate._recherche_mots_cles", new=AsyncMock(return_value=[])):
        yield SimpleNamespace(enqueue=enqueue)


async def _appeler(appli, db_session, url, corps, **extra):
    if "{rid}" in url:
        from models.regroupement import Regroupement
        rg = Regroupement(nom="Groupe fictif", document_ids=["doc-fictif"])
        db_session.add(rg)
        await db_session.commit()
        url = url.replace("{rid}", str(rg.id))
    return await _post(appli, url, **{**corps, **extra})


class TestBoutEnBoutRoutes:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("nom,url,corps", ROUTES, ids=[r[0] for r in ROUTES])
    @pytest.mark.parametrize("scenario", ["explicite", "force_par_la_configuration"])
    async def test_bouton_local_zero_requete_geco(self, appli, db_session, reseau, base_geco, faux_travail,
                                                  acteur_admin, nom, url, corps, scenario):
        await base_geco.ecrire("local")
        if scenario == "explicite":
            extra = {"model": GECO}
        else:   # lignes écrites directement en base / dans le cache, « Auto » côté client
            _regler(default_model=GECO, usage_models=json.dumps({"rapport": GECO, "chat": GECO,
                                                                 "enrichissement": GECO}))
            extra = {}
        resp = await _appeler(appli, db_session, url, corps, **extra)
        assert reseau.geco == [], f"{nom}: une requête est partie vers GECO ({resp.status_code})"
        assert await base_geco.evenements() == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nom,url,corps", ROUTES, ids=[r[0] for r in ROUTES])
    async def test_bouton_local_cache_perime_sur_geco_zero_requete(self, appli, db_session, reseau, base_geco,
                                                                    faux_travail, acteur_admin, nom, url, corps):
        """Le cache de CE processus croit « geco » alors que la base dit « local » : rien ne sort."""
        await base_geco.ecrire("local")
        _regler(ia_destination="geco", geco_modele=GECO)
        await _appeler(appli, db_session, url, corps, model=GECO)
        assert reseau.geco == [] and await base_geco.evenements() == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nom,url,corps", ROUTES, ids=[r[0] for r in ROUTES])
    @pytest.mark.parametrize("acteur", ["acteur_utilisateur", "acteur_jeton", None])
    async def test_mode_geco_acteur_non_administrateur_zero_requete(self, request, appli, db_session, reseau,
                                                                      base_geco, faux_travail, nom, url, corps,
                                                                      acteur):
        """Mode GECO, mais session « utilisateur », automate ou authentification inactive : jamais GECO."""
        if acteur:
            request.getfixturevalue(acteur)
        await base_geco.ecrire("geco")
        resp = await _appeler(appli, db_session, url, corps, model=GECO)
        assert resp.status_code == 403, (nom, resp.text)
        assert reseau.geco == [] and await base_geco.evenements() == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nom,url,corps", [r for r in ROUTES if r[0] in ROUTES_DIRECTES],
                             ids=[r[0] for r in ROUTES if r[0] in ROUTES_DIRECTES])
    @pytest.mark.parametrize("acteur", ["acteur_utilisateur", "acteur_jeton"])
    async def test_mode_geco_auto_non_administrateur_servi_en_local(self, request, appli, db_session, reseau,
                                                                      base_geco, faux_travail, nom, url, corps,
                                                                      acteur):
        request.getfixturevalue(acteur)
        await base_geco.ecrire("geco")
        await _appeler(appli, db_session, url, corps)
        assert reseau.geco == [] and await base_geco.evenements() == []
        assert any(r.url.path in ("/api/generate", "/api/chat") for r in reseau.requetes), nom   # servi en local

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nom,url,corps", [r for r in ROUTES if r[0] in ROUTES_DIRECTES],
                             ids=[r[0] for r in ROUTES if r[0] in ROUTES_DIRECTES])
    @pytest.mark.parametrize("explicite", [True, False])
    async def test_bouton_geco_administrateur_envoi_signale_et_journalise(self, appli, db_session, reseau, base_geco,
                                                                           faux_travail, acteur_admin, nom, url,
                                                                           corps, explicite):
        await base_geco.ecrire("geco")
        resp = await _appeler(appli, db_session, url, corps, **({"model": GECO} if explicite else {}))
        assert resp.status_code not in (400, 403, 409, 413, 503) or nom == "assistant_question", (nom, resp.text)
        assert reseau.geco, f"{nom}: aucun envoi GECO"
        assert all(r.headers["X-AI-Sortie"] == "geco" and r.headers["X-AI-Project"] for r in reseau.geco)
        assert all(json.loads(r.content)["model"] == GECO for r in reseau.geco)
        assert not any(r.url.path in ("/api/generate", "/api/chat") for r in reseau.requetes)   # rien en local
        lignes = await base_geco.evenements()
        assert len(lignes) == len(reseau.geco)                      # une entrée de journal PAR requête
        assert all(l.cible.startswith("/api/") and l.auteur is None or l.cible.startswith("/api/") for l in lignes)
        assert SECRET not in json.dumps([l.detail for l in lignes], default=str)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nom,url,corps", [r for r in ROUTES if r[0] in ROUTES_ENQUEUE],
                             ids=[r[0] for r in ROUTES if r[0] in ROUTES_ENQUEUE])
    async def test_bouton_geco_administrateur_job_marque_pour_le_worker(self, appli, db_session, reseau, base_geco,
                                                                        faux_travail, acteur_admin, nom, url, corps):
        await base_geco.ecrire("geco")
        resp = await _appeler(appli, db_session, url, corps, model=GECO)
        assert resp.status_code in (200, 202), (nom, resp.text)
        faux_travail.enqueue.assert_called_once()
        params = faux_travail.enqueue.call_args.args[2]
        assert params["origine"] == "GECO" and params["model"] == GECO
        assert reseau.geco == []     # la route n'envoie rien : c'est le worker, après recontrôle

    @pytest.mark.asyncio
    async def test_bouton_geco_auto_job_prend_geco_modele(self, appli, db_session, reseau, base_geco, faux_travail,
                                                          acteur_admin):
        await base_geco.ecrire("geco")
        resp = await _appeler(appli, db_session, "/api/generate/report", {"document_ids": [], "prompt": "p"})
        assert resp.status_code == 200
        params = faux_travail.enqueue.call_args.args[2]
        assert (params["model"], params["origine"]) == (GECO, "GECO")

    @pytest.mark.asyncio
    async def test_chat_erreur_geco_dite_dans_le_flux_sans_prefixe_ia_injoignable(self, appli, db_session, reseau,
                                                                                    base_geco, faux_travail,
                                                                                    acteur_admin):
        await base_geco.ecrire("geco")
        reseau.surcharge = lambda r: (httpx.Response(403, json={"code": "projet_non_autorise"})
                                      if r.url.path == CHEMIN_GECO else None)
        resp = await _post(appli, "/api/generate/chat", messages=[{"role": "user", "content": "q"}],
                           ged_mode="jamais", model=GECO)
        assert resp.status_code == 200
        assert "⚠️ Matothèque n'est pas autorisée à sortir vers GECO" in resp.text
        assert "IA injoignable" not in resp.text

    @pytest.mark.asyncio
    async def test_chat_taille_413_avant_envoi(self, appli, reseau, base_geco, faux_travail, acteur_admin):
        await base_geco.ecrire("geco")
        enorme = "a" * (32 * 1024 * 1024 + 1)
        resp = await _post(appli, "/api/generate/chat", messages=[{"role": "user", "content": enorme}],
                           ged_mode="jamais", model=GECO)
        assert resp.status_code == 413 and reseau.geco == []

    @pytest.mark.asyncio
    async def test_chat_en_mode_local_non_regresse(self, appli, reseau, base_geco, faux_travail, acteur_admin):
        await base_geco.ecrire("local")
        resp = await _post(appli, "/api/generate/chat", messages=[{"role": "user", "content": "q"}],
                           ged_mode="jamais", model="llama3.1:latest")
        assert resp.status_code == 200 and "local" in resp.text
        assert reseau.geco == [] and any(r.url.path == "/api/chat" for r in reseau.requetes)
        assert all("x-ai-sortie" not in r.headers for r in reseau.requetes)


# ─── Worker : recontrôle et exécution ─────────────────────────────────────────

TYPES_INTERACTIFS = ["rapport", "fill_template", "comparatif", "analyse_regroupement", "presentation"]


def _job(type_job, **params):
    from models.job import Job
    base = {"model": GECO, "origine": "GECO", "proprietaire": "admin-fictif", "proprietaire_role": "admin",
            "prompt": "p", "document_ids": [], "sources": []}
    return Job(type=type_job, statut="running", progress=0, parametres={**base, **params})


async def _lancer(db_session, job):
    from services import job_worker
    db_session.add(job)
    await db_session.commit()
    jid = str(job.id)
    await job_worker._run(jid)
    from models.job import Job
    async with async_sessionmaker(db_session.bind, expire_on_commit=False)() as db:
        return await db.get(Job, uuid.UUID(jid))


class TestWorker:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("type_job", TYPES_INTERACTIFS)
    async def test_bouton_local_zero_requete_sur_chaque_type_interactif(self, db_session, base_geco, reseau,
                                                                        type_job):
        await base_geco.ecrire("local")       # remis sur LOCAL entre l'enqueue et l'exécution
        relu = await _lancer(db_session, _job(type_job))
        assert reseau.geco == []
        assert relu.statut == "failed" and "revenu sur LOCAL" in relu.erreur
        assert await base_geco.evenements() == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("type_job", TYPES_INTERACTIFS)
    async def test_auteur_non_administrateur_refuse(self, db_session, base_geco, reseau, type_job):
        await base_geco.ecrire("geco")
        for role, auteur in (("utilisateur", "marie-fictive"), ("jeton", "jeton:n8n-fictif"), (None, None)):
            job = _job(type_job, proprietaire_role=role, proprietaire=auteur)
            if role is None:
                job.parametres = {k: v for k, v in job.parametres.items()
                                  if k not in ("proprietaire", "proprietaire_role")}
            relu = await _lancer(db_session, job)
            assert relu.statut == "failed" and "réservée à l'administrateur" in relu.erreur + "réservée à l'administrateur" \
                or "automates" in relu.erreur, (type_job, role)
            assert reseau.geco == []

    @pytest.mark.asyncio
    async def test_job_sans_marque_ou_de_fond_refuse(self, db_session, base_geco, reseau):
        await base_geco.ecrire("geco")
        sans_marque = _job("rapport")
        sans_marque.parametres = {k: v for k, v in sans_marque.parametres.items() if k != "origine"}
        assert "confirmé" in (await _lancer(db_session, sans_marque)).erreur
        for type_job in ("ia_enrich", "ia_embed", "ia_contenu", "indexation", "musique", "video", "comparatif_reparer"):
            relu = await _lancer(db_session, _job(type_job))
            assert relu.statut == "failed" and "interactives" in relu.erreur, type_job
        assert reseau.geco == []

    @pytest.mark.asyncio
    async def test_rapport_bouton_geco_envoi_signale_journalise_auteur_du_job(self, db_session, base_geco, reseau):
        await base_geco.ecrire("geco")
        relu = await _lancer(db_session, _job("rapport"))
        assert relu.statut == "completed", relu.erreur
        assert len(reseau.geco) == 1
        envoi = reseau.geco[0]
        assert envoi.headers["X-AI-Sortie"] == "geco" and envoi.headers["X-AI-Usage"] == "rapport"
        assert json.loads(envoi.content)["model"] == GECO
        (ligne,) = await base_geco.evenements()
        assert ligne.auteur == "admin-fictif" and ligne.detail["origine"] == "job:rapport"
        assert ligne.acteur == "worker"

    @pytest.mark.asyncio
    async def test_worker_local_non_regresse(self, db_session, base_geco, reseau):
        await base_geco.ecrire("local")
        relu = await _lancer(db_session, _job("rapport", model="llama3.1:latest", origine=None))
        assert relu.statut == "completed", relu.erreur
        assert reseau.geco == [] and any(r.url.path == "/api/generate" for r in reseau.requetes)

    @pytest.mark.parametrize("type_job", TYPES_INTERACTIFS)
    @pytest.mark.asyncio
    async def test_controle_job_accepte_admin_marque_bouton_geco(self, base_geco, type_job):
        from services import modeles_externes
        await base_geco.ecrire("geco")
        assert await modeles_externes.controle_job(
            type_job, {"model": GECO, "origine": "GECO", "proprietaire_role": "admin"}) is None

    @pytest.mark.asyncio
    async def test_controle_job_lit_la_base_pas_le_cache(self, base_geco):
        from services import modeles_externes
        await base_geco.ecrire("local")
        _regler(ia_destination="geco")           # cache périmé
        params = {"model": GECO, "origine": "GECO", "proprietaire_role": "admin"}
        assert "revenu sur LOCAL" in await modeles_externes.controle_job("rapport", params)

    @pytest.mark.asyncio
    async def test_controle_job_modele_local_ou_absent_inchange(self):
        from services import modeles_externes
        assert await modeles_externes.controle_job("ia_enrich", {"model": "llama3.1"}) is None
        assert await modeles_externes.controle_job("rapport", {}) is None
        assert await modeles_externes.controle_job("rapport", None) is None

    @pytest.mark.asyncio
    async def test_controle_job_modele_effectif_du_regroupement(self, base_geco):
        from services import modeles_externes
        await base_geco.ecrire("geco")
        assert await modeles_externes.controle_job("analyse_regroupement", {"proprietaire_role": "admin"}, GECO)
        assert await modeles_externes.controle_job(
            "analyse_regroupement", {"origine": "GECO", "proprietaire_role": "admin"}, GECO) is None

    @pytest.mark.asyncio
    async def test_enqueue_enregistre_l_auteur_et_son_role(self, db_session, journal, acteur_admin):
        from models.job import Job
        from services import job_worker
        jid = await job_worker.enqueue(db_session, "rapport", {"prompt": "x"})
        job = await db_session.get(Job, uuid.UUID(jid))
        assert job.parametres["proprietaire"] == "admin-fictif" and job.parametres["proprietaire_role"] == "admin"

    @pytest.mark.asyncio
    async def test_comparatif_reparer_refuse_un_comparatif_geco(self, db_session, monkeypatch):
        from models.job import Job
        from services import compare_jobs
        from services.job_worker import JobContext
        monkeypatch.setattr(compare_jobs, "AsyncSessionLocal",
                            async_sessionmaker(db_session.bind, expire_on_commit=False))
        original = Job(type="comparatif", statut="completed", progress=100, resultat={"groupes": []},
                       parametres={"model": GECO, "origine": "GECO", "groupes": []})
        db_session.add(original)
        await db_session.commit()
        ctx = JobContext("j", "comparatif_reparer", {"job_id": str(original.id)}, None)
        with pytest.raises(ValueError, match="GECO"):
            await compare_jobs.handler_comparatif_reparer(ctx)


# ─── ErreurGeco jamais avalée (C5) ────────────────────────────────────────────

class TestErreurGecoNonAvalee:
    @staticmethod
    def _ollama_en_refus():
        from services.ollama_service import erreur_http_geco
        ollama = MagicMock()
        ollama.generate = AsyncMock(side_effect=erreur_http_geco(403))
        return ollama

    @pytest.mark.asyncio
    async def test_deduire_colonnes_synthese_fiche_grille_recommandation(self):
        from routers.compare import _analyser_groupe, _deduire_colonnes, _synthetiser_ecarts
        from services.fiches_candidats import rediger_fiche
        from services.ollama_service import ErreurGeco
        from services.recommandation_comparatif import recommander
        ollama = self._ollama_en_refus()
        docs = [_doc()]
        with pytest.raises(ErreurGeco):
            await _deduire_colonnes(docs, None, GECO, ollama)
        with pytest.raises(ErreurGeco):
            await _analyser_groupe(nom_groupe="A", docs=docs, colonnes=["Prix"], instructions=None, model=GECO,
                                   ollama=ollama)
        with pytest.raises(ErreurGeco):
            await _synthetiser_ecarts(["Prix"], [{"nom": "A", "valeurs": {"Prix": "1"}},
                                                 {"nom": "B", "valeurs": {"Prix": "2"}}], None, GECO, ollama)
        with pytest.raises(ErreurGeco):
            await rediger_fiche("A", {"Prix": "1"}, None, GECO, ollama)
        with pytest.raises(ErreurGeco):
            await recommander("| a |", [{"nom": "A"}, {"nom": "B"}], None, None, None, GECO, ollama)
        assert ollama.generate.await_count == 5       # un seul appel chacun : aucun deuxième essai

    @pytest.mark.asyncio
    async def test_evaluer_critere_de_grille(self):
        from services import grille_analyse
        from services.ollama_service import ErreurGeco
        ollama = self._ollama_en_refus()
        critere = grille_analyse.Critere(ligne=1, libelle="Prix", documents="", points=None)
        with pytest.raises(ErreurGeco):
            await grille_analyse.evaluer_critere("A", critere, [_doc()], None, GECO, ollama, contexte="ctx",
                                                 note_max=20)
        assert ollama.generate.await_count == 1

    @pytest.mark.asyncio
    async def test_qa_comprendre_et_extraire_un_ne_mettent_rien_en_cache(self):
        from services import qa_service
        from services.ollama_service import ErreurGeco, erreur_http_geco
        qa_service._FAITS_CACHE.clear()
        cand = {"id": "doc-1", "nom": "a.pdf", "texte": "du texte", "extension": "pdf", "categorie": None,
                "score": 1, "pertinence": 1}
        with patch("services.qa_service.OllamaService") as cls:
            cls.return_value.generate = AsyncMock(side_effect=erreur_http_geco(403))
            with pytest.raises(ErreurGeco):
                await qa_service.comprendre("question ?", GECO)
            with pytest.raises(ErreurGeco):
                await qa_service.extraire_un(cand, GECO)
        assert "doc-1" not in qa_service._FAITS_CACHE
        with patch("services.qa_service.OllamaService") as cls:       # échec ORDINAIRE : pas non plus en cache
            cls.return_value.generate = AsyncMock(side_effect=RuntimeError("panne"))
            await qa_service.extraire_un(cand, "llama3.1")
        assert "doc-1" not in qa_service._FAITS_CACHE

    @pytest.mark.asyncio
    async def test_extraire_faits_borne_a_4_et_annule_au_premier_refus(self):
        import asyncio
        from services import qa_service
        from services.ollama_service import ErreurGeco, erreur_http_geco
        en_vol = 0
        pic = 0
        appels = 0

        async def lent(cand, model):
            nonlocal en_vol, pic, appels
            appels += 1
            en_vol += 1
            pic = max(pic, en_vol)
            await asyncio.sleep(0.02)
            en_vol -= 1
            return {"id": cand["id"]}

        with patch.object(qa_service, "extraire_un", lent):
            assert len(await qa_service.extraire_faits([{"id": str(i)} for i in range(12)], "m")) == 12
        assert pic == 4

        appels = 0

        async def refus(cand, model):
            nonlocal appels
            appels += 1
            await asyncio.sleep(0.01)
            raise erreur_http_geco(403)

        with patch.object(qa_service, "extraire_un", refus):
            with pytest.raises(ErreurGeco):
                await qa_service.extraire_faits([{"id": str(i)} for i in range(12)], "m")
        assert appels <= 4                        # le refus arrête les appels suivants

    def test_cause_echec_ia_connait_erreur_geco(self):
        from services import cause_echec_ia
        from services.ollama_service import erreur_http_geco
        assert "n'est pas autorisée à sortir vers GECO" in cause_echec_ia.cause_erreur(erreur_http_geco(403))

    @pytest.mark.asyncio
    async def test_comparatif_s_arrete_au_premier_refus_et_le_job_echoue_avec_le_message_geco(
            self, db_session, base_geco, reseau):
        """Handler réel : un refus 403 de l'AIGUILLEUR au premier envoi ; ni 2e essai, ni groupe suivant."""
        await base_geco.ecrire("geco")
        reseau.surcharge = lambda r: (httpx.Response(403, json={"code": "projet_non_autorise"})
                                      if r.url.path == CHEMIN_GECO else None)
        job = _job("comparatif", groupes=[{"nom": "A", "document_ids": []}, {"nom": "B", "document_ids": []}],
                   colonnes=["Prix"], synthese=False, fiches=False)
        with patch("routers.compare._charger_documents", new=AsyncMock(return_value=[_doc()])):
            relu = await _lancer(db_session, job)
        assert relu.statut == "failed" and "n'est pas autorisée à sortir vers GECO" in relu.erreur
        assert len(reseau.geco) == 1


# ─── Réglages : validation à l'écriture ───────────────────────────────────────

class TestValidationReglages:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("cle", ["default_model", "vision_model"])
    @pytest.mark.parametrize("nom", [GECO, "geco/jamais-liste", "sans-prefixe", "GECO/x", "ＧＥＣＯ/x"])
    async def test_nom_geco_refuse_422(self, appli, liste_ok, cle, nom):
        resp = await _put(appli, **{cle: nom})
        assert resp.status_code == 422, resp.text
        assert cle in resp.json()["detail"] and "GECO" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_usage_models_json_avec_geco_422(self, appli, liste_ok):
        resp = await _put(appli, usage_models=json.dumps({"rapport": "llama3.1", "chat": GECO}))
        assert resp.status_code == 422 and "usage_models" in resp.json()["detail"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("valeur", [123, None, ["geco/x"], {"a": 1}, True])
    async def test_usage_models_valeur_non_chaine_422(self, appli, liste_ok, valeur):
        resp = await _put(appli, usage_models=json.dumps({"rapport": valeur}))
        assert resp.status_code == 422 and "usage_models" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_usage_models_local_accepte(self, appli, liste_ok):
        resp = await _put(appli, usage_models=json.dumps({"rapport": "ministral-3:14b"}),
                          default_model="llama3.1:latest", vision_model="qwen2.5vl:7b")
        assert resp.status_code == 200, resp.text

    @pytest.mark.asyncio
    async def test_nom_local_accepte_liste_geco_muette_et_prefixe_refuse(self, appli):
        assert (await _put(appli, default_model="llama3.1:latest")).status_code == 200
        assert (await _put(appli, default_model="geco/x")).status_code == 422

    @pytest.mark.asyncio
    async def test_geco_modele_doit_etre_dans_la_liste(self, appli, liste_ok, ecriture_geco_ok):
        assert (await _put(appli, geco_modele="geco/inconnu")).status_code == 422
        assert (await _put(appli, geco_modele="sans-prefixe")).status_code == 422
        resp = await _put(appli, geco_modele=EMBED)
        assert resp.status_code == 422 and "embeddings" in resp.json()["detail"]
        ok = await _put(appli, geco_modele=GECO)
        assert ok.status_code == 200 and "geco_modele" in ok.json()["mis_a_jour"]

    @pytest.mark.asyncio
    async def test_geco_modele_liste_indisponible_422(self, appli, ecriture_geco_ok):
        resp = await _put(appli, geco_modele=GECO)
        assert resp.status_code == 422 and "liste" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_ia_destination_valeur_invalide_422(self, appli, liste_ok):
        assert (await _put(appli, ia_destination="internet")).status_code == 422

    @pytest.mark.asyncio
    async def test_geco_exige_un_modele_et_une_liste_disponible(self, appli, liste_ok, ecriture_geco_ok):
        resp = await _put(appli, ia_destination="geco")
        assert resp.status_code == 422 and "geco_modele" in resp.json()["detail"]
        _regler(geco_modele=GECO)
        resp = await _put(appli, ia_destination="geco", modeles_externes_url="")
        assert resp.status_code == 422 and "modeles_externes_url" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_geco_liste_indisponible_422(self, appli, ecriture_geco_ok):
        _regler(geco_modele=GECO)
        resp = await _put(appli, ia_destination="geco")
        assert resp.status_code == 422 and "liste GECO" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_passage_a_geco_revalide_les_reglages_deja_en_base(self, appli, liste_ok, ecriture_geco_ok):
        for reglage in ({"default_model": GECO}, {"vision_model": "geco/x"},
                        {"usage_models": json.dumps({"chat": GECO})}):
            _regler(**reglage)
            resp = await _put(appli, ia_destination="geco", geco_modele=GECO)
            assert resp.status_code == 422, reglage
            from services import runtime_config
            for cle in reglage:
                runtime_config._overrides.pop(cle, None)

    @pytest.mark.asyncio
    async def test_passage_a_geco_revalide_le_defaut_d_environnement(self, appli, liste_ok, ecriture_geco_ok,
                                                                    monkeypatch):
        monkeypatch.setattr("routers.system.settings", SimpleNamespace(ollama_model_default=GECO,
                                                                        **{}), raising=False)
        resp = await _put(appli, ia_destination="geco", geco_modele=GECO)
        assert resp.status_code == 422 and "environnement" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_geco_et_modele_dans_la_meme_requete_puis_retour_local(self, appli, liste_ok, ecriture_geco_ok,
                                                                         journal):
        from services import modeles_externes
        resp = await _put(appli, ia_destination="geco", geco_modele=GECO)
        assert resp.status_code == 200, resp.text
        assert modeles_externes.destination_ia() == "geco"
        resp = await _put(appli, ia_destination="local")
        assert resp.status_code == 200 and modeles_externes.destination_ia() == "local"

    @pytest.mark.asyncio
    async def test_vider_la_destination_revient_a_local_et_journalise(self, appli, liste_ok, ecriture_geco_ok,
                                                                      journal):
        from services import modeles_externes
        _regler(ia_destination="geco", geco_modele=GECO)
        resp = await _put(appli, ia_destination="")
        assert resp.status_code == 200 and modeles_externes.destination_ia() == "local"
        assert len([e for e in journal if e["action"] == "ia_destination"]) == 1

    @pytest.mark.asyncio
    async def test_pas_de_changement_pas_de_journal(self, appli, liste_ok, journal):
        assert (await _put(appli, ia_destination="local")).status_code == 200
        assert [e for e in journal if e["action"] == "ia_destination"] == []

    @pytest.mark.asyncio
    async def test_vider_geco_modele_en_mode_geco_422(self, appli, liste_ok, ecriture_geco_ok):
        _regler(ia_destination="geco", geco_modele=GECO)
        assert (await _put(appli, geco_modele="")).status_code == 422

    @pytest.mark.asyncio
    async def test_reglages_ia_visibles_dans_la_config(self, appli):
        resp = await _get(appli, "/api/system/config")
        config = resp.json()["config"]
        assert config["ia_destination"]["valeur"] == "local" and config["geco_modele"]["valeur"] == ""
        assert config["geco_timeout_s"]["valeur"] == "300"


class TestAuthentificationEtRoleDeLEcriture:
    """B3 : activer « IA GECO » ou écrire `geco_modele` exige authentification active + SESSION administrateur."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corps", [{"ia_destination": "geco", "geco_modele": GECO}, {"geco_modele": GECO}])
    async def test_refus_403_sans_authentification_active(self, appli, liste_ok, corps):
        resp = await _put(appli, **corps)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Activer « IA GECO » exige l'authentification active et un compte administrateur"
        from services import modeles_externes
        assert modeles_externes.destination_ia() == "local"

    @pytest.mark.asyncio
    async def test_revenir_a_local_reste_permis(self, appli, liste_ok):
        _regler(ia_destination="geco", geco_modele=GECO)
        resp = await _put(appli, ia_destination="local")
        assert resp.status_code == 200

    @pytest.mark.parametrize("auth, user, attendu", [
        (True, SimpleNamespace(role="admin"), True),
        (True, SimpleNamespace(role="utilisateur"), False),
        (True, None, False),                                      # jeton ou anonyme : pas de session
        (False, SimpleNamespace(role="admin"), False),            # authentification inactive
    ])
    def test_ecriture_geco_autorisee(self, monkeypatch, auth, user, attendu):
        from routers import system
        monkeypatch.setattr(system.oidc_service, "auth_active", lambda: auth)
        requete = SimpleNamespace(state=SimpleNamespace(utilisateur=user))
        assert system._ecriture_geco_autorisee(requete) is attendu

    def test_ecriture_geco_refusee_pendant_une_suspension(self, monkeypatch):
        """Suspension de secours : pas d'activation, meme avec la session d'un administrateur."""
        from datetime import datetime, timezone
        from routers import system
        monkeypatch.setattr(system.oidc_service, "auth_active", lambda: True)
        admin = SimpleNamespace(role="admin")
        en_vigueur = SimpleNamespace(state=SimpleNamespace(utilisateur=admin, suspension=None))
        suspendue = SimpleNamespace(state=SimpleNamespace(utilisateur=admin, suspension=datetime.now(timezone.utc)))
        assert system._ecriture_geco_autorisee(en_vigueur) is True
        assert system._ecriture_geco_autorisee(suspendue) is False


# ─── Listes d'Ollama : jamais de modèle GECO ──────────────────────────────────

class TestTagsSansGeco:
    @pytest.mark.asyncio
    async def test_list_models_et_detailed_filtrent_geco(self):
        from services.ollama_service import OllamaService
        tags = {"models": [{"name": "llama3.1:latest", "size": 1}, {"name": GECO, "size": 1},
                           {"name": "GECO/x", "size": 1}]}
        with _faux_client(lambda r: _json(tags)), patch("services.ollama_service.log") as log:
            service = OllamaService(base_url=BASE_AIGUILLEUR)
            assert await service.list_models() == ["llama3.1:latest"]
            assert [m["name"] for m in await service.list_models_detailed()] == ["llama3.1:latest"]
        assert log.error.called

    @pytest.mark.asyncio
    async def test_model_candidates_filtre_geco(self):
        from services import runtime_config
        _regler(default_model=GECO.replace("geco/", ""))
        faux = MagicMock()
        faux.list_models_detailed = AsyncMock(return_value=[{"name": "llama3.1:latest", "size": 1},
                                                            {"name": GECO, "size": 2}])
        with patch("services.ollama_service.OllamaService", return_value=faux):
            assert GECO not in await runtime_config.model_candidates("rapport")
        faux.list_models_detailed = AsyncMock(side_effect=ConnectionError("down"))
        _regler(usage_models=json.dumps({"rapport": GECO}))
        with patch("services.ollama_service.OllamaService", return_value=faux):
            assert await runtime_config.model_candidates("rapport") == []


# ─── Routes de lecture ────────────────────────────────────────────────────────

def _detailles(noms):
    return [{"name": n, "size": 1000, "digest": "d", "famille": "llama", "parametres": "8B"} for n in noms]


async def _modeles(appli):
    instance = MagicMock()
    instance.list_models_detailed = AsyncMock(return_value=_detailles(INSTALLES))
    with patch("routers.system.OllamaService", return_value=instance):
        return (await _get(appli, "/api/system/models")).json()


class TestRoutesLecture:
    @pytest.mark.asyncio
    async def test_models_geco_selectionnables_bouton_actif_admin_liste_disponible(self, appli, liste_ok, mode_geco):
        data = await _modeles(appli)
        assert data["externes_etat"] == "disponible"
        par_nom = {m["name"]: m for m in data["externes"]}
        assert par_nom[GECO]["selectionnable"] is True and par_nom[GECO]["origine"] == "GECO"
        assert par_nom[GECO]["embedding"] is False
        assert par_nom["sans-prefixe"]["selectionnable"] is False
        assert par_nom[EMBED]["embedding"] is True and par_nom[EMBED]["selectionnable"] is False
        assert (data["ia_destination"], data["geco_modele"]) == ("geco", GECO)
        assert all(m["origine"] == "MATO" and m["selectionnable"] is True for m in data["models"])

    @pytest.mark.asyncio
    async def test_models_geco_non_selectionnables_bouton_desactive(self, appli, liste_ok, acteur_admin):
        data = await _modeles(appli)
        assert data["ia_destination"] == "local"
        assert data["externes"] and all(m["selectionnable"] is False for m in data["externes"])

    @pytest.mark.asyncio
    async def test_models_geco_non_selectionnables_sans_acteur_admin(self, appli, liste_ok):
        _regler(ia_destination="geco", geco_modele=GECO)
        data = await _modeles(appli)
        assert all(m["selectionnable"] is False for m in data["externes"])

    @pytest.mark.asyncio
    async def test_models_liste_absente_defauts(self, appli):
        data = await _modeles(appli)
        assert data["externes"] == [] and data["externes_etat"] == "non_configure"
        assert (data["ia_destination"], data["geco_modele"]) == ("local", "")

    @pytest.mark.asyncio
    async def test_route_destination_administrateur_etat_reel(self, appli, acteur_admin):
        assert (await _get(appli, "/api/system/ia/destination")).json() == {"destination": "local", "geco_modele": ""}
        _regler(ia_destination="geco", geco_modele=GECO)
        assert (await _get(appli, "/api/system/ia/destination")).json() == {"destination": "geco", "geco_modele": GECO}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("acteur", ["acteur_utilisateur", "acteur_jeton", None])
    async def test_route_destination_toujours_local_pour_un_non_administrateur(self, request, appli, acteur):
        if acteur:
            request.getfixturevalue(acteur)
        _regler(ia_destination="geco", geco_modele=GECO)
        assert (await _get(appli, "/api/system/ia/destination")).json() == {"destination": "local", "geco_modele": ""}

    def test_droits_d_acces(self):
        """Lecture ouverte à tout utilisateur connecté ; l'écriture (bascule) reste administrateur."""
        from services import acces
        assert acces.classer("GET", "/api/system/ia/destination") == acces.UTILISATEUR
        assert acces.classer("PUT", "/api/system/config") == acces.ADMIN
        assert acces.classer("GET", "/api/system/config") == acces.ADMIN


# ─── Test STATIQUE : un seul chemin d'envoi ───────────────────────────────────

class TestStatique:
    RACINE = Path(__file__).resolve().parent.parent

    def _fichiers(self):
        return [p for p in self.RACINE.rglob("*.py")
                if "tests" not in p.relative_to(self.RACINE).parts and "__pycache__" not in p.parts]

    def test_chemin_v1_chat_completions_seulement_dans_les_fonctions_d_envoi_geco(self):
        autorises = {"_generate_geco", "_stream_geco"}
        trouves = []
        for fichier in self._fichiers():
            texte = fichier.read_text(encoding="utf-8")
            if CHEMIN_GECO not in texte:
                continue
            assert fichier.name == "ollama_service.py", f"{fichier} mentionne {CHEMIN_GECO}"
            arbre = ast.parse(texte)
            parents = {}
            for noeud in ast.walk(arbre):
                for enfant in ast.iter_child_nodes(noeud):
                    parents[enfant] = noeud
            for noeud in ast.walk(arbre):
                if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str) and noeud.value == CHEMIN_GECO:
                    parent = noeud
                    while parent in parents and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        parent = parents[parent]
                    trouves.append(parent.name if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)) else None)
        assert trouves and set(trouves) <= autorises, trouves

    def test_en_tete_x_ai_sortie_seulement_dans_le_chemin_geco(self):
        for fichier in self._fichiers():
            texte = fichier.read_text(encoding="utf-8")
            if "X-AI-Sortie" in texte:
                assert fichier.name == "ollama_service.py", fichier
                arbre = ast.parse(texte)
                for noeud in ast.walk(arbre):
                    if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)) and noeud.name == "entetes_projet":
                        assert "X-AI-Sortie" not in ast.get_source_segment(texte, noeud).replace(
                            ast.get_docstring(noeud) or "", "")

    def test_aucune_route_n_envoie_sans_resoudre_le_modele(self):
        """Les routes qui parlent à l'IA passent par `resoudre_modele_interactif` (ou `_resoudre_complet`)."""
        for nom in ("generate", "compare", "regroupements", "assistant", "prompts", "presentations"):
            texte = (self.RACINE / "routers" / f"{nom}.py").read_text(encoding="utf-8")
            assert "resoudre_modele_interactif" in texte or "_resoudre_complet" in texte, nom
            assert "exiger_modele_installe" not in texte and "sortie_confirmee" not in texte, nom


# ─── Authentification en vigueur : active ET non suspendue, relue en base ─────

def _echeance(heures: float) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(hours=heures)).isoformat()


class TestAuthentificationEnVigueur:
    """
    « Authentification inactive ou suspendue » = on reste en local (décision de Thomas). Pendant une
    suspension de secours, toute personne qui joint l'API a tous les droits : « administrateur » ne
    veut plus rien dire, donc rien ne sort — même pour une tâche mise en file avant.
    """

    @pytest.mark.asyncio
    async def test_envoi_refuse_zero_requete_zero_journal(self, mode_geco, journal, monkeypatch):
        from services.ollama_service import ErreurGeco
        monkeypatch.setattr("services.ollama_service.authentification_en_base", AsyncMock(return_value=False))
        appels = []
        with _faux_client(lambda r: (appels.append(r), _reponse_chat())[1]):
            with pytest.raises(ErreurGeco) as exc:
                await _generer()
            with pytest.raises(ErreurGeco):
                await _flux()
        assert exc.value.status_code == 403 and "authentification" in str(exc.value)
        assert appels == [] and journal == []

    @pytest.mark.asyncio
    async def test_lecture_en_base(self, base_geco):
        from services.ollama_service import authentification_en_base
        await base_geco.ecrire("geco")
        assert await authentification_en_base() is True
        for valeur in ("false", "0", "", "autre chose"):
            await base_geco.ecrire("geco", auth=valeur)
            assert await authentification_en_base() is False, valeur
        await base_geco.ecrire("geco", auth=None)                       # ligne absente = éteinte
        assert await authentification_en_base() is False
        await base_geco.ecrire("geco", suspension=_echeance(2))         # suspension de secours en cours
        assert await authentification_en_base() is False
        await base_geco.ecrire("geco", suspension=_echeance(-1))        # échue : le contrôle a repris
        assert await authentification_en_base() is True
        await base_geco.ecrire("geco", suspension=_echeance(48))        # au-delà du plafond : ignorée
        assert await authentification_en_base() is True

    @pytest.mark.asyncio
    async def test_lecture_impossible_refuse(self, monkeypatch):
        from services.ollama_service import authentification_en_base

        def en_panne():
            raise RuntimeError("base injoignable")

        monkeypatch.setattr("services.ollama_service.AsyncSessionLocal", en_panne)
        assert await authentification_en_base() is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cas", ["eteinte", "absente", "suspendue"])
    async def test_job_mis_en_file_par_un_admin_puis_auth_coupee_zero_requete(self, db_session, base_geco,
                                                                               reseau, cas):
        """Le rôle de l'auteur est figé à la mise en file : c'est l'état en base, à l'exécution, qui tranche."""
        etat = {"eteinte": {"auth": "false"}, "absente": {"auth": None},
                "suspendue": {"suspension": _echeance(2)}}[cas]
        await base_geco.ecrire("geco", **etat)
        relu = await _lancer(db_session, _job("rapport"))
        assert relu.statut == "failed" and "éteinte ou suspendue" in relu.erreur
        assert reseau.geco == [] and await base_geco.evenements() == []


# ─── Un modèle ENREGISTRÉ reste local ─────────────────────────────────────────

class TestModeleEnregistre:
    def test_refus_des_noms_geco_seulement(self):
        from fastapi import HTTPException
        from services.modeles_externes import refuser_geco_enregistre
        for nom in (None, "", "llama3.1:latest", "ministral-3:14b"):
            refuser_geco_enregistre(nom, "Modèle")
        for nom in (GECO, "  geco/autre ", "GECO/Majuscules"):
            with pytest.raises(HTTPException) as exc:
                refuser_geco_enregistre(nom, "Modèle du regroupement")
            assert exc.value.status_code == 422 and "Modèle du regroupement" in exc.value.detail

    @pytest.mark.asyncio
    async def test_regroupement_creation_et_modification(self, appli):
        assert (await _post(appli, "/api/regroupements", nom="Devis", modele=GECO)).status_code == 422
        cree = await _post(appli, "/api/regroupements", nom="Devis", modele="llama3.1:latest")
        assert cree.status_code == 200 and cree.json()["modele"] == "llama3.1:latest"
        rid = cree.json()["id"]
        async with AsyncClient(transport=ASGITransport(app=appli), base_url="http://test") as c:
            refus = await c.put(f"/api/regroupements/{rid}", json={"modele": GECO})
            garde = await c.get(f"/api/regroupements/{rid}")
            autre = await c.put(f"/api/regroupements/{rid}", json={"prompt": "Compare."})
        assert refus.status_code == 422 and "GECO" in refus.json()["detail"]
        assert garde.json()["modele"] == "llama3.1:latest"          # le refus n'a rien écrit
        assert autre.status_code == 200 and autre.json()["prompt"] == "Compare."

    @pytest.mark.asyncio
    async def test_prompt_modele_prefere(self, appli):
        refus = await _post(appli, "/api/prompts", nom="P", prompt_text="Résume.", modele_prefere=GECO)
        assert refus.status_code == 422 and "Modèle préféré du prompt" in refus.json()["detail"]
        cree = await _post(appli, "/api/prompts", nom="P", prompt_text="Résume.", modele_prefere="llama3.1:latest")
        assert cree.status_code == 201
        identifiant = cree.json()["id"]
        async with AsyncClient(transport=ASGITransport(app=appli), base_url="http://test") as c:
            modif = await c.put(f"/api/prompts/{identifiant}", json={"modele_prefere": "geco/autre"})
        assert modif.status_code == 422
