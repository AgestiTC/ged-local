"""
Tests d'intégration — rétroplanning d'un dossier thématique
============================================================
Ce qui est réellement fragile ici, et donc testé :

- le **calcul des fenêtres de mois** depuis la date du terme (mois calendaires, pas
  tranches de 30 jours, et report correct des fins de mois) ;
- le fait que le planning **reste consultable sans date de terme** — une page qui
  refuse de s'ouvrir tant qu'on n'a pas saisi une date ne sert à personne ;
- l'**horodatage du suivi** : décocher un jalon doit effacer sa date de réalisation ;
- l'**idempotence du seed**, et surtout qu'il ne réécrit jamais le suivi personnel.
"""

from datetime import date

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def client(db_session):
    from database import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def dossier(client):
    """Un dossier vide, prêt à recevoir des jalons."""
    async with client as c:
        resp = await c.post("/api/dossiers", json={"titre": "Devenir parent (test)"})
        yield resp.json()["slug"]


# ─── Calcul des fenêtres de mois ──────────────────────────────────────────────

class TestFenetresDeMois:
    def test_mois_calendaires_et_non_tranches_de_30_jours(self):
        """
        Un planning qui affiche « mars » doit tomber sur mars. Avec des tranches de
        30 jours, l'erreur atteint une semaine au bout de neuf mois.
        """
        from routers.dossiers import _ajouter_mois

        terme = date(2026, 12, 15)
        assert _ajouter_mois(terme, -9) == date(2026, 3, 15)
        assert _ajouter_mois(terme, -1) == date(2026, 11, 15)
        assert _ajouter_mois(terme, 0) == terme
        assert _ajouter_mois(terme, 12) == date(2027, 12, 15)

    def test_report_des_fins_de_mois(self):
        """31 mars moins un mois n'est pas le 31 février."""
        from routers.dossiers import _ajouter_mois

        assert _ajouter_mois(date(2026, 3, 31), -1) == date(2026, 2, 28)
        assert _ajouter_mois(date(2028, 3, 31), -1) == date(2028, 2, 29)   # année bissextile
        assert _ajouter_mois(date(2026, 1, 31), 1) == date(2026, 2, 28)

    def test_date_au_jour_pres_depuis_les_SA(self):
        """
        Un jalon qui porte des semaines d'aménorrhée se date exactement : c'est ce qui rend
        la vue calendrier honnête. Le terme est à 41 SA (convention française).
        """
        from routers.dossiers import _date_prevue

        class J:
            def __init__(self, mois, sa=None):
                self.mois, self.sa = mois, sa

        terme = date(2027, 1, 20)
        assert _date_prevue(J(-7, 14), terme) == ("2026-07-15", True)   # 27 semaines avant
        assert _date_prevue(J(-5, 22), terme) == ("2026-09-09", True)
        assert _date_prevue(J(-1, 39), terme) == ("2027-01-06", True)   # 2 semaines avant

    def test_sans_SA_la_date_est_approximative_et_le_dit(self):
        """
        Sans SA, on ne sait rien de plus fin que le mois : on pose au début de la fenêtre
        ET on le signale. Prétendre à une date exacte ferait croire à un rendez-vous.
        """
        from routers.dossiers import _date_prevue

        class J:
            def __init__(self, mois, sa=None):
                self.mois, self.sa = mois, sa

        terme = date(2027, 1, 20)
        assert _date_prevue(J(-6), terme) == ("2026-07-20", False)
        assert _date_prevue(J(2), terme) == ("2027-03-20", False)
        assert _date_prevue(J(-7, 14), None) == (None, False)   # pas d'ancre, pas de date

    def test_libelles_de_mois(self):
        """Le rang de grossesse se lit à l'endroit : -9 est le 1ᵉʳ mois, pas le 9ᵉ."""
        from routers.dossiers import _libelle_mois

        assert _libelle_mois(-9) == "1ᵉʳ mois de grossesse"
        assert _libelle_mois(-1) == "9ᵉ mois de grossesse"
        assert _libelle_mois(0) == "Naissance — 1ᵉʳ mois"
        assert _libelle_mois(6) == "6 mois"
        assert _libelle_mois(24) == "2 ans"
        assert _libelle_mois(30) == "2 ans et 6 mois"


