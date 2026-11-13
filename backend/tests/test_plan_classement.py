"""
Plan de classement (Rangement, étape 9) — modèle de départ, règles, IA, propositions, décisions.

Sur un faux partage `media` (dossier temporaire) scanné dans le dépôt en mémoire, et une IA simulée.
Critère d'acceptation : pour chaque grand dossier de la carte, l'outil dit où il irait ; rien n'est
appliqué sans validation (et rien n'est déplacé du tout : c'est l'étape 10).
"""

from pathlib import Path

import pytest
from fakes.depot_memoire import DepotMemoire
from sqlalchemy import select

from models.job import Job
from models.plan_classement import PlanNoeud, PlanProposition, PlanRegle
from services.rangement import plan, service
from services.rangement.exclusions import Exclusions
from services.rangement.scan import Scanner


def _ecrire(p: Path, n: int = 10) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * n)


@pytest.fixture
def depot(monkeypatch) -> DepotMemoire:
    d = DepotMemoire()
    monkeypatch.setattr(service, "fabrique", lambda: d)
    return d


@pytest.fixture
async def media(tmp_path, depot):
    r = tmp_path / "media"
    _ecrire(r / "Films" / "Le Film (2020)" / "film.mkv", 500)
    _ecrire(r / "Films" / "Breaking.Bad.S01E01.mkv", 300)          # mal placé : un épisode dans Films
    _ecrire(r / "Series" / "Dark" / "S01" / "e1.mkv", 400)
    _ecrire(r / "Ebook" / "livre.epub", 50)
    _ecrire(r / "01_Liste" / "notes.txt", 5)                       # C6 : à ranger, pas une rubrique
    _ecrire(r / "roman.epub", 40)                                  # fichier isolé à la racine
    _ecrire(r / "installeur.exe", 70)
    _ecrire(r / "Concert" / "live.mkv", 600)                       # rien ne le place : l'IA
    _ecrire(r / "nas-media" / "x.mkv", 10)                         # un autre emplacement (autre NAS)
    emp = await depot.creer_emplacement("Médiathèque", str(r).replace("\\", "/"))
    nas2 = await depot.creer_emplacement("NAS 2", str(r / "nas-media").replace("\\", "/"))
    await Scanner(depot, emp, Exclusions()).executer()
    return emp, nas2


async def _ia_films(c, noeuds):
    """IA simulée : envoie tout dans Films (et dit pourquoi)."""
    return "Films", "ressemble à un film", 0.7


def _props(db_session):
    async def lire():
        return {p.chemin: p for p in (await db_session.execute(select(PlanProposition))).scalars().all()}
    return lire


def test_partage_d_un_emplacement():
    from services.rangement.depot import Emplacement
    assert plan.partage_de(Emplacement(1, "M", "/mnt/media")) == "media"
    assert plan.partage_de(Emplacement(2, "M", "/mnt/media/nas-media/")) == "nas-media"
    assert plan.partage_de(Emplacement(3, "PC", "C:\\Users", source="agent", poste_id=1)) is None


async def test_modele_de_depart_de_media(db_session, depot, media):
    emp, _ = media
    r = await plan.charger_modele_media(db_session, depot, emp)
    noeuds = {n.chemin: n for n in (await db_session.execute(select(PlanNoeud))).scalars().all()}
    # 1er niveau verrouillé (Plex) + 00-A-TRIER ; ni 01_Liste (C6), ni l'autre NAS.
    assert set(noeuds) == {"00-A-TRIER", "Films", "Series", "Ebook", "Concert"}
    assert noeuds["Films"].verrouille and not noeuds["00-A-TRIER"].verrouille
    regles = (await db_session.execute(select(PlanRegle))).scalars().all()
    assert len(regles) == 3 and all(x.active for x in regles)
    # Idempotent.
    assert (await plan.charger_modele_media(db_session, depot, emp))["noeuds_crees"] == 0 == \
        (await plan.charger_modele_media(db_session, depot, emp))["regles_creees"]
    assert r["partage"] == "media"


