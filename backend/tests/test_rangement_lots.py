"""
Ranger par lots, avec annulation (Rangement, étape 10) — dans un BAC À SABLE (dossier temporaire).

Le dev ne déplace jamais de vrais fichiers. Critère d'acceptation du plan : un lot de 1 000 fichiers
est rangé, vérifié puis annulé en un clic ; aucune ligne du journal n'est supprimée.
"""

import os
from pathlib import Path

import pytest
from sqlalchemy import func, select

from fakes.depot_memoire import DepotMemoire
from models.job import Job
from models.plan_classement import PlanLot, PlanProposition
from models.reorg import ReorgMove
from services.rangement import deplacements, plan, service
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


async def _pret(db, depot, racine: Path):
    """Scan + modèle de départ + calcul par les règles + validation de toutes les propositions."""
    emp = await depot.creer_emplacement("Médiathèque", str(racine).replace("\\", "/"))
    await Scanner(depot, emp, Exclusions()).executer()
    await plan.charger_modele_media(db, depot, emp)
    await plan.calculer(db, depot, emp, ia=None)
    for p in (await db.execute(select(PlanProposition).where(PlanProposition.statut == "proposee"))).scalars().all():
        await plan.decider(db, p, "validee", "tclement")
    return emp


@pytest.fixture
def bac(tmp_path) -> Path:
    r = tmp_path / "media"
    _ecrire(r / "Films" / "Le Film (2020)" / "film.mkv", 500)
    _ecrire(r / "Films" / "Dark.S01E01.mkv", 300)               # règle : → Series/Dark/S01 (règle des séries)
    _ecrire(r / "Series" / "Autre" / "e.mkv", 300)
    _ecrire(r / "Ebook" / "livre.epub", 50)
    _ecrire(r / "roman.epub", 40)                               # règle : → Ebook
    _ecrire(r / "setup.exe", 70)                                # règle : → 00-A-TRIER (dossier à créer)
    return r


async def test_ranger_puis_annuler(db_session, depot, bac):
    emp = await _pret(db_session, depot, bac)
    ops = await deplacements.apercu(db_session, depot, emp)
    assert {(o["source"], o["dossier"]) for o in ops} == {
        ("Films/Dark.S01E01.mkv", "Series/Dark/S01"), ("roman.epub", "Ebook"), ("setup.exe", "00-A-TRIER")}
    lot = await deplacements.creer_lot(db_session, depot, emp, "essai", "tclement")
    await deplacements.appliquer(db_session, lot, emp, racine_autorisee=str(bac.parent))
    assert lot.statut == "range"
    assert (bac / "Series" / "Dark" / "S01" / "Dark.S01E01.mkv").exists() and not (bac / "Films" / "Dark.S01E01.mkv").exists()
    assert (bac / "Ebook" / "roman.epub").exists() and (bac / "00-A-TRIER" / "setup.exe").exists()
    moves = (await db_session.execute(select(ReorgMove).where(ReorgMove.batch_id == lot.id))).scalars().all()
    assert len(moves) == 3 and all(m.origine == "rangement" and m.document_id is None for m in moves)

    await deplacements.annuler(db_session, lot, "tclement")
    assert lot.statut == "annule"
    assert (bac / "Films" / "Dark.S01E01.mkv").exists() and (bac / "roman.epub").exists() and (bac / "setup.exe").exists()
    moves = (await db_session.execute(select(ReorgMove).where(ReorgMove.batch_id == lot.id))).scalars().all()
    assert len(moves) == 3 and all(m.annule_le is not None and m.annule_par == "tclement" for m in moves)
    with pytest.raises(deplacements.RangementRefuse):
        await deplacements.annuler(db_session, lot, "tclement")      # on n'annule pas deux fois


async def test_place_prise_donne_un_nom_suffixe(db_session, depot, bac):
    _ecrire(bac / "Ebook" / "roman.epub", 99)                         # même nom déjà dans la cible
    emp = await _pret(db_session, depot, bac)
    ops = await deplacements.apercu(db_session, depot, emp)
    roman = next(o for o in ops if o["source"] == "roman.epub")
    assert roman["nom"] == "roman_(2).epub" and roman["renomme"]
    lot = await deplacements.creer_lot(db_session, depot, emp, "essai", None)
    await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    assert (bac / "Ebook" / "roman_(2).epub").stat().st_size == 40 and (bac / "Ebook" / "roman.epub").stat().st_size == 99