# ─── Le planning ──────────────────────────────────────────────────────────────

class TestPlanning:
    @pytest.mark.asyncio
    async def test_consultable_sans_date_de_terme(self, client, dossier):
        """Sans ancre, les mois sortent quand même — avec leur rang, sans dates."""
        async with client as c:
            await c.post(f"/api/dossiers/{dossier}/jalons",
                         json={"mois": -5, "titre": "Échographie morphologique"})
            resp = await c.get(f"/api/dossiers/{dossier}/planning")

        assert resp.status_code == 200
        data = resp.json()
        assert data["date_terme"] is None
        assert data["mois"][0]["libelle"] == "5ᵉ mois de grossesse"
        assert data["mois"][0]["debut"] is None
        assert data["avertissement"]        # jamais servi sans son avertissement

    @pytest.mark.asyncio
    async def test_dates_calculees_depuis_le_terme(self, client, dossier):
        async with client as c:
            await c.post(f"/api/dossiers/{dossier}/jalons",
                         json={"mois": -3, "titre": "5ᵉ examen prénatal", "sa": 31})
            resp = await c.get(f"/api/dossiers/{dossier}/planning",
                               params={"date_terme": "2027-01-20"})

        m = resp.json()["mois"][0]
        assert m["debut"] == "2026-10-20"
        assert m["fin"] == "2026-11-20"
        # Le jalon porte 31 SA → daté au jour près pour la vue calendrier.
        assert m["jalons"][0]["date_prevue"] == "2026-11-11"
        assert m["jalons"][0]["date_precise"] is True

    @pytest.mark.asyncio
    async def test_date_illisible_ne_casse_pas_la_page(self, client, dossier):
        """Une date invalide dégrade le planning, elle ne le rend pas inaccessible."""
        async with client as c:
            await c.post(f"/api/dossiers/{dossier}/jalons", json={"mois": 0, "titre": "Déclaration"})
            resp = await c.get(f"/api/dossiers/{dossier}/planning",
                               params={"date_terme": "pas-une-date"})

        assert resp.status_code == 200
        assert resp.json()["date_terme"] is None

    @pytest.mark.asyncio
    async def test_mois_groupes_et_ordonnes(self, client, dossier):
        """Les mois sortent dans l'ordre du temps, grossesse d'abord."""
        async with client as c:
            for mois, titre in [(2, "Vaccins"), (-9, "Acide folique"), (0, "Déclaration")]:
                await c.post(f"/api/dossiers/{dossier}/jalons", json={"mois": mois, "titre": titre})
            resp = await c.get(f"/api/dossiers/{dossier}/planning")

        mois = resp.json()["mois"]
        assert [m["index"] for m in mois] == [-9, 0, 2]
        assert [m["phase"] for m in mois] == ["grossesse", "enfant", "enfant"]

    @pytest.mark.asyncio
    async def test_stats(self, client, dossier):
        async with client as c:
            a = (await c.post(f"/api/dossiers/{dossier}/jalons",
                              json={"mois": -7, "titre": "Déclaration de grossesse",
                                    "obligatoire": True})).json()
            await c.post(f"/api/dossiers/{dossier}/jalons",
                         json={"mois": -5, "titre": "Liste de naissance"})
            await c.patch(f"/api/dossiers/jalons/{a['id']}", json={"fait": True})
            stats = (await c.get(f"/api/dossiers/{dossier}/planning")).json()["stats"]

        assert stats == {"total": 2, "faits": 1, "obligatoires": 1, "obligatoires_faits": 1}


# ─── Suivi personnel ──────────────────────────────────────────────────────────