async def test_chaque_grand_dossier_dit_ou_il_irait(db_session, depot, media):
    emp, _ = media
    await plan.charger_modele_media(db_session, depot, emp)
    r = await plan.calculer(db_session, depot, emp, ia=_ia_films)
    props = await _props(db_session)()
    # Règles d'abord.
    assert props["Films/Breaking.Bad.S01E01.mkv"].destination == "Series"
    assert props["Films/Breaking.Bad.S01E01.mkv"].par == "regle" and props["Films/Breaking.Bad.S01E01.mkv"].statut == "proposee"
    assert props["roman.epub"].destination == "Ebook"
    assert props["installeur.exe"].destination == "00-A-TRIER"
    # Déjà au bon endroit.
    assert props["Films/Le Film (2020)"].statut == "en_place"
    # L'IA pour le reste, avec sa raison.
    assert props["01_Liste"].par == "ia" and props["01_Liste"].raison == "ressemble à un film"
    # L'autre NAS n'est jamais candidat ; chaque grand dossier a une réponse.
    assert "nas-media" not in props
    assert all(p.destination for p in props.values())
    assert r["statut"] == "termine" and r["ia"] >= 1


async def test_sans_ia_ce_qu_aucune_regle_ne_place_reste_sans_place(db_session, depot, media):
    emp, _ = media
    await plan.charger_modele_media(db_session, depot, emp)
    await plan.calculer(db_session, depot, emp, ia=None)
    props = await _props(db_session)()
    assert props["01_Liste"].statut == "sans_place" and props["01_Liste"].destination is None


async def test_une_reponse_de_l_ia_hors_du_plan_est_ecartee(db_session, depot, media):
    emp, _ = media
    await plan.charger_modele_media(db_session, depot, emp)

    async def ia_folle(c, noeuds):
        return None, "réponse de l'IA hors du plan : « /etc »", 0.0

    await plan.calculer(db_session, depot, emp, ia=ia_folle)
    assert (await _props(db_session)())["01_Liste"].statut == "sans_place"


async def test_une_decision_humaine_est_gardee_tant_que_le_dossier_ne_change_pas(db_session, depot, media, tmp_path):
    emp, _ = media
    await plan.charger_modele_media(db_session, depot, emp)
    await plan.calculer(db_session, depot, emp, ia=_ia_films)
    p = (await _props(db_session)())["01_Liste"]
    await plan.decider(db_session, p, "validee", "tclement", "00-A-TRIER")
    assert p.statut == "validee" and p.destination == "00-A-TRIER" and p.par == "humain"
    await plan.calculer(db_session, depot, emp, ia=_ia_films)
    p = (await _props(db_session)())["01_Liste"]
    assert p.statut == "validee" and p.destination == "00-A-TRIER"
    # Le dossier grossit : la décision ne valait que pour ce qu'il était → recalculée.
    _ecrire(tmp_path / "media" / "01_Liste" / "autre.txt", 500)
    await Scanner(depot, emp, Exclusions()).executer()
    await plan.calculer(db_session, depot, emp, ia=_ia_films)
    p = (await _props(db_session)())["01_Liste"]
    assert p.statut == "proposee" and p.valide_par is None


async def test_corriger_vers_un_dossier_hors_plan_refuse(db_session, depot, media):
    emp, _ = media
    await plan.charger_modele_media(db_session, depot, emp)
    await plan.calculer(db_session, depot, emp, ia=_ia_films)
    p = (await _props(db_session)())["01_Liste"]
    with pytest.raises(ValueError):
        await plan.decider(db_session, p, "validee", "x", "/etc")
    with pytest.raises(ValueError):
        await plan.decider(db_session, p, "rangee", "x")


