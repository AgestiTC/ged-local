"""
Cloche du Rangement (plan rangement + mails, étape 11) — `services/notifier.py`, la route de la cloche
et `services/rangement/alertes.py`. Données fictives, aucun appel réseau.

Critères d'acceptation :
  - un fichier déposé hors plan dans le bac à sable apparaît dans la cloche le jour même, avec une
    proposition ;
  - les préférences d'un utilisateur ne touchent pas celles d'un autre.
"""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from fakes.depot_memoire import DepotMemoire
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from models.auth import SessionAuth, Utilisateur
from models.job import Job
from models.notification import POSTE_LOCAL, Notification, NotificationPreference
from models.plan_classement import PlanProposition
from services import notifier, oidc_service, runtime_config
from services.notifier import Evenement
from services.rangement import alertes, plan, service
from services.rangement.exclusions import Exclusions
from services.rangement.scan import Scanner

PARIS = ZoneInfo("Europe/Paris")
ISSUER = "https://sso.test.invalid/webman/sso"
SYNC = {"Sec-Fetch-Site": "same-origin"}


def _pref(**kw) -> NotificationPreference:
    base = dict(utilisateur_id=POSTE_LOCAL, alertes={}, seuil_disque_pct=80, seuil_croissance_pct=50,
                seuil_croissance_gio=5, silence_debut=None, silence_fin=None)
    return NotificationPreference(**(base | kw))


def _ev(type_="rangement_taches", cle="k", **kw) -> Evenement:
    return Evenement(type=type_, cle=cle, titre=kw.pop("titre", "titre"), contenu="contenu", **kw)


# --------------------------------------------------------------------------- #
# Règles PURES                                                                 #
# --------------------------------------------------------------------------- #
class TestPur:
    def test_heures_de_silence_qui_passent_minuit(self):
        p = _pref(silence_debut="22:00", silence_fin="07:00")
        fin = notifier.fin_de_silence(p, datetime(2026, 11, 14, 23, 30, tzinfo=PARIS))
        assert fin == datetime(2026, 11, 15, 7, 0, tzinfo=PARIS).astimezone(timezone.utc)
        assert notifier.fin_de_silence(p, datetime(2026, 11, 14, 6, 0, tzinfo=PARIS)) == \
            datetime(2026, 11, 14, 7, 0, tzinfo=PARIS).astimezone(timezone.utc)
        assert notifier.fin_de_silence(p, datetime(2026, 11, 14, 12, 0, tzinfo=PARIS)) is None

    def test_heures_de_silence_dans_la_journee_ou_absentes(self):
        p = _pref(silence_debut="12:00", silence_fin="14:00")
        assert notifier.fin_de_silence(p, datetime(2026, 11, 14, 13, 0, tzinfo=PARIS)) is not None
        assert notifier.fin_de_silence(p, datetime(2026, 11, 14, 14, 0, tzinfo=PARIS)) is None
        assert notifier.fin_de_silence(_pref(), datetime(2026, 11, 14, 13, 0, tzinfo=PARIS)) is None

    def test_seuils(self):
        p = _pref(seuil_disque_pct=85)
        assert not notifier.accepte(p, _ev("rangement_disque", mesures={"pct": 84.9}))
        assert notifier.accepte(p, _ev("rangement_disque", mesures={"pct": 85}))
        gio = 1024 ** 3
        assert not notifier.accepte(p, _ev("rangement_croissance", mesures={"pct": 80, "octets": 4 * gio}))
        assert notifier.accepte(p, _ev("rangement_croissance", mesures={"pct": 80, "octets": 6 * gio}))
        assert not notifier.accepte(p, _ev("rangement_croissance", mesures={"pct": 20, "octets": 60 * gio}))

    def test_alerte_coupee(self):
        assert notifier.accepte(_pref(), _ev())
        assert not notifier.accepte(_pref(alertes={"rangement_taches": False}), _ev())

    def test_croissances(self):
        r = alertes.croissances({"A": 300, "B": 100, "B/x": 900, "C": 50, "D": 10},
                                {"A": 100, "B": 99, "B/x": 1, "C": 60, "D": 0})
        assert [c[0] for c in r] == ["A", "D"]          # B : +1 %, sous le plancher ; B/x : pas 1er niveau
        assert r[0] == ("A", 200, 200.0) and r[1][2] == 1000.0

    def test_doublons_seulement_s_il_y_en_a_de_nouveaux(self):
        assert alertes.evenement_doublons({"nb_groupes": 3}, {"nb_groupes": 3, "recuperable": 9}) is None
        assert alertes.evenement_doublons(None, {"nb_groupes": 3}) is None
        ev = alertes.evenement_doublons({"nb_groupes": 3}, {"nb_groupes": 5, "recuperable": 2048})
        assert ev.cle == "doublons" and "2 nouveau" in ev.titre

    def test_fin_de_tache(self):
        assert alertes.evenement_tache("inventaire_nuit", "j", "completed", {}, None) is None
        assert alertes.evenement_tache("inventaire_scan", "j", "completed", {"statut": "termine"}, None) is None
        ev = alertes.evenement_tache("inventaire_nuit", "j", "failed", None, "OSError: NAS absent")
        assert ev.titre.startswith("⚠️") and "NAS absent" in ev.contenu
        ev = alertes.evenement_tache("rangement_appliquer", "j", "completed", {"statut": "range", "message": "3 éléments"}, None)
        assert "rangé" in ev.titre and ev.lien == alertes.LIEN_PLAN
        ev = alertes.evenement_tache("rangement_appliquer", "j", "completed", {"statut": "refuse", "message": "lecture seule"}, None)
        assert "échec" in ev.titre
        assert alertes.evenement_tache("indexation", "j", "failed", None, "x") is None


