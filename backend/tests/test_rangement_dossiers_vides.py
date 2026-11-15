"""
Retirer les dossiers qu'un lot a vidés (option demandée par Thomas, 15/11/2026).

Seuls les dossiers dont le lot a sorti le CONTENU (packs de série) sont candidats ; un dossier où il reste
quelque chose est gardé ; l'index de vignettes Synology (`@eaDir`) ne compte pas ; annuler le lot recrée
les dossiers et remet chaque fichier. Disque local et faux NAS en mémoire, données fictives.
"""

from pathlib import Path

import pytest
from fakes.depot_memoire import DepotMemoire
from sqlalchemy import select
from test_rangement_smb import HOTE, _bac, _brancher

from models.plan_classement import PlanProposition
from services.rangement import deplacements, plan, service
from services.rangement.exclusions import Exclusions
from services.rangement.scan import Scanner
from services.rangement.source_smb import SourceSmb
from services.smb_session import SessionSmb


def _ecrire(p: Path, n: int = 10) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * n)


@pytest.fixture
def depot(monkeypatch) -> DepotMemoire:
    d = DepotMemoire()
    monkeypatch.setattr(service, "fabrique", lambda: d)
    return d


async def _tout_valider(db, depot, emp):
    await plan.charger_modele_media(db, depot, emp)
    await plan.calculer(db, depot, emp, ia=None)
    props = (await db.execute(select(PlanProposition).where(PlanProposition.statut == "proposee"))).scalars().all()
    for p in props:
        await plan.decider(db, p, "validee", "tclement")
    return props


async def test_local_retire_les_packs_vides_garde_les_autres_et_l_annulation_recree(db_session, depot, tmp_path):
    r = tmp_path / "media"
    _ecrire(r / "Films" / "Le Film (2020)" / "film.mkv", 500)
    _ecrire(r / "Series" / "Adolescence.S01.FR" / "Adolescence.S01E01.mp4", 100)
    _ecrire(r / "Series" / "Adolescence.S01.FR" / "@eaDir" / "Adolescence.S01E01.mp4" / "SYNOVIDEO_VIDEO_SCREENSHOT.jpg", 5)
    _ecrire(r / "Series" / "Westworld.S01" / "Westworld.S01E01.mkv", 100)
    emp = await depot.creer_emplacement("Médiathèque", str(r).replace("\\", "/"))
    await Scanner(depot, emp, Exclusions()).executer()
    await _tout_valider(db_session, depot, emp)
    lot = await deplacements.creer_lot(db_session, depot, emp, "séries", "tclement")
    lot = await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    assert lot.statut == "range", lot.message
    # Un fichier de l'utilisateur arrive entre-temps dans un pack vidé : ce pack-là est gardé.
    _ecrire(r / "Series" / "Westworld.S01" / "a-garder.txt", 3)

    r_ = await deplacements.retirer_dossiers_vides(db_session, lot, emp)
    assert (r_["retires"], r_["gardes"]) == (1, 1), r_
    assert not (r / "Series" / "Adolescence.S01.FR").exists()            # vide (à @eaDir près) : retiré
    assert (r / "Series" / "Westworld.S01" / "a-garder.txt").is_file()   # pas vide : gardé, intact
    assert "1 dossier(s) vidé(s) retiré(s)" in lot.message

    lot = await deplacements.annuler(db_session, lot, "tclement", emp)
    assert lot.statut == "annule", lot.message
    assert (r / "Series" / "Adolescence.S01.FR" / "Adolescence.S01E01.mp4").is_file()   # dossier recréé


async def test_un_lot_sans_pack_ne_retire_rien(db_session, depot, tmp_path):
    r = tmp_path / "media"
    _ecrire(r / "Films" / "Le Film (2020)" / "film.mkv", 500)
    _ecrire(r / "roman.epub", 40)
    _ecrire(r / "Ebook" / "livre.epub", 50)
    emp = await depot.creer_emplacement("Médiathèque", str(r).replace("\\", "/"))
    await Scanner(depot, emp, Exclusions()).executer()
    await _tout_valider(db_session, depot, emp)
    lot = await deplacements.appliquer(db_session, await deplacements.creer_lot(db_session, depot, emp, "x", "t"), emp,
                                       racine_autorisee=None)
    assert (await deplacements.retirer_dossiers_vides(db_session, lot, emp))["retires"] == 0
    assert (r / "Films").is_dir() and (r / "Ebook" / "roman.epub").is_file()


