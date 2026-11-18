"""
Prompts système modifiables — Paramètres › Prompts (plan prompts, étapes A4-A5)
===============================================================================
Versions successives (jamais d'écrasement), retour à l'origine, restauration, contrat vérifié à
l'enregistrement, version active servie par `prompts.texte` / `rendre` après rechargement du cache,
version hors contrat ignorée au rendu, routes (accès + contenu), « Essayer » et « Relire » avec une
IA simulée (aucun appel réseau). Données 100 % fictives.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from services import prompts

LITTERAL = "rapport.systeme"           # sans variable
GABARIT = "comparatif.ecarts"          # variables : tableau, attentes
AVEC_FORMAT = "grille.critere"         # contient {note_max:g}
SYNC = {"Sec-Fetch-Site": "same-origin"}

TEXTE_GABARIT = "Nouvelle consigne fictive.\nTableau : {tableau}\nAttentes : {attentes}\nRéponds en JSON {{\"a\": 1}}."


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


# ─── Contrat ──────────────────────────────────────────────────────────────────

class TestContrat:
    def test_toutes_les_origines_respectent_leur_contrat(self):
        for cle in prompts.cles():
            assert prompts.verifier_contrat(cle, prompts.prompt(cle).texte) == [], cle

    def test_variable_manquante(self):
        erreurs = prompts.verifier_contrat(GABARIT, "Une consigne fictive assez longue : {tableau} seulement.")
        assert any("manquante" in e and "{attentes}" in e for e in erreurs)

    def test_variable_en_trop(self):
        erreurs = prompts.verifier_contrat(GABARIT, TEXTE_GABARIT + " Et {inconnue}.")
        assert any("inconnue" in e and "{inconnue}" in e for e in erreurs)

    def test_accolade_orpheline(self):
        erreurs = prompts.verifier_contrat(GABARIT, "Tableau {tableau} attentes {attentes} et { orpheline")
        assert erreurs and "orpheline" in erreurs[0]
        erreurs = prompts.verifier_contrat(GABARIT, "Tableau {tableau} attentes {attentes} et } seule")
        assert erreurs and "orpheline" in erreurs[0]

    def test_trop_court_et_trop_long(self):
        assert "trop court" in prompts.verifier_contrat(LITTERAL, "   court   ")[0]
        assert "trop court" in prompts.verifier_contrat(LITTERAL, " " * 50)[0]
        assert "trop long" in prompts.verifier_contrat(LITTERAL, "x" * 20_001)[0]

    def test_litteral_accepte_les_accolades(self):
        assert prompts.verifier_contrat(LITTERAL, 'Réponds en JSON : {"categorie": "x"} et { seule.') == []

    def test_format_admis_seulement_s_il_existe_dans_l_origine(self):
        origine = prompts.prompt(AVEC_FORMAT).texte
        assert prompts.verifier_contrat(AVEC_FORMAT, origine.replace("{note_max:g}", "{note_max}")) == []
        erreurs = prompts.verifier_contrat(AVEC_FORMAT, origine.replace("{candidat}", "{candidat:>40}", 1))
        assert any("Format non prévu" in e for e in erreurs)

    def test_cle_inconnue(self):
        with pytest.raises(KeyError):
            prompts.verifier_contrat("cle.inconnue", "texte quelconque assez long")


# ─── Cache servi par texte() / rendre() ──────────────────────────────────────

class TestServiAChaud:
    def test_sans_version_origine_a_l_octet_pres(self):
        for cle in prompts.cles():
            assert prompts.texte(cle) == prompts.prompt(cle).texte
            assert prompts.version_servie(cle) == 0

    def test_version_active_servie(self):
        prompts.appliquer_versions_actives({LITTERAL: (3, "Consigne système fictive, version trois."),
                                            GABARIT: (1, TEXTE_GABARIT)})
        assert prompts.texte(LITTERAL) == "Consigne système fictive, version trois."
        assert prompts.rendre(LITTERAL) == "Consigne système fictive, version trois."
        assert prompts.version_servie(LITTERAL) == 3
        rendu = prompts.rendre(GABARIT, tableau="T", attentes="A")
        assert rendu == 'Nouvelle consigne fictive.\nTableau : T\nAttentes : A\nRéponds en JSON {"a": 1}.'

    def test_rendre_reste_strict_sur_les_variables(self):
        prompts.appliquer_versions_actives({GABARIT: (1, TEXTE_GABARIT)})
        with pytest.raises(KeyError):
            prompts.rendre(GABARIT, tableau="T")
        with pytest.raises(ValueError):
            prompts.rendre(GABARIT, tableau="T", attentes="A", autre="x")

    def test_retour_origine_texte_null(self):
        prompts.appliquer_versions_actives({LITTERAL: (2, None)})
        assert prompts.texte(LITTERAL) == prompts.prompt(LITTERAL).texte
        assert prompts.version_servie(LITTERAL) == 0

    def test_version_hors_contrat_ignoree_et_journalisee(self):
        # Le code a changé ses variables depuis : la version en base n'a plus {attentes}.
        with patch.object(prompts, "_journal") as journal:
            prompts.appliquer_versions_actives({GABARIT: (4, "Ancienne version fictive : {tableau} seulement.")})
        journal.return_value.warning.assert_called_once()
        assert prompts.version_ignoree(GABARIT)[0] == 4
        assert prompts.version_servie(GABARIT) == 0
        assert prompts.rendre(GABARIT, tableau="T", attentes="A") == \
            prompts.prompt(GABARIT).texte.format_map({"tableau": "T", "attentes": "A"})

    def test_version_avec_format_rendue(self):
        origine = prompts.prompt(AVEC_FORMAT).texte
        prompts.appliquer_versions_actives({AVEC_FORMAT: (1, "Version fictive. " + origine)})
        valeurs = {v: "x" for v in prompts.prompt(AVEC_FORMAT).variables}
        valeurs["note_max"] = 20.0
        assert prompts.rendre(AVEC_FORMAT, **valeurs).startswith("Version fictive. ")

    def test_echec_de_format_au_rendu_sert_l_origine(self):
        # Cas qui ne passe pas le contrôle d'enregistrement : simulé en écrivant le cache directement.
        prompts._SURCHARGES[GABARIT] = "Fictif {tableau:d} et {attentes}"
        with patch.object(prompts, "_journal") as journal:
            rendu = prompts.rendre(GABARIT, tableau="T", attentes="A")
        assert rendu == prompts.prompt(GABARIT).texte.format_map({"tableau": "T", "attentes": "A"})
        journal.return_value.warning.assert_called_once()

    def test_cle_inconnue_en_base_ignoree(self):
        prompts.appliquer_versions_actives({"cle.disparue": (1, "texte quelconque assez long")})
        assert prompts.version_servie("cle.disparue") == 0

    @pytest.mark.asyncio
    async def test_charger_depuis_la_base_plus_haute_version(self, db_session):
        from models.prompt_version import PromptVersion

        db_session.add_all([
            PromptVersion(cle=LITTERAL, version=1, texte="Première version fictive du prompt."),
            PromptVersion(cle=LITTERAL, version=2, texte="Deuxième version fictive du prompt."),
            PromptVersion(cle=GABARIT, version=1, texte=TEXTE_GABARIT),
            PromptVersion(cle=GABARIT, version=2, texte=None),
        ])
        await db_session.commit()
        await prompts.charger(db_session)
        assert prompts.texte(LITTERAL) == "Deuxième version fictive du prompt."
        assert prompts.version_servie(LITTERAL) == 2
        assert prompts.texte(GABARIT) == prompts.prompt(GABARIT).texte   # revenu à l'origine

    @pytest.mark.asyncio
    async def test_echec_de_lecture_garde_le_cache(self):
        prompts.appliquer_versions_actives({LITTERAL: (1, "Version fictive gardée en cache.")})
        db = MagicMock()
        db.execute = AsyncMock(side_effect=RuntimeError("base indisponible"))
        await prompts.recharger(db)   # ne lève pas
        assert prompts.texte(LITTERAL) == "Version fictive gardée en cache."

    @pytest.mark.asyncio
    async def test_rafraichir_respecte_la_fraicheur(self, db_session):
        await prompts.charger(db_session)
        db = MagicMock()
        db.execute = AsyncMock(side_effect=AssertionError("ne doit pas relire"))
        await prompts.rafraichir_si_perime(db)   # chargé à l'instant : pas de relecture


# ─── Routes ───────────────────────────────────────────────────────────────────

class TestRoutes:
    @pytest.mark.asyncio
    async def test_liste_groupable_par_usage(self, client):
        r = await client.get("/api/system/prompts")
        assert r.status_code == 200
        liste = r.json()["prompts"]
        # Les consignes de référence (A6) sont versionnées par /api/consignes : absentes d'ici.
        assert [p["cle"] for p in liste] == [c for c in prompts.cles() if not c.startswith("reference.")]
        p = next(x for x in liste if x["cle"] == GABARIT)
        assert p == {**p, "usage": "analyse", "variables": ["tableau", "attentes"], "version_active": 0,
                     "modifie": False, "nb_versions": 0, "ignoree": None}

    @pytest.mark.asyncio
    async def test_versions_successives_origine_et_restauration(self, client):
        url = f"/api/system/prompts/{GABARIT}"
        d = (await client.get(url)).json()
        assert d["active"] is None and d["versions"] == [] and d["texte_actif"] == d["origine"]

        v1 = await client.post(url + "/versions", json={"texte": TEXTE_GABARIT, "commentaire": "essai"})
        assert v1.status_code == 201 and v1.json()["version"] == 1
        # servie tout de suite par ce processus
        assert prompts.texte(GABARIT) == TEXTE_GABARIT
        d = (await client.get(url)).json()
        assert d["servie"]["version"] == 1 and d["texte_actif"] == TEXTE_GABARIT

        v2 = await client.post(url + "/versions", json={"texte": None, "commentaire": "retour"})
        assert v2.json()["version"] == 2 and v2.json()["origine"] is True
        assert prompts.texte(GABARIT) == prompts.prompt(GABARIT).texte

        # restaurer la v1 = une v3 avec son texte
        v3 = await client.post(url + "/versions", json={"texte": TEXTE_GABARIT, "commentaire": "Restauration de la version 1"})
        assert v3.json()["version"] == 3
        d = (await client.get(url)).json()
        assert [v["version"] for v in d["versions"]] == [3, 2, 1]          # rien d'écrasé
        assert d["active"]["version"] == 3 and prompts.version_servie(GABARIT) == 3

        liste = (await client.get("/api/system/prompts")).json()["prompts"]
        p = next(x for x in liste if x["cle"] == GABARIT)
        assert p["version_active"] == 3 and p["modifie"] is True and p["nb_versions"] == 3

    @pytest.mark.asyncio
    async def test_contrat_refuse_422_et_cle_inconnue_404(self, client):
        url = f"/api/system/prompts/{GABARIT}/versions"
        r = await client.post(url, json={"texte": "Fictif : {tableau} sans l'autre variable."})
        assert r.status_code == 422 and "manquante" in r.json()["detail"]
        r = await client.post(url, json={"texte": TEXTE_GABARIT + " {en_trop}"})
        assert r.status_code == 422 and "inconnue" in r.json()["detail"]
        r = await client.post(url, json={"texte": "{tableau} {attentes} accolade { orpheline"})
        assert r.status_code == 422 and "orpheline" in r.json()["detail"]
        r = await client.post(url, json={"texte": "court"})
        assert r.status_code == 422 and "trop court" in r.json()["detail"]
        assert (await client.get(f"/api/system/prompts/{GABARIT}")).json()["versions"] == []
        assert (await client.get("/api/system/prompts/cle.inconnue")).status_code == 404
        assert (await client.post("/api/system/prompts/cle.inconnue/versions", json={"texte": None})).status_code == 404

    @pytest.mark.asyncio
    async def test_auteur_enregistre(self, client):
        from services import audit

        with patch.object(audit, "auteur_courant", return_value="admin.fictif"):
            r = await client.post(f"/api/system/prompts/{LITTERAL}/versions",
                                  json={"texte": "Consigne système fictive pour l'auteur."})
        assert r.json()["auteur"] == "admin.fictif"

    @pytest.mark.asyncio
    async def test_reserve_a_l_administrateur(self, client, db_session):
        from models.auth import SessionAuth, Utilisateur
        from services import acces, oidc_service, runtime_config

        for methode, chemin in [("GET", "/api/system/prompts"), ("GET", "/api/system/prompts/{cle}"),
                                ("POST", "/api/system/prompts/{cle}/versions"),
                                ("POST", "/api/system/prompts/{cle}/essayer"),
                                ("POST", "/api/system/prompts/{cle}/relire")]:
            assert acces.classer(methode, chemin) == acces.ADMIN
        assert not acces.a_tracer("POST", "/api/system/prompts/{cle}/essayer")
        assert not acces.a_tracer("POST", "/api/system/prompts/{cle}/relire")
        assert acces.a_tracer("POST", "/api/system/prompts/{cle}/versions")

        runtime_config._overrides["auth_active"] = "true"
        now = datetime.now(timezone.utc)
        jetons = {}
        for role in ("utilisateur", "admin"):
            u = Utilisateur(emetteur=oidc_service.emetteur_configure(), sub=f"sub-{role}-prompts", role=role,
                            bloque=False, identifiant=role, nom=role, groupes=[])
            db_session.add(u)
            await db_session.flush()
            jetons[role] = f"jeton-fictif-prompts-{role}"
            db_session.add(SessionAuth(id=oidc_service.hacher_jeton(jetons[role]), utilisateur_id=u.id, creee=now,
                                       derniere_activite=now, expire_max=now + timedelta(days=1)))
        await db_session.commit()

        def entetes(role):
            return {"Cookie": f"matotheque_session={jetons[role]}", **SYNC}

        assert (await client.get("/api/system/prompts")).status_code == 401
        assert (await client.get("/api/system/prompts", headers=entetes("utilisateur"))).status_code == 403
        r = await client.post(f"/api/system/prompts/{LITTERAL}/versions", headers=entetes("utilisateur"),
                              json={"texte": "Tentative fictive d'un utilisateur."})
        assert r.status_code == 403
        assert (await client.get("/api/system/prompts", headers=entetes("admin"))).status_code == 200
        r = await client.post(f"/api/system/prompts/{LITTERAL}/versions", headers=entetes("admin"),
                              json={"texte": "Version fictive enregistrée par l'admin."})
        assert r.status_code == 201 and r.json()["auteur"] == "admin"


# ─── Essayer / Relire (IA simulée) ───────────────────────────────────────────

def _ollama(reponse: str, vu: dict | None = None):
    o = MagicMock()

    async def generate(prompt, **kw):
        from services.ollama_service import _USAGE_IA
        if vu is not None:
            vu.update(prompt=prompt, usage=_USAGE_IA.get(), **kw)
        return reponse

    o.generate = AsyncMock(side_effect=generate)
    return o


class TestEssayerRelire:
    @pytest.mark.asyncio
    async def test_essayer_candidat_avec_variables_sous_l_usage(self, client):
        from services import runtime_config

        runtime_config._overrides["default_model"] = "modele-local-fictif:1b"
        vu: dict = {}
        with patch("services.ollama_service.OllamaService", return_value=_ollama("réponse fictive", vu)):
            r = await client.post(f"/api/system/prompts/{GABARIT}/essayer",
                                  json={"texte": TEXTE_GABARIT, "variables": {"tableau": "T1"}})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["reponse"] == "réponse fictive" and d["usage"] == "analyse" and isinstance(d["duree_ms"], int)
        assert vu["usage"] == "analyse" and vu["model"] == d["model"]
        assert vu["prompt"] == 'Nouvelle consigne fictive.\nTableau : T1\nAttentes : \nRéponds en JSON {"a": 1}.'
        # rien d'enregistré
        assert (await client.get(f"/api/system/prompts/{GABARIT}")).json()["versions"] == []

    @pytest.mark.asyncio
    async def test_essayer_message_en_consigne_systeme(self, client):
        vu: dict = {}
        with patch("services.ollama_service.OllamaService", return_value=_ollama("ok", vu)):
            r = await client.post(f"/api/system/prompts/{LITTERAL}/essayer", json={"message": "Question fictive ?"})
        assert r.status_code == 200
        assert vu["prompt"] == "Question fictive ?" and vu["system"] == prompts.prompt(LITTERAL).texte
        assert vu["usage"] == "rapport"

    @pytest.mark.asyncio
    async def test_essayer_refuse_hors_contrat_et_geco(self, client):
        from services import runtime_config

        r = await client.post(f"/api/system/prompts/{GABARIT}/essayer", json={"texte": "Fictif {tableau} seul, sans plus."})
        assert r.status_code == 422
        runtime_config._overrides["default_model"] = "geco/modele-fictif"
        with patch("services.ollama_service.OllamaService", return_value=_ollama("x")) as o:
            r = await client.post(f"/api/system/prompts/{LITTERAL}/essayer", json={})
        assert r.status_code == 400 and not o.return_value.generate.called

    @pytest.mark.asyncio
    async def test_essayer_format_numerique(self, client):
        variables = {v: "x" for v in prompts.prompt(AVEC_FORMAT).variables}
        variables["note_max"] = "20"
        vu: dict = {}
        with patch("services.ollama_service.OllamaService", return_value=_ollama("ok", vu)):
            r = await client.post(f"/api/system/prompts/{AVEC_FORMAT}/essayer", json={"variables": variables})
        assert r.status_code == 200, r.text
        assert "20" in vu["prompt"]

    @pytest.mark.asyncio
    async def test_relire_contrat_respecte_ou_casse(self, client):
        bon = '{"prompt": "Consigne relue et fictive : {tableau} puis {attentes}.", "remarques": ["clarifié"]}'
        with patch("services.ollama_service.OllamaService", return_value=_ollama(bon)):
            r = await client.post(f"/api/system/prompts/{GABARIT}/relire", json={})
        assert r.status_code == 200 and r.json()["contrat_ok"] is True and r.json()["erreurs"] == []

        casse = '{"prompt": "Consigne relue qui a perdu une variable : {tableau}.", "remarques": []}'
        vu: dict = {}
        with patch("services.ollama_service.OllamaService", return_value=_ollama(casse, vu)):
            r = await client.post(f"/api/system/prompts/{GABARIT}/relire", json={"texte": TEXTE_GABARIT})
        d = r.json()
        assert d["contrat_ok"] is False and any("manquante" in e for e in d["erreurs"])
        assert "VARIABLES remplies par le code" in vu["prompt"]   # contexte « gabarit » donné à la relecture
        assert (await client.get(f"/api/system/prompts/{GABARIT}")).json()["versions"] == []
