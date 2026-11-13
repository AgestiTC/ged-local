"""
Plage horaire des lots IA (plan docs/plan-lots-ia-par-modele.md, étape 4).

Hors de la plage, le worker se conduit comme en pause IA : les lots attendent, « Créer » part.
Sans plage réglée (le défaut), rien ne change. Tâches 100 % FICTIVES.
"""

from datetime import datetime, timezone

import pytest

from models.job import Job
from services import file_ia, runtime_config

SYNC = {"Sec-Fetch-Site": "same-origin"}


def _plage(debut: str, fin: str) -> None:
    runtime_config._overrides.update({"lots_ia_plage_debut": debut, "lots_ia_plage_fin": fin})


def _utc(annee, mois, jour, heure, minute=0) -> datetime:
    return datetime(annee, mois, jour, heure, minute, tzinfo=timezone.utc)


# ─── Fonctions pures ──────────────────────────────────────────────────────────

class TestLireHeure:
    @pytest.mark.parametrize("texte, minutes", [("00:00", 0), ("06:00", 360), ("22:30", 1350), ("23:59", 1439),
                                                (" 07:05 ", 425)])
    def test_valide(self, texte, minutes):
        assert runtime_config.lire_heure(texte) == minutes

    @pytest.mark.parametrize("texte", [None, "", "22", "22h00", "24:00", "12:60", "7:05", "07:5", "aa:bb",
                                       "22:00:00", "-1:00", "22 :00"])
    def test_illisible(self, texte):
        assert runtime_config.lire_heure(texte) is None


class TestDansPlage:
    def test_plage_de_jour(self):
        debut, fin = 8 * 60, 18 * 60
        assert runtime_config.dans_plage(debut, fin, 8 * 60) is True        # borne de début incluse
        assert runtime_config.dans_plage(debut, fin, 12 * 60) is True
        assert runtime_config.dans_plage(debut, fin, 18 * 60) is False      # borne de fin exclue
        assert runtime_config.dans_plage(debut, fin, 7 * 60 + 59) is False

    def test_plage_a_cheval_sur_minuit(self):
        debut, fin = 22 * 60, 6 * 60
        assert runtime_config.dans_plage(debut, fin, 22 * 60) is True
        assert runtime_config.dans_plage(debut, fin, 23 * 60 + 59) is True
        assert runtime_config.dans_plage(debut, fin, 0) is True             # minuit
        assert runtime_config.dans_plage(debut, fin, 5 * 60 + 59) is True
        assert runtime_config.dans_plage(debut, fin, 6 * 60) is False
        assert runtime_config.dans_plage(debut, fin, 12 * 60) is False
        assert runtime_config.dans_plage(debut, fin, 21 * 60 + 59) is False

    def test_plage_vide_ou_incomplete_toujours(self):
        for debut, fin in ((None, None), (22 * 60, None), (None, 6 * 60)):
            assert runtime_config.dans_plage(debut, fin, 12 * 60) is True

    def test_debut_egal_fin_toute_la_journee(self):
        assert runtime_config.dans_plage(600, 600, 0) is True
        assert runtime_config.dans_plage(600, 600, 600) is True


# ─── Réglage lu, heure de Paris ───────────────────────────────────────────────

class TestHorsPlage:
    def test_defaut_aucune_plage_rien_n_est_retenu(self):
        assert runtime_config.plage_lots_ia() is None
        assert runtime_config.lots_ia_hors_plage(_utc(2026, 11, 13, 11)) is False
        assert runtime_config.lots_ia_suspendus() is False

    def test_heure_de_paris_en_hiver(self):
        _plage("22:00", "06:00")
        assert runtime_config.plage_lots_ia() == ("22:00", "06:00")
        assert runtime_config.lots_ia_hors_plage(_utc(2026, 11, 13, 20, 59)) is True    # 21:59 à Paris
        assert runtime_config.lots_ia_hors_plage(_utc(2026, 11, 13, 21, 0)) is False    # 22:00 à Paris
        assert runtime_config.lots_ia_hors_plage(_utc(2026, 11, 14, 4, 59)) is False    # 05:59
        assert runtime_config.lots_ia_hors_plage(_utc(2026, 11, 14, 5, 0)) is True      # 06:00
        assert runtime_config.lots_ia_hors_plage(_utc(2026, 11, 13, 11, 0)) is True     # midi

    def test_heure_de_paris_en_ete(self):
        """Heure d'été : Paris = UTC + 2. Une plage en UTC fixe se décalerait d'une heure deux fois l'an."""
        _plage("22:00", "06:00")
        assert runtime_config.lots_ia_hors_plage(_utc(2026, 7, 1, 19, 59)) is True      # 21:59 à Paris
        assert runtime_config.lots_ia_hors_plage(_utc(2026, 7, 1, 20, 0)) is False      # 22:00 à Paris
        assert runtime_config.lots_ia_hors_plage(_utc(2026, 7, 2, 4, 0)) is True        # 06:00 à Paris

    def test_date_sans_fuseau_lue_comme_utc(self):
        _plage("22:00", "06:00")
        assert runtime_config.lots_ia_hors_plage(datetime(2026, 11, 13, 21, 0)) is False

    @pytest.mark.parametrize("debut, fin", [("22:00", ""), ("", "06:00"), ("22h", "06:00"), ("25:00", "06:00")])
    def test_reglage_incomplet_ou_illisible_pas_de_plage(self, debut, fin):
        """Dans le doute on ne retient PAS les lots : une indexation arrêtée sans raison lisible est pire."""
        _plage(debut, fin)
        assert runtime_config.plage_lots_ia() is None
        assert runtime_config.lots_ia_hors_plage(_utc(2026, 11, 13, 11)) is False

    def test_fuseau_indisponible_pas_de_retenue(self, monkeypatch):
        _plage("22:00", "06:00")
        monkeypatch.setattr(runtime_config, "_minute_locale", lambda maintenant: None)
        assert runtime_config.lots_ia_hors_plage(_utc(2026, 11, 13, 11)) is False

    def test_suspendus_pause_ou_hors_plage(self, monkeypatch):
        monkeypatch.setattr(runtime_config, "lots_ia_hors_plage", lambda maintenant=None: True)
        assert runtime_config.lots_ia_suspendus() is True
        monkeypatch.setattr(runtime_config, "lots_ia_hors_plage", lambda maintenant=None: False)
        assert runtime_config.lots_ia_suspendus() is False
        runtime_config._overrides["ia_pause"] = "1"
        assert runtime_config.lots_ia_suspendus() is True


