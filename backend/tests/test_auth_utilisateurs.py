"""
Tests — gestion des personnes (plan d'authentification, étape 3 : Paramètres › Utilisateurs)
=============================================================================================
Données 100 % fictives, aucun appel réseau. Sessions créées directement en base.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from models.auth import SessionAuth, Utilisateur
from services import acces, audit, oidc_service, runtime_config

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


async def personne(db, role="utilisateur", *, ident=None, bloque=False, sessions=1, expiree=False):
    """Fiche fictive + ses sessions ; rend (fiche, cookie de la première session)."""
    ident = ident or f"{role}-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    u = Utilisateur(emetteur=oidc_service.emetteur_configure(), sub=f"sub-{ident}", role=role, bloque=bloque,
                    identifiant=ident, nom=f"{ident} Fictif", email=f"{ident}@test.invalid", groupes=["g-test"])
    db.add(u)
    await db.flush()
    premier = ""
    for i in range(sessions):
        jeton = f"jeton-{ident}-{i}"
        premier = premier or jeton
        db.add(SessionAuth(id=oidc_service.hacher_jeton(jeton), utilisateur_id=u.id, creee=now,
                           derniere_activite=now,
                           expire_max=now - timedelta(hours=1) if expiree else now + timedelta(days=1)))
    await db.commit()
    return u, premier


def ck(jeton: str) -> dict:
    return {"Cookie": f"matotheque_session={jeton}", **SYNC}


async def nb_sessions(db, uid) -> int:
    return len((await db.execute(select(SessionAuth).where(SessionAuth.utilisateur_id == uid))).scalars().all())


class TestClassement:
    def test_routes_classees_admin_explicitement(self):
        regles = [(m, p, r) for m, p, r in acces.REGLES if p.startswith("/api/auth/utilisateurs")]
        assert regles and all(r == acces.ADMIN for _, _, r in regles)
        for m, p in [("GET", "/api/auth/utilisateurs"), ("POST", "/api/auth/utilisateurs/{utilisateur_id}/deconnecter"),
                     ("POST", "/api/auth/utilisateurs/{utilisateur_id}/bloquer")]:
            assert acces.classer(m, p) == acces.ADMIN

    def test_hors_liste_blanche(self):
        assert not any(c.startswith("/api/auth/utilisateurs") for c in acces.LISTE_BLANCHE)

    @pytest.mark.asyncio
    async def test_anonyme_401_utilisateur_403(self, client, auth_on, db_session):
        assert (await client.get("/api/auth/utilisateurs")).status_code == 401
        u, jeton = await personne(db_session, "utilisateur")
        for methode, url, corps in [("GET", "/api/auth/utilisateurs", None),
                                    ("POST", f"/api/auth/utilisateurs/{u.id}/deconnecter", None),
                                    ("POST", f"/api/auth/utilisateurs/{u.id}/bloquer", {"bloque": True})]:
            r = await client.request(methode, url, json=corps, headers=ck(jeton))
            assert r.status_code == 403, url
        await db_session.refresh(u)
        assert u.bloque is False

    @pytest.mark.asyncio
    async def test_auth_eteinte_aucune_identite_aucune_action(self, client, db_session):
        """Sans session identifiée (auth éteinte), la liste et les écritures sont refusées."""
        u, _ = await personne(db_session, "utilisateur")
        assert (await client.get("/api/auth/utilisateurs")).status_code == 401
        assert (await client.post(f"/api/auth/utilisateurs/{u.id}/bloquer", json={"bloque": True})).status_code == 401
        assert (await client.post(f"/api/auth/utilisateurs/{u.id}/deconnecter")).status_code == 401
        await db_session.refresh(u)
        assert u.bloque is False and await nb_sessions(db_session, u.id) == 1


class TestListe:
    @pytest.mark.asyncio
    async def test_liste_complete(self, client, auth_on, db_session):
        adm, jeton = await personne(db_session, "admin", ident="adm-test")
        await personne(db_session, "utilisateur", ident="ml-test", sessions=3)
        await personne(db_session, "utilisateur", ident="expire-test", sessions=2, expiree=True)
        r = await client.get("/api/auth/utilisateurs", headers=ck(jeton))
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-store"
        par_id = {p["identifiant"]: p for p in r.json()["utilisateurs"]}
        assert set(par_id) == {"adm-test", "ml-test", "expire-test"}
        ml = par_id["ml-test"]
        assert ml["sessions"] == 3 and ml["role"] == "utilisateur" and ml["bloque"] is False
        assert ml["email"] == "ml-test@test.invalid" and ml["nom"] == "ml-test Fictif"
        assert ml["groupes"] == ["g-test"] and ml["premiere_connexion"] and ml["derniere_connexion"]
        assert par_id["expire-test"]["sessions"] == 0          # sessions expirées non comptées
        assert par_id["adm-test"]["id"] == str(adm.id)

    @pytest.mark.asyncio
    async def test_aucun_secret_dans_la_reponse(self, client, auth_on, db_session):
        _, jeton = await personne(db_session, "admin")
        texte = (await client.get("/api/auth/utilisateurs", headers=ck(jeton))).text
        assert jeton not in texte and oidc_service.hacher_jeton(jeton) not in texte
        assert "sub-" not in texte and ISSUER not in texte


class TestDeconnecter:
    @pytest.mark.asyncio
    async def test_supprime_toutes_les_sessions_et_journalise(self, client, auth_on, db_session, evenements):
        _, adm = await personne(db_session, "admin", ident="tc-test")
        cible, jeton_cible = await personne(db_session, "utilisateur", ident="ml-test", sessions=3)
        autre, _ = await personne(db_session, "utilisateur", ident="autre-test")
        r = await client.post(f"/api/auth/utilisateurs/{cible.id}/deconnecter", headers=ck(adm))
        assert r.status_code == 200 and r.json()["sessions_supprimees"] == 3
        assert await nb_sessions(db_session, cible.id) == 0
        assert await nb_sessions(db_session, autre.id) == 1           # les autres ne sont pas touchés
        assert (await client.get("/api/prompts", headers=ck(jeton_cible))).status_code == 401
        assert len(evenements) == 1
        action, _, kw = evenements[0]
        assert action == "auth_deconnexion_forcee" and kw["acteur"] == "tc-test" and kw["cible"] == "ml-test"

    @pytest.mark.asyncio
    async def test_inconnu_404(self, client, auth_on, db_session):
        _, adm = await personne(db_session, "admin")
        r = await client.post(f"/api/auth/utilisateurs/{uuid.uuid4()}/deconnecter", headers=ck(adm))
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_identifiant_invalide_422(self, client, auth_on, db_session):
        _, adm = await personne(db_session, "admin")
        r = await client.post("/api/auth/utilisateurs/pas-un-uuid/deconnecter", headers=ck(adm))
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_csrf_origine_etrangere(self, client, auth_on, db_session):
        _, adm = await personne(db_session, "admin")
        cible, _ = await personne(db_session, "utilisateur")
        r = await client.post(f"/api/auth/utilisateurs/{cible.id}/deconnecter",
                              headers={"Cookie": f"matotheque_session={adm}", "Origin": "https://evil.invalid"})
        assert r.status_code == 403
        assert await nb_sessions(db_session, cible.id) == 1


class TestBloquer:
    @pytest.mark.asyncio
    async def test_bloque_coupe_les_sessions_et_journalise(self, client, auth_on, db_session, evenements):
        _, adm = await personne(db_session, "admin", ident="tc-test")
        cible, jeton_cible = await personne(db_session, "utilisateur", ident="ml-test", sessions=2)
        r = await client.post(f"/api/auth/utilisateurs/{cible.id}/bloquer", json={"bloque": True}, headers=ck(adm))
        assert r.status_code == 200 and r.json()["bloque"] is True
        await db_session.refresh(cible)
        assert cible.bloque is True and await nb_sessions(db_session, cible.id) == 0
        assert (await client.get("/api/prompts", headers=ck(jeton_cible))).status_code == 401
        action, _, kw = evenements[0]
        assert action == "auth_blocage" and kw["acteur"] == "tc-test" and kw["cible"] == "ml-test"

    @pytest.mark.asyncio
    async def test_debloquer(self, client, auth_on, db_session, evenements):
        _, adm = await personne(db_session, "admin")
        cible, _ = await personne(db_session, "utilisateur", bloque=True, sessions=0)
        r = await client.post(f"/api/auth/utilisateurs/{cible.id}/bloquer", json={"bloque": False}, headers=ck(adm))
        assert r.status_code == 200 and r.json()["bloque"] is False
        await db_session.refresh(cible)
        assert cible.bloque is False
        assert evenements[0][0] == "auth_deblocage"

    @pytest.mark.asyncio
    async def test_un_admin_ne_se_bloque_pas_lui_meme(self, client, auth_on, db_session):
        moi, adm = await personne(db_session, "admin")
        await personne(db_session, "admin", ident="second-test")      # pas le dernier : c'est bien l'auto-blocage
        r = await client.post(f"/api/auth/utilisateurs/{moi.id}/bloquer", json={"bloque": True}, headers=ck(adm))
        assert r.status_code == 409 and "vous-même" in r.json()["detail"]
        await db_session.refresh(moi)
        assert moi.bloque is False and await nb_sessions(db_session, moi.id) == 1

    @pytest.mark.asyncio
    async def test_bloquer_un_autre_admin_si_un_reste_actif(self, client, auth_on, db_session):
        _, adm = await personne(db_session, "admin", ident="a-test")
        autre, _ = await personne(db_session, "admin", ident="b-test")
        assert (await client.post(f"/api/auth/utilisateurs/{autre.id}/bloquer", json={"bloque": True},
                                  headers=ck(adm))).status_code == 200

    @pytest.mark.asyncio
    async def test_compte_des_autres_admins_actifs(self, db_session):
        from routers import auth as rauth
        cible, _ = await personne(db_session, "admin", ident="seul-test")
        assert await rauth._autres_admins_actifs(db_session, cible.id) == 0
        await personne(db_session, "admin", ident="actif-test")
        await personne(db_session, "admin", ident="bloque-test", bloque=True)   # un admin bloqué ne compte pas
        await personne(db_session, "utilisateur", ident="simple-test")          # ni un utilisateur
        assert await rauth._autres_admins_actifs(db_session, cible.id) == 1

    @pytest.mark.asyncio
    async def test_le_dernier_admin_refuse_409(self, client, auth_on, db_session, monkeypatch):
        """Garde-fou testé par route : l'acteur est forcé à « aucun autre admin actif »."""
        from routers import auth as rauth
        cible, _ = await personne(db_session, "admin", ident="seul-test")
        _, adm = await personne(db_session, "admin", ident="acteur-test")

        async def aucun(db, exclu):
            return 0
        monkeypatch.setattr(rauth, "_autres_admins_actifs", aucun)
        r = await client.post(f"/api/auth/utilisateurs/{cible.id}/bloquer", json={"bloque": True}, headers=ck(adm))
        assert r.status_code == 409 and "dernier" in r.json()["detail"]
        await db_session.refresh(cible)
        assert cible.bloque is False

    @pytest.mark.asyncio
    async def test_bloquer_un_utilisateur_simple_meme_avec_un_seul_admin(self, client, auth_on, db_session):
        _, adm = await personne(db_session, "admin")
        cible, _ = await personne(db_session, "utilisateur")
        assert (await client.post(f"/api/auth/utilisateurs/{cible.id}/bloquer", json={"bloque": True},
                                  headers=ck(adm))).status_code == 200

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corps", [None, {}, {"bloque": "peut-etre"}, {"bloque": None}, []])
    async def test_corps_invalide_422(self, client, auth_on, db_session, corps):
        _, adm = await personne(db_session, "admin")
        cible, _ = await personne(db_session, "utilisateur")
        r = await client.post(f"/api/auth/utilisateurs/{cible.id}/bloquer", json=corps, headers=ck(adm))
        assert r.status_code == 422
        await db_session.refresh(cible)
        assert cible.bloque is False

    @pytest.mark.asyncio
    async def test_inconnu_404(self, client, auth_on, db_session):
        _, adm = await personne(db_session, "admin")
        r = await client.post(f"/api/auth/utilisateurs/{uuid.uuid4()}/bloquer", json={"bloque": True}, headers=ck(adm))
        assert r.status_code == 404