async def test_lecture_seule_rien_ne_bouge(db_session, depot, bac, monkeypatch):
    emp = await _pret(db_session, depot, bac)
    lot = await deplacements.creer_lot(db_session, depot, emp, "essai", None)
    monkeypatch.setattr(deplacements.os, "access", lambda *_a, **_k: False)
    with pytest.raises(deplacements.RangementRefuse, match="LECTURE SEULE"):
        await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    assert lot.statut == "refuse" and (bac / "roman.epub").exists()
    assert (await db_session.execute(select(func.count()).select_from(ReorgMove))).scalar() == 0


async def test_fichier_disparu_depuis_l_apercu(db_session, depot, bac):
    emp = await _pret(db_session, depot, bac)
    lot = await deplacements.creer_lot(db_session, depot, emp, "essai", None)
    (bac / "roman.epub").unlink()
    await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    assert lot.statut == "partiel" and "roman.epub" in lot.message
    assert (bac / "00-A-TRIER" / "setup.exe").exists()


async def test_rien_de_valide_rien_a_ranger(db_session, depot, bac):
    emp = await depot.creer_emplacement("Médiathèque", str(bac).replace("\\", "/"))
    await Scanner(depot, emp, Exclusions()).executer()
    await plan.charger_modele_media(db_session, depot, emp)
    await plan.calculer(db_session, depot, emp, ia=None)                  # proposées, pas validées
    with pytest.raises(deplacements.RangementRefuse, match="Rien à ranger"):
        await deplacements.creer_lot(db_session, depot, emp, "essai", None)


async def test_lot_de_mille_fichiers_range_verifie_annule(db_session, depot, tmp_path):
    """Critère d'acceptation de l'étape 10 : 1 000 fichiers, rangés, vérifiés, annulés en un clic."""
    r = tmp_path / "media"
    (r / "Ebook").mkdir(parents=True)
    for i in range(1000):
        _ecrire(r / f"livre-{i:04d}.epub", 3)
    emp = await _pret(db_session, depot, r)
    lot = await deplacements.creer_lot(db_session, depot, emp, "mille livres", "tclement")
    assert lot.nb == 1000
    await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    assert lot.statut == "range" and len(os.listdir(r / "Ebook")) == 1000
    assert not any(n.endswith(".epub") for n in os.listdir(r))
    await deplacements.annuler(db_session, lot, "tclement")
    assert lot.statut == "annule" and len(os.listdir(r / "Ebook")) == 0
    total = (await db_session.execute(select(func.count()).select_from(ReorgMove).where(ReorgMove.batch_id == lot.id))).scalar()
    assert total == 1000                                                    # aucune ligne supprimée


@pytest.mark.skipif(os.name == "nt", reason="liens symboliques soumis à privilège sous Windows")
async def test_un_lien_n_est_jamais_deplace(db_session, depot, bac):
    emp = await _pret(db_session, depot, bac)
    lot = await deplacements.creer_lot(db_session, depot, emp, "essai", None)
    (bac / "roman.epub").unlink()
    os.symlink("/etc/hostname", bac / "roman.epub")
    await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    assert os.path.islink(bac / "roman.epub") and "lien" in lot.message


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #
async def test_routes_du_rangement(client, db_session, depot, bac):
    emp = await _pret(db_session, depot, bac)
    r = await client.post("/api/inventaire/rangement/apercu", json={"emplacement_id": emp.id})
    assert r.status_code == 200 and r.json()["nb"] == 3
    r = await client.post("/api/inventaire/rangement/lots", json={"emplacement_id": emp.id, "libelle": "premier lot"})
    assert r.status_code == 201
    lot_id = r.json()["id"]
    assert (await client.post(f"/api/inventaire/rangement/lots/{lot_id}/annuler")).status_code == 409   # pas encore rangé
    r = await client.post(f"/api/inventaire/rangement/lots/{lot_id}/appliquer")
    assert r.status_code == 202
    job = (await db_session.execute(select(Job).where(Job.type == "rangement_appliquer"))).scalar_one()
    from services import job_worker
    assert job_worker.classe_tache(job.type) == "fond"
    lots = (await client.get("/api/inventaire/rangement/lots", params={"emplacement_id": emp.id})).json()["lots"]
    assert lots[0]["libelle"] == "premier lot" and lots[0]["nb"] == 3
    assert (await client.post("/api/inventaire/rangement/lots/pas-un-uuid/appliquer")).status_code == 404
    lot = await db_session.get(PlanLot, __import__("uuid").UUID(lot_id))
    assert lot.statut == "pret"     # rien n'a bougé tant que le worker n'a pas pris la tâche