# ─── Motif d'attente (écran « File IA ») ──────────────────────────────────────

def _j(type_: str) -> dict:
    return {"id": "x", "type": type_, "statut": "pending", "created_at": datetime(2026, 11, 13, tzinfo=timezone.utc),
            "started_at": None, "progress": 0, "prioritaire": False}


class TestMotif:
    def test_un_lot_attend_la_plage_pas_un_creer(self):
        assert file_ia.raison(_j("analyze"), False, 0, 2, 0, hors_plage=True) == "hors_plage"
        assert file_ia.raison(_j("comparatif"), False, 0, 2, 0, hors_plage=True) == "demarrage"

    def test_la_pause_se_dit_d_abord(self):
        assert file_ia.raison(_j("analyze"), True, 0, 2, 0, hors_plage=True) == "pause_ia"

    def test_message_nomme_la_plage(self):
        texte = file_ia.message("hors_plage", plage=("22:00", "06:00"))
        assert "22:00" in texte and "06:00" in texte and "{" not in texte

    @pytest.mark.asyncio
    async def test_route_file_dit_la_plage(self, client, db_session, monkeypatch):
        _plage("22:00", "06:00")
        monkeypatch.setattr(runtime_config, "lots_ia_hors_plage", lambda maintenant=None: True)
        lot, creer = Job(type="analyze", statut="pending"), Job(type="comparatif", statut="pending")
        db_session.add_all([lot, creer])
        await db_session.commit()
        corps = (await client.get(f"/api/jobs/{lot.id}/file")).json()
        assert corps["raison"] == "hors_plage" and corps["hors_plage"] is True
        assert corps["estimation"] is None and "22:00" in corps["message"]
        # Le lot retenu ne passe pas devant la demande de « Créer », qui part tout de suite.
        vu_par_creer = (await client.get(f"/api/jobs/{creer.id}/file")).json()
        assert vu_par_creer["raison"] != "hors_plage" and vu_par_creer["nb_devant"] == 0

    @pytest.mark.asyncio
    async def test_route_file_dans_la_plage_rien_de_special(self, client, db_session, monkeypatch):
        _plage("22:00", "06:00")
        monkeypatch.setattr(runtime_config, "lots_ia_hors_plage", lambda maintenant=None: False)
        lot = Job(type="analyze", statut="pending")
        db_session.add(lot)
        await db_session.commit()
        corps = (await client.get(f"/api/jobs/{lot.id}/file")).json()
        assert corps["raison"] != "hors_plage" and corps["hors_plage"] is False


# ─── Écriture du réglage et état exposé ───────────────────────────────────────

class TestReglage:
    @pytest.mark.asyncio
    async def test_plage_valide_enregistree_puis_videe(self, client):
        r = await client.put("/api/system/config", json={"lots_ia_plage_debut": "22:00", "lots_ia_plage_fin": "06:00"},
                             headers=SYNC)
        assert r.status_code == 200
        assert runtime_config.plage_lots_ia() == ("22:00", "06:00")
        etat = (await client.get("/api/system/ia/status")).json()
        assert etat["plage"] == {"debut": "22:00", "fin": "06:00"} and isinstance(etat["hors_plage"], bool)
        r = await client.put("/api/system/config", json={"lots_ia_plage_debut": "", "lots_ia_plage_fin": ""},
                             headers=SYNC)
        assert r.status_code == 200 and runtime_config.plage_lots_ia() is None
        etat = (await client.get("/api/system/ia/status")).json()
        assert etat["plage"] is None and etat["hors_plage"] is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("corps", [
        {"lots_ia_plage_debut": "22h00", "lots_ia_plage_fin": "06:00"},
        {"lots_ia_plage_debut": "22:00", "lots_ia_plage_fin": "24:00"},
        {"lots_ia_plage_debut": "22:00"},                                    # une seule borne
        {"lots_ia_plage_debut": "22:00", "lots_ia_plage_fin": ""},
    ])
    async def test_plage_refusee(self, client, corps):
        r = await client.put("/api/system/config", json=corps, headers=SYNC)
        assert r.status_code == 422
        assert runtime_config.plage_lots_ia() is None        # rien n'a été écrit

    @pytest.mark.asyncio
    async def test_une_borne_seule_acceptee_si_l_autre_est_deja_en_base(self, client):
        _plage("22:00", "06:00")
        r = await client.put("/api/system/config", json={"lots_ia_plage_fin": "07:30"}, headers=SYNC)
        assert r.status_code == 200 and runtime_config.plage_lots_ia() == ("22:00", "07:30")
        # … mais on ne peut pas vider une seule des deux.
        r = await client.put("/api/system/config", json={"lots_ia_plage_fin": ""}, headers=SYNC)
        assert r.status_code == 422 and runtime_config.plage_lots_ia() == ("22:00", "07:30")
