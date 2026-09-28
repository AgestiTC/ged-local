"""
Tests — congés liés à la naissance, pour la mère et le co-parent
================================================================
Chaque attendu ci-dessous est une règle relevée le 15/09/2026 sur service-public.gouv.fr,
ameli.fr et Légifrance (cf. `services/conges/regles.SOURCES`). Un test qui change sans que la
loi ait changé est un test qui ment : on corrige le calcul, pas l'attendu.

Ce qui est réellement fragile ici, et donc testé :

- **les durées** selon la situation (rang de l'enfant, jumeaux, triplés) ;
- **le terme n'est pas la naissance** : en avance, le prénatal non pris passe sur le
  postnatal ; en retard, le prénatal s'allonge et le postnatal reste entier ;
- **les jours ouvrables** du congé de naissance — dimanches et jours fériés exclus, samedi
  compris : c'est là que les calculs faits de tête se trompent d'un jour ;
- **les préavis**, dont l'oubli coûte le congé lui-même ;
- **le congé supplémentaire de naissance** : il SUIT le congé principal, exige d'avoir pris le
  congé de paternité en entier, débute dans les 9 mois, et se compte de date à date ;
- **l'agenda** : idempotent, il déplace au lieu de dupliquer et n'efface jamais un jalon
  coché fait.
"""

from datetime import date

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from services.conges import calcul, regles
from services.conges.calcul import ParamsCoparent, ParamsMere

TERME = date(2027, 1, 20)          # un mercredi, loin des jours fériés


def _periode(plan_parent, cle):
    return next(p for p in plan_parent.periodes if p.cle == cle)


def _echeance(plan_parent, cle):
    return next(e for e in plan_parent.echeances if e.cle == cle)


def _bloquants(plan_parent):
    return [a.message for a in plan_parent.alertes if a.niveau == "bloquant"]


# ─── Arithmétique de dates ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("debut,mois,fin", [
    (date(2027, 3, 15), 1, date(2027, 4, 14)),
    (date(2027, 1, 31), 1, date(2027, 2, 28)),     # le 31 février n'existe pas
    (date(2028, 1, 31), 1, date(2028, 2, 29)),     # année bissextile
    (date(2027, 3, 31), 2, date(2027, 5, 30)),
])
def test_un_mois_se_compte_de_date_a_date(debut, mois, fin):
    """« Chaque période se calcule de date à date » (ameli.fr)."""
    assert calcul.fin_de_mois(debut, mois) == fin


def test_jours_feries_2027_dont_les_fetes_mobiles():
    feries = regles.jours_feries(2027)
    assert date(2027, 3, 29) in feries      # lundi de Pâques (Pâques = 28 mars 2027)
    assert date(2027, 5, 6) in feries       # Ascension
    assert date(2027, 5, 17) in feries      # lundi de Pentecôte
    assert len(feries) == 11


# ─── Congé de maternité ────────────────────────────────────────────────────────────────

def test_premier_enfant_six_semaines_avant_dix_apres():
    plan = calcul.calculer(terme=TERME)
    pre, post = _periode(plan.mere, "maternite_prenatal"), _periode(plan.mere, "maternite_postnatal")
    assert pre.debut == date(2026, 12, 9) and pre.fin == date(2027, 1, 19)
    assert post.debut == TERME and post.fin == date(2027, 3, 30)
    assert pre.jours + post.jours == 16 * 7


def test_troisieme_enfant_huit_semaines_avant_dix_huit_apres():
    plan = calcul.calculer(terme=TERME, situation="rang_3_plus")
    assert _periode(plan.mere, "maternite_prenatal").debut == date(2026, 11, 25)
    assert _periode(plan.mere, "maternite_postnatal").fin == date(2027, 5, 25)


@pytest.mark.parametrize("situation,pre,post", [
    ("rang_1_2", 6, 10), ("rang_3_plus", 8, 18), ("jumeaux", 12, 22), ("triples", 24, 22),
])
def test_durees_officielles_par_situation(situation, pre, post):
    plan = calcul.calculer(terme=TERME, situation=situation)
    assert _periode(plan.mere, "maternite_prenatal").jours == pre * 7
    assert _periode(plan.mere, "maternite_postnatal").jours == post * 7


def test_report_du_prenatal_sur_le_postnatal():
    plan = calcul.calculer(terme=TERME, mere=ParamsMere(report_prenatal_semaines=2))
    assert _periode(plan.mere, "maternite_prenatal").debut == date(2026, 12, 23)
    assert _periode(plan.mere, "maternite_postnatal").fin == date(2027, 4, 13)