# --------------------------------------------------------------------------- #
# Écriture : destinataires, préférences, dédoublonnage                         #
# --------------------------------------------------------------------------- #
@pytest.fixture
def auth_on():
    runtime_config._overrides.update({"auth_active": "true", "oidc_issuer": ISSUER,
                                      "oidc_client_id": "matotheque-test",
                                      "oidc_redirect_uri": "https://ged.test.invalid/api/auth/callback"})


async def _personne(db, role="admin", ident=None) -> Utilisateur:
    ident = ident or f"{role}-{uuid.uuid4().hex[:8]}"
    u = Utilisateur(emetteur=oidc_service.emetteur_configure(), sub=f"sub-{ident}", role=role, identifiant=ident)
    db.add(u)
    await db.commit()
    return u


async def _lignes(db) -> list[Notification]:
    return list((await db.execute(select(Notification).order_by(Notification.created_at))).scalars().all())


MIDI = datetime(2026, 11, 14, 12, 0, tzinfo=PARIS)


async def test_auth_eteinte_une_seule_ligne_reservee_aux_admins(db_session):
    assert await notifier.notifier(db_session, _ev(), maintenant_local=MIDI) == 1
    await db_session.commit()
    [n] = await _lignes(db_session)
    assert n.utilisateur_id is None and n.pour_role == "admin" and n.visible_le is None


async def test_meme_cle_non_lue_remplacee_puis_nouvelle_une_fois_lue(db_session):
    await notifier.notifier(db_session, _ev(titre="v1"), maintenant_local=MIDI)
    await notifier.notifier(db_session, _ev(titre="v2"), maintenant_local=MIDI)
    await db_session.commit()
    [n] = await _lignes(db_session)
    assert n.titre == "v2"
    n.lu = True
    await db_session.commit()
    await notifier.notifier(db_session, _ev(titre="v3"), maintenant_local=MIDI)
    await db_session.commit()
    assert [x.titre for x in await _lignes(db_session)] == ["v2", "v3"]


async def test_les_preferences_de_l_un_ne_touchent_pas_l_autre(db_session, auth_on):
    a = await _personne(db_session, "admin")
    b = await _personne(db_session, "admin")
    await _personne(db_session, "utilisateur")          # jamais destinataire d'une alerte du Rangement
    db_session.add(NotificationPreference(utilisateur_id=a.id, alertes={"rangement_taches": False}))
    db_session.add(NotificationPreference(utilisateur_id=b.id, alertes={}, silence_debut="11:00", silence_fin="13:00"))
    await db_session.commit()
    assert await notifier.notifier(db_session, _ev(), maintenant_local=MIDI) == 1
    await notifier.notifier(db_session, _ev("rangement_doublons", cle="d"), maintenant_local=MIDI)
    await db_session.commit()
    lignes = await _lignes(db_session)
    assert {(n.utilisateur_id, n.type) for n in lignes} == {
        (b.id, "rangement_taches"), (a.id, "rangement_doublons"), (b.id, "rangement_doublons")}
    # B est dans ses heures de silence : écrite, mais masquée jusqu'à 13 h ; A n'en a pas.
    assert all(n.visible_le is not None for n in lignes if n.utilisateur_id == b.id)
    assert all(n.visible_le is None for n in lignes if n.utilisateur_id == a.id)