async def test_un_emplacement_sans_plan_n_a_pas_de_propositions(db_session, depot, media):
    _, nas2 = media
    assert (await plan.calculer(db_session, depot, nas2, ia=_ia_films))["statut"] == "ignore"


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #
async def test_parcours_complet_par_l_api(client, db_session, depot, media):
    emp, _ = media
    assert (await client.post(f"/api/inventaire/plan/modele/{emp.id}")).json()["noeuds_crees"] == 5
    plan_ = (await client.get("/api/inventaire/plan", params={"partage": "media"})).json()
    films = next(n for n in plan_["noeuds"] if n["chemin"] == "Films")
    # Verrouillé : ni renommé, ni supprimé.
    assert (await client.patch(f"/api/inventaire/plan/noeuds/{films['id']}", json={"nom": "Movies"})).status_code == 409
    assert (await client.delete(f"/api/inventaire/plan/noeuds/{films['id']}")).status_code == 409
    # Un sous-dossier créé à la main, puis une règle qui le vise.
    r = await client.post("/api/inventaire/plan/noeuds", json={"partage": "media", "nom": "Concerts", "parent_id": films["id"]})
    assert r.status_code == 201 and r.json()["chemin"] == "Films/Concerts"
    assert (await client.post("/api/inventaire/plan/noeuds", json={"partage": "media", "nom": "../x"})).status_code == 400
    r = await client.post("/api/inventaire/plan/regles", json={"type": "motif_nom", "valeur": "live*",
                                                               "noeud_id": r.json()["id"], "priorite": 5})
    assert r.status_code == 201 and r.json()["active"]
    assert (await client.post("/api/inventaire/plan/regles", json={"type": "inconnu", "valeur": "x",
                                                                   "noeud_id": films["id"]})).status_code == 400
    # Le calcul part au worker (classe GPU : il interroge l'IA).
    r = await client.post(f"/api/inventaire/plan/calcul/{emp.id}", params={"ia": "false"})
    assert r.status_code == 202
    job = (await db_session.execute(select(Job).where(Job.type == "plan_propositions"))).scalar_one()
    from services import job_worker
    assert job_worker.classe_tache(job.type) == "gpu"
    await plan.calculer(db_session, depot, emp, ia=None)
    lst = (await client.get("/api/inventaire/plan/propositions", params={"emplacement_id": emp.id})).json()
    par_chemin = {p["chemin"]: p for p in lst["propositions"]}
    assert par_chemin["Concert/live.mkv"]["destination"] == "Films/Concerts"
    # Décider : valider, corriger, refuser — et valider tout ce qu'une règle propose.
    p = par_chemin["roman.epub"]
    r = await client.post(f"/api/inventaire/plan/propositions/{p['id']}/decision", json={"statut": "validee"})
    assert r.status_code == 200 and r.json()["statut"] == "validee"
    p = par_chemin["Concert/live.mkv"]
    r = await client.post(f"/api/inventaire/plan/propositions/{p['id']}/decision",
                          json={"statut": "validee", "destination": "00-A-TRIER"})
    assert r.json()["destination"] == "00-A-TRIER" and r.json()["par"] == "humain"
    regle_serie = par_chemin["Films/Breaking.Bad.S01E01.mkv"]["regle_id"]
    r = await client.post(f"/api/inventaire/plan/regles/{regle_serie}/valider-propositions",
                          params={"emplacement_id": emp.id})
    assert r.json()["validees"] == 1


async def test_desactiver_une_regle(client, db_session, depot, media):
    emp, _ = media
    await client.post(f"/api/inventaire/plan/modele/{emp.id}")
    regle = (await client.get("/api/inventaire/plan")).json()["regles"][0]
    r = await client.patch(f"/api/inventaire/plan/regles/{regle['id']}", json={"active": False})
    assert r.json()["active"] is False
    await plan.calculer(db_session, depot, emp, ia=None)
    props = await _props(db_session)()
    assert props["Films/Breaking.Bad.S01E01.mkv"].statut == "sans_place"


async def test_une_ia_en_panne_n_est_interrogee_qu_une_fois(db_session, depot, media):
    """Essai du 13/11/2026 : IA injoignable → ~25 s par élément. Après la 1re panne, règles seules."""
    emp, _ = media
    await plan.charger_modele_media(db_session, depot, emp)
    appels = []

    async def ia_en_panne(c, noeuds):
        appels.append(c.chemin)
        raise ConnectionError("Ollama injoignable")

    r = await plan.calculer(db_session, depot, emp, ia=ia_en_panne)
    assert len(appels) == 1 and r["ia_hors_service"]
    props = await _props(db_session)()
    assert props["roman.epub"].destination == "Ebook"            # les règles, elles, ont tourné
    assert "IA indisponible" in props["01_Liste"].raison
