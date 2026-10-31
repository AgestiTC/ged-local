"""
Tests — correctifs de la revue de sécurité de l'étape 2 (plan d'authentification)
==================================================================================
A1  écriture des réglages d'authentification refusée à qui n'est pas admin (suspension comprise) ;
A2  `state` du callback OAuth des connecteurs lié au navigateur (cookie) et signé ;
B2  aperçu inline : nosniff, et types actifs forcés en pièce jointe sandboxée.
Données fictives, aucun réseau.
"""

import base64
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from models.auth import SessionAuth, Utilisateur
from models.config import Config
from models.source import Source
from services import acces, oidc_service, runtime_config

ISSUER = "https://sso.test.invalid/webman/sso"
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


async def session(db, role, sub):
    now = datetime.now(timezone.utc)
    u = Utilisateur(emetteur=ISSUER, sub=sub, role=role, identifiant=role, groupes=[])
    db.add(u)
    await db.flush()
    jeton = f"jeton-{sub}"
    db.add(SessionAuth(id=oidc_service.hacher_jeton(jeton), utilisateur_id=u.id, creee=now,
                       derniere_activite=now, expire_max=now + timedelta(days=1)))
    await db.commit()
    return {"Cookie": f"matotheque_session={jeton}"}


@pytest.fixture
def auth_complete():
    """Authentification active, SSO complet (le secret est lié à l'émetteur)."""
    from services.crypto import encrypt
    runtime_config._overrides.update({
        "auth_active": "true", "oidc_issuer": ISSUER, "oidc_client_id": "cid",
        "oidc_redirect_uri": "https://ged.test.invalid/api/auth/callback",
        "oidc_client_secret": encrypt("secret-fictif"), "oidc_secret_emetteur": ISSUER})


# ─── A1 ───────────────────────────────────────────────────────────────────────

class TestA1ReglagesAuthPendantSuspension:
    @pytest_asyncio.fixture
    async def suspension(self, db_session, auth_complete):
        db_session.add(Config(cle=acces.CLE_SUSPENSION,
                              valeur=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()))
        await db_session.commit()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corps", [
        {"oidc_issuer": "https://pirate.test.invalid/sso"},
        {"oidc_groupe_admin": "tout-le-monde"},
        {"oidc_client_secret": "secret-du-pirate"},
        {"oidc_client_id": "autre"},
        {"auth_session_max_jours": "9999"},
        {"oidc_groupe_utilisateurs": ""},          # « vider » est aussi une écriture
    ])
    async def test_anonyme_pendant_suspension_refuse_et_rien_ecrit(self, client, db_session, suspension, corps):
        avant = dict(runtime_config._overrides)
        r = await client.put("/api/system/config", json=corps, headers=SYNC)
        assert r.status_code == 403, corps
        assert runtime_config._overrides == avant
        cle = next(iter(corps))
        assert (await db_session.get(Config, cle)) is None

    @pytest.mark.asyncio
    async def test_autre_reglage_reste_possible_pendant_suspension(self, client, suspension):
        r = await client.put("/api/system/config", json={"default_model": "autre"}, headers=SYNC)
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_utilisateur_simple_refuse(self, client, db_session, auth_complete):
        h = await session(db_session, "utilisateur", "u1")
        r = await client.put("/api/system/config", json={"oidc_groupe_admin": "x"}, headers={**h, **SYNC})
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_accepte(self, client, db_session, auth_complete):
        h = await session(db_session, "admin", "a1")
        r = await client.put("/api/system/config", json={"oidc_groupe_admin": "mes-admins"}, headers={**h, **SYNC})
        assert r.status_code == 200
        assert runtime_config.effective("oidc_groupe_admin") == "mes-admins"

    @pytest.mark.asyncio
    async def test_auth_eteinte_non_concernee(self, client):
        r = await client.put("/api/system/config", json={"oidc_groupe_admin": "mes-admins"})
        assert r.status_code == 200


# ─── A2 ───────────────────────────────────────────────────────────────────────