async def test_la_tache_va_a_qui_l_a_lancee(db_session, auth_on):
    a = await _personne(db_session, "admin", "tclement")
    await _personne(db_session, "admin")
    await notifier.notifier(db_session, _ev(), proprietaire="tclement", maintenant_local=MIDI)
    await db_session.commit()
    assert [n.utilisateur_id for n in await _lignes(db_session)] == [a.id]


# --------------------------------------------------------------------------- #
# Lecture par la route                                                         #
# --------------------------------------------------------------------------- #
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


async def _cookie(db, u: Utilisateur) -> dict:
    now = datetime.now(timezone.utc)
    jeton = f"cookie-{u.identifiant}"
    db.add(SessionAuth(id=oidc_service.hacher_jeton(jeton), utilisateur_id=u.id, creee=now,
                       derniere_activite=now, expire_max=now + timedelta(days=1)))
    await db.commit()
    return {"Cookie": f"matotheque_session={jeton}", **SYNC}


async def test_chacun_ne_voit_que_ce_qui_lui_est_adresse(client, db_session, auth_on):
    a = await _personne(db_session, "admin")
    b = await _personne(db_session, "admin")
    u = await _personne(db_session, "utilisateur")
    db_session.add_all([
        Notification(type="idees_evolution", titre="pour tous", contenu=""),
        Notification(type="rangement_disque", titre="admins (auth éteinte)", contenu="", pour_role="admin"),
        Notification(type="rangement_taches", titre="à A", contenu="", utilisateur_id=a.id, pour_role="admin"),
        Notification(type="rangement_taches", titre="à B", contenu="", utilisateur_id=b.id, pour_role="admin"),
        Notification(type="rangement_taches", titre="à A plus tard", contenu="", utilisateur_id=a.id,
                     visible_le=datetime.now(timezone.utc) + timedelta(hours=2)),
    ])
    await db_session.commit()
    ca, cu = await _cookie(db_session, a), await _cookie(db_session, u)

    r = await client.get("/api/notifications", headers=ca)
    assert r.status_code == 200
    assert {n["titre"] for n in r.json()["notifications"]} == {"pour tous", "admins (auth éteinte)", "à A"}
    assert r.json()["non_lues"] == 3

    r = await client.get("/api/notifications", headers=cu)
    assert {n["titre"] for n in r.json()["notifications"]} == {"pour tous"}

    # Personne ne lit ni ne supprime celle de B à sa place, même par son identifiant.
    id_b = (await db_session.execute(select(Notification.id).where(Notification.titre == "à B"))).scalar()
    assert (await client.post(f"/api/notifications/{id_b}/lu", headers=cu)).status_code == 404
    assert (await client.delete(f"/api/notifications/{id_b}", headers=ca)).status_code == 404
    # « Tout lire » ne touche que les siennes.
    assert (await client.post("/api/notifications/lu-tout", headers=ca)).status_code == 200
    await db_session.commit()
    lu_b = (await db_session.execute(select(Notification.lu).where(Notification.titre == "à B"))).scalar()
    assert lu_b is False


async def test_preferences_par_personne(client, db_session, auth_on):
    a = await _personne(db_session, "admin")
    u = await _personne(db_session, "utilisateur")
    ca, cu = await _cookie(db_session, a), await _cookie(db_session, u)

    r = await client.get("/api/notifications/preferences", headers=ca)
    assert r.status_code == 200 and r.json()["seuil_disque_pct"] == 80
    assert {x["type"] for x in r.json()["alertes"]} == set(notifier.TYPES)
    corps = {"alertes": {"rangement_disque": False}, "seuil_disque_pct": 90, "seuil_croissance_pct": 50,
             "seuil_croissance_gio": 5, "silence_debut": "22:00", "silence_fin": "07:00"}
    r = await client.put("/api/notifications/preferences", json=corps, headers=ca)
    assert r.status_code == 200 and r.json()["seuil_disque_pct"] == 90
    assert next(x for x in r.json()["alertes"] if x["type"] == "rangement_disque")["active"] is False

    # Un utilisateur n'a pas les alertes du Rangement, et ne peut pas les régler.
    r = await client.get("/api/notifications/preferences", headers=cu)
    assert r.json()["alertes"] == [] and r.json()["seuil_disque_pct"] == 80   # celles de A ne le touchent pas
    r = await client.put("/api/notifications/preferences", json=corps, headers=cu)
    assert r.status_code == 403

    r = await client.put("/api/notifications/preferences", json=corps | {"silence_fin": "25:00"}, headers=ca)
    assert r.status_code == 422
    r = await client.put("/api/notifications/preferences", json=corps | {"silence_fin": None}, headers=ca)
    assert r.status_code == 422


