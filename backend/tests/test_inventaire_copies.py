"""
Copies sur disque (étape 6 du plan rangement + mails) : les trois passes, leurs garde-fous, la façade
`duplicate_service.copies_sur_disque` et la route `GET /api/duplicates` — sur le dépôt en mémoire.

Porté de rangement (`tests/test_doublons.py`, « copies multiples »). La promesse centrale : on lit
le moins possible (128 Ko par fichier de taille partagée, le fichier entier seulement si le début et
la fin coïncident), et une empreinte déjà calculée n'est jamais relue tant que le fichier n'a pas changé.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from fakes.depot_memoire import DepotMemoire
from models.job import Job
from services import duplicate_service
from services.rangement import copies, jobs, service
from services.rangement.exclusions import Exclusions
from services.rangement.reglages import ReglagesInventaire
from services.rangement.scan import Scanner

MO = 1024 * 1024
NUIT = datetime(2099, 10, 14, 2, tzinfo=timezone.utc)
JOUR = datetime(2099, 10, 14, 14, tzinfo=timezone.utc)


def _ecrire(p: Path, contenu: bytes) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(contenu)
    return p


@pytest.fixture
def depot(monkeypatch) -> DepotMemoire:
    d = DepotMemoire()
    monkeypatch.setattr(service, "fabrique", lambda: d)
    return d


@pytest.fixture
async def nas(tmp_path, depot):
    """Deux emplacements du serveur : une vraie copie de 2 Mo entre eux, plus des leurres."""
    video = bytes((i * 13) % 251 for i in range(2 * MO))
    r1, r2 = tmp_path / "media", tmp_path / "nas2"
    _ecrire(r1 / "Films" / "film.mkv", video)
    _ecrire(r2 / "Sauvegarde" / "film (copie).mkv", video)
    # Même taille, même début et même fin, mais un octet diffère au milieu : seule la 3ᵉ passe le voit.
    milieu = bytearray(video)
    milieu[MO] ^= 0xFF
    _ecrire(r1 / "Films" / "presque.mkv", bytes(milieu))
    _ecrire(r1 / "petit.txt", b"petit")          # sous la taille minimale : jamais lu
    e1 = await depot.creer_emplacement("Médiathèque", str(r1))
    e2 = await depot.creer_emplacement("NAS 2", str(r2))
    for e in (e1, e2):
        await Scanner(depot, e, Exclusions()).executer()
    return e1, e2, r1, r2


async def _passe(depot, *, a_la_demande=True, limite=200 * MO, quand=NUIT, exclusions=Exclusions()):
    return await copies.executer(depot, ReglagesInventaire(exclusions=exclusions), taille_min=MO,
                                 limite_nuit=limite, horloge=lambda: quand, a_la_demande=a_la_demande)


async def test_trois_passes_trouvent_la_vraie_copie_seulement(depot, nas):
    e1, e2, _, _ = nas
    r = await _passe(depot)
    assert r["statut"] == "termine"
    # 3 fichiers de 2 Mo : 3 partielles (128 Ko chacune), puis 3 complètes (partielle partagée par les 3).
    assert (r["partielles"], r["completes"]) == (3, 3)
    assert r["octets_lus"] == 3 * 2 * copies.TAILLE_BLOC + 3 * 2 * MO
    groupes = await depot.groupes_identiques([e1.id, e2.id], 10)
    assert len(groupes) == 1
    assert {(c.emplacement_id, c.chemin) for c in groupes[0].copies} == {
        (e1.id, "Films/film.mkv"), (e2.id, "Sauvegarde/film (copie).mkv")}


async def test_une_empreinte_n_est_jamais_relue(depot, nas):
    await _passe(depot)
    r = await _passe(depot)
    assert r["octets_lus"] == 0 and r["statut"] == "termine"


async def test_fichier_modifie_depuis_le_scan_pas_lu(depot, nas):
    _, _, r1, _ = nas
    (r1 / "Films" / "film.mkv").write_bytes(b"x" * (2 * MO))   # même taille, autre date
    import os
    os.utime(r1 / "Films" / "film.mkv", (1, 1))
    r = await _passe(depot)
    assert "modifié" in r["message"]


async def test_exclusion_ajoutee_apres_le_scan_respectee(depot, nas):
    _, _, r1, r2 = nas
    r = await _passe(depot, exclusions=Exclusions.depuis_reglages("Sauvegarde", ""))
    groupes = await depot.groupes_identiques([1, 2], 10)
    assert groupes == [] and r["statut"] == "termine"


async def test_limite_de_lecture_de_la_nuit(depot, nas):
    r = await _passe(depot, limite=300 * 1024)
    assert r["statut"] == "limite"
    assert r["octets_lus"] <= 300 * 1024
    # La nuit suivante reprend là où on s'était arrêté : les partielles déjà faites ne sont pas relues.
    suite = await copies.executer(depot, ReglagesInventaire(), taille_min=MO, limite_nuit=200 * MO,
                                  horloge=lambda: NUIT.replace(day=15), a_la_demande=True)
    assert suite["partielles"] < 3


async def test_la_nuit_seulement_dans_la_fenetre(depot, nas):
    assert (await _passe(depot, a_la_demande=False, quand=JOUR))["statut"] == "ignore"
    assert (await _passe(depot, a_la_demande=False, quand=NUIT))["statut"] == "termine"


async def test_jamais_pendant_un_scan(depot, nas):
    e1, *_ = nas
    await depot.ouvrir_scan(e1.id, "manuel")
    r = await _passe(depot)
    assert r["statut"] == "ignore" and "scan" in r["message"]


async def test_les_fichiers_d_un_poste_ne_sont_jamais_lus_par_le_serveur(depot, nas, monkeypatch):
    """Un emplacement de PC entre dans la comparaison, mais c'est son agent qui le lit."""
    poste = await depot.creer_poste("PC")
    pc = await depot.creer_emplacement("PC", "C:\\Users\\Thomas", source="agent", poste_id=poste.id)
    from services.rangement.depot import DossierEnvoye, Element
    envoi = await depot.ouvrir_envoi(pc.id)
    await depot.ajouter_dossiers_envoi(envoi, [DossierEnvoye("", False, (Element("film.mkv", False, 2 * MO, 1.0),))])
    from services.rangement.scan import SourceEnvoi
    await Scanner(depot, pc, Exclusions(), source=SourceEnvoi(depot, envoi, Exclusions())).executer()
    lus: list[str] = []
    vrai = copies._lire

    def espion(racine, f, complete):
        lus.append(racine)
        return vrai(racine, f, complete)

    monkeypatch.setattr(copies, "_lire", espion)
    await _passe(depot)
    assert lus and not any(r.startswith("C:\\") for r in lus)


