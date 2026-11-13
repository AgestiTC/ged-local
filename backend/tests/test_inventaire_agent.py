"""
Inventaire — agent de poste, côté serveur (étape 5 du plan rangement + mails).

Porté de rangement (`tests/test_agent.py`). Le dépôt en mémoire remplace PostgreSQL ; le « poste »
est simulé par des requêtes HTTP telles que l'agent Go les envoie (JSON gzip, `Authorization:
Bearer mato_…`). Le jeton est un vrai jeton de `jetons_api`, de portée `agent`. La fin d'un envoi
enfile une tâche `inventaire_envoi`, exécutée ici directement.
"""

import gzip
import json
from types import SimpleNamespace

import pytest
from fakes.depot_memoire import DepotMemoire
from sqlalchemy import select

from main import app
from models.auth import JetonApi
from models.job import Job
from routers.auth import admin_identifie
from services import job_worker
from services.rangement import agent, jobs, postes, reglages, service
from services.rangement.erreurs import InventaireRefus

MO = 1024 * 1024
T = 1_712_345_678.5

ARBO = [
    {"chemin": "", "enfants": [["Factures", True, 0, T], ["photo.jpg", False, 2 * MO, T]]},
    {"chemin": "Factures", "enfants": [["edf.pdf", False, 5000, T], ["eau.pdf", False, 3000, T]]},
]


@pytest.fixture
def depot(monkeypatch) -> DepotMemoire:
    d = DepotMemoire()
    monkeypatch.setattr(service, "fabrique", lambda: d)
    return d


@pytest.fixture
async def poste(db_session, depot):
    p, jeton = await postes.creer_poste(db_session, depot, "PC-GAME", "admin", None)
    emp = await agent.declarer_emplacement(depot, p.id, "Documents", r"C:\Users\Thomas")
    return p, jeton, emp


@pytest.fixture
def api(client, poste):
    client.headers.update({"Authorization": f"Bearer {poste[1]}", "X-Agent-Version": "0.1.0"})
    return client


def _lot(dossiers) -> bytes:
    return gzip.compress(json.dumps({"dossiers": dossiers}).encode())


async def _traiter_taches(db_session) -> None:
    """Ce que ferait le worker : exécuter les tâches `inventaire_envoi` en attente."""
    for job in (await db_session.execute(select(Job).where(Job.type == service.JOB_ENVOI,
                                                           Job.statut == "pending"))).scalars().all():
        await jobs._handler_envoi(job_worker.JobContext(str(job.id), job.type, job.parametres, None))
        job.statut = "completed"
    await db_session.commit()


