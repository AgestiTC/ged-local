"""
Tests — connexion OpenID Connect (plan d'authentification, étape 1)
===================================================================
Fournisseur OIDC SIMULÉ : clés RSA et EC générées ici, découverte / JWKS / échange du code
remplacés par monkeypatch du service. Aucun appel réseau, données 100 % fictives.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from models.auth import OidcTentative, SessionAuth, Utilisateur
from services import oidc_service, runtime_config

# Vraies fonctions réseau, capturées AVANT que la fixture `idp` ne les remplace par des simulacres.
_VRAI_DISCOVER = oidc_service.discover
_VRAI_GET_JWKS = oidc_service.get_jwks
_VRAI_EXCHANGE = oidc_service.exchange_code

ISSUER = "https://sso.test.invalid/webman/sso"
CLIENT_ID = "matotheque-test"
REDIRECT = "https://ged.test.invalid/api/auth/callback"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _int_b64(n: int, taille: int | None = None) -> str:
    taille = taille or (n.bit_length() + 7) // 8
    return _b64(n.to_bytes(taille, "big"))


class FauxFournisseur:
    """Émetteur OIDC de test : produit des jetons signés et sert la découverte / les clés."""

    def __init__(self):
        self.rsa = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.ec = ec.generate_private_key(ec.SECP256R1())
        nums = self.rsa.public_key().public_numbers()
        enums = self.ec.public_key().public_numbers()
        self.jwks = {"keys": [
            {"kty": "RSA", "kid": "rsa1", "use": "sig", "alg": "RS256",
             "n": _int_b64(nums.n), "e": _int_b64(nums.e)},
            {"kty": "EC", "kid": "ec1", "use": "sig", "alg": "ES256", "crv": "P-256",
             "x": _int_b64(enums.x, 32), "y": _int_b64(enums.y, 32)},
        ]}
        self.nonce = ""                 # renseigné par le login
        self.claims_extra: dict = {}    # surcharges de revendications
        self.supprimer: set[str] = set()
        self.jeton_force: str | None = None
        self.appels_echange = 0

    def claims(self, **extra) -> dict:
        now = int(time.time())
        c = {"iss": ISSUER, "aud": CLIENT_ID, "sub": "sub-alice-001", "iat": now, "exp": now + 300,
             "nonce": self.nonce, "preferred_username": "alice", "name": "Alice Fictive",
             "email": "alice@test.invalid", "groups": ["matotheque-utilisateurs"]}
        c.update(self.claims_extra)
        c.update(extra)
        for k in self.supprimer:
            c.pop(k, None)
        return c

    def jeton(self, claims: dict | None = None, alg: str = "RS256", kid: str | None = "rsa1",
              corrompre: bool = False) -> str:
        claims = self.claims() if claims is None else claims
        header = {"alg": alg, "typ": "JWT"}
        if kid:
            header["kid"] = kid
        signing = f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}".encode()
        if alg == "RS256":
            sig = self.rsa.sign(signing, padding.PKCS1v15(), hashes.SHA256())
        elif alg == "ES256":
            r, s = decode_dss_signature(self.ec.sign(signing, ec.ECDSA(hashes.SHA256())))
            sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        elif alg == "none":
            sig = b""
        else:  # HS256 : attaque classique, la « clé » HMAC est la clé publique
            sig = hmac.new(self.jwks["keys"][0]["n"].encode(), signing, hashlib.sha256).digest()
        if corrompre:
            sig = bytes([sig[0] ^ 0xFF]) + sig[1:]
        return f"{signing.decode()}.{_b64(sig)}"


@pytest.fixture
def idp(monkeypatch) -> FauxFournisseur:
    f = FauxFournisseur()

    async def discover():
        return {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token", "jwks_uri": f"{ISSUER}/jwks",
                "end_session_endpoint": f"{ISSUER}/logout"}

    async def get_jwks(uri, *, forcer=False):
        return f.jwks

    async def exchange_code(disco, code, code_verifier):
        f.appels_echange += 1
        assert code_verifier  # PKCE toujours transmis
        return {"id_token": f.jeton_force or f.jeton(), "access_token": "x"}

    monkeypatch.setattr(oidc_service, "discover", discover)
    monkeypatch.setattr(oidc_service, "get_jwks", get_jwks)
    monkeypatch.setattr(oidc_service, "exchange_code", exchange_code)
    runtime_config._overrides.update({
        "oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID, "oidc_redirect_uri": REDIRECT,
    })
    return f


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


async def _login(client, idp, retour: str | None = None) -> str:
    """Appelle /auth/login, mémorise le nonce chez le faux SSO, rend le state."""
    params = {"retour": retour} if retour is not None else {}
    r = await client.get("/api/auth/login", params=params)
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    idp.nonce = q["nonce"][0]
    return q["state"][0]


async def _connecter(client, idp, **kw):
    state = await _login(client, idp, kw.pop("retour", None))
    return await client.get("/api/auth/callback", params={"code": "code-fictif", "state": state})


def _erreur(r) -> str | None:
    assert r.status_code == 302
    return parse_qs(urlparse(r.headers["location"]).query).get("auth_erreur", [None])[0]


# ─── Parcours complet ─────────────────────────────────────────────────────────

class TestParcours:
    @pytest.mark.asyncio
    async def test_login_callback_me_logout(self, client, idp, db_session):
        r = await client.get("/api/auth/login", params={"retour": "/ged?q=1"})
        assert r.status_code == 302
        url = urlparse(r.headers["location"])
        q = parse_qs(url.query)
        assert f"{url.scheme}://{url.netloc}{url.path}" == f"{ISSUER}/authorize"
        assert q["response_type"] == ["code"] and q["client_id"] == [CLIENT_ID]
        assert q["redirect_uri"] == [REDIRECT]
        assert q["scope"] == ["openid profile email groups"]
        assert q["code_challenge_method"] == ["S256"] and q["code_challenge"][0]
        assert q["state"][0] != q["nonce"][0]
        idp.nonce = q["nonce"][0]

        r = await client.get("/api/auth/callback", params={"code": "c", "state": q["state"][0]})
        assert r.status_code == 302 and r.headers["location"] == "/ged?q=1"
        cookie = r.headers["set-cookie"].lower()
        assert "matotheque_session=" in cookie and "httponly" in cookie
        assert "samesite=lax" in cookie and "path=/" in cookie
        assert "secure" not in cookie   # requête en http

        me = (await client.get("/api/auth/me")).json()
        assert me["auth_active"] is False
        assert me["utilisateur"] == {"identifiant": "alice", "nom": "Alice Fictive",
                                     "email": "alice@test.invalid", "role": "utilisateur"}

        r = await client.post("/api/auth/logout")
        assert r.json() == {"deconnecte": True, "end_session_endpoint": f"{ISSUER}/logout"}
        assert (await client.get("/api/auth/me")).json()["utilisateur"] is None
        assert (await db_session.execute(select(SessionAuth))).scalars().all() == []

    @pytest.mark.asyncio
    async def test_session_stockee_hachee(self, client, idp, db_session):
        r = await _connecter(client, idp)
        jeton = r.headers["set-cookie"].split("matotheque_session=")[1].split(";")[0]
        assert len(jeton) >= 43   # 32 octets en base64url
        sess = (await db_session.execute(select(SessionAuth))).scalars().one()
        assert sess.id == hashlib.sha256(jeton.encode()).hexdigest() and sess.id != jeton

    @pytest.mark.asyncio
    async def test_cookie_secure_derriere_proxy_tls(self, client, idp):
        state = await _login(client, idp)
        r = await client.get("/api/auth/callback", params={"code": "c", "state": state},
                             headers={"X-Forwarded-Proto": "https"})
        assert "secure" in r.headers["set-cookie"].lower()

    @pytest.mark.asyncio
    async def test_es256_accepte(self, client, idp):
        state = await _login(client, idp)
        idp.jeton_force = idp.jeton(alg="ES256", kid="ec1")
        r = await client.get("/api/auth/callback", params={"code": "c", "state": state})
        assert _erreur_ou_none(r) is None
        assert (await client.get("/api/auth/me")).json()["utilisateur"]["identifiant"] == "alice"

    @pytest.mark.asyncio
    async def test_groupe_admin_donne_role_admin_et_jit_mis_a_jour(self, client, idp, db_session):
        await _connecter(client, idp)
        idp.claims_extra = {"groups": ["matotheque-admin", "matotheque-utilisateurs"], "name": "Alice B."}
        await _connecter(client, idp)
        users = (await db_session.execute(select(Utilisateur))).scalars().all()
        assert len(users) == 1                      # pas de doublon à la 2e connexion
        assert users[0].role == "admin" and users[0].nom == "Alice B."
        assert "matotheque-admin" in users[0].groupes

    @pytest.mark.asyncio
    async def test_oidc_non_configure_503(self, client):
        r = await client.get("/api/auth/login")
        assert r.status_code == 503 and "non configur" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_me_sans_session(self, client):
        r = await client.get("/api/auth/me")
        assert r.json() == {"auth_active": False, "utilisateur": None}


def _erreur_ou_none(r):
    q = parse_qs(urlparse(r.headers["location"]).query)
    return q.get("auth_erreur", [None])[0]


# ─── Jeton d'identité ─────────────────────────────────────────────────────────

class TestJetonRefuse:
    async def _refus(self, client, idp, jeton: str | None = None, **claims):
        state = await _login(client, idp)
        idp.jeton_force = jeton if jeton is not None else idp.jeton(idp.claims(**claims))
        r = await client.get("/api/auth/callback", params={"code": "c", "state": state})
        assert _erreur(r) == "jeton_invalide"
        assert (await client.get("/api/auth/me")).json()["utilisateur"] is None
        assert not any("matotheque_session=" in v for v in r.headers.get_list("set-cookie"))

    @pytest.mark.asyncio
    async def test_signature_invalide(self, client, idp):
        state = await _login(client, idp)
        idp.jeton_force = idp.jeton(corrompre=True)
        r = await client.get("/api/auth/callback", params={"code": "c", "state": state})
        assert _erreur(r) == "jeton_invalide"

    @pytest.mark.asyncio
    async def test_signature_es256_invalide(self, client, idp):
        state = await _login(client, idp)
        idp.jeton_force = idp.jeton(alg="ES256", kid="ec1", corrompre=True)
        r = await client.get("/api/auth/callback", params={"code": "c", "state": state})
        assert _erreur(r) == "jeton_invalide"

    @pytest.mark.asyncio
    async def test_kid_inconnu(self, client, idp):
        await self._refus(client, idp, idp.jeton(kid="inconnu"))

    @pytest.mark.asyncio
    async def test_kid_absent(self, client, idp):
        await self._refus(client, idp, idp.jeton(kid=None))

    @pytest.mark.asyncio
    async def test_cle_rsa_pour_alg_es256_refusee(self, client, idp):
        await self._refus(client, idp, idp.jeton(alg="ES256", kid="rsa1"))

    @pytest.mark.asyncio
    async def test_issuer_faux(self, client, idp):
        await self._refus(client, idp, iss="https://faux.invalid")

    @pytest.mark.asyncio
    async def test_audience_fausse(self, client, idp):
        await self._refus(client, idp, aud="autre-client")

    @pytest.mark.asyncio
    async def test_audience_multiple_sans_azp(self, client, idp):
        await self._refus(client, idp, aud=[CLIENT_ID, "autre"])

    @pytest.mark.asyncio
    async def test_expire(self, client, idp):
        await self._refus(client, idp, exp=int(time.time()) - 600)

    @pytest.mark.asyncio
    async def test_exp_absent(self, client, idp):
        idp.supprimer = {"exp"}
        await self._refus(client, idp)

    @pytest.mark.asyncio
    async def test_iat_dans_le_futur(self, client, idp):
        await self._refus(client, idp, iat=int(time.time()) + 3600)

    @pytest.mark.asyncio
    async def test_nonce_faux(self, client, idp):
        await self._refus(client, idp, nonce="rejoue-d-une-autre-tentative")

    @pytest.mark.asyncio
    async def test_nonce_absent(self, client, idp):
        idp.supprimer = {"nonce"}
        await self._refus(client, idp)

    @pytest.mark.asyncio
    async def test_alg_none(self, client, idp):
        await self._refus(client, idp, idp.jeton(alg="none"))

    @pytest.mark.asyncio
    async def test_alg_hs256(self, client, idp):
        await self._refus(client, idp, idp.jeton(alg="HS256"))

    @pytest.mark.asyncio
    async def test_jeton_mal_forme(self, client, idp):
        await self._refus(client, idp, "pas.un.jeton")

    def test_tolerance_horloge(self, idp):
        now = time.time()
        # exp dépassé de 60 s : toléré (120 s) ; iat à +60 s : toléré
        c = idp.claims(nonce="n", exp=int(now) - 60, iat=int(now) + 60)
        assert oidc_service.validate_id_token(idp.jeton(c), idp.jwks, issuer=ISSUER,
                                              client_id=CLIENT_ID, nonce="n")["sub"]


# ─── State ────────────────────────────────────────────────────────────────────

class TestState:
    @pytest.mark.asyncio
    async def test_state_inconnu(self, client, idp):
        r = await client.get("/api/auth/callback", params={"code": "c", "state": "inconnu"})
        assert _erreur(r) == "etat_invalide" and idp.appels_echange == 0

    @pytest.mark.asyncio
    async def test_state_absent(self, client, idp):
        r = await client.get("/api/auth/callback", params={"code": "c"})
        assert _erreur(r) == "etat_invalide"

    @pytest.mark.asyncio
    async def test_state_rejoue(self, client, idp):
        state = await _login(client, idp)
        r1 = await client.get("/api/auth/callback", params={"code": "c", "state": state})
        assert _erreur_ou_none(r1) is None
        r2 = await client.get("/api/auth/callback", params={"code": "c", "state": state})
        assert _erreur(r2) == "etat_invalide" and idp.appels_echange == 1

    @pytest.mark.asyncio
    async def test_state_expire(self, client, idp, db_session):
        state = await _login(client, idp)
        t = (await db_session.execute(select(OidcTentative))).scalars().one()
        t.creee = oidc_service.maintenant() - timedelta(minutes=11)
        await db_session.commit()
        r = await client.get("/api/auth/callback", params={"code": "c", "state": state})
        assert _erreur(r) == "etat_expire" and idp.appels_echange == 0
        assert (await db_session.execute(select(OidcTentative))).scalars().all() == []

    @pytest.mark.asyncio
    async def test_tentative_supprimee_meme_en_echec(self, client, idp, db_session):
        state = await _login(client, idp)
        idp.jeton_force = idp.jeton(corrompre=True)
        await client.get("/api/auth/callback", params={"code": "c", "state": state})
        assert (await db_session.execute(select(OidcTentative))).scalars().all() == []

    @pytest.mark.asyncio
    async def test_erreur_du_sso(self, client, idp):
        state = await _login(client, idp)
        r = await client.get("/api/auth/callback", params={"error": "access_denied", "state": state})
        assert _erreur(r) == "sso_refuse"


# ─── Rôles et blocage ─────────────────────────────────────────────────────────

class TestAcces:
    @pytest.mark.asyncio
    async def test_groupe_absent_refuse_sans_creation(self, client, idp, db_session):
        idp.claims_extra = {"groups": ["autre-groupe"]}
        r = await _connecter(client, idp)
        assert _erreur(r) == "acces_refuse"
        assert (await db_session.execute(select(Utilisateur))).scalars().all() == []
        assert (await db_session.execute(select(SessionAuth))).scalars().all() == []

    @pytest.mark.asyncio
    async def test_sans_revendication_groups(self, client, idp):
        idp.supprimer = {"groups"}
        assert _erreur(await _connecter(client, idp)) == "acces_refuse"

    @pytest.mark.asyncio
    async def test_groupes_configurables(self, client, idp):
        runtime_config._overrides["oidc_groupe_utilisateurs"] = "equipe-x"
        idp.claims_extra = {"groups": ["matotheque-utilisateurs"]}
        assert _erreur(await _connecter(client, idp)) == "acces_refuse"
        idp.claims_extra = {"groups": ["equipe-x"]}
        assert _erreur_ou_none(await _connecter(client, idp)) is None

    @pytest.mark.asyncio
    async def test_utilisateur_bloque(self, client, idp, db_session):
        await _connecter(client, idp)
        u = (await db_session.execute(select(Utilisateur))).scalars().one()
        u.bloque = True
        await db_session.commit()
        # La session ouverte est coupée au prochain appel…
        assert (await client.get("/api/auth/me")).json()["utilisateur"] is None
        # … et une nouvelle connexion est refusée même si le SSO accepte.
        assert _erreur(await _connecter(client, idp)) == "compte_bloque"
        assert (await db_session.execute(select(SessionAuth))).scalars().all() == []


# ─── Redirection ouverte ──────────────────────────────────────────────────────

class TestRetour:
    @pytest.mark.parametrize("retour", ["//evil.com", "https://evil.example", "http://evil", "evil.com",
                                         "/\\evil.com", "javascript:alert(1)", "", "/x://evil"])
    @pytest.mark.asyncio
    async def test_retour_dangereux_devient_racine(self, client, idp, retour):
        r = await _connecter(client, idp, retour=retour)
        assert r.status_code == 302 and r.headers["location"] == "/"

    @pytest.mark.asyncio
    async def test_retour_relatif_conserve(self, client, idp):
        r = await _connecter(client, idp, retour="/parametres#auth")
        assert r.headers["location"] == "/parametres#auth"


# ─── Expiration des sessions ──────────────────────────────────────────────────

class TestExpiration:
    @pytest.mark.asyncio
    async def test_inactivite(self, client, idp, db_session):
        await _connecter(client, idp)
        s = (await db_session.execute(select(SessionAuth))).scalars().one()
        s.derniere_activite = oidc_service.maintenant() - timedelta(hours=12, minutes=1)
        await db_session.commit()
        assert (await client.get("/api/auth/me")).json()["utilisateur"] is None
        assert (await db_session.execute(select(SessionAuth))).scalars().all() == []

    @pytest.mark.asyncio
    async def test_inactivite_configurable(self, client, idp, db_session):
        runtime_config._overrides["auth_session_inactivite_heures"] = "1"
        await _connecter(client, idp)
        s = (await db_session.execute(select(SessionAuth))).scalars().one()
        s.derniere_activite = oidc_service.maintenant() - timedelta(hours=2)
        await db_session.commit()
        assert (await client.get("/api/auth/me")).json()["utilisateur"] is None

    @pytest.mark.asyncio
    async def test_duree_max(self, client, idp, db_session):
        await _connecter(client, idp)
        s = (await db_session.execute(select(SessionAuth))).scalars().one()
        # activité récente mais durée maximale dépassée
        s.expire_max = oidc_service.maintenant() - timedelta(seconds=1)
        await db_session.commit()
        assert (await client.get("/api/auth/me")).json()["utilisateur"] is None
        assert (await db_session.execute(select(SessionAuth))).scalars().all() == []

    @pytest.mark.asyncio
    async def test_expire_max_par_defaut_7_jours(self, client, idp, db_session):
        await _connecter(client, idp)
        s = (await db_session.execute(select(SessionAuth))).scalars().one()
        reste = (s.expire_max.replace(tzinfo=None) - oidc_service.maintenant().replace(tzinfo=None))
        assert timedelta(days=6, hours=23) < reste <= timedelta(days=7)

    @pytest.mark.asyncio
    async def test_activite_mise_a_jour_au_plus_une_fois_par_minute(self, client, idp, db_session):
        await _connecter(client, idp)
        s = (await db_session.execute(select(SessionAuth))).scalars().one()
        avant = s.derniere_activite
        await client.get("/api/auth/me")
        await db_session.refresh(s)
        assert s.derniere_activite == avant                   # < 1 min : pas d'écriture
        ancien = oidc_service.maintenant() - timedelta(minutes=5)
        s.derniere_activite = ancien
        await db_session.commit()
        assert (await client.get("/api/auth/me")).json()["utilisateur"] is not None
        await db_session.refresh(s)
        assert s.derniere_activite.replace(tzinfo=None) > ancien.replace(tzinfo=None) + timedelta(minutes=4)

    @pytest.mark.asyncio
    async def test_cookie_inconnu(self, client, idp):
        client.cookies.set("matotheque_session", "jeton-forge")
        assert (await client.get("/api/auth/me")).json()["utilisateur"] is None


# ─── Secret et réglages ───────────────────────────────────────────────────────

class TestReglages:
    def test_defauts(self):
        e = runtime_config.effective
        assert e("oidc_redirect_uri") == "https://ged.tclement.fr/api/auth/callback"
        assert e("oidc_groupe_admin") == "matotheque-admin"
        assert e("oidc_groupe_utilisateurs") == "matotheque-utilisateurs"
        assert e("auth_session_inactivite_heures") == "12" and e("auth_session_max_jours") == "7"
        assert e("auth_active") == "false" and not oidc_service.auth_active()

    @pytest.mark.asyncio
    async def test_secret_chiffre_et_masque(self, client, db_session):
        secret = "S3cret-Fictif-à-ne-jamais-voir"
        r = await client.put("/api/system/config", json={"oidc_client_secret": secret, "oidc_client_id": CLIENT_ID})
        assert r.status_code == 200 and secret not in r.text
        stocke = runtime_config._overrides["oidc_client_secret"]
        assert stocke.startswith("enc::") and secret not in stocke
        assert oidc_service.client_secret() == secret          # le service, lui, le déchiffre

        r = await client.get("/api/system/config")
        assert secret not in r.text and stocke not in r.text
        entree = r.json()["config"]["oidc_client_secret"]
        assert entree["valeur"] != secret and entree["defini"] is True
        assert r.json()["config"]["oidc_client_id"]["valeur"] == CLIENT_ID

    @pytest.mark.asyncio
    async def test_auth_active_sans_effet_sur_routes_existantes(self, client):
        runtime_config._overrides["auth_active"] = "true"
        assert (await client.get("/api/version")).status_code == 200
        assert (await client.get("/api/auth/me")).json()["auth_active"] is True

    @pytest.mark.asyncio
    async def test_pas_de_fuite_dans_les_journaux(self, client, idp, capsys, caplog):
        runtime_config._overrides["oidc_client_secret"] = "enc::x"
        state = await _login(client, idp)
        idp.jeton_force = idp.jeton(corrompre=True)
        await client.get("/api/auth/callback", params={"code": "code-secret-fictif", "state": state})
        vu = capsys.readouterr()
        sortie = vu.out + vu.err + caplog.text
        assert "code-secret-fictif" not in sortie and idp.jeton_force not in sortie


# ─── Courses entre workers ────────────────────────────────────────────────────

class TestCourses:
    @pytest.mark.asyncio
    async def test_premiere_connexion_concurrente_meme_sub(self, client, idp, db_session, monkeypatch):
        """Une autre connexion crée la fiche entre notre lecture et notre insertion : pas de 500."""
        from routers import auth as routeur
        reel = routeur._utilisateur_par_sub
        appels = {"n": 0}

        async def lecture_en_retard(db, emetteur, sub):
            appels["n"] += 1
            if appels["n"] == 1:   # 1re lecture : la fiche n'existe pas encore, puis le concurrent l'insère
                await db.execute(Utilisateur.__table__.insert().values(
                    id=uuid.uuid4(), emetteur=emetteur, sub=sub, role="utilisateur", identifiant="deja-la", bloque=False))
                return None
            return await reel(db, emetteur, sub)

        monkeypatch.setattr(routeur, "_utilisateur_par_sub", lecture_en_retard)
        r = await _connecter(client, idp)
        assert _erreur_ou_none(r) is None
        users = (await db_session.execute(select(Utilisateur))).scalars().all()
        assert len(users) == 1 and users[0].identifiant == "alice"
        assert (await client.get("/api/auth/me")).json()["utilisateur"]["identifiant"] == "alice"

    @pytest.mark.asyncio
    async def test_course_concurrente_sur_compte_bloque_refusee(self, client, idp, monkeypatch):
        from routers import auth as routeur
        reel = routeur._utilisateur_par_sub
        appels = {"n": 0}

        async def lecture_en_retard(db, emetteur, sub):
            appels["n"] += 1
            if appels["n"] == 1:
                await db.execute(Utilisateur.__table__.insert().values(
                    id=uuid.uuid4(), emetteur=emetteur, sub=sub, role="utilisateur", bloque=True))
                return None
            return await reel(db, emetteur, sub)

        monkeypatch.setattr(routeur, "_utilisateur_par_sub", lecture_en_retard)
        assert _erreur(await _connecter(client, idp)) == "compte_bloque"

    @pytest.mark.asyncio
    async def test_logout_puis_me_apres_activite_ancienne(self, client, idp, db_session):
        await _connecter(client, idp)
        s = (await db_session.execute(select(SessionAuth))).scalars().one()
        s.derniere_activite = oidc_service.maintenant() - timedelta(minutes=5)
        await db_session.commit()
        await client.post("/api/auth/logout")
        assert (await client.get("/api/auth/me")).json()["utilisateur"] is None

    @pytest.mark.asyncio
    async def test_purge_au_login_des_sessions_inactives(self, client, idp, db_session):
        await _connecter(client, idp)
        s = (await db_session.execute(select(SessionAuth))).scalars().one()
        s.derniere_activite = oidc_service.maintenant() - timedelta(hours=13)
        await db_session.commit()
        await _login(client, idp)
        assert (await db_session.execute(select(SessionAuth))).scalars().all() == []


# ─── Lien state / navigateur (login CSRF) ─────────────────────────────────────

class TestNavigateur:
    @pytest.mark.asyncio
    async def test_login_pose_cookie_navigateur(self, client, idp):
        r = await client.get("/api/auth/login")
        c = r.headers["set-cookie"].lower()
        assert "matotheque_oidc=" in c and "httponly" in c and "samesite=lax" in c
        assert "path=/api/auth" in c and "max-age=600" in c

    @pytest.mark.asyncio
    async def test_callback_sans_cookie_refuse(self, client, idp):
        state = await _login(client, idp)
        client.cookies.clear()      # le state arrive dans un navigateur qui n'a pas lancé la connexion
        r = await client.get("/api/auth/callback", params={"code": "c", "state": state})
        assert _erreur(r) == "etat_invalide" and idp.appels_echange == 0
        assert (await client.get("/api/auth/me")).json()["utilisateur"] is None

    @pytest.mark.asyncio
    async def test_callback_cookie_autre_navigateur_refuse(self, client, idp):
        state = await _login(client, idp)
        client.cookies.clear()
        r = await client.get("/api/auth/callback", params={"code": "c", "state": state},
                             headers={"cookie": "matotheque_oidc=secret-d-un-autre-navigateur"})
        assert _erreur(r) == "etat_invalide" and idp.appels_echange == 0

    @pytest.mark.asyncio
    async def test_tentative_consommee_meme_si_cookie_faux(self, client, idp, db_session):
        state = await _login(client, idp)
        client.cookies.clear()
        await client.get("/api/auth/callback", params={"code": "c", "state": state})
        assert (await db_session.execute(select(OidcTentative))).scalars().all() == []

    @pytest.mark.asyncio
    async def test_cookie_navigateur_efface_au_callback(self, client, idp):
        r = await _connecter(client, idp)
        assert any("matotheque_oidc=" in v and "max-age=0" in v.lower()
                   for v in r.headers.get_list("set-cookie"))
        idp.jeton_force = idp.jeton(corrompre=True)
        state = await _login(client, idp)
        r = await client.get("/api/auth/callback", params={"code": "c", "state": state})
        assert _erreur(r) == "jeton_invalide"
        assert any("matotheque_oidc=" in v and "max-age=0" in v.lower()
                   for v in r.headers.get_list("set-cookie"))

    @pytest.mark.asyncio
    async def test_empreinte_seule_en_base(self, client, idp, db_session):
        r = await client.get("/api/auth/login")
        secret = r.headers["set-cookie"].split("matotheque_oidc=")[1].split(";")[0]
        t = (await db_session.execute(select(OidcTentative))).scalars().one()
        assert t.navigateur == hashlib.sha256(secret.encode()).hexdigest() != secret


# ─── Chemins réseau réels (httpx.MockTransport) ───────────────────────────────

@pytest.fixture
def reseau(monkeypatch):
    """Injecte un faux transport HTTP dans le service ; `appels` journalise les requêtes."""
    oidc_service._cache.clear()
    etat = type("Reseau", (), {})()
    etat.appels = []
    etat.routes = {}

    def handler(request: httpx.Request) -> httpx.Response:
        etat.appels.append(request)
        h = etat.routes.get(str(request.url).split("?")[0])
        if h is None:
            return httpx.Response(404)
        return h(request) if callable(h) else h

    monkeypatch.setattr(oidc_service, "_TRANSPORT", httpx.MockTransport(handler), raising=False)
    runtime_config._overrides.update({"oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID,
                                      "oidc_redirect_uri": REDIRECT})
    yield etat
    oidc_service._cache.clear()


def _doc(**extra) -> dict:
    d = {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize",
         "token_endpoint": f"{ISSUER}/token", "jwks_uri": f"{ISSUER}/jwks"}
    d.update(extra)
    return d


class TestReseau:
    @pytest.mark.asyncio
    async def test_secret_en_basic_si_seul_basic_annonce(self, reseau):
        from services.crypto import encrypt
        runtime_config._overrides["oidc_client_secret"] = encrypt("secret-fictif")
        runtime_config._overrides["oidc_secret_emetteur"] = ISSUER
        reseau.routes[f"{ISSUER}/token"] = httpx.Response(200, json={"id_token": "x.y.z"})
        await _VRAI_EXCHANGE(_doc(token_endpoint_auth_methods_supported=["client_secret_basic"]), "code", "ver")
        req = reseau.appels[-1]
        assert req.headers["authorization"] == "Basic " + base64.b64encode(
            f"{CLIENT_ID}:secret-fictif".encode()).decode()
        corps = parse_qs(req.content.decode())
        assert "client_secret" not in corps and corps["code_verifier"] == ["ver"]
        assert corps["grant_type"] == ["authorization_code"] and corps["redirect_uri"] == [REDIRECT]

    @pytest.mark.asyncio
    async def test_secret_dans_le_corps_si_post_annonce(self, reseau):
        from services.crypto import encrypt
        runtime_config._overrides["oidc_client_secret"] = encrypt("secret-fictif")
        runtime_config._overrides["oidc_secret_emetteur"] = ISSUER
        reseau.routes[f"{ISSUER}/token"] = httpx.Response(200, json={"id_token": "x.y.z"})
        await _VRAI_EXCHANGE(_doc(token_endpoint_auth_methods_supported=["client_secret_post", "client_secret_basic"]),
                             "code", "ver")
        req = reseau.appels[-1]
        corps = parse_qs(req.content.decode())
        assert corps["client_secret"] == ["secret-fictif"] and corps["client_id"] == [CLIENT_ID]
        assert "authorization" not in req.headers

    @pytest.mark.asyncio
    async def test_token_endpoint_non_200(self, reseau):
        reseau.routes[f"{ISSUER}/token"] = httpx.Response(400, json={"error": "invalid_grant"})
        with pytest.raises(oidc_service.OidcError) as e:
            await _VRAI_EXCHANGE(_doc(), "code", "ver")
        assert e.value.code == "echange_refuse"

    @pytest.mark.asyncio
    async def test_reponse_sans_id_token(self, reseau):
        reseau.routes[f"{ISSUER}/token"] = httpx.Response(200, json={"access_token": "a"})
        with pytest.raises(oidc_service.OidcError) as e:
            await _VRAI_EXCHANGE(_doc(), "code", "ver")
        assert e.value.code == "echange_refuse"

    @pytest.mark.asyncio
    async def test_token_endpoint_http_refuse_sans_envoi(self, reseau):
        with pytest.raises(oidc_service.OidcError):
            await _VRAI_EXCHANGE(_doc(token_endpoint="http://sso.test.invalid/token"), "code", "ver")
        assert reseau.appels == []      # le secret client ne part jamais en clair

    @pytest.mark.asyncio
    async def test_cache_de_decouverte(self, reseau):
        reseau.routes[f"{ISSUER}/.well-known/openid-configuration"] = httpx.Response(200, json=_doc())
        a = await _VRAI_DISCOVER()
        b = await _VRAI_DISCOVER()
        assert a == b and len(reseau.appels) == 1

    @pytest.mark.asyncio
    async def test_decouverte_issuer_different_refusee(self, reseau):
        reseau.routes[f"{ISSUER}/.well-known/openid-configuration"] = httpx.Response(
            200, json=_doc(issuer="https://autre.invalid"))
        with pytest.raises(oidc_service.OidcError):
            await _VRAI_DISCOVER()

    @pytest.mark.asyncio
    async def test_decouverte_issuer_slash_final_tolere(self, reseau):
        reseau.routes[f"{ISSUER}/.well-known/openid-configuration"] = httpx.Response(
            200, json=_doc(issuer=ISSUER + "/"))
        assert (await _VRAI_DISCOVER())["token_endpoint"]

    @pytest.mark.asyncio
    async def test_decouverte_token_endpoint_http_refusee(self, reseau):
        reseau.routes[f"{ISSUER}/.well-known/openid-configuration"] = httpx.Response(
            200, json=_doc(token_endpoint="http://sso.test.invalid/token"))
        with pytest.raises(oidc_service.OidcError):
            await _VRAI_DISCOVER()

    @pytest.mark.asyncio
    async def test_decouverte_jwks_http_refusee(self, reseau):
        reseau.routes[f"{ISSUER}/.well-known/openid-configuration"] = httpx.Response(
            200, json=_doc(jwks_uri="http://sso.test.invalid/jwks"))
        with pytest.raises(oidc_service.OidcError):
            await _VRAI_DISCOVER()

    @pytest.mark.asyncio
    async def test_decouverte_injoignable(self, reseau):
        with pytest.raises(oidc_service.OidcError) as e:     # 404 par défaut
            await _VRAI_DISCOVER()
        assert e.value.code == "sso_indisponible"

    @pytest.mark.asyncio
    async def test_rotation_de_cle_relit_les_jwks(self, client, idp, reseau, monkeypatch):
        """kid inconnu du cache : les JWKS sont relus (forcer=True) et la nouvelle clé est acceptée."""
        monkeypatch.setattr(oidc_service, "get_jwks", _VRAI_GET_JWKS)
        ancien = {"keys": [k for k in idp.jwks["keys"] if k["kid"] == "ec1"]}   # sans rsa1
        n = {"appels": 0}

        def jwks(_req):
            n["appels"] += 1
            return httpx.Response(200, json=ancien if n["appels"] == 1 else idp.jwks)

        reseau.routes[f"{ISSUER}/jwks"] = jwks
        r = await _connecter(client, idp)
        assert _erreur_ou_none(r) is None and n["appels"] == 2
        assert (await client.get("/api/auth/me")).json()["utilisateur"]["identifiant"] == "alice"

    @pytest.mark.asyncio
    async def test_kid_toujours_inconnu_apres_relecture(self, client, idp, reseau, monkeypatch):
        monkeypatch.setattr(oidc_service, "get_jwks", _VRAI_GET_JWKS)
        reseau.routes[f"{ISSUER}/jwks"] = httpx.Response(200, json={"keys": []})
        assert _erreur(await _connecter(client, idp)) == "jeton_invalide"


# ─── Cas limites du jeton et du retour ────────────────────────────────────────

class TestLimites:
    @pytest.mark.asyncio
    async def test_sub_absent(self, client, idp):
        idp.supprimer = {"sub"}
        assert _erreur(await _connecter(client, idp)) == "jeton_invalide"

    @pytest.mark.asyncio
    async def test_nonce_non_ascii_refus_propre(self, client, idp):
        state = await _login(client, idp)
        idp.jeton_force = idp.jeton(idp.claims(nonce="nonce-é-€"))
        r = await client.get("/api/auth/callback", params={"code": "c", "state": state})
        assert _erreur(r) == "jeton_invalide"

    def test_nonce_attendu_non_ascii(self, idp):
        c = idp.claims(nonce="é")
        with pytest.raises(oidc_service.OidcError):
            oidc_service.validate_id_token(idp.jeton(c), idp.jwks, issuer=ISSUER,
                                           client_id=CLIENT_ID, nonce="e")

    @pytest.mark.parametrize("retour", ["/a\x01b", "/a\nb", "/a\rb", "/a\x7f", "/a\x00"])
    def test_retour_caractere_de_controle(self, retour):
        assert oidc_service.retour_sur(retour) == "/"


# ─── Secret client lié à l'émetteur (anti-exfiltration) ───────────────────────

PIRATE = "https://pirate.test.invalid"


class TestSecretLie:
    @pytest.mark.asyncio
    async def test_changer_emetteur_sans_secret_efface_le_secret(self, client, reseau):
        await client.put("/api/system/config", json={
            "oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID, "oidc_client_secret": "secret-fictif"})
        assert runtime_config._overrides.get("oidc_client_secret")
        r = await client.put("/api/system/config", json={"oidc_issuer": PIRATE})
        assert r.status_code == 200
        assert "oidc_client_secret" not in runtime_config._overrides
        assert r.json()["config"]["oidc_client_secret"]["defini"] is False
        # Aucun envoi du secret vers l'émetteur du pirate.
        reseau.routes[f"{PIRATE}/token"] = httpx.Response(200, json={"id_token": "x.y.z"})
        await _VRAI_EXCHANGE(_doc(issuer=PIRATE, token_endpoint=f"{PIRATE}/token"), "code", "ver")
        assert "secret-fictif" not in reseau.appels[-1].content.decode()
        assert "authorization" not in reseau.appels[-1].headers

    @pytest.mark.asyncio
    async def test_changer_client_id_ou_redirect_efface_aussi(self, client):
        for champ, valeur in (("oidc_client_id", "autre-client"),
                              ("oidc_redirect_uri", "https://autre.test.invalid/cb")):
            await client.put("/api/system/config", json={
                "oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID, "oidc_client_secret": "secret-fictif"})
            await client.put("/api/system/config", json={champ: valeur})
            assert "oidc_client_secret" not in runtime_config._overrides, champ

    @pytest.mark.asyncio
    async def test_meme_emetteur_conserve_le_secret(self, client):
        await client.put("/api/system/config", json={
            "oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID, "oidc_client_secret": "secret-fictif"})
        await client.put("/api/system/config", json={"oidc_issuer": ISSUER + "/", "oidc_client_secret": "",
                                                     "oidc_groupe_admin": "autre-groupe"})
        assert oidc_service.client_secret() == "secret-fictif"

    @pytest.mark.asyncio
    async def test_nouvel_emetteur_avec_nouveau_secret_conserve(self, client):
        await client.put("/api/system/config", json={
            "oidc_issuer": ISSUER, "oidc_client_id": CLIENT_ID, "oidc_client_secret": "ancien"})
        await client.put("/api/system/config", json={"oidc_issuer": PIRATE, "oidc_client_secret": "nouveau"})
        assert oidc_service.client_secret() == "nouveau"
        assert runtime_config.effective("oidc_secret_emetteur") == PIRATE

    @pytest.mark.asyncio
    async def test_exchange_refuse_si_secret_lie_a_un_autre_emetteur(self, reseau):
        from services.crypto import encrypt
        runtime_config._overrides["oidc_client_secret"] = encrypt("secret-fictif")
        runtime_config._overrides["oidc_secret_emetteur"] = "https://autre.test.invalid"
        with pytest.raises(oidc_service.OidcError):
            await _VRAI_EXCHANGE(_doc(), "code", "ver")
        assert reseau.appels == []

    @pytest.mark.asyncio
    async def test_exchange_refuse_si_secret_sans_lien(self, reseau):
        from services.crypto import encrypt
        runtime_config._overrides["oidc_client_secret"] = encrypt("secret-fictif")
        with pytest.raises(oidc_service.OidcError):
            await _VRAI_EXCHANGE(_doc(), "code", "ver")
        assert reseau.appels == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("champ", ["oidc_issuer", "oidc_redirect_uri"])
    async def test_http_refuse_a_l_ecriture(self, client, champ):
        r = await client.put("/api/system/config", json={champ: "http://sso.test.invalid/x"})
        assert r.status_code == 422 and "https" in r.text
        assert champ not in runtime_config._overrides

    @pytest.mark.asyncio
    async def test_lien_interne_non_expose(self, client):
        await client.put("/api/system/config", json={"oidc_issuer": ISSUER, "oidc_client_secret": "s"})
        r = await client.get("/api/system/config")
        assert "oidc_secret_emetteur" not in r.json()["config"]
        r = await client.put("/api/system/config", json={"oidc_secret_emetteur": PIRATE})
        assert runtime_config.effective("oidc_secret_emetteur") != PIRATE

    @pytest.mark.asyncio
    async def test_discover_refuse_emetteur_http(self, reseau):
        runtime_config._overrides["oidc_issuer"] = "http://interne.test.invalid"
        with pytest.raises(oidc_service.OidcError):
            await _VRAI_DISCOVER()
        assert reseau.appels == []


# ─── Durcissements divers ─────────────────────────────────────────────────────

class TestDurcissement:
    @pytest.mark.asyncio
    async def test_utilisateur_distinct_par_emetteur(self, client, idp, db_session):
        await _connecter(client, idp)
        runtime_config._overrides["oidc_issuer"] = "https://sso2.test.invalid"
        idp.claims_extra = {"iss": "https://sso2.test.invalid"}
        assert _erreur_ou_none(await _connecter(client, idp)) is None
        users = (await db_session.execute(select(Utilisateur))).scalars().all()
        assert len(users) == 2 and {u.emetteur for u in users} == {ISSUER, "https://sso2.test.invalid"}
        assert {u.sub for u in users} == {"sub-alice-001"}

    @pytest.mark.asyncio
    async def test_plafond_de_tentatives_login(self, client, idp, db_session):
        for i in range(200):
            db_session.add(OidcTentative(state=f"s{i}", nonce="n", code_verifier="v", retour="/",
                                         navigateur="x"))
        await db_session.commit()
        r = await client.get("/api/auth/login")
        assert r.status_code == 429 and "tentatives" in r.json()["detail"]

    @pytest.mark.asyncio
    async def test_echec_de_decouverte_mis_en_cache(self, reseau):
        for _ in range(2):
            with pytest.raises(oidc_service.OidcError):
                await _VRAI_DISCOVER()
        assert len(reseau.appels) == 1

    @pytest.mark.asyncio
    async def test_id_token_non_chaine(self, reseau):
        reseau.routes[f"{ISSUER}/token"] = httpx.Response(200, json={"id_token": 123})
        with pytest.raises(oidc_service.OidcError) as e:
            await _VRAI_EXCHANGE(_doc(), "code", "ver")
        assert e.value.code == "echange_refuse"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corps", [{"keys": "x"}, {"keys": {"a": 1}}, {"keys": [1, "a"]}, {}])
    async def test_jwks_mal_formes_pas_de_500(self, client, idp, monkeypatch, corps):
        async def jwks(uri, *, forcer=False):
            return corps
        monkeypatch.setattr(oidc_service, "get_jwks", jwks)
        assert _erreur(await _connecter(client, idp)) == "jeton_invalide"

    @pytest.mark.asyncio
    async def test_jwks_reseau_non_liste(self, reseau):
        reseau.routes[f"{ISSUER}/jwks"] = httpx.Response(200, json={"keys": "x"})
        with pytest.raises(oidc_service.OidcError):
            await _VRAI_GET_JWKS(f"{ISSUER}/jwks")

    @pytest.mark.asyncio
    async def test_json_inattendu_decouverte(self, reseau):
        reseau.routes[f"{ISSUER}/.well-known/openid-configuration"] = httpx.Response(200, json=[1, 2])
        with pytest.raises(oidc_service.OidcError):
            await _VRAI_DISCOVER()

    @pytest.mark.asyncio
    async def test_revendications_de_mauvais_type_pas_de_500(self, client, idp, db_session):
        idp.claims_extra = {"preferred_username": 123, "name": {"a": 1}, "email": ["x"],
                            "groups": ["matotheque-utilisateurs", 5, None, {"x": 1}]}
        assert _erreur_ou_none(await _connecter(client, idp)) is None
        u = (await db_session.execute(select(Utilisateur))).scalars().one()
        assert u.identifiant is None and u.nom is None and u.email is None
        assert u.groupes == ["matotheque-utilisateurs"]

    @pytest.mark.asyncio
    async def test_champs_bornes(self, client, idp, db_session):
        idp.claims_extra = {"preferred_username": "a" * 1000, "name": "n" * 1000, "email": "e" * 1000,
                            "groups": ["matotheque-utilisateurs"] + [f"g{i}" for i in range(500)]
                            + ["z" * 1000]}
        assert _erreur_ou_none(await _connecter(client, idp)) is None
        u = (await db_session.execute(select(Utilisateur))).scalars().one()
        assert len(u.identifiant) == len(u.nom) == len(u.email) == 255
        assert len(u.groupes) <= 100 and all(len(g) <= 255 for g in u.groupes)

    @pytest.mark.asyncio
    async def test_role_calcule_sur_tous_les_groupes(self, client, idp, db_session):
        idp.claims_extra = {"groups": [f"g{i}" for i in range(300)] + ["matotheque-admin"]}
        assert _erreur_ou_none(await _connecter(client, idp)) is None
        assert (await client.get("/api/auth/me")).json()["utilisateur"]["role"] == "admin"

    @pytest.mark.asyncio
    async def test_sub_trop_long_refuse(self, client, idp):
        idp.claims_extra = {"sub": "s" * 300}
        assert _erreur(await _connecter(client, idp)) == "jeton_invalide"

    @pytest.mark.asyncio
    async def test_no_store(self, client, idp):
        r = await client.get("/api/auth/login")
        assert r.headers["cache-control"] == "no-store"
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        idp.nonce = parse_qs(urlparse(r.headers["location"]).query)["nonce"][0]
        r = await client.get("/api/auth/callback", params={"code": "c", "state": state})
        assert r.headers["cache-control"] == "no-store"
        r = await client.get("/api/auth/callback", params={"code": "c", "state": "inconnu"})
        assert r.headers["cache-control"] == "no-store"
        assert (await client.get("/api/auth/me")).headers["cache-control"] == "no-store"

    @pytest.mark.asyncio
    async def test_no_store_login_non_configure(self, client):
        r = await client.get("/api/auth/login")
        assert r.status_code == 503 and r.headers["cache-control"] == "no-store"

    def test_issuer_normalise_des_deux_cotes(self, idp):
        c = idp.claims(nonce="n", iss=ISSUER + "/")
        assert oidc_service.validate_id_token(idp.jeton(c), idp.jwks, issuer=ISSUER,
                                              client_id=CLIENT_ID, nonce="n")["sub"]
        c = idp.claims(nonce="n")
        assert oidc_service.validate_id_token(idp.jeton(c), idp.jwks, issuer=ISSUER + "/",
                                              client_id=CLIENT_ID, nonce="n")["sub"]


# ─── Compatibilité SSO Server Synology (découverte relevée le 31/10/2026) ─────────────────────
# Synology annonce scopes_supported = openid, email, groups (pas « profile ») et fournit
# « username » au lieu de « preferred_username » / « name ».


class TestSynology:
    @pytest.mark.asyncio
    async def test_portees_limitees_a_celles_annoncees(self, client, idp, monkeypatch):
        async def discover():
            return {"issuer": ISSUER, "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token", "jwks_uri": f"{ISSUER}/jwks",
                    "scopes_supported": ["email", "groups", "openid"]}
        monkeypatch.setattr(oidc_service, "discover", discover)
        r = await client.get("/api/auth/login")
        assert r.status_code == 302
        assert parse_qs(urlparse(r.headers["location"]).query)["scope"] == ["openid email groups"]

    @pytest.mark.asyncio
    async def test_identifiant_depuis_username(self, client, idp):
        idp.supprimer = {"preferred_username", "name"}
        idp.claims_extra = {"username": "MLB", "groups": ["matotheque-utilisateurs"]}
        r = await _connecter(client, idp)
        assert _erreur(r) is None
        me = (await client.get("/api/auth/me")).json()["utilisateur"]
        assert me["identifiant"] == "MLB" and me["nom"] == "MLB" and me["role"] == "utilisateur"