class TestA2StateOauthLie:
    @pytest.fixture
    def google(self, monkeypatch):
        from services.connectors import gdrive
        appels = []

        async def exchange_code(code, redirect):
            appels.append(code)
            return {"refresh_token": "rt-fictif", "email": "alice@test.invalid"}

        monkeypatch.setattr(gdrive, "exchange_code", exchange_code)
        monkeypatch.setattr(gdrive, "auth_url", lambda redirect, state: f"https://google.test.invalid/auth?state={state}")
        return appels

    async def _start(self, client, libelle="Mon Drive", **kw):
        r = await client.get("/api/connectors/oauth/start", params={"libelle": libelle}, **kw)
        assert r.status_code == 200
        state = parse_qs(urlparse(r.json()["url"]).query)["state"][0]
        return r, state

    async def _nb_sources(self, db):
        return len((await db.execute(select(Source))).scalars().all())

    @pytest.mark.asyncio
    async def test_start_pose_un_cookie_de_liaison(self, client, google):
        r, state = await self._start(client)
        c = r.headers["set-cookie"].lower()
        assert "matotheque_oauth=" in c and "httponly" in c and "samesite=lax" in c
        assert "path=/api/connectors/oauth" in c and "max-age=600" in c
        assert "secure" not in c
        assert "." in state                      # charge utile signée + signature

    @pytest.mark.asyncio
    async def test_start_cookie_secure_derriere_proxy_tls(self, client, google):
        r, _ = await self._start(client, headers={"X-Forwarded-Proto": "https"})
        assert "secure" in r.headers["set-cookie"].lower()

    @pytest.mark.asyncio
    async def test_parcours_nominal_cree_la_source_et_efface_le_cookie(self, client, db_session, google):
        _, state = await self._start(client, "Perso")
        r = await client.get("/api/connectors/oauth/callback", params={"code": "c", "state": state})
        assert r.status_code in (302, 307) and "statut=ok" in r.headers["location"]
        src = (await db_session.execute(select(Source))).scalars().one()
        assert src.libelle == "Perso (alice@test.invalid)" and src.type == "gdrive"
        assert "matotheque_oauth=" in r.headers["set-cookie"] and "max-age=0" in r.headers["set-cookie"].lower()

    async def _refus(self, client, db_session, google, state, **kw):
        r = await client.get("/api/connectors/oauth/callback", params={"code": "c", "state": state}, **kw)
        assert "statut=erreur" in r.headers["location"]
        assert await self._nb_sources(db_session) == 0
        assert google == []                       # le code n'est même pas échangé

    @pytest.mark.asyncio
    async def test_sans_cookie(self, client, db_session, google):
        _, state = await self._start(client)
        client.cookies.clear()
        await self._refus(client, db_session, google, state)

    @pytest.mark.asyncio
    async def test_cookie_different(self, client, db_session, google):
        _, state = await self._start(client)
        client.cookies.clear()
        client.cookies.set("matotheque_oauth", "cookie-d-un-autre", path="/api/connectors/oauth")
        await self._refus(client, db_session, google, state)

    @pytest.mark.asyncio
    async def test_state_altere(self, client, db_session, google):
        _, state = await self._start(client)
        charge, sig = state.split(".")
        d = json.loads(base64.urlsafe_b64decode(charge + "=" * (-len(charge) % 4)))
        d["l"] = "Drive du pirate"
        faux = base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
        await self._refus(client, db_session, google, f"{faux}.{sig}")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", ["", "n-importe-quoi", "a.b", "....", "e30.AAAA"])
    async def test_state_invalide(self, client, db_session, google, state):
        await self._start(client)
        await self._refus(client, db_session, google, state)

    @pytest.mark.asyncio
    async def test_ancien_format_sans_signature_refuse(self, client, db_session, google):
        await self._start(client)
        ancien = base64.urlsafe_b64encode(json.dumps({"libelle": "Pirate"}).encode()).decode()
        await self._refus(client, db_session, google, ancien)

    @pytest.mark.asyncio
    async def test_state_expire(self, client, db_session, google, monkeypatch):
        _, state = await self._start(client)
        vrai = time.time
        monkeypatch.setattr(time, "time", lambda: vrai() + 11 * 60)
        await self._refus(client, db_session, google, state)

    @pytest.mark.asyncio
    async def test_state_signe_par_une_autre_cle_refuse(self, client, db_session, google, monkeypatch):
        from services import crypto
        _, state = await self._start(client)
        monkeypatch.setattr(crypto, "cle_derivee", lambda contexte: b"une-autre-cle-" + contexte.encode())
        await self._refus(client, db_session, google, state)

    @pytest.mark.asyncio
    async def test_refus_google_efface_quand_meme_le_cookie(self, client, db_session, google):
        await self._start(client)
        r = await client.get("/api/connectors/oauth/callback", params={"error": "access_denied"})
        assert "statut=refus" in r.headers["location"]
        assert "matotheque_oauth=" in r.headers["set-cookie"]


