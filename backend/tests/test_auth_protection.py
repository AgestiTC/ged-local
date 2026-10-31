"""
Tests — protection de toutes les routes de l'API (plan d'authentification, étape 2)
===================================================================================
Données 100 % fictives, aucun appel réseau. Les sessions sont créées directement en base (le
parcours SSO lui-même est couvert par test_auth_oidc.py) ; seul l'exigence 9 rejoue le callback,
avec un SSO simulé par monkeypatch.

Le test « toutes les routes » énumère `app.routes` AU MOMENT DU TEST : une route ajoutée demain
sans être classée (services/acces.py) fait échouer ce fichier.
"""

import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from models.audit import AuditEvent
from models.auth import SessionAuth, Utilisateur
from models.config import Config
from services import acces, oidc_service, runtime_config

ISSUER = "https://sso.test.invalid/webman/sso"
CLIENT_ID = "matotheque-test"
REDIRECT = "https://ged.test.invalid/api/auth/callback"
SYNC = {"Sec-Fetch-Site": "same-origin"}   # ce qu'envoie un navigateur depuis l'application elle-même


@pytest_asyncio.fixture
async def client(db_session):
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_on():
    runtime_config._overrides["auth_active"] = "true"


@pytest.fixture
def oidc_configure():
    runtime_config._overrides.update({"oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID,
                                      "oidc_redirect_uri": REDIRECT})


async def creer_session(db, role="utilisateur", *, bloque=False, sub=None, identifiant=None) -> str:
    """Fiche + session en base ; rend la valeur du cookie."""
    sub = sub or f"sub-{role}-{datetime.now().timestamp()}"
    now = datetime.now(timezone.utc)
    u = Utilisateur(emetteur=oidc_service.emetteur_configure(), sub=sub, role=role, bloque=bloque,
                    identifiant=identifiant or role, nom=f"{role.title()} Fictif", groupes=[])
    db.add(u)
    await db.flush()
    jeton = f"jeton-fictif-{sub}"
    db.add(SessionAuth(id=oidc_service.hacher_jeton(jeton), utilisateur_id=u.id, creee=now,
                       derniere_activite=now, expire_max=now + timedelta(days=1)))
    await db.commit()
    return jeton


async def ajouter_fiche(db, role="admin", *, bloque=False, emetteur=ISSUER, sub="sub-fiche") -> None:
    """Fiche locale seule (sans session) : « cette personne s'est déjà connectée une fois »."""
    db.add(Utilisateur(emetteur=emetteur, sub=sub, role=role, bloque=bloque, identifiant=role, groupes=[]))
    await db.commit()


def cookie(jeton: str) -> dict:
    return {"Cookie": f"matotheque_session={jeton}"}