def test_report_plafonne_a_trois_semaines():
    plan = calcul.calculer(terme=TERME, mere=ParamsMere(report_prenatal_semaines=5))
    assert _periode(plan.mere, "maternite_prenatal").jours == 3 * 7
    assert any("plafonné" in a.message for a in plan.mere.alertes)


def test_naissance_en_avance_le_prenatal_non_pris_passe_sur_le_postnatal():
    """10 jours d'avance : la fin du congé ne bouge pas, la durée totale est conservée."""
    plan = calcul.calculer(terme=TERME, naissance=date(2027, 1, 10))
    post = _periode(plan.mere, "maternite_postnatal")
    assert _periode(plan.mere, "maternite_prenatal").fin == date(2027, 1, 9)
    assert post.debut == date(2027, 1, 10) and post.fin == date(2027, 3, 30)
    assert post.jours == 70 + 10


def test_naissance_en_retard_le_postnatal_reste_entier():
    plan = calcul.calculer(terme=TERME, naissance=date(2027, 1, 25))
    assert _periode(plan.mere, "maternite_prenatal").fin == date(2027, 1, 24)
    post = _periode(plan.mere, "maternite_postnatal")
    assert post.debut == date(2027, 1, 25) and post.jours == 70


def test_conge_pathologique_prenatal_juste_avant_le_prenatal():
    plan = calcul.calculer(terme=TERME, mere=ParamsMere(patho_prenatal_jours=14))
    patho = _periode(plan.mere, "pathologique_prenatal")
    assert (patho.debut, patho.fin) == (date(2026, 11, 25), date(2026, 12, 8))
    # Il s'ajoute : le prénatal ne raccourcit pas, le postnatal ne s'allonge pas.
    assert _periode(plan.mere, "maternite_prenatal").debut == date(2026, 12, 9)
    assert _periode(plan.mere, "maternite_postnatal").fin == date(2027, 3, 30)


def test_conge_pathologique_postnatal_repousse_le_csn_et_la_reprise():
    m = calcul.calculer(terme=TERME, mere=ParamsMere(patho_postnatal_jours=28, csn_mois=1)).mere
    patho = _periode(m, "pathologique_postnatal")
    assert (patho.debut, patho.fin) == (date(2027, 3, 31), date(2027, 4, 27))
    assert _periode(m, "csn_1").debut == date(2027, 4, 28)
    assert m.reprise == date(2027, 5, 28)
    assert not _bloquants(m)


def test_conges_pathologiques_plafonnes():
    m = calcul.calculer(terme=TERME, mere=ParamsMere(
        patho_prenatal_jours=30, patho_postnatal_jours=60)).mere
    assert _periode(m, "pathologique_prenatal").jours == regles.PATHO_PRENATAL_MAX_JOURS
    assert _periode(m, "pathologique_postnatal").jours == regles.PATHO_POSTNATAL_MAX_JOURS
    assert sum("plafonné" in a.message for a in m.alertes) == 2


def test_prenatal_pathologique_coupe_par_une_naissance_tres_en_avance():
    """Né avant même le prénatal : le pathologique s'arrête la veille de la naissance."""
    m = calcul.calculer(terme=TERME, naissance=date(2026, 12, 1),
                        mere=ParamsMere(patho_prenatal_jours=14)).mere
    assert _periode(m, "pathologique_prenatal").fin == date(2026, 11, 30)


def test_tant_que_la_naissance_n_a_pas_eu_lieu_tout_est_previsionnel():
    assert calcul.calculer(terme=TERME).previsionnel is True
    assert calcul.calculer(terme=TERME, naissance=TERME).previsionnel is False


# ─── Congé de naissance et congé de paternité ──────────────────────────────────────────

def test_co_parent_naissance_obligatoire_puis_solde():
    plan = calcul.calculer(terme=TERME)
    c = plan.coparent
    assert (_periode(c, "naissance").debut, _periode(c, "naissance").fin) == (TERME, date(2027, 1, 22))
    ob = _periode(c, "paternite_obligatoire")
    assert (ob.debut, ob.fin, ob.jours) == (date(2027, 1, 23), date(2027, 1, 26), 4)
    solde = _periode(c, "paternite_solde_1")
    assert (solde.debut, solde.fin, solde.jours) == (date(2027, 1, 27), date(2027, 2, 16), 21)


