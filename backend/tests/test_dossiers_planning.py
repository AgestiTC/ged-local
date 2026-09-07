"""
Tests d'intégration — rétroplanning d'un dossier thématique
============================================================
Ce qui est réellement fragile ici, et donc testé :

- le **calcul des fenêtres de mois** depuis la date du terme (mois calendaires, pas
  tranches de 30 jours, et report correct des fins de mois) ;
- le fait que le planning **reste consultable sans date de terme** — une page qui
  refuse de s'ouvrir tant qu'on n'a pas saisi une date ne sert à personne ;
- l'**horodatage du suivi** : décocher un jalon doit effacer sa date de réalisation ;
- l'**idempotence du seed**, et surtout qu'il ne réécrit jamais le suivi personnel ;
- les **rendez-vous datés** (`date_reelle` + créneau) : qu'ils priment sur le mois et les
  SA, que leur mois se déduise seul, et qu'ils sortent horodatés à l'export.
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
async def dossier(client, db_session):
    """
    Un dossier vide, prêt à recevoir des jalons.

    La fixture ouvre son PROPRE client plutôt que celui du test : `httpx.AsyncClient` refuse
    d'être ouvert deux fois, et chaque test fait son `async with client`. Elle dépend quand
    même de `client`, qui installe la surcharge de session sur l'application.
    """
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/dossiers", json={"titre": "Devenir parent (test)"})
    return resp.json()["slug"]


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
            def __init__(self, mois, sa=None, date_reelle=None):
                self.mois, self.sa, self.date_reelle = mois, sa, date_reelle

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
            def __init__(self, mois, sa=None, date_reelle=None):
                self.mois, self.sa, self.date_reelle = mois, sa, date_reelle

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


# ─── Rendez-vous datés ────────────────────────────────────────────────────────

class TestRendezVousDate:
    def test_le_mois_se_deduit_de_la_date(self):
        """
        Saisir une date, c'est déjà dire son mois : demander les deux ferait recalculer à
        la main ce que le serveur sait faire. Le jour d'ancrage compte — avec un terme au
        20, le 5 du mois suivant appartient encore à la fenêtre précédente.
        """
        from routers.dossiers import _mois_depuis_date

        terme = date(2027, 1, 20)
        assert _mois_depuis_date(date(2027, 1, 20), terme) == 0
        assert _mois_depuis_date(date(2027, 2, 5), terme) == 0      # avant le 20 février
        assert _mois_depuis_date(date(2027, 2, 20), terme) == 1
        assert _mois_depuis_date(date(2026, 9, 25), terme) == -4
        assert _mois_depuis_date(date(2026, 9, 19), terme) == -5    # veille de la bascule

    def test_le_mois_deduit_reste_dans_les_bornes_du_modele(self):
        """Une date fantaisiste ne doit pas faire échouer l'enregistrement du reste."""
        from routers.dossiers import _mois_depuis_date

        assert _mois_depuis_date(date(1990, 1, 1), date(2027, 1, 20)) == -12
        assert _mois_depuis_date(date(2099, 1, 1), date(2027, 1, 20)) == 216

    def test_la_date_reelle_prime_sur_les_SA_et_sur_le_mois(self):
        """
        Un rendez-vous PRIS est un fait ; le mois et les SA ne sont que des repères. Et il
        vaut même sans terme saisi : il ne se calcule pas, il est connu.
        """
        from routers.dossiers import _date_prevue

        class J:
            def __init__(self, mois, sa=None, date_reelle=None):
                self.mois, self.sa, self.date_reelle = mois, sa, date_reelle

        terme = date(2027, 1, 20)
        assert _date_prevue(J(-5, 22, date(2026, 9, 25)), terme) == ("2026-09-25", True)
        assert _date_prevue(J(-5, 22, date(2026, 9, 25)), None) == ("2026-09-25", True)

    @pytest.mark.asyncio
    async def test_ajout_sans_mois_avec_une_date(self, client, dossier):
        """Le formulaire n'envoie qu'une date : le mois doit sortir juste malgré tout."""
        async with client as c:
            await c.put("/api/system/config", json={"parents_date_terme": "2027-01-20"})
            j = (await c.post(f"/api/dossiers/{dossier}/jalons",
                              json={"titre": "Entretien prénatal", "categorie": "medical",
                                    "date_reelle": "2026-09-25",
                                    "heure_debut": "13:00", "heure_fin": "14:00"})).json()

        assert j["mois"] == -4
        assert j["date_prevue"] == "2026-09-25" and j["date_precise"] is True
        assert j["heure_debut"] == "13:00" and j["heure_fin"] == "14:00"

    @pytest.mark.asyncio
    async def test_deplacer_un_rendez_vous_le_change_de_mois(self, client, dossier):
        """Sinon il tomberait au bon jour dans le calendrier tout en restant classé sous
        l'ancien mois dans la vue Cartes."""
        async with client as c:
            await c.put("/api/system/config", json={"parents_date_terme": "2027-01-20"})
            j = (await c.post(f"/api/dossiers/{dossier}/jalons",
                              json={"titre": "Rendez-vous", "date_reelle": "2026-09-25"})).json()
            maj = (await c.patch(f"/api/dossiers/jalons/{j['id']}",
                                 json={"date_reelle": "2026-11-25"})).json()

        assert j["mois"] == -4 and maj["mois"] == -2

    @pytest.mark.asyncio
    async def test_heure_invalide_refusee(self, client, dossier):
        """« 25:00 » ne doit pas atteindre la base : l'export produirait un .ics illisible."""
        async with client as c:
            resp = await c.post(f"/api/dossiers/{dossier}/jalons",
                                json={"titre": "X", "date_reelle": "2026-09-25",
                                      "heure_debut": "25:00"})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_champs_vides_du_formulaire_valent_null(self, client, dossier):
        """Un champ effacé arrive en chaîne vide : le stocker ferait une date « » en base."""
        async with client as c:
            j = (await c.post(f"/api/dossiers/{dossier}/jalons",
                              json={"mois": 0, "titre": "X", "date_reelle": "",
                                    "heure_debut": "", "url": ""})).json()

        assert j["date_reelle"] is None and j["heure_debut"] is None and j["url"] is None

    @pytest.mark.asyncio
    async def test_export_ics_horodate_un_creneau(self, client, dossier):
        """Un créneau pris occupe l'agenda ; un repère de période reste transparent."""
        async with client as c:
            await c.post(f"/api/dossiers/{dossier}/jalons",
                         json={"titre": "Entretien prénatal", "mois": -4,
                               "date_reelle": "2026-09-25",
                               "heure_debut": "13:00", "heure_fin": "14:00"})
            ics = (await c.get(f"/api/dossiers/{dossier}/planning.ics",
                               params={"date_terme": "2027-01-20"})).text

        # Sans « Z » ni fuseau : heure locale flottante (13h reste 13h à l'import).
        assert "DTSTART:20260925T130000" in ics
        assert "DTEND:20260925T140000" in ics
        assert "TRANSP:OPAQUE" in ics
        assert "(période)" not in ics

    @pytest.mark.asyncio
    async def test_export_ics_sans_heure_de_fin_compte_une_heure(self, client, dossier):
        """Un événement de durée nulle est refusé à l'import par plusieurs agendas."""
        async with client as c:
            await c.post(f"/api/dossiers/{dossier}/jalons",
                         json={"titre": "Rendez-vous sage-femme", "mois": -4,
                               "date_reelle": "2026-09-25", "heure_debut": "23:30"})
            ics = (await c.get(f"/api/dossiers/{dossier}/planning.ics",
                               params={"date_terme": "2027-01-20"})).text

        # 23h30 + 1h déborderait sur le lendemain : on s'arrête à 23h59 plutôt que
        # d'écrire une fin antérieure au début.
        assert "DTSTART:20260925T233000" in ics
        assert "DTEND:20260925T235900" in ics

    @pytest.mark.asyncio
    async def test_export_ics_possible_sans_terme_si_un_rendez_vous_est_date(self, client, dossier):
        """Refuser l'export alors qu'un rendez-vous est daté serait un refus gratuit."""
        async with client as c:
            await c.post(f"/api/dossiers/{dossier}/jalons",
                         json={"mois": 0, "titre": "Rendez-vous", "date_reelle": "2026-09-25"})
            resp = await c.get(f"/api/dossiers/{dossier}/planning.ics")

        assert resp.status_code == 200
        assert "DTSTART;VALUE=DATE:20260925" in resp.text