# ─── B2 ───────────────────────────────────────────────────────────────────────

class TestB2ApercuInline:
    CSP = "sandbox; default-src 'none'"

    async def _apercu(self, client, db_session, tmp_path, nom, contenu=b"x", **q):
        from models.document import Document
        f = tmp_path / nom
        f.write_bytes(contenu)
        doc = Document(nom=nom, chemin=str(f), extension=nom.rsplit(".", 1)[-1], hash_sha256="a" * 64,
                       taille_octets=len(contenu), statut="enriched", source="upload")
        db_session.add(doc)
        await db_session.commit()
        return await client.get(f"/api/documents/{doc.id}/file", params=q)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nom", ["a.svg", "a.html", "a.htm", "a.xhtml", "a.xml", "a.js"])
    async def test_types_actifs_en_piece_jointe_sandboxee(self, client, db_session, tmp_path, nom):
        r = await self._apercu(client, db_session, tmp_path, nom, b"<svg onload='alert(1)'/>")
        assert r.status_code == 200
        assert r.headers["content-disposition"].lower().startswith("attachment")
        assert r.headers["content-security-policy"] == self.CSP
        assert r.headers["x-content-type-options"] == "nosniff"

    @pytest.mark.asyncio
    async def test_type_mime_actif_declare_par_tika_aussi(self, client, db_session, tmp_path):
        from models.document import Document
        f = tmp_path / "rapport.dat"
        f.write_bytes(b"<html></html>")
        doc = Document(nom="rapport.dat", chemin=str(f), extension="dat", type_mime="text/html; charset=UTF-8",
                       hash_sha256="b" * 64, taille_octets=13, statut="enriched", source="upload")
        db_session.add(doc)
        await db_session.commit()
        r = await client.get(f"/api/documents/{doc.id}/file")
        assert r.headers["content-disposition"].lower().startswith("attachment")
        assert r.headers["content-security-policy"] == self.CSP

    @pytest.mark.asyncio
    async def test_pdf_reste_inline(self, client, db_session, tmp_path):
        r = await self._apercu(client, db_session, tmp_path, "a.pdf", b"%PDF-1.4")
        assert r.headers["content-disposition"].lower().startswith("inline")
        assert r.headers["x-content-type-options"] == "nosniff"
        assert "content-security-policy" not in r.headers

    @pytest.mark.asyncio
    async def test_telechargement_explicite_inchange(self, client, db_session, tmp_path):
        r = await self._apercu(client, db_session, tmp_path, "a.pdf", b"%PDF", download="true")
        assert r.headers["content-disposition"].lower().startswith("attachment")
        assert r.headers["x-content-type-options"] == "nosniff"

    def test_nginx_nosniff_global(self):
        from pathlib import Path
        chemin = Path(__file__).resolve().parents[2] / "frontend" / "nginx.conf"
        if not chemin.exists():
            pytest.skip("frontend/ absent du conteneur de test")
        conf = chemin.read_text(encoding="utf-8")
        assert "add_header X-Content-Type-Options nosniff always;" in conf