def test_les_jours_ouvrables_excluent_dimanche_et_ferie_mais_pas_le_samedi():
    """Né le jeudi 24/12/2026 : jeudi 24, (Noël exclu), samedi 26, (dimanche exclu), lundi 28."""
    plan = calcul.calculer(terme=date(2026, 12, 24), naissance=date(2026, 12, 24))
    n = _periode(plan.coparent, "naissance")
    assert (n.debut, n.fin) == (date(2026, 12, 24), date(2026, 12, 28))


def test_naissance_un_dimanche_le_conge_commence_le_lendemain():
    plan = calcul.calculer(terme=date(2027, 1, 17), naissance=date(2027, 1, 17))
    n = _periode(plan.coparent, "naissance")
    assert (n.debut, n.fin) == (date(2027, 1, 18), date(2027, 1, 20))


def test_naissances_multiples_solde_de_28_jours():
    plan = calcul.calculer(terme=TERME, situation="jumeaux")
    assert _periode(plan.coparent, "paternite_solde_1").jours == 28


def test_les_prevenances_d_un_mois():
    """Date présumée ET dates du solde : au moins un mois avant — l'oubli coûte le congé."""
    c = calcul.calculer(terme=TERME).coparent
    assert _echeance(c, "paternite_prevenir_terme").date == date(2026, 12, 20)
    assert _echeance(c, "paternite_preavis_solde_1").date == date(2026, 12, 27)


def test_solde_fractionne_en_deux_periodes():
    c = calcul.calculer(terme=TERME, coparent=ParamsCoparent(
        solde_fractionne=True, solde_jours_1=10, solde_debut_2=date(2027, 4, 1))).coparent
    p1, p2 = _periode(c, "paternite_solde_1"), _periode(c, "paternite_solde_2")
    assert (p1.jours, p2.jours) == (10, 11)
    assert (p2.debut, p2.fin) == (date(2027, 4, 1), date(2027, 4, 11))
    assert not _bloquants(c)


def test_une_periode_de_solde_de_moins_de_cinq_jours_est_refusee():
    c = calcul.calculer(terme=TERME, coparent=ParamsCoparent(
        solde_fractionne=True, solde_jours_1=3)).coparent
    assert _periode(c, "paternite_solde_1").jours == 5
    assert any("au moins 5 jours" in m for m in _bloquants(c))


def test_solde_au_dela_des_six_mois_bloquant():
    c = calcul.calculer(terme=TERME, coparent=ParamsCoparent(solde_debut=date(2027, 8, 1))).coparent
    assert any("6 mois" in m for m in _bloquants(c))


# ─── Congé supplémentaire de naissance ─────────────────────────────────────────────────

def test_csn_de_la_mere_suit_la_maternite_et_se_compte_de_date_a_date():
    m = calcul.calculer(terme=TERME, mere=ParamsMere(csn_mois=2)).mere
    csn = _periode(m, "csn_1")
    assert (csn.debut, csn.fin) == (date(2027, 3, 31), date(2027, 5, 30))
    assert not _bloquants(m)


def test_csn_du_co_parent_suit_le_solde_de_paternite():
    c = calcul.calculer(terme=TERME, coparent=ParamsCoparent(csn_mois=1)).coparent
    csn = _periode(c, "csn_1")
    assert (csn.debut, csn.fin) == (date(2027, 2, 17), date(2027, 3, 16))
    assert c.reprise == date(2027, 3, 17)


def test_csn_ne_peut_pas_chevaucher_le_conge_principal():
    m = calcul.calculer(terme=TERME, mere=ParamsMere(csn_mois=1, csn_debut=date(2027, 3, 1))).mere
    assert any("Il ne peut que le suivre" in msg for msg in _bloquants(m))


def test_csn_exige_d_avoir_pris_toute_la_paternite():
    c = calcul.calculer(terme=TERME, coparent=ParamsCoparent(solde_pris=False, csn_mois=1)).coparent
    assert any("INTÉGRALITÉ" in m for m in _bloquants(c))


def test_csn_doit_debuter_dans_les_neuf_mois():
    c = calcul.calculer(terme=TERME, coparent=ParamsCoparent(
        csn_mois=1, csn_debut=date(2027, 11, 1))).coparent
    assert any("19/10/2027" in m for m in _bloquants(c))