class TestSuivi:
    @pytest.mark.asyncio
    async def test_cocher_horodate_et_decocher_efface(self, client, dossier):
        """Une date de réalisation qui survit au décochage est un mensonge silencieux."""
        async with client as c:
            j = (await c.post(f"/api/dossiers/{dossier}/jalons",
                              json={"mois": 0, "titre": "Déclaration de naissance"})).json()
            assert j["fait"] is False and j["fait_le"] is None

            coche = (await c.patch(f"/api/dossiers/jalons/{j['id']}", json={"fait": True})).json()
            assert coche["fait"] is True and coche["fait_le"] is not None

            decoche = (await c.patch(f"/api/dossiers/jalons/{j['id']}", json={"fait": False})).json()
            assert decoche["fait"] is False and decoche["fait_le"] is None

    @pytest.mark.asyncio
    async def test_note_personnelle(self, client, dossier):
        async with client as c:
            j = (await c.post(f"/api/dossiers/{dossier}/jalons",
                              json={"mois": -6, "titre": "Crèche"})).json()
            maj = (await c.patch(f"/api/dossiers/jalons/{j['id']}",
                                 json={"note_perso": "Dossier déposé le 12, relancer en mars"})).json()

        assert maj["note_perso"] == "Dossier déposé le 12, relancer en mars"

    @pytest.mark.asyncio
    async def test_suppression(self, client, dossier):
        async with client as c:
            j = (await c.post(f"/api/dossiers/{dossier}/jalons",
                              json={"mois": 1, "titre": "À retirer"})).json()
            assert (await c.delete(f"/api/dossiers/jalons/{j['id']}")).status_code == 200
            assert (await c.get(f"/api/dossiers/{dossier}/planning")).json()["mois"] == []

    @pytest.mark.asyncio
    async def test_id_invalide(self, client):
        async with client as c:
            assert (await c.patch("/api/dossiers/jalons/pas-un-uuid",
                                  json={"fait": True})).status_code == 400


# ─── Export iCalendar ─────────────────────────────────────────────────────────

class TestExportICS:
    @pytest.mark.asyncio
    async def test_sans_terme_le_refus_explique_quoi_faire(self, client, dossier):
        """Sans ancre, aucun jalon n'a de date : un .ics vide serait pire qu'une erreur."""
        async with client as c:
            await c.post(f"/api/dossiers/{dossier}/jalons", json={"mois": 0, "titre": "X"})
            resp = await c.get(f"/api/dossiers/{dossier}/planning.ics")

        assert resp.status_code == 400
        assert "Paramètres" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_evenement_journee_entiere_et_uid_stable(self, client, dossier):
        """
        `UID` stable = réimporter MET À JOUR au lieu de dupliquer. C'est la différence
        entre un export utilisable deux fois et un export qui pollue l'agenda.
        """
        async with client as c:
            j = (await c.post(f"/api/dossiers/{dossier}/jalons",
                              json={"mois": -5, "titre": "2ᵉ échographie", "sa": 22})).json()
            resp = await c.get(f"/api/dossiers/{dossier}/planning.ics",
                               params={"date_terme": "2027-01-20"})

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/calendar")
        assert ".ics" in resp.headers["content-disposition"]
        ics = resp.text

        assert ics.startswith("BEGIN:VCALENDAR") and ics.rstrip().endswith("END:VCALENDAR")
        assert "\r\n" in ics                                   # CRLF exigé par la RFC 5545
        assert f"UID:jalon-{j['id']}@matotheque" in ics
        assert "DTSTART;VALUE=DATE:20260909" in ics             # 22 SA avant un terme au 20/01
        assert "DTEND;VALUE=DATE:20260910" in ics               # fin exclusive = journée entière
        assert "TRANSP:TRANSPARENT" in ics                      # informatif, pas « occupé »

    @pytest.mark.asyncio
    async def test_une_periode_ne_se_fait_pas_passer_pour_un_rendez_vous(self, client, dossier):
        """Un jalon sans SA n'a qu'un mois : l'export doit le dire, pas le maquiller."""
        async with client as c:
            await c.post(f"/api/dossiers/{dossier}/jalons",
                         json={"mois": -6, "titre": "Démarches crèche"})
            ics = (await c.get(f"/api/dossiers/{dossier}/planning.ics",
                               params={"date_terme": "2027-01-20"})).text

        assert "(période)" in ics
        assert "PÉRIODE" in ics or "PÉRIODE".lower() in ics.lower()

    @pytest.mark.asyncio
    async def test_echappement_des_caracteres_speciaux(self, client, dossier):
        """Virgules et points-virgules non échappés cassent le fichier à l'import."""
        async with client as c:
            await c.post(f"/api/dossiers/{dossier}/jalons",
                         json={"mois": 0, "titre": "Papiers : carte, mutuelle; livret",
                               "sa": 41})
            ics = (await c.get(f"/api/dossiers/{dossier}/planning.ics",
                               params={"date_terme": "2027-01-20"})).text

        assert "carte\\, mutuelle\\; livret" in ics

    @pytest.mark.asyncio
    async def test_le_seed_complet_s_exporte(self, client):
        """67 jalons : le pliage des lignes longues et les accents doivent tenir."""
        async with client as c:
            await c.post("/api/dossiers/seed/devenir-parent")
            resp = await c.get("/api/dossiers/devenir-parent/planning.ics",
                               params={"date_terme": "2027-01-20"})

        ics = resp.text
        assert resp.status_code == 200
        assert ics.count("BEGIN:VEVENT") == ics.count("END:VEVENT") > 40
        # Chaque ligne repliée tient dans 75 octets (la continuation compte son espace).
        for ligne in ics.split("\r\n"):
            assert len(ligne.encode("utf-8")) <= 76, ligne[:60]