def chemin_factice(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x", path)


def toutes_les_routes():
    """(méthode, modèle de chemin) pour TOUTES les routes montées — API ou non (docs…)."""
    from main import app
    paires = []
    for r in app.routes:
        for m in sorted(getattr(r, "methods", None) or []):
            paires.append((m, r.path))
    return paires


# ─── Démarrage à froid : réglages jamais chargés = on ne sait pas si l'auth est active ─

class TestDemarrageAFroid:
    @pytest.mark.asyncio
    async def test_reglages_jamais_charges_503(self, client, monkeypatch):
        monkeypatch.setattr(runtime_config, "_charge_reussi", False)
        for chemin in ("/api/prompts", "/api/auth/me", "/api/system/config", "/health", "/api/auth/login"):
            r = await client.get(chemin)
            assert r.status_code == 503 and r.json() == {"detail": "Réglages indisponibles"}, chemin
        r = await client.post("/api/documents/analyze-batch", json={})
        assert r.status_code == 503

    @pytest.mark.asyncio
    async def test_healthz_et_version_restent_joignables(self, client, monkeypatch):
        monkeypatch.setattr(runtime_config, "_charge_reussi", False)
        assert (await client.get("/healthz")).status_code == 200
        assert (await client.get("/api/version")).status_code == 200

    @pytest.mark.asyncio
    async def test_un_chargement_reussi_leve_le_blocage(self, client, db_session, monkeypatch):
        monkeypatch.setattr(runtime_config, "_charge_reussi", False)
        await runtime_config.load(db_session)
        assert runtime_config._charge_reussi is True
        assert (await client.get("/api/prompts")).status_code == 200

    @pytest.mark.asyncio
    async def test_un_chargement_en_echec_ne_leve_pas_le_blocage(self, monkeypatch):
        monkeypatch.setattr(runtime_config, "_charge_reussi", False)

        class BaseHS:
            async def execute(self, *a, **k):
                raise RuntimeError("base indisponible")

        with pytest.raises(RuntimeError):
            await runtime_config.load(BaseHS())
        assert runtime_config._charge_reussi is False


# ─── Liste blanche stricte ────────────────────────────────────────────────────

ATTENDUE = {"/api/version", "/healthz", "/api/auth/login", "/api/auth/callback",
            "/api/auth/logout", "/api/auth/me", "/api/passerelle/publish"}


class TestListeBlanche:
    def test_liste_exacte(self):
        assert set(acces.LISTE_BLANCHE) == ATTENDUE

    @pytest.mark.asyncio
    @pytest.mark.parametrize("methode,chemin", [
        ("GET", "/api/version"), ("GET", "/healthz"), ("GET", "/api/auth/me"),
        ("POST", "/api/auth/logout"), ("GET", "/api/auth/login"), ("GET", "/api/auth/callback"),
    ])
    async def test_accessible_sans_session(self, client, auth_on, methode, chemin):
        r = await client.request(methode, chemin)
        assert r.status_code not in (401, 403), r.text
        if chemin in ("/api/version", "/healthz", "/api/auth/me"):
            assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_publish_a_son_propre_jeton(self, client, auth_on):
        """Hors du contrôle de session, mais PAS ouverte : son jeton Bearer reste exigé."""
        r = await client.post("/api/passerelle/publish", json={"pages": []})
        assert r.status_code == 401 and "Jeton de publication" in r.json()["detail"]
        r = await client.post("/api/passerelle/publish", json={"pages": []},
                              headers={"Authorization": "Bearer faux-jeton"})
        assert r.status_code == 401 and "Jeton de publication" in r.json()["detail"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("chemin", [
        "/api/auth/loginx", "/api/auth/login/", "/api/auth/", "/api/version/x", "/api/versions",
        "/api/auth/login/../documents", "/healthz/", "/health", "//api/documents",
    ])
    async def test_correspondance_exacte_pas_de_prefixe(self, client, auth_on, chemin):
        r = await client.get(chemin)
        assert r.status_code == 401 and r.json() == {"detail": "Authentification requise"}


# ─── Toutes les routes ────────────────────────────────────────────────────────

class TestToutesLesRoutes:
    @pytest.mark.asyncio
    async def test_aucune_route_ouverte_hors_liste_blanche(self, client, auth_on):
        ouvertes = []
        for methode, path in toutes_les_routes():
            if path in ATTENDUE:
                continue
            r = await client.request(methode, chemin_factice(path))
            if r.status_code != 401 or (methode != "HEAD" and r.json() != {"detail": "Authentification requise"}):
                ouvertes.append((methode, path, r.status_code))
        assert ouvertes == []

    def test_on_enumere_bien_beaucoup_de_routes(self):
        assert len(toutes_les_routes()) > 250   # garde-fou : l'énumération n'est pas vide par accident

    def test_docs_openapi_comprises_dans_l_enumeration(self):
        chemins = {p for _, p in toutes_les_routes()}
        assert {"/api/docs", "/api/redoc", "/api/openapi.json"} <= chemins

    @pytest.mark.asyncio
    async def test_route_ajoutee_apres_coup_est_protegee_et_admin_par_defaut(self, client, auth_on, db_session):
        from main import app

        async def _x():
            return {"ok": True}

        app.add_api_route("/api/zz-nouvelle-route", _x, methods=["GET"])
        try:
            assert (await client.get("/api/zz-nouvelle-route")).status_code == 401
            jeton = await creer_session(db_session, "utilisateur")
            # Non classée => admin (échec fermé du classement) : un utilisateur ne la voit pas.
            assert (await client.get("/api/zz-nouvelle-route", headers=cookie(jeton))).status_code == 403
            adm = await creer_session(db_session, "admin")
            assert (await client.get("/api/zz-nouvelle-route", headers=cookie(adm))).status_code == 200
        finally:
            app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/api/zz-nouvelle-route"]

    def test_toute_route_est_classee_explicitement(self):
        """Échoue si quelqu'un ajoute une route sans décider qui y a droit."""
        non_classees = [(m, p) for m, p in toutes_les_routes()
                        if p not in ATTENDUE and acces.classer(m, p) is None]
        assert non_classees == []

    def test_les_routes_de_la_liste_blanche_ne_sont_pas_classees_admin(self):
        for p in ATTENDUE:
            assert acces.classer("GET", p) is None

    def test_repartition_plausible(self):
        classes = [acces.classer(m, p) for m, p in toutes_les_routes() if p not in ATTENDUE]
        assert classes.count(acces.ADMIN) > 50 and classes.count(acces.UTILISATEUR) > 50


# ─── Rôles ────────────────────────────────────────────────────────────────────

class TestRoles:
    @pytest.mark.asyncio
    async def test_utilisateur_recoit_403_sur_chaque_route_admin(self, client, auth_on, db_session):
        jeton = await creer_session(db_session, "utilisateur")
        refus_manquants = []
        n = 0
        for methode, path in toutes_les_routes():
            if path in ATTENDUE or acces.classer(methode, path) != acces.ADMIN:
                continue
            n += 1
            r = await client.request(methode, chemin_factice(path), headers={**cookie(jeton), **SYNC})
            if r.status_code != 403 or (methode != "HEAD" and r.json() != {"detail": "Réservé aux administrateurs"}):
                refus_manquants.append((methode, path, r.status_code))
        assert n > 50
        assert refus_manquants == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("chemin", ["/api/prompts", "/api/rapports", "/api/templates", "/api/version"])
    async def test_utilisateur_passe_sur_routes_utilisateur(self, client, auth_on, db_session, chemin):
        jeton = await creer_session(db_session, "utilisateur")
        r = await client.get(chemin, headers=cookie(jeton))
        assert r.status_code == 200, r.text

    @pytest.mark.asyncio
    async def test_admin_passe_partout(self, client, auth_on, db_session):
        jeton = await creer_session(db_session, "admin")
        for chemin in ("/api/system/config", "/api/prompts", "/api/audit"):
            assert (await client.get(chemin, headers=cookie(jeton))).status_code == 200, chemin

    @pytest.mark.asyncio
    @pytest.mark.parametrize("chemin", [
        "/api/system/config", "/api/logs/tail", "/api/audit", "/api/system/backups",
        "/api/system/backup-db", "/api/sources", "/api/duplicates", "/api/passerelle/projets",
        "/api/folders", "/api/connectors", "/api/documents/analyze-batch", "/api/organize/apply",
        "/api/system/models/pull", "/api/docs", "/api/openapi.json", "/api/redoc",
    ])
    async def test_sensibles_classees_admin(self, chemin):
        m = "POST" if chemin in ("/api/system/backup-db", "/api/documents/analyze-batch",
                                 "/api/organize/apply", "/api/system/models/pull") else "GET"
        assert acces.classer(m, chemin) == acces.ADMIN

    @pytest.mark.asyncio
    async def test_config_get_et_put_admin_seulement(self, client, auth_on, db_session):
        u = await creer_session(db_session, "utilisateur")
        assert (await client.get("/api/system/config", headers=cookie(u))).status_code == 403
        assert (await client.put("/api/system/config", json={"default_model": "x"},
                                 headers={**cookie(u), **SYNC})).status_code == 403

    @pytest.mark.asyncio
    async def test_role_relu_en_base_a_chaque_requete(self, client, auth_on, db_session):
        jeton = await creer_session(db_session, "admin")
        assert (await client.get("/api/system/config", headers=cookie(jeton))).status_code == 200
        u = (await db_session.execute(select(Utilisateur))).scalars().one()
        u.role = "utilisateur"          # rétrogradé au NAS puis à la connexion suivante / en base
        await db_session.commit()
        assert (await client.get("/api/system/config", headers=cookie(jeton))).status_code == 403

    @pytest.mark.asyncio
    async def test_bloque_relu_en_base_a_chaque_requete(self, client, auth_on, db_session):
        jeton = await creer_session(db_session, "utilisateur")
        assert (await client.get("/api/prompts", headers=cookie(jeton))).status_code == 200
        u = (await db_session.execute(select(Utilisateur))).scalars().one()
        u.bloque = True
        await db_session.commit()
        r = await client.get("/api/prompts", headers=cookie(jeton))
        assert r.status_code == 401 and r.json() == {"detail": "Authentification requise"}

    @pytest.mark.asyncio
    async def test_session_inconnue_ou_expiree_401(self, client, auth_on, db_session):
        assert (await client.get("/api/prompts", headers=cookie("jeton-inconnu"))).status_code == 401
        jeton = await creer_session(db_session, "utilisateur")
        s = (await db_session.execute(select(SessionAuth))).scalars().one()
        s.expire_max = datetime.now(timezone.utc) - timedelta(seconds=1)
        await db_session.commit()
        assert (await client.get("/api/prompts", headers=cookie(jeton))).status_code == 401

    @pytest.mark.asyncio
    async def test_401_json_sans_fuite(self, client, auth_on):
        r = await client.get("/api/documents")
        assert r.status_code == 401 and r.json() == {"detail": "Authentification requise"}
        assert r.headers["content-type"].startswith("application/json")


# ─── Authentification désactivée : rien ne change ─────────────────────────────

class TestAuthDesactivee:
    @pytest.mark.asyncio
    async def test_aucun_refus_quand_auth_inactive(self, client):
        for chemin in ("/api/prompts", "/api/system/config", "/api/audit", "/api/rapports"):
            r = await client.get(chemin)
            assert r.status_code == 200, chemin

    @pytest.mark.asyncio
    async def test_aucun_401_ni_403_sur_toutes_les_routes_quand_inactive(self, client):
        # Un échantillon de méthodes d'écriture : le gate ne doit jamais refuser (ni CSRF, ni rôle).
        for methode, chemin in (("POST", "/api/prompts"), ("PUT", "/api/system/config"),
                                ("DELETE", "/api/documents/x"), ("POST", "/api/duplicates/quarantine")):
            r = await client.request(methode, chemin, headers={"Origin": "https://evil.example"})
            assert r.status_code not in (401, 403), (methode, chemin, r.status_code)

    @pytest.mark.asyncio
    async def test_valeurs_non_vraies_restent_inactives(self, client):
        for v in ("false", "0", "", "non", "FALSE"):
            runtime_config._overrides["auth_active"] = v
            assert (await client.get("/api/prompts")).status_code == 200, v


# ─── CSRF ─────────────────────────────────────────────────────────────────────

class TestCsrf:
    @pytest_asyncio.fixture
    async def jeton(self, db_session, auth_on, oidc_configure):
        return await creer_session(db_session, "utilisateur")

    @pytest.mark.asyncio
    async def test_origine_etrangere_403(self, client, jeton):
        r = await client.post("/api/prompts/relire", json={}, headers={**cookie(jeton), "Origin": "https://evil.example"})
        assert r.status_code == 403
        assert "origine" in r.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_origine_etrangere_meme_si_fetch_site_same_origin(self, client, jeton):
        r = await client.post("/api/prompts/relire", json={}, headers={
            **cookie(jeton), "Origin": "https://evil.example", **SYNC})
        assert r.status_code == 403

    @pytest.mark.asyncio
    @pytest.mark.parametrize("methode", ["POST", "PUT", "PATCH", "DELETE"])
    async def test_toutes_les_methodes_d_ecriture(self, client, jeton, methode):
        r = await client.request(methode, "/api/projets/x", headers={
            **cookie(jeton), "Origin": "https://evil.example"})
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_origine_de_l_application_passe(self, client, jeton):
        # Origine identique à l'hôte de la requête.
        r = await client.post("/api/prompts/relire", json={}, headers={**cookie(jeton), "Origin": "http://test"})
        assert r.status_code == 422                       # passé le contrôle, refusé par la validation
        # Origine de l'adresse de référence (oidc_redirect_uri).
        r = await client.post("/api/prompts/relire", json={}, headers={
            **cookie(jeton), "Origin": "https://ged.test.invalid"})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_origine_cors_listee_passe(self, client, jeton, monkeypatch):
        monkeypatch.setattr(acces, "origines_cors", lambda: ["https://autre.test.invalid"])
        r = await client.post("/api/prompts/relire", json={}, headers={
            **cookie(jeton), "Origin": "https://autre.test.invalid"})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_sans_origin_fetch_site_same_origin_passe(self, client, jeton):
        r = await client.post("/api/prompts/relire", json={}, headers={**cookie(jeton), **SYNC})
        assert r.status_code == 422

    @pytest.mark.asyncio
    @pytest.mark.parametrize("valeur", ["cross-site", "same-site", "none", ""])
    async def test_sans_origin_fetch_site_autre_403(self, client, jeton, valeur):
        r = await client.post("/api/prompts/relire", json={}, headers={**cookie(jeton), "Sec-Fetch-Site": valeur})
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_sans_aucune_indication_403(self, client, jeton):
        r = await client.post("/api/prompts/relire", json={}, headers=cookie(jeton))
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_origin_null_403(self, client, jeton):
        r = await client.post("/api/prompts/relire", json={}, headers={**cookie(jeton), "Origin": "null"})
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_referer_a_defaut_d_origin(self, client, jeton):
        r = await client.post("/api/prompts/relire", json={}, headers={
            **cookie(jeton), "Referer": "https://evil.example/page"})
        assert r.status_code == 403
        r = await client.post("/api/prompts/relire", json={}, headers={
            **cookie(jeton), "Referer": "http://test/ged?q=1"})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_origine_voisine_par_prefixe_refusee(self, client, jeton):
        for o in ("http://test.evil.example", "http://test:8080", "https://test"):
            r = await client.post("/api/prompts/relire", json={}, headers={**cookie(jeton), "Origin": o})
            assert r.status_code == 403, o

    @pytest.mark.asyncio
    async def test_port_de_l_hote_compte_route_lan_http(self, client, jeton):
        """http://192.168.42.83:3003 : l'origine déduite de Host inclut le port (comme l'Origin du navigateur)."""
        hote = {"Host": "192.168.42.83:3003"}
        r = await client.post("/api/prompts/relire", json={}, headers={
            **cookie(jeton), **hote, "Origin": "http://192.168.42.83:3003"})
        assert r.status_code == 422
        for faux in ("http://192.168.42.83:9999", "http://192.168.42.83", "https://192.168.42.83:3003"):
            r = await client.post("/api/prompts/relire", json={}, headers={
                **cookie(jeton), **hote, "Origin": faux})
            assert r.status_code == 403, faux

    @pytest.mark.asyncio
    async def test_derriere_proxy_tls_x_forwarded_proto(self, client, jeton):
        r = await client.post("/api/prompts/relire", json={}, headers={
            **cookie(jeton), "Host": "ged.exemple.test", "X-Forwarded-Proto": "https",
            "Origin": "https://ged.exemple.test"})
        assert r.status_code == 422
        r = await client.post("/api/prompts/relire", json={}, headers={
            **cookie(jeton), "Host": "ged.exemple.test", "Origin": "https://ged.exemple.test"})
        assert r.status_code == 403   # sans X-Forwarded-Proto, le proxy est vu en http : schéma différent

    @pytest.mark.asyncio
    async def test_lecture_non_soumise_au_csrf(self, client, jeton):
        r = await client.get("/api/rapports", headers={**cookie(jeton), "Origin": "https://evil.example"})
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_logout_aussi_protege(self, client, jeton):
        r = await client.post("/api/auth/logout", headers={**cookie(jeton), "Origin": "https://evil.example"})
        assert r.status_code == 403
        r = await client.post("/api/auth/logout", headers={**cookie(jeton), **SYNC})
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_sans_cookie_pas_de_csrf_mais_401(self, client, auth_on):
        """Un appel par jeton (étape 4) n'est pas soumis à la règle ; sans identité : 401."""
        r = await client.post("/api/prompts/relire", json={}, headers={"Origin": "https://evil.example"})
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_publish_hors_csrf(self, client, auth_on):
        r = await client.post("/api/passerelle/publish", json={"pages": []},
                              headers={"Origin": "https://evil.example"})
        assert r.status_code == 401 and "Jeton de publication" in r.json()["detail"]


# ─── Échec fermé ──────────────────────────────────────────────────────────────

class TestEchecFerme:
    @pytest.mark.asyncio
    async def test_lecture_de_session_qui_leve(self, client, auth_on, monkeypatch, db_session):
        jeton = await creer_session(db_session, "admin")

        async def boom(*a, **k):
            raise RuntimeError("base indisponible")

        from routers import auth as auth_router
        monkeypatch.setattr(auth_router, "_session_valide", boom)
        for chemin in ("/api/prompts", "/api/system/config"):
            r = await client.get(chemin, headers=cookie(jeton))
            assert r.status_code in (401, 503), chemin
            assert "base indisponible" not in r.text          # pas de fuite de l'erreur
        r = await client.get("/api/prompts")                   # même sans cookie
        assert r.status_code in (401, 503)

    @pytest.mark.asyncio
    async def test_lecture_de_suspension_qui_leve(self, client, auth_on, monkeypatch):
        async def boom(*a, **k):
            raise RuntimeError("table illisible")

        monkeypatch.setattr(acces, "suspension_jusqua", boom)
        r = await client.get("/api/prompts")
        assert r.status_code in (401, 503)

    @pytest.mark.asyncio
    async def test_liste_blanche_survit_a_une_base_illisible(self, client, auth_on, monkeypatch):
        async def boom(*a, **k):
            raise RuntimeError("x")

        from routers import auth as auth_router
        monkeypatch.setattr(auth_router, "_session_valide", boom)
        assert (await client.get("/healthz")).status_code == 200
        assert (await client.get("/api/version")).status_code == 200

    def test_defaut_auth_inactive(self):
        assert oidc_service.auth_active() is False


# ─── Activation / désactivation de l'authentification ─────────────────────────

class TestReglageAuthActive:
    @pytest.mark.asyncio
    async def test_activation_refusee_sans_oidc(self, client):
        r = await client.put("/api/system/config", json={"auth_active": "true"})
        assert r.status_code == 400
        assert "SSO" in r.json()["detail"] or "OpenID" in r.json()["detail"]
        assert oidc_service.auth_active() is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("manque", ["oidc_issuer", "oidc_client_id", "oidc_client_secret"])
    async def test_activation_refusee_si_un_element_manque(self, client, manque):
        body = {"oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID, "oidc_client_secret": "secret-fictif"}
        body.pop(manque)
        r = await client.put("/api/system/config", json={**body, "auth_active": "true"})
        assert r.status_code == 400
        assert oidc_service.auth_active() is False
        assert "auth_active" not in runtime_config._overrides

    @pytest.mark.asyncio
    async def test_activation_refusee_et_rien_n_est_ecrit(self, client, db_session):
        r = await client.put("/api/system/config", json={"auth_active": "true", "default_model": "zzz"})
        assert r.status_code == 400
        assert runtime_config.effective("default_model") != "zzz"
        assert (await db_session.get(Config, "auth_active")) is None

    @pytest.mark.asyncio
    async def test_activation_acceptee_si_oidc_complet(self, client, db_session):
        await ajouter_fiche(db_session)
        r = await client.put("/api/system/config", json={
            "oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID, "oidc_client_secret": "secret-fictif",
            "auth_active": "true"})
        assert r.status_code == 200
        assert oidc_service.auth_active() is True

    @pytest.mark.asyncio
    async def test_activation_en_deux_temps(self, client, db_session):
        await ajouter_fiche(db_session)
        await client.put("/api/system/config", json={
            "oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID, "oidc_client_secret": "secret-fictif"})
        r = await client.put("/api/system/config", json={"auth_active": "true"})
        assert r.status_code == 200 and oidc_service.auth_active() is True

    # ── Verrouillage : il faut avoir pu se connecter en admin AVANT d'activer ──
    CORPS_OIDC = {"oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID, "oidc_client_secret": "secret-fictif"}

    @pytest.mark.asyncio
    async def test_activation_refusee_sans_fiche_admin(self, client, db_session):
        r = await client.put("/api/system/config", json={**self.CORPS_OIDC, "auth_active": "true"})
        assert r.status_code == 400
        assert "Connectez-vous d'abord une fois avec un compte du groupe matotheque-admin" in r.json()["detail"]
        assert oidc_service.auth_active() is False
        assert (await db_session.get(Config, "auth_active")) is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("fiche", [
        {"role": "utilisateur"},                        # pas admin
        {"role": "admin", "bloque": True},              # admin bloqué
        {"role": "admin", "emetteur": "https://autre.test.invalid"},   # fiche d'un AUTRE émetteur
    ])
    async def test_activation_refusee_si_aucune_fiche_admin_utilisable(self, client, db_session, fiche):
        await ajouter_fiche(db_session, **fiche)
        r = await client.put("/api/system/config", json={**self.CORPS_OIDC, "auth_active": "true"})
        assert r.status_code == 400 and "matotheque-admin" in r.json()["detail"]
        assert oidc_service.auth_active() is False

    @pytest.mark.asyncio
    async def test_activation_refusee_par_oidc_incomplet_avant_la_fiche(self, client, db_session):
        await ajouter_fiche(db_session)
        r = await client.put("/api/system/config", json={"auth_active": "true"})
        assert r.status_code == 400 and "SSO" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_activation_refusee_si_secret_perdu_par_changement_d_emetteur(self, client):
        """Changer l'émetteur sans nouveau secret efface le secret (liaison) : on ne peut plus activer."""
        await client.put("/api/system/config", json={
            "oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID, "oidc_client_secret": "secret-fictif"})
        r = await client.put("/api/system/config", json={
            "oidc_issuer": "https://autre.test.invalid/sso", "auth_active": "true"})
        assert r.status_code == 400
        assert oidc_service.auth_active() is False

    @pytest.mark.asyncio
    async def test_vider_un_element_oidc_quand_actif_refuse(self, client, db_session, auth_on, oidc_configure):
        """Verrouillage par erreur : on ne peut pas casser la config SSO tant que l'auth est active."""
        runtime_config._overrides["oidc_client_secret"] = "enc::x"
        runtime_config._overrides["oidc_secret_emetteur"] = ISSUER
        adm = await creer_session(db_session, "admin")
        r = await client.put("/api/system/config", json={"oidc_client_id": ""},
                             headers={**cookie(adm), **SYNC})
        assert r.status_code == 400
        assert runtime_config.effective("oidc_client_id") == CLIENT_ID

    @pytest.mark.asyncio
    async def test_passage_a_faux_par_non_admin_refuse(self, client, auth_on, oidc_configure, db_session):
        u = await creer_session(db_session, "utilisateur")
        r = await client.put("/api/system/config", json={"auth_active": "false"},
                             headers={**cookie(u), **SYNC})
        assert r.status_code == 403
        assert oidc_service.auth_active() is True

    @pytest.mark.asyncio
    async def test_passage_a_faux_par_anonyme_pendant_suspension_refuse(self, client, auth_on, oidc_configure, db_session):
        """La suspension de secours laisse passer, mais ne permet PAS d'éteindre l'authentification."""
        db_session.add(Config(cle=acces.CLE_SUSPENSION,
                              valeur=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()))
        await db_session.commit()
        for valeur in ("false", ""):
            r = await client.put("/api/system/config", json={"auth_active": valeur}, headers=SYNC)
            assert r.status_code == 403, valeur
        assert oidc_service.auth_active() is True

    @pytest.mark.asyncio
    async def test_passage_a_faux_par_admin_journalise(self, client, auth_on, oidc_configure, db_session, monkeypatch):
        from services import audit
        evenements = []

        async def faux_emit(action, statut, **kw):
            evenements.append((action, statut, kw))

        monkeypatch.setattr(audit, "emit", faux_emit)
        adm = await creer_session(db_session, "admin", identifiant="tclement")
        r = await client.put("/api/system/config", json={"auth_active": "false"},
                             headers={**cookie(adm), **SYNC})
        assert r.status_code == 200
        assert oidc_service.auth_active() is False
        assert len(evenements) == 1
        action, statut, kw = evenements[0]
        assert action == "config_authentification"
        assert kw["acteur"] == "tclement"
        assert "auth_active" in kw["detail"]["cles"] and kw["detail"]["auth_active"] == "false"

    @pytest.mark.asyncio
    async def test_changements_oidc_journalises_sans_secret(self, client, db_session, monkeypatch):
        from services import audit
        evenements = []

        async def faux_emit(action, statut, **kw):
            evenements.append((action, statut, kw))

        monkeypatch.setattr(audit, "emit", faux_emit)
        secret = "Secret-Tres-Fictif-123"
        r = await client.put("/api/system/config", json={
            "oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID, "oidc_client_secret": secret,
            "auth_session_max_jours": "3", "default_model": "autre"})
        assert r.status_code == 200
        assert len(evenements) == 1
        _, _, kw = evenements[0]
        assert set(kw["detail"]["cles"]) == {"oidc_issuer", "oidc_client_id", "oidc_client_secret",
                                             "auth_session_max_jours"}
        assert secret not in repr(evenements) and "enc::" not in repr(evenements)
        assert kw["acteur"] != ""

    @pytest.mark.asyncio
    async def test_autre_reglage_non_journalise_comme_auth(self, client, monkeypatch):
        from services import audit
        evenements = []

        async def faux_emit(action, statut, **kw):
            evenements.append(action)

        monkeypatch.setattr(audit, "emit", faux_emit)
        await client.put("/api/system/config", json={"default_model": "autre"})
        assert "config_authentification" not in evenements


# ─── Suspension de secours (CLI) ──────────────────────────────────────────────

class TestSuspension:
    def test_parse_duree(self):
        from outils import auth as cli
        assert cli.parse_duree("2h") == timedelta(hours=2)
        assert cli.parse_duree("30m") == timedelta(minutes=30)
        assert cli.parse_duree("1j") == timedelta(days=1)
        assert cli.parse_duree("24h") == timedelta(hours=24)
        assert cli.parse_duree("45") == timedelta(minutes=45)

    @pytest.mark.parametrize("v", ["", "abc", "0h", "-1h", "2x", "h", "1.5h", "25h", "2j", "999999999999h"])
    def test_parse_duree_invalide(self, v):
        from outils import auth as cli
        with pytest.raises(ValueError):
            cli.parse_duree(v)

    @pytest.mark.asyncio
    async def test_active_laisse_passer_et_signale(self, client, auth_on, db_session):
        from outils import auth as cli
        assert (await client.get("/api/prompts")).status_code == 401
        fin = await cli.suspendre(db_session, timedelta(hours=2))
        r = await client.get("/api/prompts")
        assert r.status_code == 200
        assert r.headers.get("x-auth-suspendue") == fin.isoformat()
        assert (await client.get("/api/system/config")).status_code == 200   # y compris les routes admin
        me = (await client.get("/api/auth/me")).json()
        assert me["auth_active"] is True and me["suspension_jusqua"] == fin.isoformat()

    @pytest.mark.asyncio
    async def test_me_sans_suspension_inchange(self, client, auth_on):
        assert (await client.get("/api/auth/me")).json() == {"auth_active": True, "utilisateur": None}

    @pytest.mark.asyncio
    async def test_echue_refuse(self, client, auth_on, db_session):
        db_session.add(Config(cle=acces.CLE_SUSPENSION,
                              valeur=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()))
        await db_session.commit()
        r = await client.get("/api/prompts")
        assert r.status_code == 401 and "x-auth-suspendue" not in r.headers
        assert "suspension_jusqua" not in (await client.get("/api/auth/me")).json()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("valeur", ["", "pas-une-date", "9999-99-99", "null"])
    async def test_valeur_illisible_refuse(self, client, auth_on, db_session, valeur):
        db_session.add(Config(cle=acces.CLE_SUSPENSION, valeur=valeur))
        await db_session.commit()
        assert (await client.get("/api/prompts")).status_code == 401

    @pytest.mark.asyncio
    async def test_echeance_trop_lointaine_refusee(self, client, auth_on, db_session):
        """Une échéance absurde (corrompue ou posée à la main) n'ouvre pas l'API pour des années."""
        db_session.add(Config(cle=acces.CLE_SUSPENSION,
                              valeur=(datetime.now(timezone.utc) + timedelta(days=400)).isoformat()))
        await db_session.commit()
        assert (await client.get("/api/prompts")).status_code == 401

    @pytest.mark.asyncio
    async def test_reprendre_annule(self, client, auth_on, db_session):
        from outils import auth as cli
        await cli.suspendre(db_session, timedelta(hours=2))
        assert (await client.get("/api/prompts")).status_code == 200
        await cli.reprendre(db_session)
        assert (await client.get("/api/prompts")).status_code == 401

    @pytest.mark.asyncio
    async def test_etat_et_journal(self, db_session):
        from outils import auth as cli
        assert "aucune" in (await cli.etat(db_session)).lower()
        await cli.suspendre(db_session, timedelta(minutes=30))
        assert "jusqu" in (await cli.etat(db_session)).lower()
        await cli.reprendre(db_session)
        events = (await db_session.execute(
            select(AuditEvent).order_by(AuditEvent.created_at))).scalars().all()
        assert sorted(e.action for e in events) == ["auth_reprise", "auth_suspension"]
        assert all(e.acteur == "cli" for e in events)

    @pytest.mark.asyncio
    async def test_executer_arguments(self, db_session):
        from outils import auth as cli
        sortie = await cli.executer(["--suspendre", "2h"], db_session)
        assert "suspendu" in sortie.lower() or "suspension" in sortie.lower()
        assert "jusqu" in (await cli.executer(["--etat"], db_session)).lower()
        await cli.executer(["--reprendre"], db_session)
        assert "aucune" in (await cli.executer(["--etat"], db_session)).lower()
        with pytest.raises(SystemExit):
            await cli.executer(["--suspendre", "pas-une-duree"], db_session)
        with pytest.raises(SystemExit):
            await cli.executer([], db_session)

    @pytest.mark.asyncio
    async def test_suspendre_remplace_et_ne_cumule_pas(self, db_session):
        from outils import auth as cli
        a = await cli.suspendre(db_session, timedelta(hours=2))
        b = await cli.suspendre(db_session, timedelta(minutes=10))
        assert b < a
        lignes = (await db_session.execute(select(Config).where(Config.cle == acces.CLE_SUSPENSION))).scalars().all()
        assert len(lignes) == 1

    def test_jamais_exposee_par_une_route(self):
        for _, path in toutes_les_routes():
            assert "suspen" not in path.lower() and "secours" not in path.lower(), path
        assert acces.CLE_SUSPENSION not in runtime_config._DEFAULTS

    @pytest.mark.asyncio
    async def test_non_ecrivable_ni_lisible_par_la_configuration(self, client, db_session, auth_on, oidc_configure):
        adm = await creer_session(db_session, "admin")
        fin = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        r = await client.put("/api/system/config", json={acces.CLE_SUSPENSION: fin},
                             headers={**cookie(adm), **SYNC})
        assert r.status_code == 200
        assert (await db_session.get(Config, acces.CLE_SUSPENSION)) is None
        r = await client.get("/api/system/config", headers=cookie(adm))
        assert acces.CLE_SUSPENSION not in r.text
        assert (await client.get("/api/prompts")).status_code == 401   # toujours pas de suspension


# ─── Exigence 9 : accès refusé pour une personne connue => sessions supprimées ─

class TestAccesRefuseSupprimeLesSessions:
    @pytest_asyncio.fixture
    async def sso(self, oidc_configure, monkeypatch):
        etat = {"claims": {}}

        async def discover():
            return {"authorization_endpoint": f"{ISSUER}/authorize", "jwks_uri": f"{ISSUER}/jwks"}

        async def exchange_code(disco, code, verifier):
            return {"id_token": "a.b.c"}

        async def get_jwks(uri, forcer=False):
            return {"keys": [{"kid": "k1"}]}

        monkeypatch.setattr(oidc_service, "discover", discover)
        monkeypatch.setattr(oidc_service, "exchange_code", exchange_code)
        monkeypatch.setattr(oidc_service, "get_jwks", get_jwks)
        monkeypatch.setattr(oidc_service, "entete_jeton", lambda t: {"kid": "k1"})
        monkeypatch.setattr(oidc_service, "validate_id_token", lambda *a, **k: etat["claims"])
        return etat

    async def _connecter(self, client, sso, sub, groupes):
        r = await client.get("/api/auth/login")
        q = parse_qs(urlparse(r.headers["location"]).query)
        sso["claims"] = {"sub": sub, "preferred_username": sub, "groups": groupes}
        return await client.get("/api/auth/callback", params={"code": "c", "state": q["state"][0]})

    @pytest.mark.asyncio
    async def test_sessions_supprimees_pour_personne_connue(self, client, sso, db_session):
        a = await creer_session(db_session, "utilisateur", sub="sub-a")
        await creer_session(db_session, "utilisateur", sub="sub-b")
        # Une 2e session de la même personne.
        ua = (await db_session.execute(select(Utilisateur).where(Utilisateur.sub == "sub-a"))).scalar_one()
        now = datetime.now(timezone.utc)
        db_session.add(SessionAuth(id=oidc_service.hacher_jeton("autre-appareil"), utilisateur_id=ua.id,
                                   creee=now, derniere_activite=now, expire_max=now + timedelta(days=1)))
        await db_session.commit()

        r = await self._connecter(client, sso, "sub-a", ["groupe-sans-rapport"])
        assert parse_qs(urlparse(r.headers["location"]).query)["auth_erreur"] == ["acces_refuse"]

        restantes = (await db_session.execute(select(SessionAuth))).scalars().all()
        assert all(s.utilisateur_id != ua.id for s in restantes)
        assert len(restantes) == 1                              # celle de sub-b est intacte
        runtime_config._overrides["auth_active"] = "true"
        assert (await client.get("/api/prompts", headers=cookie(a))).status_code == 401

    @pytest.mark.asyncio
    async def test_inconnu_refuse_ne_cree_rien(self, client, sso, db_session):
        await creer_session(db_session, "utilisateur", sub="sub-b")
        r = await self._connecter(client, sso, "sub-inconnu", [])
        assert parse_qs(urlparse(r.headers["location"]).query)["auth_erreur"] == ["acces_refuse"]
        assert len((await db_session.execute(select(Utilisateur))).scalars().all()) == 1
        assert len((await db_session.execute(select(SessionAuth))).scalars().all()) == 1

    @pytest.mark.asyncio
    async def test_meme_sub_autre_emetteur_non_touche(self, client, sso, db_session):
        u = Utilisateur(emetteur="https://autre.test.invalid", sub="sub-a", role="utilisateur", groupes=[])
        db_session.add(u)
        await db_session.flush()
        now = datetime.now(timezone.utc)
        db_session.add(SessionAuth(id="h" * 64, utilisateur_id=u.id, creee=now, derniere_activite=now,
                                   expire_max=now + timedelta(days=1)))
        await db_session.commit()
        await self._connecter(client, sso, "sub-a", [])
        assert len((await db_session.execute(select(SessionAuth))).scalars().all()) == 1

    @pytest.mark.asyncio
    async def test_connexion_normale_conserve_les_autres_sessions(self, client, sso, db_session):
        await creer_session(db_session, "utilisateur", sub="sub-a")
        r = await self._connecter(client, sso, "sub-a", ["matotheque-utilisateurs"])
        assert "auth_erreur" not in r.headers["location"]
        assert len((await db_session.execute(select(SessionAuth))).scalars().all()) == 2

    @pytest.mark.asyncio
    async def test_parcours_connexion_admin_puis_activation(self, client, sso, db_session):
        """auth_active faux : la connexion fonctionne et crée la fiche admin ; l'activation passe ensuite."""
        assert oidc_service.auth_active() is False
        r = await client.put("/api/system/config", json={
            "oidc_client_secret": "secret-fictif", "auth_active": "true"})
        assert r.status_code == 400 and "matotheque-admin" in r.json()["detail"]   # pas encore de fiche

        r = await self._connecter(client, sso, "sub-admin", ["matotheque-admin"])
        assert "auth_erreur" not in r.headers["location"]
        fiche = (await db_session.execute(select(Utilisateur).where(Utilisateur.sub == "sub-admin"))).scalar_one()
        assert fiche.role == "admin" and fiche.bloque is False

        r = await client.put("/api/system/config", json={
            "oidc_client_secret": "secret-fictif", "auth_active": "true"})
        assert r.status_code == 200 and oidc_service.auth_active() is True


# ─── Instantané des routes « utilisateur » ────────────────────────────────────

class TestInstantaneUtilisateur:
    """
    Fige l'ensemble EXACT des routes ouvertes au rôle « utilisateur ». Les règles « /* » sont larges :
    une route ajoutée demain sous un de ces préfixes serait ouverte sans que personne l'ait décidé.
    """
    FICHIER = Path(__file__).parent / "data" / "routes_utilisateur.txt"

    @staticmethod
    def courant() -> list[str]:
        return sorted({f"{m} {p}" for m, p in toutes_les_routes()
                       if p not in ATTENDUE and acces.classer(m, p) == acces.UTILISATEUR})

    def test_ensemble_fige(self):
        attendu = self.FICHIER.read_text(encoding="utf-8").split("\n")
        attendu = sorted(l for l in attendu if l.strip())
        courant = self.courant()
        ajoutees = sorted(set(courant) - set(attendu))
        retirees = sorted(set(attendu) - set(courant))
        assert not ajoutees and not retirees, (
            "Routes « utilisateur » modifiées. Décider pour chacune : utilisateur ou admin ? Puis mettre à "
            f"jour la référence tests/data/routes_utilisateur.txt VOLONTAIREMENT.\n"
            f"Ajoutées (ouvertes aux utilisateurs) : {ajoutees}\nRetirées : {retirees}")


# ─── Sortie de secours : --eteindre ───────────────────────────────────────────

class TestEteindre:
    @pytest.mark.asyncio
    async def test_eteindre_supprime_les_401_apres_relecture(self, client, db_session, auth_on):
        from outils import auth as cli
        # État réel : auth_active posé EN BASE (pas seulement en cache).
        db_session.add(Config(cle="auth_active", valeur="true"))
        await db_session.commit()
        assert (await client.get("/api/prompts")).status_code == 401

        sortie = await cli.executer(["--eteindre"], db_session)
        assert "éteinte" in sortie.lower()
        assert (await db_session.get(Config, "auth_active")).valeur == "false"

        # Relecture des réglages comme le fait un autre process.
        runtime_config._overrides.clear()
        await runtime_config.load(db_session)
        assert oidc_service.auth_active() is False
        assert (await client.get("/api/prompts")).status_code == 200
        assert (await client.get("/api/system/config")).status_code == 200

    @pytest.mark.asyncio
    async def test_eteindre_journalise_et_efface_la_suspension(self, db_session):
        from outils import auth as cli
        await cli.suspendre(db_session, timedelta(hours=1))
        await cli.executer(["--eteindre"], db_session)
        assert (await db_session.get(Config, acces.CLE_SUSPENSION)) is None
        events = (await db_session.execute(select(AuditEvent))).scalars().all()
        ext = [e for e in events if e.action == "auth_extinction"]
        assert len(ext) == 1 and ext[0].acteur == "cli"
        assert "auth_active" in (ext[0].detail or {}).get("cles", [])

    @pytest.mark.asyncio
    async def test_eteindre_sans_rien_a_eteindre(self, db_session):
        from outils import auth as cli
        sortie = await cli.executer(["--eteindre"], db_session)
        assert "éteinte" in sortie.lower()

    @pytest.mark.asyncio
    async def test_eteindre_incompatible_avec_les_autres_options(self, db_session):
        from outils import auth as cli
        with pytest.raises(SystemExit):
            await cli.executer(["--eteindre", "--etat"], db_session)

    def test_toujours_hors_de_l_api(self):
        for _, path in toutes_les_routes():
            assert "eteindre" not in path.lower() and "extinction" not in path.lower()