def test_csn_fractionne_deux_fois_un_mois():
    m = calcul.calculer(terme=TERME, mere=ParamsMere(
        csn_mois=2, csn_fractionne=True, csn_debut_2=date(2027, 7, 1))).mere
    p1, p2 = _periode(m, "csn_1"), _periode(m, "csn_2")
    assert (p1.debut, p1.fin) == (date(2027, 3, 31), date(2027, 4, 30))
    assert (p2.debut, p2.fin) == (date(2027, 7, 1), date(2027, 7, 31))
    assert not _bloquants(m)


def test_csn_rappel_de_preavis_un_mois_avant_par_prudence():
    """Le délai légal peut tomber à 15 jours ; le rappel reste à un mois — un rappel en avance
    ne coûte rien, un rappel en retard coûte le congé."""
    c = calcul.calculer(terme=TERME, coparent=ParamsCoparent(csn_mois=1)).coparent
    assert _echeance(c, "csn_preavis_1").date == date(2027, 1, 17)


def test_csn_regime_transitoire_premier_semestre_2026():
    """Né le 15/03/2026 : le délai de 9 mois court à partir du 1ᵉʳ juillet 2026."""
    naissance = date(2026, 3, 15)
    c = calcul.calculer(terme=naissance, naissance=naissance, coparent=ParamsCoparent(
        csn_mois=1, csn_debut=date(2027, 3, 1))).coparent
    assert not _bloquants(c), "le 01/03/2027 est dans le délai transitoire (jusqu'au 31/03/2027)"


def test_csn_enfant_ne_avant_2026_non_concerne():
    naissance = date(2025, 12, 1)
    m = calcul.calculer(terme=naissance, naissance=naissance, mere=ParamsMere(csn_mois=1)).mere
    assert any("1ᵉʳ janvier 2026" in msg for msg in _bloquants(m))
    assert not [p for p in m.periodes if p.cle.startswith("csn")]


def test_regles_datees_et_sourcees():
    """Aucune règle sans date de vérification ni source officielle."""
    assert regles.VERIFIE_LE
    domaines = ("service-public.gouv.fr", "ameli.fr", "legifrance.gouv.fr")
    assert regles.SOURCES and all(any(d in s["url"] for d in domaines) for s in regles.SOURCES)


# ─── L'API et l'agenda ─────────────────────────────────────────────────────────────────

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
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.post("/api/dossiers", json={"titre": "Devenir parent"})
        await c.put("/api/system/config", json={"parents_date_terme": "2027-01-20"})
    return "devenir-parent"


@pytest.mark.asyncio
async def test_sans_terme_le_plan_le_dit_au_lieu_d_etre_vide(client, dossier):
    """
    Sans terme, rien n'est datable. L'écran doit le DIRE : un plan vide se lirait « aucun
    congé », et c'est la lecture la plus coûteuse possible.
    """
    from services import runtime_config

    runtime_config._overrides.pop("parents_date_terme", None)
    async with client as c:
        r = (await c.get(f"/api/dossiers/{dossier}/conges")).json()
        agenda = await c.post(f"/api/dossiers/{dossier}/conges/agenda")
    assert r["plan"] is None and "terme" in r["message"]
    assert agenda.status_code == 400


@pytest.mark.asyncio
async def test_les_parametres_se_fusionnent_par_parent(client, dossier):
    """Régler le co-parent ne doit pas effacer ce qui a été réglé pour la mère."""
    async with client as c:
        await c.put(f"/api/dossiers/{dossier}/conges", json={"mere": {"csn_mois": 2}})
        r = (await c.put(f"/api/dossiers/{dossier}/conges",
                         json={"coparent": {"csn_mois": 1}})).json()
    assert r["parametres"]["mere"]["csn_mois"] == 2
    assert r["parametres"]["coparent"]["csn_mois"] == 1
    assert any(p["cle"] == "csn_1" for p in r["plan"]["mere"]["periodes"])