class TestBlocageEtConnexion:
    @pytest.mark.asyncio
    async def test_session_d_un_bloque_ne_passe_plus_le_middleware(self, client, auth_on, db_session):
        u, jeton = await personne(db_session, "utilisateur", bloque=True)
        assert (await client.get("/api/prompts", headers=ck(jeton))).status_code == 401
        assert await nb_sessions(db_session, u.id) == 0      # et la session est supprimée


class TestMeAdresseConnexion:
    @pytest.mark.asyncio
    async def test_origine_de_la_redirect_uri(self, client, auth_on):
        assert (await client.get("/api/auth/me")).json()["adresse_connexion"] == "https://ged.test.invalid"

    @pytest.mark.asyncio
    async def test_origine_avec_port(self, client):
        runtime_config._overrides["oidc_redirect_uri"] = "https://Ged.Test.invalid:8443/api/auth/callback"
        assert (await client.get("/api/auth/me")).json()["adresse_connexion"] == "https://ged.test.invalid:8443"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("valeur", ["   ", "pas une url", "/api/auth/callback", "javascript:alert(1)",
                                         "ftp://x.invalid/cb"])
    async def test_null_si_absente_ou_invalide(self, client, valeur):
        runtime_config._overrides["oidc_redirect_uri"] = valeur
        assert (await client.get("/api/auth/me")).json()["adresse_connexion"] is None

    @pytest.mark.asyncio
    async def test_valeur_par_defaut_du_reglage(self, client):
        etat = (await client.get("/api/auth/me")).json()
        assert etat["adresse_connexion"] == "https://ged.tclement.fr" and etat["auth_active"] is False and etat["utilisateur"] is None