async def test_preferences_du_poste_local_auth_eteinte(client):
    r = await client.put("/api/notifications/preferences", json={"seuil_disque_pct": 70}, headers=SYNC)
    assert r.status_code == 200 and r.json()["seuil_disque_pct"] == 70
    assert (await client.get("/api/notifications/preferences")).json()["seuil_disque_pct"] == 70


# --------------------------------------------------------------------------- #
# Acceptation : hors plan dans le bac à sable, le jour même, avec proposition  #
# --------------------------------------------------------------------------- #
def _ecrire(p: Path, n: int = 10) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * n)


@pytest.fixture
def depot(monkeypatch) -> DepotMemoire:
    d = DepotMemoire()
    monkeypatch.setattr(service, "fabrique", lambda: d)
    return d


async def test_un_fichier_depose_hors_plan_arrive_dans_la_cloche_avec_sa_proposition(db_session, depot, tmp_path):
    bac = tmp_path / "media"
    _ecrire(bac / "Films" / "Le Film (2020)" / "film.mkv", 500)
    _ecrire(bac / "Ebook" / "livre.epub", 50)
    emp = await depot.creer_emplacement("Bac à sable", str(bac).replace("\\", "/"))
    await Scanner(depot, emp, Exclusions()).executer()
    await plan.charger_modele_media(db_session, depot, emp)
    await plan.calculer(db_session, depot, emp, ia=None)
    # Sans IA, le film déjà rangé dans « Films » reste sans proposition : il n'est pas hors plan pour autant.
    assert await alertes.signaler_hors_plan(db_session, emp) == 0     # rien de mal placé au départ
    await db_session.commit()

    # Le dépôt du jour : un livre posé à la racine du partage.
    _ecrire(bac / "roman.epub", 40)
    await Scanner(depot, emp, Exclusions()).executer()
    assert await plan.nouveaux_elements(db_session, depot, emp) == ["roman.epub"]

    # Après le scan : un calcul limité aux nouveaux est enfilé (une seule fois).
    await alertes.apres_scan(db_session, depot, emp)
    await alertes.apres_scan(db_session, depot, emp)
    await db_session.commit()
    # Les règles TOUT DE SUITE (hors plage), l'IA dans sa plage — chacune une seule fois.
    jobs = (await db_session.execute(select(Job))).scalars().all()
    assert sorted(j.type for j in jobs) == ["plan_propositions", "plan_regles"]
    assert all(j.parametres["nouveaux_seulement"] is True for j in jobs)

    # Le worker le calcule (sans IA ici : la règle des livres suffit), puis la cloche le signale.
    avant = {p.chemin: p.calcule_le for p in (await db_session.execute(select(PlanProposition))).scalars().all()}
    r = await plan.calculer(db_session, depot, emp, ia=None, nouveaux_seulement=True)
    assert r["retirees"] == 0
    apres = {p.chemin: p.calcule_le for p in (await db_session.execute(select(PlanProposition))).scalars().all()}
    assert {c: apres[c] for c in avant} == avant                      # les anciennes n'ont pas été recalculées
    assert await alertes.signaler_hors_plan(db_session, emp) == 1
    await db_session.commit()
    [n] = await _lignes(db_session)
    assert n.type == "rangement_hors_plan" and "`roman.epub` → irait dans **Ebook**" in n.contenu
    assert n.lien == "/rangement?onglet=plan"
    # Signalé une fois : un second passage n'ajoute rien.
    assert await alertes.signaler_hors_plan(db_session, emp) == 0