# ─── Export d'un seul événement ───────────────────────────────────────────────

class TestExportEvenementSeul:
    @pytest.mark.asyncio
    async def test_un_seul_vevent_avec_le_meme_UID_que_l_export_complet(self, client, dossier):
        """
        Le point qui fait tout : même UID que dans l'export du planning. Si le planning a
        déjà été importé, réimporter l'événement seul MET À JOUR sa copie au lieu d'en
        créer une seconde — sinon chaque modification polluerait l'agenda d'un doublon.
        """
        async with client as c:
            j = (await c.post(f"/api/dossiers/{dossier}/jalons",
                              json={"titre": "Entretien prénatal", "mois": -4,
                                    "date_reelle": "2026-09-25",
                                    "heure_debut": "13:00", "heure_fin": "14:00"})).json()
            await c.post(f"/api/dossiers/{dossier}/jalons",
                         json={"mois": -6, "titre": "Un autre jalon"})
            resp = await c.get(f"/api/dossiers/jalons/{j['id']}.ics")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/calendar")
        ics = resp.text
        assert ics.count("BEGIN:VEVENT") == 1                 # LUI seul, pas le planning
        assert "Un autre jalon" not in ics
        assert f"UID:jalon-{j['id']}@matotheque" in ics
        assert "DTSTART:20260925T130000" in ics
        assert "TRANSP:OPAQUE" in ics

    @pytest.mark.asyncio
    async def test_nom_de_fichier_lisible_et_sans_accent(self, client, dossier):
        """Un nom de fichier accentué ne survit pas au transport HTTP chez tous les clients."""
        async with client as c:
            j = (await c.post(f"/api/dossiers/{dossier}/jalons",
                              json={"titre": "2ᵉ échographie : morphologique", "mois": -5,
                                    "date_reelle": "2026-09-25"})).json()
            resp = await c.get(f"/api/dossiers/jalons/{j['id']}.ics")

        assert 'filename="2-echographie-morphologique.ics"' in resp.headers["content-disposition"]

    @pytest.mark.asyncio
    async def test_un_evenement_sans_date_explique_le_refus(self, client, dossier):
        """Sans date ni terme, il n'y a rien à poser dans un agenda : on le dit, plutôt que
        de servir un fichier vide que l'agenda refusera sans expliquer pourquoi."""
        async with client as c:
            j = (await c.post(f"/api/dossiers/{dossier}/jalons",
                              json={"mois": -6, "titre": "Démarches crèche"})).json()
            resp = await c.get(f"/api/dossiers/jalons/{j['id']}.ics")

        assert resp.status_code == 400
        assert "date" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_un_repere_de_periode_s_exporte_en_le_disant(self, client, dossier):
        """Daté par son mois seulement : il part en journée entière, transparent, et le dit."""
        async with client as c:
            await c.put("/api/system/config", json={"parents_date_terme": "2027-01-20"})
            j = (await c.post(f"/api/dossiers/{dossier}/jalons",
                              json={"mois": -6, "titre": "Démarches crèche"})).json()
            ics = (await c.get(f"/api/dossiers/jalons/{j['id']}.ics")).text

        assert "DTSTART;VALUE=DATE:20260720" in ics
        assert "(période)" in ics and "TRANSP:TRANSPARENT" in ics

    @pytest.mark.asyncio
    async def test_id_invalide(self, client):
        async with client as c:
            assert (await c.get("/api/dossiers/jalons/pas-un-uuid.ics")).status_code == 400
