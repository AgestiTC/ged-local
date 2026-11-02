"""
Tests — jetons d'automates (plan d'authentification, étape 4)
==============================================================
Acceptation du plan : un jeton révoqué ou expiré est refusé ; un jeton `lecture` reçoit 403 sur une
écriture ; le jeton en clair n'est stocké nulle part. Données fictives, aucun appel réseau.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from models.auth import JetonApi, SessionAuth, Utilisateur
from services import acces, audit, jetons_api, oidc_service, runtime_config

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


@pytest.fixture
def evenements(monkeypatch):
    liste = []

    async def faux_emit(action, statut, **kw):
        liste.append((action, statut, kw))

    monkeypatch.setattr(audit, "emit", faux_emit)
    return liste


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


async def jeton_direct(db, role="utilisateur", portee="lecture", *, expire=None, revoque=None, createur_id=None) -> str:
    """Jeton fictif posé directement en base ; rend le clair."""
    clair = jetons_api.nouveau_jeton()
    db.add(JetonApi(nom=f"test-{uuid.uuid4().hex[:8]}", empreinte=jetons_api.empreinte(clair), role=role,
                    portee=portee, expire=expire, revoque=revoque, createur_id=createur_id))
    await db.commit()
    return clair


class TestClassement:
    def test_routes_de_gestion_admin(self):
        for m, p in [("GET", "/api/auth/jetons"), ("POST", "/api/auth/jetons"),
                     ("POST", "/api/auth/jetons/{jeton_id}/revoquer")]:
            assert acces.classer(m, p) == acces.ADMIN
        assert not any(c.startswith("/api/auth/jetons") for c in acces.LISTE_BLANCHE)

    def test_lire_bearer(self):
        class R:
            def __init__(self, v):
                self.headers = {"authorization": v} if v is not None else {}
        assert jetons_api.lire_bearer(R("Bearer abc")) == "abc"
        assert jetons_api.lire_bearer(R("bearer  abc ")) == "abc"
        assert jetons_api.lire_bearer(R("Basic abc")) is None
        assert jetons_api.lire_bearer(R("Bearer ")) is None
        assert jetons_api.lire_bearer(R(None)) is None


class TestGestion:
    @pytest.mark.asyncio
    async def test_creation_jeton_montre_une_fois_jamais_stocke(self, client, auth_on, db_session, evenements):
        adm = await session(db_session, "admin")
        r = await client.post("/api/auth/jetons", json={"nom": "n8n — dossiers", "role": "admin",
                                                        "portee": "ecriture", "expire_jours": 30}, headers=ck(adm))
        assert r.status_code == 201, r.text
        corps = r.json()
        clair = corps["jeton"]
        assert clair.startswith("mato_") and len(clair) > 40
        assert corps["actif"] is True and corps["createur"].startswith("admin-") and corps["expire"]

        ligne = (await db_session.execute(select(JetonApi).where(JetonApi.nom == "n8n — dossiers"))).scalar_one()
        assert ligne.empreinte == jetons_api.empreinte(clair)
        valeurs = [str(getattr(ligne, c.name)) for c in JetonApi.__table__.columns]
        assert not any(clair in v for v in valeurs), "le jeton en clair ne doit être stocké nulle part"

        liste = (await client.get("/api/auth/jetons", headers=ck(adm))).json()["jetons"]
        assert len(liste) == 1 and "jeton" not in liste[0] and "empreinte" not in liste[0]
        assert clair not in str(liste) and ligne.empreinte not in str(liste)
        assert evenements[0][0] == "auth_jeton_cree" and clair not in str(evenements)

    @pytest.mark.asyncio
    async def test_nom_deja_pris_409(self, client, auth_on, db_session):
        adm = await session(db_session, "admin")
        assert (await client.post("/api/auth/jetons", json={"nom": "doublon"}, headers=ck(adm))).status_code == 201
        assert (await client.post("/api/auth/jetons", json={"nom": "doublon"}, headers=ck(adm))).status_code == 409

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corps", [{"nom": ""}, {"nom": "x", "role": "root"}, {"nom": "x", "portee": "tout"},
                                       {"nom": "x", "expire_jours": 0}, {"nom": "x", "expire_jours": None},
                                       {"nom": "x", "expire_jours": 731}])
    async def test_entrees_invalides_422(self, client, auth_on, db_session, corps):
        adm = await session(db_session, "admin")
        assert (await client.post("/api/auth/jetons", json=corps, headers=ck(adm))).status_code == 422

    @pytest.mark.asyncio
    async def test_utilisateur_et_anonyme_refuses(self, client, auth_on, db_session):
        assert (await client.get("/api/auth/jetons")).status_code == 401
        u = await session(db_session, "utilisateur")
        assert (await client.get("/api/auth/jetons", headers=ck(u))).status_code == 403
        assert (await client.post("/api/auth/jetons", json={"nom": "x"}, headers=ck(u))).status_code == 403

    @pytest.mark.asyncio
    async def test_auth_eteinte_pas_de_creation_anonyme(self, client, db_session):
        """Sans identité (auth éteinte), personne ne crée de jeton : le journal doit savoir QUI."""
        assert (await client.post("/api/auth/jetons", json={"nom": "x"})).status_code == 401

    @pytest.mark.asyncio
    async def test_revocation_definitive_et_journalisee(self, client, auth_on, db_session, evenements):
        adm = await session(db_session, "admin")
        cree = (await client.post("/api/auth/jetons", json={"nom": "a-revoquer", "portee": "ecriture"},
                                  headers=ck(adm))).json()
        assert (await client.get("/api/prompts", headers=bearer(cree["jeton"]))).status_code == 200
        r = await client.post(f"/api/auth/jetons/{cree['id']}/revoquer", headers=ck(adm))
        assert r.status_code == 200 and r.json()["actif"] is False and r.json()["revoque"]
        assert (await client.get("/api/prompts", headers=bearer(cree["jeton"]))).status_code == 401
        # Idempotente : une 2ᵉ révocation ne rejournalise pas.
        assert (await client.post(f"/api/auth/jetons/{cree['id']}/revoquer", headers=ck(adm))).status_code == 200
        assert [e[0] for e in evenements].count("auth_jeton_revoque") == 1

    @pytest.mark.asyncio
    async def test_bloquer_le_createur_revoque_ses_jetons(self, client, auth_on, db_session, evenements):
        adm = await session(db_session, "admin")
        autre_ck = await session(db_session, "admin")
        autre = (await db_session.execute(select(SessionAuth).where(
            SessionAuth.id == oidc_service.hacher_jeton(autre_ck)))).scalar_one().utilisateur_id
        j_autre = await jeton_direct(db_session, portee="ecriture", createur_id=autre)
        j_garde = await jeton_direct(db_session, portee="ecriture")
        r = await client.post(f"/api/auth/utilisateurs/{autre}/bloquer", json={"bloque": True}, headers=ck(adm))
        assert r.status_code == 200 and r.json()["jetons_revoques"] == 1
        assert (await client.get("/api/prompts", headers=bearer(j_autre))).status_code == 401
        assert (await client.get("/api/prompts", headers=bearer(j_garde))).status_code == 200

    @pytest.mark.asyncio
    async def test_createur_id_pose_a_la_creation(self, client, auth_on, db_session):
        adm = await session(db_session, "admin")
        await client.post("/api/auth/jetons", json={"nom": "lie"}, headers=ck(adm))
        ligne = (await db_session.execute(select(JetonApi).where(JetonApi.nom == "lie"))).scalar_one()
        assert ligne.createur_id is not None and ligne.expire is not None

    @pytest.mark.asyncio
    async def test_revoquer_inconnu_404(self, client, auth_on, db_session):
        adm = await session(db_session, "admin")
        assert (await client.post(f"/api/auth/jetons/{uuid.uuid4()}/revoquer", headers=ck(adm))).status_code == 404


class TestControle:
    @pytest.mark.asyncio
    async def test_inconnu_revoque_expire_401(self, client, auth_on, db_session):
        now = datetime.now(timezone.utc)
        revoque = await jeton_direct(db_session, revoque=now)
        expire = await jeton_direct(db_session, expire=now - timedelta(seconds=1))
        for j in ("mato_inconnu", revoque, expire):
            r = await client.get("/api/prompts", headers=bearer(j))
            assert r.status_code == 401, j

    @pytest.mark.asyncio
    async def test_echeance_future_accepte(self, client, auth_on, db_session):
        j = await jeton_direct(db_session, expire=datetime.now(timezone.utc) + timedelta(days=1))
        assert (await client.get("/api/prompts", headers=bearer(j))).status_code == 200

    @pytest.mark.asyncio
    async def test_lecture_403_sur_ecriture(self, client, auth_on, db_session):
        j = await jeton_direct(db_session, role="admin", portee="lecture")
        assert (await client.get("/api/folders", headers=bearer(j))).status_code == 200
        for methode, url in [("POST", "/api/prompts/relire"), ("POST", "/api/folders"),
                             ("DELETE", f"/api/documents/{uuid.uuid4()}")]:
            r = await client.request(methode, url, headers=bearer(j), json={})
            assert r.status_code == 403 and "lecture seule" in r.json()["detail"], url

    @pytest.mark.asyncio
    async def test_role_utilisateur_403_sur_route_admin(self, client, auth_on, db_session):
        j = await jeton_direct(db_session, role="utilisateur", portee="ecriture")
        assert (await client.get("/api/prompts", headers=bearer(j))).status_code == 200
        assert (await client.get("/api/system/config", headers=bearer(j))).status_code == 403
        assert (await client.get("/api/folders", headers=bearer(j))).status_code == 403

    @pytest.mark.asyncio
    async def test_jeton_jamais_sur_auth(self, client, auth_on, db_session):
        """Même admin en écriture, un jeton ne crée pas d'autre jeton et ne touche pas aux personnes."""
        j = await jeton_direct(db_session, role="admin", portee="ecriture")
        assert (await client.get("/api/auth/jetons", headers=bearer(j))).status_code == 403
        assert (await client.post("/api/auth/jetons", json={"nom": "clone"}, headers=bearer(j))).status_code == 403
        assert (await client.get("/api/auth/utilisateurs", headers=bearer(j))).status_code == 403

    @pytest.mark.asyncio
    @pytest.mark.parametrize("methode,url", [
        ("GET", "/api/system/config"), ("PUT", "/api/system/config"), ("GET", "/api/system/backups"),
        ("GET", "/api/system/backups/dump.sql"), ("GET", "/api/logs/tail"), ("GET", "/api/audit"),
        ("GET", "/api/sources"), ("POST", "/api/passerelle/projets"), ("GET", "/api/passerelle/projets"),
        ("GET", "/api/docs"), ("GET", "/api/fiscalite/declarations"), ("GET", "/api/emploi-domicile/intervenants"),
    ])
    async def test_jeton_admin_plafonne(self, client, auth_on, db_session, methode, url):
        """Même admin + écriture, un jeton n'atteint que /api/folders* parmi les routes admin, et jamais le foyer."""
        j = await jeton_direct(db_session, role="admin", portee="ecriture")
        r = await client.request(methode, url, headers=bearer(j), json={})
        assert r.status_code == 403 and "hors de portée" in r.json()["detail"], (url, r.status_code)

    @pytest.mark.asyncio
    async def test_jeton_admin_ecriture_sur_dossiers(self, client, auth_on, db_session):
        j = await jeton_direct(db_session, role="admin", portee="ecriture")
        assert (await client.get("/api/folders", headers=bearer(j))).status_code == 200

    @pytest.mark.asyncio
    async def test_suspension_ouvre_meme_un_jeton_revoque(self, client, auth_on, db_session):
        """Accès de secours = API ouverte (voulu) : le Bearer n'y change rien, même révoqué."""
        from models.config import Config
        db_session.add(Config(cle=acces.CLE_SUSPENSION,
                              valeur=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()))
        await db_session.commit()
        j = await jeton_direct(db_session, revoque=datetime.now(timezone.utc))
        r = await client.get("/api/prompts", headers=bearer(j))
        assert r.status_code == 200 and "X-Auth-Suspendue" in r.headers

    @pytest.mark.asyncio
    async def test_bearer_invalide_ignore_le_cookie(self, client, auth_on, db_session):
        """Un en-tête Bearer décide seul : un mauvais jeton n'est pas rattrapé par un cookie admin valide."""
        adm = await session(db_session, "admin")
        r = await client.get("/api/system/config", headers={**ck(adm), **bearer("mato_faux")})
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_derniere_utilisation_datee(self, client, auth_on, db_session):
        j = await jeton_direct(db_session)
        assert (await client.get("/api/prompts", headers=bearer(j))).status_code == 200
        ligne = (await db_session.execute(
            select(JetonApi).where(JetonApi.empreinte == jetons_api.empreinte(j)))).scalar_one()
        await db_session.refresh(ligne)
        assert ligne.derniere_utilisation is not None

    @pytest.mark.asyncio
    async def test_auth_eteinte_aucun_refus(self, client, db_session):
        """Comportement historique : sans authentification active, un Bearer quelconque ne bloque rien."""
        assert (await client.get("/api/prompts", headers=bearer("mato_quelconque"))).status_code == 200