# --------------------------------------------------------------------------- #
# Façade et route                                                              #
# --------------------------------------------------------------------------- #
async def test_facade_des_copies(depot, nas):
    await _passe(depot)
    r = await duplicate_service.copies_sur_disque(depot)
    assert r["source"] == "inventaire" and r["nb_groupes"] == 1 and r["octets_recuperables"] == 2 * MO
    g = r["groupes"][0]
    assert {f["emplacement"] for f in g["fichiers"]} == {"Médiathèque", "NAS 2"}
    assert sum(f["garder"] for f in g["fichiers"]) == 1
    garde = next(f for f in g["fichiers"] if f["garder"])
    assert garde["relatif"] == "Films/film.mkv"            # la moins profonde
    assert garde["chemin"].endswith("film.mkv") and r["derniere_passe"]["statut"] == "termine"


async def test_route_sans_inventaire_ne_dit_pas_aucun_doublon(client):
    """Avant : liste vide → « Aucun doublon 🎉 » pour un scan qui n'avait rien vu (audit M3)."""
    r = await client.get("/api/duplicates")
    assert r.status_code == 503 and "rien n'a été analysé" in r.json()["detail"]


async def test_route_lit_l_inventaire_sans_parcourir_le_disque(client, depot, nas, monkeypatch):
    await _passe(depot)

    def interdit(*a, **k):
        raise AssertionError("la page Doublons ne doit plus parcourir le disque")

    monkeypatch.setattr("os.scandir", interdit)
    monkeypatch.setattr(Path, "rglob", interdit)
    r = await client.get("/api/duplicates")
    assert r.status_code == 200 and r.json()["nb_groupes"] == 1
    assert "dossier_quarantaine" in r.json()


async def test_lancer_une_passe_a_la_demande(client, db_session, depot, nas):
    r = await client.post("/api/inventaire/copies")
    assert r.status_code == 202
    job = (await db_session.execute(select(Job).where(Job.type == service.JOB_COPIES))).scalar_one()
    from services import job_worker
    assert job_worker.classe_tache(job.type) == "fond"
    resultat = await jobs._handler_copies(job_worker.JobContext(str(job.id), job.type, job.parametres, None))
    assert resultat["statut"] == "termine" and resultat["completes"] == 3


async def test_un_meme_fichier_dans_deux_emplacements_imbriques_n_est_pas_sa_copie(depot, tmp_path):
    """Relevé à l'essai : « NAS 2 » déclaré DANS la médiathèque après son scan. Tant que la médiathèque
    n'est pas rescannée, `nas-media/x` y figure encore : ce n'est pas une copie du `x` de NAS 2."""
    media = tmp_path / "media"
    _ecrire(media / "nas-media" / "x.mkv", bytes((i * 7) % 251 for i in range(2 * MO)))
    m = await depot.creer_emplacement("Médiathèque", str(media))
    await Scanner(depot, m, Exclusions()).executer()
    n2 = await depot.creer_emplacement("NAS 2", str(media / "nas-media"))
    await Scanner(depot, n2, Exclusions()).executer()
    await _passe(depot)
    assert (await duplicate_service.copies_sur_disque(depot))["groupes"] == []


async def test_declarer_un_emplacement_dedans_relance_le_scan_du_parent(client, db_session, depot, tmp_path,
                                                                        monkeypatch):
    from services import runtime_config
    monkeypatch.setitem(runtime_config._overrides, "inventaire_racine_autorisee", tmp_path.as_posix())
    (tmp_path / "media" / "nas-media").mkdir(parents=True)
    r = await client.post("/api/inventaire/emplacements",
                          json={"libelle": "Médiathèque", "racine": (tmp_path / "media").as_posix()})
    assert r.json()["rescans"] == []
    r = await client.post("/api/inventaire/emplacements",
                          json={"libelle": "NAS 2", "racine": (tmp_path / "media" / "nas-media").as_posix()})
    assert r.status_code == 201 and r.json()["rescans"] == [1]
    job = (await db_session.execute(select(Job).where(Job.type == service.JOB_SCAN))).scalar_one()
    assert job.parametres["emplacement_id"] == 1