class TestMeIdentiteEtWiki:
    @pytest.mark.asyncio
    async def test_me_renvoie_l_id_de_la_personne(self, client, auth_on, db_session):
        u, jeton = await personne(db_session, "utilisateur", ident="ml-test")
        r = (await client.get("/api/auth/me", headers=ck(jeton))).json()
        assert r["utilisateur"]["id"] == str(u.id) and r["utilisateur"]["identifiant"] == "ml-test"

    @pytest.mark.asyncio
    async def test_wiki_url_pour_une_personne_connectee(self, client, auth_on, db_session):
        runtime_config._overrides["bookstack_url"] = "https://wiki.test.invalid/"
        _, jeton = await personne(db_session, "utilisateur")
        assert (await client.get("/api/auth/me", headers=ck(jeton))).json()["wiki_url"] == "https://wiki.test.invalid/"

    @pytest.mark.asyncio
    async def test_wiki_url_cachee_a_un_anonyme_quand_l_auth_est_active(self, client, auth_on):
        runtime_config._overrides["bookstack_url"] = "https://wiki.test.invalid/"
        assert (await client.get("/api/auth/me")).json()["wiki_url"] is None

    @pytest.mark.asyncio
    async def test_wiki_url_visible_quand_l_auth_est_eteinte(self, client):
        runtime_config._overrides["bookstack_url"] = "http://wiki.test.invalid:6875"
        assert (await client.get("/api/auth/me")).json()["wiki_url"] == "http://wiki.test.invalid:6875"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("valeur", ["   ", "javascript:alert(1)", "ftp://x.invalid", "/relatif",
                                         "https://user:mdp@wiki.test.invalid/"])
    async def test_wiki_url_invalide_ou_avec_identifiants_ignoree(self, client, valeur):
        runtime_config._overrides["bookstack_url"] = valeur
        assert (await client.get("/api/auth/me")).json()["wiki_url"] is None

    @pytest.mark.asyncio
    async def test_me_ne_renvoie_rien_d_autre_de_la_configuration(self, client, auth_on, db_session):
        secrets = {"bookstack_token_secret": "secret-wiki-fictif", "bookstack_token_id": "id-wiki-fictif",
                   "oidc_client_secret": "secret-oidc-fictif", "huggingface_token": "hf-fictif",
                   "ha_token": "ha-fictif", "bookstack_url": "https://wiki.test.invalid/"}
        runtime_config._overrides.update(secrets)
        _, jeton = await personne(db_session, "admin")
        r = await client.get("/api/auth/me", headers=ck(jeton))
        assert set(r.json()) == {"auth_active", "adresse_connexion", "wiki_url", "utilisateur"}
        assert set(r.json()["utilisateur"]) == {"id", "identifiant", "nom", "email", "role"}
        for v in ("secret-wiki-fictif", "id-wiki-fictif", "secret-oidc-fictif", "hf-fictif", "ha-fictif"):
            assert v not in r.text


