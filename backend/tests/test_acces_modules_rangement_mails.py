"""
Tests — accès aux futurs modules Mails et Rangement (plan rangement + mails, étape 2)
====================================================================================
Décisions d'architecture n° 1 et 2 (10/11/2026) et D1 (11/11/2026, mails = foyer) :
  - /api/mail/* = rôle utilisateur ; /api/inventaire/* et /api/rangement/* = admin ;
    aucun jeton d'automate n'atteint ces trois préfixes ;
  - un jeton de POSTE (portée `agent`) n'atteint que /api/agent/*, et /api/agent/* n'accepte que lui
    (ni session, même admin, ni autre jeton) ;
  - `poste_authentifie` exige ce jeton même quand l'authentification est éteinte.
Les routes de ces modules n'existent pas encore : un appel que le contrôle laisse passer finit en 404
(le rôle des futures routes est vérifié par `acces.classer`). Données fictives, aucun appel réseau.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from models.auth import JetonApi, SessionAuth, Utilisateur
from services import acces, jetons_api, oidc_service, runtime_config

ISSUER = "https://sso.test.invalid/webman/sso"
REDIRECT = "https://ged.test.invalid/api/auth/callback"
SYNC = {"Sec-Fetch-Site": "same-origin"}


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
    runtime_config._overrides.update({"auth_active": "true", "oidc_issuer": ISSUER,
                                      "oidc_client_id": "matotheque-test", "oidc_redirect_uri": REDIRECT})


async def session(db, role="admin") -> str:
    """Personne fictive + session ; rend le cookie."""
    ident = f"{role}-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    u = Utilisateur(emetteur=oidc_service.emetteur_configure(), sub=f"sub-{ident}", role=role, identifiant=ident)
    db.add(u)
    await db.flush()
    jeton = f"cookie-{ident}"
    db.add(SessionAuth(id=oidc_service.hacher_jeton(jeton), utilisateur_id=u.id, creee=now,
                       derniere_activite=now, expire_max=now + timedelta(days=1)))
    await db.commit()
    return jeton


def ck(jeton: str) -> dict:
    return {"Cookie": f"matotheque_session={jeton}", **SYNC}


def bearer(jeton: str) -> dict:
    return {"Authorization": f"Bearer {jeton}"}


async def jeton_direct(db, role="utilisateur", portee="lecture", *, revoque=None) -> str:
    """Jeton fictif posé directement en base ; rend le clair."""
    clair = jetons_api.nouveau_jeton()
    db.add(JetonApi(nom=f"test-{uuid.uuid4().hex[:8]}", empreinte=jetons_api.empreinte(clair), role=role,
                    portee=portee, revoque=revoque))
    await db.commit()
    return clair


class TestClassement:
    @pytest.mark.parametrize("chemin,role", [
        ("/api/mail", acces.UTILISATEUR), ("/api/mail/comptes", acces.UTILISATEUR),
        ("/api/mail/comptes/{compte_id}/dossiers", acces.UTILISATEUR),
        ("/api/inventaire", acces.ADMIN), ("/api/inventaire/scans", acces.ADMIN),
        ("/api/rangement", acces.ADMIN), ("/api/rangement/lots/{lot_id}", acces.ADMIN),
        ("/api/agent/config", acces.ADMIN),
    ])
    def test_prefixes_classes(self, chemin, role):
        for m in ("GET", "POST", "PUT", "DELETE"):
            assert acces.classer(m, chemin) == role

    def test_prefixes_interdits_aux_jetons(self):
        for c in ("/api/mail", "/api/mail/x", "/api/inventaire/x", "/api/rangement/x"):
            assert any(acces._correspond(m, c) for m in acces.INTERDIT_AUX_JETONS)

    def test_portee_agent_declaree(self):
        assert jetons_api.PORTEE_AGENT in jetons_api.PORTEES


class TestMailsEtRangement:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("chemin", ["/api/mail/comptes", "/api/inventaire/scans", "/api/rangement/lots"])
    async def test_sans_session_401(self, client, auth_on, chemin):
        """Critère d'acceptation de l'étape 2 : avec auth_active, une route mail sans session → 401."""
        assert (await client.get(chemin)).status_code == 401

    @pytest.mark.asyncio
    async def test_mail_ouvert_au_foyer(self, client, auth_on, db_session):
        util = await session(db_session, "utilisateur")
        # Contrôle franchi : la route n'existe pas encore → 404, ni 401 ni 403.
        assert (await client.get("/api/mail/comptes", headers=ck(util))).status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.parametrize("chemin", ["/api/mail/comptes", "/api/inventaire/scans", "/api/rangement/lots"])
    async def test_jeton_admin_ecriture_refuse(self, client, auth_on, db_session, chemin):
        clair = await jeton_direct(db_session, role="admin", portee="ecriture")
        assert (await client.get(chemin, headers=bearer(clair))).status_code == 403


class TestJetonDePoste:
    @pytest.mark.asyncio
    async def test_agent_passe_sur_son_prefixe(self, client, auth_on, db_session):
        """Critère d'acceptation : l'agent passe avec son jeton (route absente → 404), écriture comprise."""
        clair = await jeton_direct(db_session, portee="agent")
        assert (await client.get("/api/agent/config", headers=bearer(clair))).status_code == 404
        assert (await client.post("/api/agent/lots", headers=bearer(clair))).status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.parametrize("chemin", ["/api/documents", "/api/mail/comptes", "/api/folders", "/api/system/config"])
    async def test_agent_refuse_ailleurs(self, client, auth_on, db_session, chemin):
        clair = await jeton_direct(db_session, portee="agent")
        assert (await client.get(chemin, headers=bearer(clair))).status_code == 403

    @pytest.mark.asyncio
    @pytest.mark.parametrize("portee,role", [("lecture", "utilisateur"), ("ecriture", "admin")])
    async def test_autre_jeton_refuse_sur_agent(self, client, auth_on, db_session, portee, role):
        clair = await jeton_direct(db_session, role=role, portee=portee)
        assert (await client.get("/api/agent/config", headers=bearer(clair))).status_code == 403

    @pytest.mark.asyncio
    async def test_session_admin_refusee_sur_agent(self, client, auth_on, db_session):
        adm = await session(db_session, "admin")
        assert (await client.get("/api/agent/config", headers=ck(adm))).status_code == 403

    @pytest.mark.asyncio
    async def test_agent_revoque_401(self, client, auth_on, db_session):
        clair = await jeton_direct(db_session, portee="agent", revoque=datetime.now(timezone.utc))
        assert (await client.get("/api/agent/config", headers=bearer(clair))).status_code == 401

    @pytest.mark.asyncio
    async def test_creation_force_le_role_utilisateur(self, client, auth_on, db_session):
        adm = await session(db_session, "admin")
        r = await client.post("/api/auth/jetons", json={"nom": "poste PC-TEST", "role": "admin", "portee": "agent",
                                                        "expire_jours": 30}, headers=ck(adm))
        assert r.status_code == 201, r.text
        ligne = (await db_session.execute(select(JetonApi).where(JetonApi.nom == "poste PC-TEST"))).scalar_one()
        assert ligne.portee == "agent" and ligne.role == "utilisateur"


class TestPosteAuthentifie:
    """La dépendance protège le routeur de l'agent même sans middleware (= authentification éteinte)."""

    @pytest_asyncio.fixture
    async def mini(self, db_session):
        from database import get_db
        app = FastAPI()

        async def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db

        @app.get("/api/agent/ping")
        async def ping(jeton: JetonApi = Depends(jetons_api.poste_authentifie)):
            return {"nom": jeton.nom}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c

    @pytest.mark.asyncio
    async def test_sans_jeton_401(self, mini):
        assert (await mini.get("/api/agent/ping")).status_code == 401

    @pytest.mark.asyncio
    async def test_jeton_inconnu_401(self, mini):
        assert (await mini.get("/api/agent/ping", headers=bearer("mato_inconnu"))).status_code == 401

    @pytest.mark.asyncio
    async def test_autre_portee_403(self, mini, db_session):
        clair = await jeton_direct(db_session, role="admin", portee="ecriture")
        assert (await mini.get("/api/agent/ping", headers=bearer(clair))).status_code == 403

    @pytest.mark.asyncio
    async def test_jeton_de_poste_200(self, mini, db_session):
        clair = await jeton_direct(db_session, portee="agent")
        r = await mini.get("/api/agent/ping", headers=bearer(clair))
        assert r.status_code == 200 and r.json()["nom"].startswith("test-")