async def test_un_lot_pas_encore_range_est_refuse(db_session, depot, tmp_path):
    r = tmp_path / "media"
    _ecrire(r / "Series" / "Westworld.S01" / "Westworld.S01E01.mkv", 100)
    _ecrire(r / "Films" / "f" / "f.mkv", 1)
    emp = await depot.creer_emplacement("Médiathèque", str(r).replace("\\", "/"))
    await Scanner(depot, emp, Exclusions()).executer()
    await _tout_valider(db_session, depot, emp)
    lot = await deplacements.creer_lot(db_session, depot, emp, "x", "t")
    with pytest.raises(deplacements.RangementRefuse):
        await deplacements.retirer_dossiers_vides(db_session, lot, emp)
    assert (r / "Series" / "Westworld.S01" / "Westworld.S01E01.mkv").is_file()


async def test_smb_retire_le_pack_vide_avec_son_eadir_puis_l_annulation_le_recree(db_session, depot, monkeypatch):
    n = _bac({
        "Series/Westworld.S01/Westworld.S01E01.mkv": b"w" * 100,
        "Series/Westworld.S01/@eaDir/Westworld.S01E01.mkv/SYNOVIDEO_VIDEO_SCREENSHOT.jpg": b"j" * 5,
        "Series/Dark.S02/Dark.S02E01.mkv": b"d" * 100,
    })
    _brancher(monkeypatch, n)
    emp = await depot.creer_emplacement("Médiathèque", f"smb://{HOTE}/homes/media", source="smb",
                                        source_id="src-fictive", partage="homes", sous_dossier="/media")
    source = SourceSmb(SessionSmb(HOTE, "homes", "svc", "fictif", connecter=n.connecter), emp, Exclusions())
    assert (await Scanner(depot, emp, Exclusions(), source=source).executer()).statut == "termine"
    await _tout_valider(db_session, depot, emp)
    lot = await deplacements.creer_lot(db_session, depot, emp, "séries", "tclement")
    await deplacements.appliquer(db_session, lot, emp, racine_autorisee="/ne/sert/pas")
    assert lot.statut == "range", lot.message
    n.arbre["/media/Series/Dark.S02/reste.txt"] = b"r"             # arrivé après : Dark.S02 sera gardé

    r_ = await deplacements.retirer_dossiers_vides(db_session, lot, emp)
    assert (r_["retires"], r_["gardes"]) == (1, 1), r_
    assert not any(p.startswith("/media/Series/Westworld.S01") for p in n.arbre)
    assert n.arbre["/media/Series/Westworld/S01/Westworld.S01E01.mkv"] == b"w" * 100
    assert n.arbre["/media/Series/Dark.S02/reste.txt"] == b"r"

    await deplacements.annuler(db_session, lot, "tclement", emp)
    assert lot.statut == "annule", lot.message
    assert n.arbre["/media/Series/Westworld.S01/Westworld.S01E01.mkv"] == b"w" * 100


async def test_la_route_lance_la_tache(client, db_session, depot, tmp_path):
    from models.job import Job
    from models.plan_classement import PlanLot
    lot = PlanLot(emplacement_id=1, libelle="x", operations=[], nb=0, octets=0, statut="range")
    db_session.add(lot)
    await db_session.commit()
    r = await client.post(f"/api/inventaire/rangement/lots/{lot.id}/retirer-vides")
    assert r.status_code == 202, r.text
    r = await client.post(f"/api/inventaire/rangement/lots/{lot.id}/appliquer?retirer_vides=true")
    assert r.status_code == 409          # déjà rangé
    jobs = (await db_session.execute(select(Job).where(Job.type == "rangement_retirer_vides"))).scalars().all()
    assert len(jobs) == 1