@pytest.mark.asyncio
async def test_situation_inconnue_refusee(client, dossier):
    async with client as c:
        r = await c.put(f"/api/dossiers/{dossier}/conges", json={"situation": "quintuplés"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_poser_dans_l_agenda_puis_reposer_ne_duplique_pas(client, dossier):
    async with client as c:
        a = (await c.post(f"/api/dossiers/{dossier}/conges/agenda")).json()
        b = (await c.post(f"/api/dossiers/{dossier}/conges/agenda")).json()
        planning = (await c.get(f"/api/dossiers/{dossier}/planning")).json()

    poses = [j for m in planning["mois"] for j in m["jalons"] if j["origine"].startswith("conges:")]
    assert a["crees"] > 0 and b["crees"] == 0 and b["mis_a_jour"] == a["crees"]
    assert len(poses) == a["crees"]
    assert b["agenda"]["a_jour"] is True
    titres = {j["titre"] for j in poses}
    assert "Mère — Congé de maternité — postnatal" in titres
    assert "Co-parent — Congé de naissance" in titres


@pytest.mark.asyncio
async def test_un_changement_de_scenario_rend_l_agenda_perime_puis_le_met_a_jour(client, dossier):
    async with client as c:
        await c.put(f"/api/dossiers/{dossier}/conges", json={"coparent": {"csn_mois": 1}})
        await c.post(f"/api/dossiers/{dossier}/conges/agenda")
        r = (await c.put(f"/api/dossiers/{dossier}/conges",
                         json={"coparent": {"csn_mois": 0}})).json()
        assert r["agenda"]["a_jour"] is False, "l'écran doit dire que l'agenda n'est plus à jour"
        s = (await c.post(f"/api/dossiers/{dossier}/conges/agenda")).json()
    assert s["retires"] == 2        # le congé supplémentaire et son préavis
    assert s["agenda"]["a_jour"] is True


@pytest.mark.asyncio
async def test_un_jalon_coche_fait_n_est_jamais_efface(client, dossier):
    """Le suivi de l'utilisateur ne s'efface pas parce qu'un scénario a changé."""
    async with client as c:
        await c.put(f"/api/dossiers/{dossier}/conges", json={"coparent": {"csn_mois": 1}})
        await c.post(f"/api/dossiers/{dossier}/conges/agenda")
        planning = (await c.get(f"/api/dossiers/{dossier}/planning")).json()
        preavis = next(j for m in planning["mois"] for j in m["jalons"]
                       if j["origine"] == "conges:coparent:csn_preavis_1")
        await c.patch(f"/api/dossiers/jalons/{preavis['id']}", json={"fait": True})

        await c.put(f"/api/dossiers/{dossier}/conges", json={"coparent": {"csn_mois": 0}})
        s = (await c.post(f"/api/dossiers/{dossier}/conges/agenda")).json()
        apres = (await c.get(f"/api/dossiers/{dossier}/planning")).json()

    assert s["retires"] == 1
    assert any(j["id"] == preavis["id"] for m in apres["mois"] for j in m["jalons"])


@pytest.mark.asyncio
async def test_la_date_reelle_de_naissance_deplace_les_jalons(client, dossier):
    async with client as c:
        await c.post(f"/api/dossiers/{dossier}/conges/agenda")
        await c.put(f"/api/dossiers/{dossier}/conges", json={"naissance_reelle": "2027-01-25"})
        await c.post(f"/api/dossiers/{dossier}/conges/agenda")
        planning = (await c.get(f"/api/dossiers/{dossier}/planning")).json()
    naissance = next(j for m in planning["mois"] for j in m["jalons"]
                     if j["origine"] == "conges:coparent:naissance")
    assert naissance["date_reelle"] == "2027-01-25"


def test_le_dossier_devenir_parent_declare_la_capacite_conges():
    from services.dossier_seed import SEEDS
    assert "conges" in SEEDS["devenir-parent"]["modules"]


# ─── Simuler, puis valider par parent et par type ──────────────────────────────────────

def _etat(r, parent, type_):
    return next(g["etat"] for g in r["agenda"]["groupes"]
                if g["parent"] == parent and g["type"] == type_)


@pytest.mark.asyncio
async def test_simuler_n_ecrit_rien_dans_l_agenda(client, dossier):
    """On essaie des scénarios : le planning ne doit pas se remplir d'hypothèses."""
    async with client as c:
        r = (await c.put(f"/api/dossiers/{dossier}/conges", json={"mere": {"csn_mois": 2}})).json()
        planning = (await c.get(f"/api/dossiers/{dossier}/planning")).json()
    assert not [j for m in planning["mois"] for j in m["jalons"] if j["origine"].startswith("conges:")]
    assert all(g["etat"] == "simule" for g in r["agenda"]["groupes"])


@pytest.mark.asyncio
async def test_valider_un_seul_parent_et_un_seul_type(client, dossier):
    """Le congé de maternité se déclare au 6ᵉ mois ; le reste peut attendre."""
    async with client as c:
        await c.put(f"/api/dossiers/{dossier}/conges", json={"coparent": {"csn_mois": 1}})
        r = (await c.post(f"/api/dossiers/{dossier}/conges/agenda",
                          json={"parents": ["mere"], "types": ["maternite"]})).json()
    assert _etat(r, "mere", "maternite") == "valide"
    assert _etat(r, "coparent", "paternite") == "simule"
    assert _etat(r, "coparent", "csn") == "simule"


@pytest.mark.asyncio
async def test_un_groupe_valide_puis_modifie_se_signale(client, dossier):
    async with client as c:
        await c.post(f"/api/dossiers/{dossier}/conges/agenda",
                     json={"parents": ["mere"], "types": ["maternite"]})
        r = (await c.put(f"/api/dossiers/{dossier}/conges",
                         json={"mere": {"report_prenatal_semaines": 2}})).json()
    assert _etat(r, "mere", "maternite") == "modifie"
    assert r["agenda"]["a_jour"] is False


@pytest.mark.asyncio
async def test_retirer_un_type_ne_touche_pas_au_reste(client, dossier):
    async with client as c:
        await c.put(f"/api/dossiers/{dossier}/conges", json={"coparent": {"csn_mois": 1}})
        await c.post(f"/api/dossiers/{dossier}/conges/agenda")
        r = (await c.delete(f"/api/dossiers/{dossier}/conges/agenda?parent=coparent&type=csn")).json()
    assert r["retires"] == 2
    assert _etat(r, "coparent", "csn") == "simule"
    assert _etat(r, "coparent", "paternite") == "valide"
    assert _etat(r, "mere", "maternite") == "valide"


@pytest.mark.asyncio
async def test_le_conge_pathologique_se_valide_a_part_de_la_maternite(client, dossier):
    """Il se décide sur prescription, pas au 6ᵉ mois avec le congé de maternité."""
    async with client as c:
        await c.put(f"/api/dossiers/{dossier}/conges", json={"mere": {"patho_postnatal_jours": 14}})
        r = (await c.post(f"/api/dossiers/{dossier}/conges/agenda",
                          json={"parents": ["mere"], "types": ["maternite"]})).json()
    assert _etat(r, "mere", "maternite") == "valide"
    assert _etat(r, "mere", "pathologique") == "simule"


# ─── Vérification en ligne des règles (sans réseau : pages simulées) ───────────────────

# Extraits des pages officielles, tels que lus le 28/09/2026 (texte normalisé). Si une durée
# de `regles.py` change sans que la loi ait changé, sa phrase témoin ne s'y trouve plus.
EXTRAITS = {
    regles.URL_F2265: (
        "vérifié le 01 juin 2026 durée totale du congé de maternité 1 er enfant 6 semaines "
        "10 semaines 16 semaines 3 e enfant 8 semaines 18 semaines 26 semaines jumeaux "
        "12 semaines 22 semaines 34 semaines triplés 24 semaines 22 semaines 46 semaines. vous "
        "pouvez réduire votre congé prénatal pour une durée maximale de 3 semaines . en cas de "
        "maladie due à votre grossesse ou aux suites de votre accouchement, la durée de votre "
        "congé de maternité est augmentée dans les limites suivantes : 2 semaines avant la date "
        "présumée de l'accouchement, 4 semaines après l'accouchement."),
    regles.URL_F3156: (
        "vérifié le 01 juin 2026 la durée du congé de paternité et d'accueil de l'enfant est de "
        "25 jours calendaires : précédé du congé de naissance d'une durée de 3 jours ouvrables "
        "période obligatoire de 4 jours calendaires période facultative de 21 jours calendaires "
        "période facultative de 28 jours calendaires le congé doit être pris dans les 6 mois "
        "suivant la naissance le salarié doit avertir son employeur au moins 1 mois avant"),
    regles.URL_AMELI_MATERNITE: (
        "le congé pathologique peut vous être prescrit en une fois ou en plusieurs fois, mais "
        "dans la limite de 2 semaines maximum"),
    regles.URL_AMELI_CSN: (
        "le congé supplémentaire de naissance doit débuter dans les 9 mois suivant la naissance"),
}


def test_normaliser_rend_le_texte_visible_comme_il_a_ete_releve():
    from services.conges.verification import normaliser
    page = ("<html><style>p{}</style><p>La durée est <strong>augmentée</strong>&nbsp;: "
            "<b>2 semaines avant</b> la date présumée de l’accouchement</p></html>")
    assert "est augmentée : 2 semaines avant la date présumée de l'accouchement" in normaliser(page)
    assert "p{}" not in normaliser(page)


def test_les_regles_du_code_se_retrouvent_sur_les_pages_officielles():
    from services.conges.verification import controler
    r = controler(EXTRAITS, {})
    manquantes = [c["libelle"] for c in r["controles"] if not c["ok"]]
    assert not manquantes, f"phrases témoins absentes des extraits : {manquantes}"
    assert r["conforme"] is True and len(r["controles"]) == 16


def test_une_phrase_disparue_de_la_page_est_signalee():
    """La loi (ou la page) a changé : 4 semaines devenues 6 après l'accouchement."""
    from services.conges.verification import controler
    textes = {**EXTRAITS, regles.URL_F2265: EXTRAITS[regles.URL_F2265].replace(
        "4 semaines après", "6 semaines après")}
    r = controler(textes, {})
    assert r["conforme"] is False and r["absentes"] == 1
    assert next(c for c in r["controles"] if c["cle"] == "pathologique_postnatal")["ok"] is False


def test_une_page_injoignable_n_est_pas_un_changement_de_loi():
    """Une coupure réseau ne doit pas se lire « la règle a disparu »."""
    from services.conges.verification import controler
    textes = {k: v for k, v in EXTRAITS.items() if k != regles.URL_F3156}
    r = controler(textes, {regles.URL_F3156: "ConnectError : injoignable"})
    assert r["absentes"] == 0 and r["non_verifiees"] == 7
    assert r["conforme"] is False
    page = next(p for p in r["pages"] if p["url"] == regles.URL_F3156)
    assert page["joignable"] is False and "injoignable" in page["erreur"]


def test_une_page_revue_apres_notre_releve_est_a_relire():
    """Toutes nos phrases y sont encore, mais l'administration a revu la page depuis."""
    from services.conges.verification import controler
    textes = {**EXTRAITS, regles.URL_F2265: EXTRAITS[regles.URL_F2265].replace(
        "vérifié le 01 juin 2026", "vérifié le 15 janvier 2027")}
    r = controler(textes, {})
    assert r["absentes"] == 0 and r["pages_revues"] == 1 and r["conforme"] is False
    page = next(p for p in r["pages"] if p["url"] == regles.URL_F2265)
    assert page["verifie_le_page"] == "2027-01-15" and page["revue_depuis"] is True


@pytest.mark.asyncio
async def test_verifier_ne_fait_que_des_get_sans_rien_envoyer():
    """La seule sortie : un GET par page, sans paramètre ni corps."""
    import httpx
    from services.conges.verification import verifier

    vues = []

    def repondre(requete: httpx.Request) -> httpx.Response:
        vues.append(requete)
        return httpx.Response(200, text=f"<p>{EXTRAITS[str(requete.url)]}</p>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(repondre)) as c:
        r = await verifier(c)
    assert r["conforme"] is True
    assert len(vues) == 4, "une seule requête par page, même visée par plusieurs contrôles"
    assert all(v.method == "GET" and not v.url.query and not v.content for v in vues)


@pytest.mark.asyncio
async def test_le_rapport_est_garde_et_affiche_sans_ressortir(client, dossier, monkeypatch):
    """POST vérifie et enregistre ; ouvrir le panneau relit le rapport sans sortir."""
    from services.conges import verification

    async def faux_verifier():
        return verification.controler(EXTRAITS, {})

    monkeypatch.setattr(verification, "verifier", faux_verifier)
    async with client as c:
        assert (await c.get("/api/conges/regles/verification")).json() == {}
        r = (await c.post("/api/conges/regles/verification")).json()
        monkeypatch.setattr(verification, "verifier", None)     # plus aucune sortie possible
        lu = (await c.get("/api/conges/regles/verification")).json()
        panneau = (await c.get(f"/api/dossiers/{dossier}/conges")).json()
    assert r["conforme"] is True and lu == r
    assert panneau["regles"]["controle_en_ligne"]["le"] == r["le"]


@pytest.mark.asyncio
async def test_type_inconnu_refuse(client, dossier):
    async with client as c:
        r = await c.post(f"/api/dossiers/{dossier}/conges/agenda", json={"types": ["rtt"]})
    assert r.status_code == 422