class TestCourseDernierAdmin:
    def test_requete_verrouille_tous_les_admins_dans_un_ordre_stable(self):
        from sqlalchemy.dialects import postgresql
        from routers import auth as rauth
        sql = str(rauth._requete_admins().compile(dialect=postgresql.dialect()))
        assert "FOR UPDATE" in sql and "ORDER BY utilisateurs.id" in sql and "utilisateurs.role" in sql

    @pytest.mark.asyncio
    @pytest.mark.parametrize("etape", ["verrou", "commit"])
    async def test_interblocage_ou_serialisation_donne_409_reessayez(self, client, auth_on, db_session, monkeypatch, etape):
        from sqlalchemy.exc import OperationalError
        from routers import auth as rauth
        cible, _ = await personne(db_session, "admin", ident="cible-test")
        _, adm = await personne(db_session, "admin", ident="acteur-test")
        erreur = OperationalError("SELECT", {}, Exception("deadlock detected"))

        if etape == "verrou":
            async def casse(db, exclu):
                raise erreur
            monkeypatch.setattr(rauth, "_autres_admins_actifs", casse)
        else:
            reel = db_session.commit
            appels = {"n": 0}

            async def commit_qui_echoue():
                appels["n"] += 1
                if appels["n"] == 1:
                    raise erreur
                await reel()
            monkeypatch.setattr(db_session, "commit", commit_qui_echoue)
        r = await client.post(f"/api/auth/utilisateurs/{cible.id}/bloquer", json={"bloque": True}, headers=ck(adm))
        assert r.status_code == 409 and "réessayez" in r.json()["detail"].lower()
        monkeypatch.undo()
        await db_session.refresh(cible)
        assert cible.bloque is False


class TestJobsOuvertsEnLecture:
    """JobsIndicator (en-tête) suit les tâches par GET /api/jobs : cela doit rester ouvert au rôle utilisateur ;
    annuler, purger et la démo restent admin."""

    def test_lecture_utilisateur_ecriture_admin(self):
        for m, p in [("GET", "/api/jobs"), ("GET", "/api/jobs/stats"), ("GET", "/api/jobs/{job_id}")]:
            assert acces.classer(m, p) == acces.UTILISATEUR
        for m, p in [("POST", "/api/jobs/{job_id}/cancel"), ("POST", "/api/jobs/purge"), ("POST", "/api/jobs/demo")]:
            assert acces.classer(m, p) == acces.ADMIN