# ─── Seed « Devenir parent » ──────────────────────────────────────────────────

class TestSeedJalons:
    @pytest.mark.asyncio
    async def test_le_seed_installe_son_retroplanning(self, client):
        """Installer le dossier doit livrer ses jalons : un onglet Planning vide serait
        une seconde action que personne ne devinerait."""
        async with client as c:
            resp = await c.post("/api/dossiers/seed/devenir-parent")
            assert resp.json()["jalons_ajoutes"] > 40
            data = (await c.get("/api/dossiers/devenir-parent/planning")).json()

        index = [m["index"] for m in data["mois"]]
        assert index == sorted(index)
        assert min(index) == -9 and max(index) >= 24          # grossesse ET âges de l'enfant
        assert any(m["phase"] == "grossesse" for m in data["mois"])
        assert any(m["phase"] == "enfant" for m in data["mois"])

    @pytest.mark.asyncio
    async def test_echeances_legales_portent_leur_formulation(self, client):
        """« Avant la fin de la 14ᵉ semaine » est opposable ; « au 3ᵉ mois » ne l'est pas."""
        async with client as c:
            await c.post("/api/dossiers/seed/devenir-parent")
            data = (await c.get("/api/dossiers/devenir-parent/planning")).json()

        tous = [j for m in data["mois"] for j in m["jalons"]]
        declaration = next(j for j in tous if "Déclaration de grossesse" in j["titre"])
        assert "14" in declaration["echeance"] and declaration["obligatoire"] is True

        naissance = next(j for j in tous if "Déclaration de naissance" in j["titre"])
        assert "5 jours" in naissance["echeance"]

    @pytest.mark.asyncio
    async def test_reinstallation_ne_duplique_ni_n_efface_le_suivi(self, client):
        """Le point le plus facile à casser : un seed relancé doit respecter le vécu."""
        async with client as c:
            await c.post("/api/dossiers/seed/devenir-parent")
            avant = (await c.get("/api/dossiers/devenir-parent/planning")).json()
            cible = avant["mois"][0]["jalons"][0]
            await c.patch(f"/api/dossiers/jalons/{cible['id']}",
                          json={"fait": True, "note_perso": "fait le 3"})

            rejoue = await c.post("/api/dossiers/seed/devenir-parent")
            apres = (await c.get("/api/dossiers/devenir-parent/planning")).json()

        assert rejoue.json()["jalons_ajoutes"] == 0
        assert apres["stats"]["total"] == avant["stats"]["total"]
        garde = next(j for m in apres["mois"] for j in m["jalons"] if j["id"] == cible["id"])
        assert garde["fait"] is True and garde["note_perso"] == "fait le 3"
