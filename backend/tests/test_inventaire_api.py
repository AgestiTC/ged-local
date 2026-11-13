"""
Inventaire — API `/api/inventaire/*`, tâches du worker (classe « fond »), tournée de nuit, réglages.

L'API ne voit pas le NAS (montage du worker seul, décision d'architecture n° 5) : elle contrôle les
chemins sur le texte et enfile des tâches. Les tâches sont exécutées ici directement, sur le dépôt
en mémoire (les tables `inv_*` n'existent pas sous SQLite).
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fakes.depot_memoire import DepotMemoire
from sqlalchemy import select

from models.job import Job
from routers import inventaire as routeur
from services import job_worker, runtime_config
from services.rangement import jobs, reglages, service
from services.rangement.erreurs import InventaireRefus
from services.rangement.reglages import ReglagesInventaire


@pytest.fixture
def depot(monkeypatch) -> DepotMemoire:
    d = DepotMemoire()
    monkeypatch.setattr(service, "fabrique", lambda: d)
    return d


@pytest.fixture
def nas(tmp_path, monkeypatch) -> Path:
    r = tmp_path / "nas"
    (r / "Photos" / "2024").mkdir(parents=True)
    (r / "Photos" / "2024" / "a.jpg").write_bytes(b"x" * 30)
    (r / "lisez-moi.txt").write_bytes(b"x" * 5)
    monkeypatch.setitem(runtime_config._overrides, "inventaire_racine_autorisee", r.as_posix())
    return r


# --------------------------------------------------------------------------- #
# Classe « fond » du worker                                                    #
# --------------------------------------------------------------------------- #
def test_les_parcours_ont_leur_propre_classe():
    for t in service.TYPES_JOB:
        assert job_worker.classe_tache(t) == "fond"
        assert t in job_worker._HANDLERS            # enregistrés par l'import de `jobs`
    assert job_worker._budget("fond") == 1
    assert "fond" in job_worker.CLASSES


def test_budget_fond_insensible_aux_reglages_io(monkeypatch):
    monkeypatch.setitem(runtime_config._overrides, "concurrence_io", "6")
    assert job_worker._budget("fond") == 1


# --------------------------------------------------------------------------- #
# Racines : contrôle sur le texte (API)                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("racine,attendu", [
    ("/mnt/media/Photos", "/mnt/media/Photos"),
    ("/mnt/media/Photos/", "/mnt/media/Photos"),
    ("/mnt/media", "/mnt/media"),
    ("/mnt/media//Films/./2024", "/mnt/media/Films/2024"),
])
def test_racine_acceptee(racine, attendu):
    assert service.racine_normalisee(racine, "/mnt/media") == attendu


@pytest.mark.parametrize("racine,code", [
    ("Photos", "racine_relative"),
    ("/mnt/media/../../etc", "racine_invalide"),
    ("/mnt/media-bis/x", "racine_hors_perimetre"),   # préfixe de nom, pas de chemin
    ("/etc", "racine_hors_perimetre"),
    ("/mnt/media\\x", "racine_invalide"),
])
def test_racine_refusee(racine, code):
    with pytest.raises(InventaireRefus) as exc:
        service.racine_normalisee(racine, "/mnt/media")
    assert exc.value.code == code


def test_fichier_d_import_controle_sur_le_texte():
    assert service.chemin_fichier_import("/mnt/media/exports/pc.csv", "/mnt/media") == "/mnt/media/exports/pc.csv"
    for mauvais in ("/mnt/media/x.txt", "/etc/passwd.csv", "/mnt/media/../x.csv"):
        with pytest.raises(InventaireRefus):
            service.chemin_fichier_import(mauvais, "/mnt/media")


# --------------------------------------------------------------------------- #
# Réglages                                                                     #
# --------------------------------------------------------------------------- #
def test_reglages_par_defaut():
    r = reglages.lire()
    assert (r.heure_debut, r.heure_fin, r.intervalle_min) == (1, 6, 60)
    assert r.racine_autorisee == "/mnt/media"


def test_reglage_illisible_retombe_sur_le_defaut(monkeypatch):
    monkeypatch.setitem(runtime_config._overrides, "inventaire_heure_debut", "abc")
    monkeypatch.setitem(runtime_config._overrides, "inventaire_pause_ms", "99999")
    r = reglages.lire()
    assert r.heure_debut == 1 and r.pause_ms == 1000   # défaut, puis borne haute


def test_validation_des_reglages():
    assert reglages.valider({"inventaire_heure_debut": " 22 "}) == {"inventaire_heure_debut": "22"}
    for mauvais in ({"inventaire_heure_debut": "24"}, {"inventaire_heure_debut": "x"},
                    {"inventaire_racine_autorisee": "relatif"}, {"ollama_url": "http://ailleurs"}):
        with pytest.raises(ValueError):
            reglages.valider(mauvais)


# --------------------------------------------------------------------------- #
# Tournée de nuit : quand l'enfiler                                            #
# --------------------------------------------------------------------------- #
UTC = timezone.utc


def _local(heure: int) -> datetime:
    return datetime(2026, 11, 14, heure, 0, tzinfo=UTC)


@pytest.mark.parametrize("heure,derniere_il_y_a_min,intervalle,attendu", [
    (2, None, 60, True),        # dans la fenêtre, jamais faite
    (14, None, 60, False),      # hors fenêtre
    (2, 30, 60, False),         # trop récente
    (2, 61, 60, True),
    (2, None, 0, False),        # scans automatiques coupés
])
def test_tournee_due(heure, derniere_il_y_a_min, intervalle, attendu):
    maintenant = _local(heure)
    derniere = None if derniere_il_y_a_min is None else maintenant - timedelta(minutes=derniere_il_y_a_min)
    r = ReglagesInventaire(intervalle_min=intervalle)
    assert jobs.tournee_due(maintenant, derniere, r, maintenant) is attendu


async def test_planifier_nuit_sans_postgres_ne_fait_rien():
    assert await jobs.planifier_nuit() is None   # tests sous SQLite : pas de tables d'inventaire


# --------------------------------------------------------------------------- #
# Tâche de scan (corps exécuté par le worker)                                  #
# --------------------------------------------------------------------------- #
async def test_tache_de_scan_parcourt_l_emplacement(depot, nas):
    emp = await depot.creer_emplacement("NAS", nas.as_posix())
    scan_id = await service.ouvrir_scan_manuel(depot, emp.id)
    resultat = await jobs.executer_scan(depot, emp.id, scan_id)
    assert resultat["statut"] == "termine" and resultat["scan_id"] == scan_id
    assert resultat["fichiers"] == 2


async def test_tache_de_scan_rouvre_un_scan_clos_entre_temps(depot, nas):
    emp = await depot.creer_emplacement("NAS", nas.as_posix())
    scan_id = await service.ouvrir_scan_manuel(depot, emp.id)
    await service.clore_en_echec(depot, scan_id, "interrompu pour le test")
    resultat = await jobs.executer_scan(depot, emp.id, scan_id)
    assert resultat["statut"] == "termine" and resultat["scan_id"] != scan_id


async def test_tache_de_scan_refuse_une_racine_hors_perimetre(depot, nas, tmp_path, monkeypatch):
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    emp = await depot.creer_emplacement("Ailleurs", ailleurs.as_posix())
    resultat = await jobs.executer_scan(depot, emp.id, None)
    assert resultat["statut"] == "echec" and "racine autorisée" in resultat["message"]


async def test_scan_manuel_refuse_un_emplacement_inactif_ou_de_poste(depot, nas):
    emp = await depot.creer_emplacement("NAS", nas.as_posix())
    await depot.activer_emplacement(emp.id, False)
    with pytest.raises(InventaireRefus):
        await service.ouvrir_scan_manuel(depot, emp.id)
    poste = await depot.creer_poste("PC")
    emp_pc = await depot.creer_emplacement("PC", "C:\\", source="import", poste_id=poste.id)
    with pytest.raises(InventaireRefus):
        await service.ouvrir_scan_manuel(depot, emp_pc.id)


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #
async def test_routes_sans_postgres_repondent_503(client):
    r = await client.get("/api/inventaire/etat")
    assert r.status_code == 503


async def test_declarer_puis_scanner_un_emplacement(client, db_session, depot, nas):
    r = await client.post("/api/inventaire/emplacements",
                          json={"libelle": "Photos", "racine": f"{nas.as_posix()}/Photos/"})
    assert r.status_code == 201, r.text
    emp_id = r.json()["id"]
    assert r.json()["racine"] == f"{nas.as_posix()}/Photos"

    r = await client.post(f"/api/inventaire/emplacements/{emp_id}/scan")
    assert r.status_code == 202, r.text
    corps = r.json()
    job = (await db_session.execute(select(Job).where(Job.type == "inventaire_scan"))).scalar_one()
    assert job.parametres["emplacement_id"] == emp_id and job.parametres["scan_id"] == corps["scan_id"]

    # Un second scan pendant que le premier attend : refusé tout de suite.
    assert (await client.post(f"/api/inventaire/emplacements/{emp_id}/scan")).status_code == 409

    # Le worker exécute la tâche ; la carte se lit ensuite en base.
    await jobs.executer_scan(depot, emp_id, corps["scan_id"])
    r = await client.get(f"/api/inventaire/emplacements/{emp_id}/carte")
    assert r.status_code == 200, r.text
    vue = r.json()
    assert vue["taille"] == 30 and [ligne["nom"] for ligne in vue["lignes"]] == ["2024"]
    assert vue["dernier_scan"]["statut"] == "termine"
    assert (await client.get(f"/api/inventaire/emplacements/{emp_id}/carte",
                             params={"chemin": "Nexiste"})).status_code == 404

    etat = (await client.get("/api/inventaire/etat")).json()
    assert etat["emplacements"][0]["dernier_scan"]["nb_fichiers"] == 1


async def test_declaration_refusee(client, depot, nas):
    racine = nas.as_posix()
    r = await client.post("/api/inventaire/emplacements", json={"libelle": "Etc", "racine": "/etc"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "racine_hors_perimetre"
    assert (await client.post("/api/inventaire/emplacements",
                              json={"libelle": "Tout", "racine": racine})).status_code == 201
    assert (await client.post("/api/inventaire/emplacements",
                              json={"libelle": "Tout", "racine": racine})).status_code == 409
    # Un emplacement DANS un autre est accepté : le parent le saute au scan (cas d'un 2ᵉ NAS monté).
    r = await client.post("/api/inventaire/emplacements", json={"libelle": "Sous", "racine": f"{racine}/Photos"})
    assert r.status_code == 201
    assert (await client.post("/api/inventaire/emplacements",
                              json={"libelle": "  ", "racine": racine})).status_code == 422


async def test_scan_d_un_emplacement_inconnu(client, depot):
    assert (await client.post("/api/inventaire/emplacements/99/scan")).status_code == 404


async def test_desactiver_un_emplacement(client, depot, nas):
    emp_id = (await client.post("/api/inventaire/emplacements",
                                json={"libelle": "NAS", "racine": nas.as_posix()})).json()["id"]
    r = await client.patch(f"/api/inventaire/emplacements/{emp_id}", json={"actif": False})
    assert r.status_code == 200
    assert (await client.post(f"/api/inventaire/emplacements/{emp_id}/scan")).status_code == 400


async def test_import_wiztree_enfile_une_tache(client, db_session, depot, nas):
    r = await client.post("/api/inventaire/imports",
                          json={"nom_pc": "PC-SALON", "chemin": f"{nas.as_posix()}/exports/pc.csv"})
    assert r.status_code == 202, r.text
    job = (await db_session.execute(select(Job).where(Job.type == "inventaire_import"))).scalar_one()
    assert job.parametres["nom_pc"] == "PC-SALON"
    r = await client.post("/api/inventaire/imports", json={"nom_pc": "PC", "chemin": "/etc/passwd.csv"})
    assert r.status_code == 400
    r = await client.post("/api/inventaire/imports", json={"nom_pc": "PC/..", "chemin": f"{nas.as_posix()}/a.csv"})
    assert r.status_code == 400


async def test_reglages_lus_et_ecrits(client, monkeypatch):
    # `set_many` écrit aussi le cache en mémoire : on le rend au test suivant intact.
    monkeypatch.setattr(runtime_config, "_overrides", dict(runtime_config._overrides))
    r = await client.get("/api/inventaire/reglages")
    assert r.status_code == 200 and set(r.json()) == set(reglages.CLES)
    r = await client.put("/api/inventaire/reglages", json={"inventaire_heure_debut": "22",
                                                           "inventaire_heure_fin": "6"})
    assert r.status_code == 200 and r.json()["inventaire_heure_debut"] == "22"
    assert (await client.put("/api/inventaire/reglages", json={"inventaire_heure_fin": "25"})).status_code == 400
    assert (await client.put("/api/inventaire/reglages", json={"ollama_url": "x"})).status_code == 400


def test_le_routeur_ne_lit_jamais_le_disque():
    """Garde-fou : le NAS n'est monté que dans le worker. Le routeur ne doit pas l'interroger."""
    source = Path(routeur.__file__).read_text(encoding="utf-8")
    for interdit in ("os.path.isdir", "os.scandir", "os.path.realpath", "open("):
        assert interdit not in source


async def test_un_autre_nas_monte_dedans_est_son_propre_emplacement(depot, nas):
    """`nas-media` (autre NAS monté dans la médiathèque) : inventorié à part, sauté par le parent,
    et son absence (dossier vide) fait échouer SON scan au lieu de faire disparaître ses fichiers."""
    autre = nas / "nas-media"
    (autre / "Films").mkdir(parents=True)
    (autre / "Films" / "f.mkv").write_bytes(b"x" * 100)
    media = await depot.creer_emplacement("Médiathèque", nas.as_posix())
    nas2 = await depot.creer_emplacement("NAS 2", autre.as_posix())
    r_media = await jobs.executer_scan(depot, media.id, None)
    r_nas2 = await jobs.executer_scan(depot, nas2.id, None)
    assert (r_media["fichiers"], r_nas2["fichiers"]) == (2, 1)   # rien n'est compté deux fois
    assert await depot.dossier(media.id, "nas-media") is None

    # L'autre NAS est éteint : son point de montage apparaît vide.
    (autre / "Films" / "f.mkv").unlink()
    (autre / "Films").rmdir()
    r_nas2 = await jobs.executer_scan(depot, nas2.id, None)
    assert r_nas2["statut"] == "echec" and r_nas2["disparus"] == 0
    assert (await jobs.executer_scan(depot, media.id, None))["disparus"] == 0