async def _envoyer(api, db_session, emp_id: int, dossiers: list[dict]) -> dict:
    envoi = await api.post("/api/agent/envois", json={"emplacement_id": emp_id})
    assert envoi.status_code == 201, envoi.text
    eid = envoi.json()["envoi_id"]
    r = await api.post(f"/api/agent/envois/{eid}/lots", content=_lot(dossiers),
                       headers={"Content-Encoding": "gzip", "Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    fin = await api.post(f"/api/agent/envois/{eid}/fin")
    assert fin.status_code == 202, fin.text
    await _traiter_taches(db_session)
    return fin.json()


def _presents(depot: DepotMemoire) -> set[str]:
    return {e["chemin"] for e in depot.entrees.values() if e["disparu_scan_id"] is None}


# --------------------------------------------------------------------------- #
# Jetons et postes                                                             #
# --------------------------------------------------------------------------- #
async def test_le_jeton_n_est_garde_qu_en_empreinte(db_session, poste):
    _, clair, _ = poste
    assert clair.startswith("mato_")
    j = (await db_session.execute(select(JetonApi))).scalar_one()
    assert j.portee == "agent" and j.role == "utilisateur" and clair not in j.empreinte and j.expire is not None


async def test_sans_jeton_ou_jeton_faux_401(client, depot, poste):
    assert (await client.get("/api/agent/config")).status_code == 401
    r = await client.get("/api/agent/config", headers={"Authorization": "Bearer mato_faux"})
    assert r.status_code == 401


async def test_jeton_d_automate_ordinaire_refuse(client, db_session, depot, poste):
    jeton, clair = await postes.emettre_jeton(db_session, "x", None, None)
    jeton.portee = "ecriture"
    await db_session.commit()
    r = await client.get("/api/agent/config", headers={"Authorization": f"Bearer {clair}"})
    assert r.status_code == 403


async def test_poste_desactive_refuse(api, depot, poste):
    await depot.activer_poste(poste[0].id, False)
    assert (await api.get("/api/agent/config")).status_code == 403


async def test_contact_et_version_notes(api, depot, poste):
    await api.get("/api/agent/config")
    p = await depot.poste(poste[0].id)
    assert p.dernier_contact is not None and p.version == "0.1.0"


async def test_nouveau_jeton_invalide_l_ancien(api, db_session, depot, poste):
    nouveau = await postes.renouveler_jeton(db_session, depot, poste[0].id, "admin", None)
    assert (await api.get("/api/agent/config")).status_code == 401          # l'ancien est révoqué
    r = await api.get("/api/agent/config", headers={"Authorization": f"Bearer {nouveau}"})
    assert r.status_code == 200


async def test_poste_en_double_sans_jeton_orphelin(db_session, depot, poste):
    with pytest.raises(InventaireRefus):
        await postes.creer_poste(db_session, depot, "pc-game", "admin", None)
    assert len((await db_session.execute(select(JetonApi))).scalars().all()) == 1


@pytest.mark.parametrize("racine", ["\\\\serveur\\partage", "Users", "C:\\Users\\..\\Windows"])
async def test_racine_de_poste_refusee(depot, poste, racine):
    with pytest.raises(InventaireRefus):
        await agent.declarer_emplacement(depot, poste[0].id, "X", racine)


async def test_dossiers_imbriques_refuses_sur_un_meme_poste(depot, poste):
    with pytest.raises(InventaireRefus):
        await agent.declarer_emplacement(depot, poste[0].id, "Tout", "C:\\Users")


# --------------------------------------------------------------------------- #
# Configuration et envois                                                      #
# --------------------------------------------------------------------------- #
async def test_configuration(api, poste):
    cfg = (await api.get("/api/agent/config")).json()
    assert cfg["racines"] == [{"emplacement_id": poste[2].id, "racine": r"C:\Users\Thomas", "inventaire_du": True}]
    assert "@eaDir" in cfg["exclusions_noms"] and cfg["intervalle_min"] == 15


async def test_envoi_complet_puis_inventaire(api, db_session, depot, poste):
    emp = poste[2]
    await _envoyer(api, db_session, emp.id, ARBO)
    scan = await depot.dernier_scan(emp.id)
    assert scan["statut"] == "termine" and scan["declencheur"] == "agent"
    assert scan["nb_fichiers"] == 3 and scan["volume_octets"] == 2 * MO + 8000
    assert (await depot.dossier(emp.id, "Factures")).totaux == (8000, 2, 0)
    assert not depot.envoi_dossiers
    assert (await api.get("/api/agent/config")).json()["racines"][0]["inventaire_du"] is False


async def test_disparition_et_prudence(api, db_session, depot, poste):
    emp = poste[2]
    await _envoyer(api, db_session, emp.id, ARBO)
    await _envoyer(api, db_session, emp.id, [{"chemin": "", "enfants": [["Factures", True, 0, T]]}])
    assert "photo.jpg" not in _presents(depot)
    assert {"Factures/edf.pdf", "Factures/eau.pdf"} <= _presents(depot)   # jamais « disparu » sur un doute


async def test_racine_vide_ne_vide_pas_l_inventaire(api, db_session, depot, poste):
    emp = poste[2]
    await _envoyer(api, db_session, emp.id, ARBO)
    await _envoyer(api, db_session, emp.id, [{"chemin": "", "enfants": []}])
    assert (await depot.dernier_scan(emp.id))["statut"] == "echec"
    assert await depot.a_des_entrees(emp.id)


@pytest.mark.parametrize("dossiers", [
    [{"chemin": "../x", "enfants": []}],
    [{"chemin": "", "enfants": [["a", False, -1, T]]}],
    [{"chemin": "", "enfants": [["a", "non", 1, T]]}],
    [{"chemin": "", "enfants": [["a", False, 1]]}],
    [{"chemin": "", "enfants": [["a", False, True, T]]}],
    "pas une liste",
    [{"chemin": "", "enfants": [["a", False, 10**30, T]]}],
    [{"chemin": "", "enfants": [["a", False, 1, 1e300]]}],
])
async def test_lot_mal_forme_refuse(api, poste, dossiers):
    eid = (await api.post("/api/agent/envois", json={"emplacement_id": poste[2].id})).json()["envoi_id"]
    r = await api.post(f"/api/agent/envois/{eid}/lots", content=json.dumps({"dossiers": dossiers}))
    assert r.status_code == 422


async def test_noms_pieges_ecartes(api, db_session, depot, poste):
    await _envoyer(api, db_session, poste[2].id, [{"chemin": "", "enfants": [
        ["..", True, 0, T], ["a/b", False, 1, T], ["ok.txt", False, 1, T], ["@eaDir", True, 0, T]]}])
    assert {e["chemin"] for e in depot.entrees.values()} == {"ok.txt"}


async def test_bombe_gzip_refusee(api, poste, monkeypatch):
    monkeypatch.setattr(agent, "TAILLE_DECOMPRESSEE_MAX", 1000)
    eid = (await api.post("/api/agent/envois", json={"emplacement_id": poste[2].id})).json()["envoi_id"]
    r = await api.post(f"/api/agent/envois/{eid}/lots", content=gzip.compress(b" " * 100_000),
                       headers={"Content-Encoding": "gzip"})
    assert r.status_code == 413


async def test_lot_trop_gros_refuse_avant_lecture_complete(api, poste, monkeypatch):
    monkeypatch.setattr(agent, "TAILLE_LOT_RECU_MAX", 1000)
    eid = (await api.post("/api/agent/envois", json={"emplacement_id": poste[2].id})).json()["envoi_id"]
    r = await api.post(f"/api/agent/envois/{eid}/lots", content=b"x" * 5000)
    assert r.status_code == 413


async def test_un_poste_ne_touche_pas_aux_emplacements_d_un_autre(client, db_session, depot, poste):
    _, jeton_autre = await postes.creer_poste(db_session, depot, "PORTABLE", "admin", None)
    proprio = {"Authorization": f"Bearer {poste[1]}"}
    intrus = {"Authorization": f"Bearer {jeton_autre}"}
    eid = (await client.post("/api/agent/envois", json={"emplacement_id": poste[2].id},
                             headers=proprio)).json()["envoi_id"]
    assert (await client.post("/api/agent/envois", json={"emplacement_id": poste[2].id},
                              headers=intrus)).status_code == 404
    assert (await client.post(f"/api/agent/envois/{eid}/lots", content=_lot(ARBO), headers=intrus)).status_code == 404
    assert (await client.post(f"/api/agent/envois/{eid}/fin", headers=intrus)).status_code == 404


async def test_emplacement_du_serveur_refuse_a_l_agent(api, depot, tmp_path):
    nas = await depot.creer_emplacement("NAS", str(tmp_path))
    assert (await api.post("/api/agent/envois", json={"emplacement_id": nas.id})).status_code == 404


async def test_nouvel_envoi_abandonne_le_precedent(api, depot, poste):
    emp = poste[2]
    e1 = (await api.post("/api/agent/envois", json={"emplacement_id": emp.id})).json()["envoi_id"]
    await api.post(f"/api/agent/envois/{e1}/lots", content=_lot(ARBO), headers={"Content-Encoding": "gzip"})
    e2 = (await api.post("/api/agent/envois", json={"emplacement_id": emp.id})).json()["envoi_id"]
    assert (await depot.envoi(e1))["statut"] == "abandonne"
    assert (await api.post(f"/api/agent/envois/{e1}/fin")).status_code == 409
    assert e2 != e1


async def test_envoi_termine_ne_se_rouvre_pas(api, db_session, poste):
    eid = (await api.post("/api/agent/envois", json={"emplacement_id": poste[2].id})).json()["envoi_id"]
    await api.post(f"/api/agent/envois/{eid}/lots", content=_lot(ARBO), headers={"Content-Encoding": "gzip"})
    await api.post(f"/api/agent/envois/{eid}/fin")
    assert (await api.post(f"/api/agent/envois/{eid}/lots", content=_lot(ARBO))).status_code == 409


async def test_scan_manuel_d_un_emplacement_de_poste_refuse(depot, poste):
    with pytest.raises(InventaireRefus):
        await service.ouvrir_scan_manuel(depot, poste[2].id)


# --------------------------------------------------------------------------- #
# Empreintes : copies entre le PC et le NAS                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture
async def pc_et_nas(api, db_session, depot, poste, tmp_path):
    """Une vidéo de 2 Mo présente sur le NAS (scannée) et sur le PC (envoyée par l'agent)."""
    from services.rangement.exclusions import Exclusions
    from services.rangement.scan import Scanner
    video = tmp_path / "nas" / "video.mp4"
    video.parent.mkdir()
    video.write_bytes(b"v" * (2 * MO))
    nas = await depot.creer_emplacement("NAS", str(video.parent))
    await Scanner(depot, nas, Exclusions()).executer()
    await _envoyer(api, db_session, poste[2].id, [{"chemin": "", "enfants": [["video.mp4", False, 2 * MO, T]]}])
    return nas


def _resultat(demande: dict, **kw) -> dict:
    return {"id": demande["id"], "taille": demande["taille"], "mtime": demande["mtime"],
            "partielle": "ab" * 32, "complete": None, "octets_lus": 2 * 64 * 1024, **kw}


async def test_empreintes_demandees_puis_retenues(api, depot, poste, pc_et_nas):
    demandes = (await api.get("/api/agent/empreintes")).json()["demandes"]
    assert [d["chemin"] for d in demandes] == ["video.mp4"] and demandes[0]["emplacement_id"] == poste[2].id
    r = await api.post("/api/agent/empreintes", json={"resultats": [_resultat(demandes[0])]})
    assert r.json()["retenus"] == 1
    assert (await depot.poste(poste[0].id)).lecture_octets == 2 * 64 * 1024


async def test_empreinte_d_un_fichier_change_ou_mal_formee_ignoree(api, pc_et_nas):
    d = (await api.get("/api/agent/empreintes")).json()["demandes"][0]
    for faux in (_resultat(d, mtime=d["mtime"] + 10), _resultat(d, partielle="zz"), _resultat(d, taille=1)):
        assert (await api.post("/api/agent/empreintes", json={"resultats": [faux]})).json()["retenus"] == 0


async def test_empreinte_d_un_autre_poste_ignoree(client, db_session, depot, pc_et_nas, api):
    d = (await api.get("/api/agent/empreintes")).json()["demandes"][0]
    _, jeton_autre = await postes.creer_poste(db_session, depot, "PORTABLE", "admin", None)
    r = await client.post("/api/agent/empreintes", json={"resultats": [_resultat(d)]},
                          headers={"Authorization": f"Bearer {jeton_autre}"})
    assert r.json()["retenus"] == 0


async def test_limite_de_lecture_du_jour(api, depot, poste, pc_et_nas, monkeypatch):
    monkeypatch.setattr(reglages, "lire_agent", lambda: reglages.ReglagesAgent(lecture_max_jour=100 * 1024))
    await depot.compter_lecture_poste(poste[0].id, service.maintenant_local().date(), 50 * 1024)
    r = (await api.get("/api/agent/empreintes")).json()
    assert r["demandes"] == [] and r["octets_permis"] == 50 * 1024


# --------------------------------------------------------------------------- #
# Routes d'administration des postes                                           #
# --------------------------------------------------------------------------- #
@pytest.fixture
def admin():
    app.dependency_overrides[admin_identifie] = lambda: SimpleNamespace(id=None, identifiant="tclement")
    yield
    app.dependency_overrides.pop(admin_identifie, None)


async def test_ajouter_un_poste_montre_le_jeton_une_fois(client, depot, admin):
    r = await client.post("/api/inventaire/postes", json={"nom": "PORTABLE"})
    assert r.status_code == 201, r.text
    assert r.json()["jeton_clair"].startswith("mato_")
    liste = (await client.get("/api/inventaire/postes")).json()["postes"]
    assert liste[0]["nom"] == "PORTABLE" and liste[0]["jeton"] is True and "jeton_clair" not in liste[0]
    assert (await client.post("/api/inventaire/postes", json={"nom": "portable"})).status_code == 409
    assert (await client.post("/api/inventaire/postes", json={"nom": "PC/../x"})).status_code == 400


async def test_confier_un_dossier_puis_renouveler_et_desactiver(client, depot, admin):
    pid = (await client.post("/api/inventaire/postes", json={"nom": "PORTABLE"})).json()["id"]
    r = await client.post(f"/api/inventaire/postes/{pid}/emplacements",
                          json={"libelle": "Documents", "racine": "C:\\Users\\Thomas"})
    assert r.status_code == 201 and r.json()["racine"] == "C:\\Users\\Thomas"
    assert (await client.post(f"/api/inventaire/postes/{pid}/emplacements",
                              json={"libelle": "X", "racine": "\\\\nas\\x"})).status_code == 400
    r = await client.post(f"/api/inventaire/postes/{pid}/jeton")
    assert r.status_code == 200 and r.json()["jeton_clair"].startswith("mato_")
    assert (await client.patch(f"/api/inventaire/postes/{pid}", json={"actif": False})).status_code == 200
    assert (await depot.poste(pid)).actif is False
    assert (await client.post("/api/inventaire/postes/99/jeton")).status_code == 404


async def test_emission_de_jeton_exige_une_identite_admin(client, depot):
    """Sans session d'administrateur, pas de jeton émis — même authentification éteinte."""
    assert (await client.post("/api/inventaire/postes", json={"nom": "PORTABLE"})).status_code == 401
