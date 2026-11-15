"""
Contrat du dépôt de l'inventaire — les MÊMES tests pour le dépôt en mémoire et pour PostgreSQL.

Le dépôt en mémoire sert de double à toute la logique du module Rangement (les tables `inv_*`
n'existent pas sous SQLite). Il ne vaut que s'il se comporte comme le vrai : chaque test tourne
donc deux fois, et un écart entre les deux est un échec.

Le passage PostgreSQL exige une vraie base : `INVENTAIRE_TEST_DATABASE_URL`
(ex. `postgresql+asyncpg://docflow:dev@hote:5432/docflow`). Sans elle, il est ignoré. Chaque test
travaille dans un **schéma jetable**, supprimé à la fin : la base visée n'est jamais polluée.
"""

import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from fakes.depot_memoire import DepotMemoire
from models.inventaire import SCHEMA_INVENTAIRE, appliquer_schema, evolutions_manquantes
from services.rangement.depot import (
    Bilan,
    Compteurs,
    Copie,
    DossierEnvoye,
    DoublonRacine,
    Element,
    EnvoiEnCours,
    Groupe,
    LigneInstantane,
    PasseEnCours,
    PosteEnDouble,
    RecuperableLieu,
    ResumePasse,
    ScanEnCours,
    extension,
)
from services.rangement.depot_postgres import DepotPostgres

URL = os.environ.get("INVENTAIRE_TEST_DATABASE_URL", "")
T = 1_712_345_678.5


@dataclass
class Banc:
    depot: Any
    moteur: AsyncEngine | None = None   # None = dépôt en mémoire

    async def jeton(self) -> uuid.UUID:
        """Un jeton utilisable par un poste (en base : une ligne de `jetons_api`)."""
        jeton_id = uuid.uuid4()
        if self.moteur is not None:
            async with self.moteur.begin() as conn:
                await conn.execute(text("INSERT INTO jetons_api (id) VALUES (:id)"), {"id": jeton_id})
        return jeton_id


@pytest_asyncio.fixture(params=["memoire", "postgres"])
async def banc(request):
    if request.param == "memoire":
        yield Banc(DepotMemoire())
        return
    if not URL:
        pytest.skip("INVENTAIRE_TEST_DATABASE_URL non définie")
    schema = f"test_inv_{uuid.uuid4().hex[:10]}"
    admin = create_async_engine(URL)
    async with admin.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    moteur = create_async_engine(URL, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with moteur.begin() as conn:
            # `inv_postes` référence la table des jetons du socle : ici, sa seule clé suffit.
            await conn.execute(text("CREATE TABLE jetons_api (id uuid PRIMARY KEY)"))
            # Idem pour `inv_emplacements.source_id` (emplacements SMB) → `sources`. Sans elle, ce
            # banc échouait depuis l'étape 3 (relevé le 15/11/2026, étape 8).
            await conn.execute(text("CREATE TABLE sources (id uuid PRIMARY KEY)"))
            # Une base neuve : toutes les créations, puis toutes les évolutions (colonnes SMB, CHECK).
            assert await appliquer_schema(conn) == len(SCHEMA_INVENTAIRE) + len(evolutions_manquantes(set(), None))
        yield Banc(DepotPostgres(moteur), moteur)
    finally:
        await moteur.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def _arbre(depot) -> tuple[Any, int]:
    """Un petit NAS : 4 dossiers de tête, dont deux aux noms pièges, et 5 fichiers."""
    emp = await depot.creer_emplacement("NAS", "/mnt/nas")
    scan = await depot.ouvrir_scan(emp.id, "manuel")
    await depot.ajouter(emp.id, scan, "", [
        Element("Photos", True, 0, T), Element("100%_bio", True, 0, T), Element("100x_bio", True, 0, T),
        Element("Impôts été", True, 0, T), Element("lisezmoi.TXT", False, 7, T)])
    await depot.ajouter(emp.id, scan, "Photos", [Element("2024", True, 0, T)])
    await depot.ajouter(emp.id, scan, "Photos/2024", [Element("vacances.jpg", False, 100, T)])
    await depot.ajouter(emp.id, scan, "100%_bio", [Element("recette.txt", False, 5, T)])
    await depot.ajouter(emp.id, scan, "100x_bio", [Element("autre.txt", False, 6, T)])
    await depot.ajouter(emp.id, scan, "Impôts été", [Element("avis.pdf", False, 40, T)])
    return emp, scan


# --------------------------------------------------------------------------- #
# Hors base                                                                    #
# --------------------------------------------------------------------------- #
def test_extension():
    assert extension(Element("Rapport.PDF", False, 1, T)) == "pdf"
    assert extension(Element("archive.tar.gz", False, 1, T)) == "gz"
    assert extension(Element("Makefile", False, 1, T)) is None
    assert extension(Element(".gitignore", False, 1, T)) is None
    assert extension(Element("dossier.v2", True, 0, T)) is None


# --------------------------------------------------------------------------- #
# Emplacements et scans                                                        #
# --------------------------------------------------------------------------- #
async def test_emplacements(banc):
    d = banc.depot
    nas = await d.creer_emplacement("NAS", "/mnt/nas")
    assert (nas.libelle, nas.racine, nas.actif, nas.source, nas.poste_id) == ("NAS", "/mnt/nas", True, "serveur", None)
    assert nas.sur_serveur
    with pytest.raises(DoublonRacine):
        await d.creer_emplacement("Autre nom", "/mnt/nas")
    # La même racine sur deux postes : permise (unicité par source et par poste).
    pc, portable = await d.creer_poste("PC-GAME"), await d.creer_poste("PORTABLE")
    a = await d.creer_emplacement("Docs", "C:/Users/Thomas", "agent", pc.id)
    b = await d.creer_emplacement("Docs", "C:/Users/Thomas", "agent", portable.id)
    with pytest.raises(DoublonRacine):
        await d.creer_emplacement("Docs bis", "C:/Users/Thomas", "agent", pc.id)
    assert not a.sur_serveur and a.poste_id == pc.id
    assert await d.emplacement(nas.id) == nas and await d.emplacement(9999) is None
    await d.activer_emplacement(a.id, False)
    assert [e.id for e in await d.emplacements()] == [nas.id, a.id, b.id]
    assert [e.id for e in await d.emplacements(actifs_seulement=True)] == [nas.id, b.id]


async def test_rebrancher_un_emplacement_garde_son_inventaire(banc):
    """Bascule montage → SMB (étape 8) : même identifiant, mêmes entrées ; avec un préfixe, ce
    sous-dossier devient la racine (« 100%_bio » : jokers LIKE ; « Photos/Photos » : collision évitée)."""
    d = banc.depot
    emp, scan = await _arbre(d)
    await d.ajouter(emp.id, scan, "Photos", [Element("Photos", True, 0, T)])
    await d.ajouter(emp.id, scan, "Photos/Photos", [Element("2024", True, 0, T)])
    await d.enregistrer_instantane(scan, [LigneInstantane("", 0, 158, 5, 4), LigneInstantane("Photos", 1, 100, 1, 1),
                                          LigneInstantane("Photos/2024", 2, 100, 1, 0),
                                          LigneInstantane("100%_bio", 1, 5, 1, 0)])
    avant = await d.enfants(emp.id, "Photos")
    autre = await d.creer_emplacement("Autre", "smb://192.0.2.1/media", "smb")
    with pytest.raises(DoublonRacine):
        await d.rebrancher_emplacement(emp.id, racine=autre.racine, source="smb", source_id=None,
                                       partage="media", sous_dossier="/")
    assert (await d.emplacement(emp.id)).racine == "/mnt/nas"   # rien n'a changé

    assert await d.rebrancher_emplacement(emp.id, racine="smb://192.0.2.1/homes/Tom", source="smb", source_id=None,
                                          partage="homes", sous_dossier="/Tom") == (12, 0)
    e = await d.emplacement(emp.id)
    assert (e.id, e.racine, e.source, e.partage, e.sous_dossier) == (
        emp.id, "smb://192.0.2.1/homes/Tom", "smb", "homes", "/Tom")
    assert await d.enfants(emp.id, "Photos") == avant

    # Recentrer sur « Photos » : « Photos/Photos/2024 » devient « Photos/2024 », qui existait déjà.
    gardees, retirees = await d.rebrancher_emplacement(
        emp.id, racine="smb://192.0.2.1/homes/Tom/Photos", source="smb", source_id=None, partage="homes",
        sous_dossier="/Tom/Photos", prefixe="Photos")
    assert (gardees, retirees) == (4, 8)
    assert set(await d.enfants(emp.id, "")) == {"2024", "Photos"}
    assert set(await d.enfants(emp.id, "2024")) == {"vacances.jpg"}
    assert set(await d.enfants(emp.id, "Photos")) == {"2024"}
    assert await d.tailles_instantane(scan) == {"": 100, "2024": 100}


async def test_un_seul_scan_en_cours_par_emplacement(banc):
    d = banc.depot
    emp = await d.creer_emplacement("NAS", "/mnt/nas")
    autre = await d.creer_emplacement("Sauvegarde", "/mnt/sauvegarde")
    assert await d.scan_en_cours() is False and await d.dernier_scan(emp.id) is None
    scan = await d.ouvrir_scan(emp.id, "manuel")
    with pytest.raises(ScanEnCours):
        await d.ouvrir_scan(emp.id, "nuit")
    await d.ouvrir_scan(autre.id, "nuit")   # un autre emplacement n'est pas gêné
    assert await d.scan_en_cours() is True
    assert await d.dernier_scan(emp.id, termine_seulement=True) is None

    await d.fermer_scan(scan, "termine", Compteurs(nb_dossiers=3, nb_fichiers=4, volume_octets=151, nb_ajouts=7),
                        "tout va bien")
    dernier = await d.dernier_scan(emp.id, termine_seulement=True)
    assert dernier["id"] == scan and dernier["statut"] == "termine" and dernier["declencheur"] == "manuel"
    assert (dernier["nb_dossiers"], dernier["nb_fichiers"], dernier["volume_octets"], dernier["nb_ajouts"]) == (3, 4, 151, 7)
    assert dernier["message"] == "tout va bien" and dernier["fin"] is not None
    suivant = await d.ouvrir_scan(emp.id, "nuit")   # le précédent est fermé : la place est libre
    assert (await d.dernier_scan(emp.id))["id"] == suivant
    assert (await d.dernier_scan(emp.id, termine_seulement=True))["id"] == scan


async def test_scans_orphelins_interrompus(banc):
    d = banc.depot
    emp = await d.creer_emplacement("NAS", "/mnt/nas")
    scan = await d.ouvrir_scan(emp.id, "manuel")
    assert await d.interrompre_scans_orphelins(24) == 0   # trop récent pour être un orphelin
    assert await d.interrompre_scans_orphelins(0) == 1
    assert (await d.dernier_scan(emp.id))["statut"] == "interrompu"
    assert await d.ouvrir_scan(emp.id, "manuel") != scan


# --------------------------------------------------------------------------- #
# Entrées                                                                      #
# --------------------------------------------------------------------------- #
async def test_ajout_et_lecture_par_dossier(banc):
    d = banc.depot
    emp = await d.creer_emplacement("NAS", "/mnt/nas")
    assert await d.a_des_entrees(emp.id) is False
    scan = await d.ouvrir_scan(emp.id, "manuel")
    await d.ajouter(emp.id, scan, "", [Element("Photos", True, 0, T), Element("note.txt", False, 12, T)])
    await d.ajouter(emp.id, scan, "Photos", [Element("a.jpg", False, 100, T)])
    await d.ajouter(emp.id, scan, "", [])   # liste vide : sans effet
    assert await d.a_des_entrees(emp.id) is True and d.ecritures_entrees == 3
    racine = await d.enfants(emp.id, "")
    assert set(racine) == {"Photos", "note.txt"}
    assert (racine["note.txt"].est_dossier, racine["note.txt"].taille, racine["note.txt"].mtime) == (False, 12, T)
    assert racine["Photos"].est_dossier and racine["Photos"].totaux is None
    assert set(await d.enfants(emp.id, "Photos")) == {"a.jpg"}
    assert await d.enfants(emp.id, "Absent") == {}


async def test_modification(banc):
    d = banc.depot
    emp, scan = await _arbre(d)
    avant = d.ecritures_entrees
    await d.modifier(emp.id, scan, "Impôts été", [Element("avis.pdf", False, 99, T + 60)])
    connu = (await d.enfants(emp.id, "Impôts été"))["avis.pdf"]
    assert (connu.taille, connu.mtime) == (99, T + 60) and d.ecritures_entrees == avant + 1


async def test_disparition_d_un_dossier_au_nom_piege(banc):
    """`%` et `_` sont des jokers SQL : « 100%_bio » ne doit pas emporter « 100x_bio »."""
    d = banc.depot
    emp, scan = await _arbre(d)
    await d.fermer_scan(scan, "termine", Compteurs())
    scan2 = await d.ouvrir_scan(emp.id, "nuit")
    assert await d.marquer_disparus(emp.id, scan2, "", ["100%_bio"]) == 2   # le dossier et son fichier
    assert "100%_bio" not in await d.enfants(emp.id, "")
    assert await d.enfants(emp.id, "100%_bio") == {}
    assert set(await d.enfants(emp.id, "100x_bio")) == {"autre.txt"}
    assert await d.marquer_disparus(emp.id, scan2, "", ["100%_bio"]) == 0   # déjà disparu
    assert await d.marquer_disparus(emp.id, scan2, "", []) == 0


async def test_reapparition(banc):
    """Un fichier qui revient reprend sa ligne : pas de doublon de chemin."""
    d = banc.depot
    emp, scan = await _arbre(d)
    await d.marquer_disparus(emp.id, scan, "Impôts été", ["avis.pdf"])
    assert await d.enfants(emp.id, "Impôts été") == {}
    await d.ajouter(emp.id, scan, "Impôts été", [Element("avis.pdf", False, 1, T + 5)])
    connu = (await d.enfants(emp.id, "Impôts été"))["avis.pdf"]
    assert (connu.taille, connu.mtime) == (1, T + 5)
    assert await d.plus_gros_fichiers(emp.id, "Impôts été", 5) == [("Impôts été/avis.pdf", 1)]


# --------------------------------------------------------------------------- #
# Totaux par dossier et lectures de la carte                                   #
# --------------------------------------------------------------------------- #
async def test_totaux_et_lectures_de_la_carte(banc):
    d = banc.depot
    emp, _ = await _arbre(d)
    avant = d.ecritures_entrees
    await d.mettre_a_jour_totaux(emp.id, "", [("Photos", 100, 1, 1), ("Impôts été", 40, 1, 0),
                                              ("100%_bio", 5, 1, 0), ("100x_bio", 6, 1, 0)])
    await d.mettre_a_jour_totaux(emp.id, "", [])
    assert d.ecritures_entrees == avant + 4
    assert (await d.dossier(emp.id, "Photos")).totaux == (100, 1, 1)
    assert (await d.dossier(emp.id, "Photos/2024")).totaux is None       # pas encore calculé
    assert await d.dossier(emp.id, "lisezmoi.TXT") is None               # un fichier n'est pas un dossier
    assert await d.dossier(emp.id, "Absent") is None

    enfants, total = await d.enfants_tries(emp.id, "", 2)
    assert [c.nom for c in enfants] == ["Photos", "Impôts été"] and total == 5
    tous, _ = await d.enfants_tries(emp.id, "", 50)
    assert [c.nom for c in tous] == ["Photos", "Impôts été", "lisezmoi.TXT", "100x_bio", "100%_bio"]

    assert sorted(await d.repartition_types(emp.id, "")) == [("jpg", 1, 100), ("pdf", 1, 40), ("txt", 3, 18)]
    # Le préfixe « 100%_bio » ne doit pas avaler « 100x_bio ».
    assert await d.repartition_types(emp.id, "100%_bio") == [("txt", 1, 5)]
    assert await d.plus_gros_fichiers(emp.id, "100%_bio", 5) == [("100%_bio/recette.txt", 5)]
    assert await d.plus_gros_fichiers(emp.id, "", 2) == [("Photos/2024/vacances.jpg", 100),
                                                         ("Impôts été/avis.pdf", 40)]


async def test_fichier_sans_extension(banc):
    d = banc.depot
    emp = await d.creer_emplacement("NAS", "/mnt/nas")
    scan = await d.ouvrir_scan(emp.id, "manuel")
    await d.ajouter(emp.id, scan, "", [Element("Makefile", False, 3, T), Element(".gitignore", False, 2, T)])
    assert await d.repartition_types(emp.id, "") == [(None, 2, 5)]


# --------------------------------------------------------------------------- #
# Instantanés                                                                  #
# --------------------------------------------------------------------------- #
async def test_instantanes(banc):
    d = banc.depot
    emp = await d.creer_emplacement("NAS", "/mnt/nas")
    autre = await d.creer_emplacement("Sauvegarde", "/mnt/sauvegarde")
    scans = []
    for taille in (100, 150, 300):
        scan = await d.ouvrir_scan(emp.id, "nuit")
        await d.enregistrer_instantane(scan, [LigneInstantane("", 0, taille, 4, 3),
                                              LigneInstantane("Photos", 1, taille - 50, 1, 1)])
        await d.fermer_scan(scan, "termine", Compteurs())
        scans.append(scan)
    ailleurs = await d.ouvrir_scan(autre.id, "nuit")
    await d.enregistrer_instantane(ailleurs, [LigneInstantane("", 0, 9, 1, 0)])
    await d.enregistrer_instantane(ailleurs, [])   # liste vide : sans effet

    assert await d.scans_avec_instantane(emp.id, 2) == [scans[2], scans[1]]
    assert await d.tailles_instantane(scans[1]) == {"": 150, "Photos": 100}
    assert await d.purger_instantanes(emp.id, 2) == 2            # les 2 lignes du plus ancien
    assert await d.scans_avec_instantane(emp.id, 10) == [scans[2], scans[1]]
    assert await d.tailles_instantane(scans[0]) == {}
    assert await d.tailles_instantane(ailleurs) == {"": 9}       # l'autre emplacement n'est pas touché


# --------------------------------------------------------------------------- #
# Copies sur disque                                                            #
# --------------------------------------------------------------------------- #
async def test_copies_sur_disque(banc):
    d = banc.depot
    a = await d.creer_emplacement("Famille", "/mnt/famille")
    b = await d.creer_emplacement("Thomas", "/mnt/thomas")
    scan_a, scan_b = await d.ouvrir_scan(a.id, "manuel"), await d.ouvrir_scan(b.id, "manuel")
    await d.ajouter(a.id, scan_a, "", [Element("film.mp4", False, 2000, T), Element("copie.mp4", False, 2000, T),
                                       Element("autre.bin", False, 2000, T), Element("petit.txt", False, 10, T),
                                       Element("Dossier", True, 2000, T)])
    await d.ajouter(b.id, scan_b, "", [Element("film.mp4", False, 2000, T), Element("seul.iso", False, 5000, T)])
    ids = [a.id, b.id]

    # Passe 1 : quelles tailles reviennent plusieurs fois ?
    assert await d.tailles_en_double(ids, 1000, None, 10) == [2000]
    assert await d.tailles_en_double(ids, 3000, None, 10) == []
    assert await d.tailles_en_double(ids, 1000, 2000, 10) == []     # « sous » est une borne exclue
    assert await d.tailles_en_double([b.id], 1000, None, 10) == []  # seul, B n'a pas de doublon de taille
    candidats = await d.fichiers_de_taille(ids, 2000)
    assert [(f.emplacement_id, f.chemin) for f in candidats] == [
        (a.id, "autre.bin"), (a.id, "copie.mp4"), (a.id, "film.mp4"), (b.id, "film.mp4")]
    assert all(f.partielle is None and not f.partielle_valide for f in candidats)
    par_chemin = {(f.emplacement_id, f.chemin): f.id for f in candidats}

    # Ce qu'un poste devrait lire pour A : d'abord les empreintes partielles.
    demandes = await d.empreintes_a_calculer(a.id, ids, 1000, 10)
    assert [(f.chemin, nature) for f, nature in demandes] == [
        ("film.mp4", "partielle"), ("copie.mp4", "partielle"), ("autre.bin", "partielle")]
    assert len(await d.empreintes_a_calculer(a.id, ids, 1000, 2)) == 2
    assert await d.empreintes_a_calculer(a.id, ids, 3000, 10) == []

    await d.enregistrer_empreinte(par_chemin[(a.id, "film.mp4")], b"p1", None, 2000, T)
    await d.enregistrer_empreinte(par_chemin[(a.id, "copie.mp4")], b"p1", None, 2000, T)
    await d.enregistrer_empreinte(par_chemin[(a.id, "autre.bin")], b"p2", None, 2000, T)
    await d.enregistrer_empreinte(par_chemin[(b.id, "film.mp4")], b"p1", None, 2000, T)
    # Puis les complètes, seulement là où la partielle est partagée (« autre.bin » est écarté).
    demandes = await d.empreintes_a_calculer(a.id, ids, 1000, 10)
    assert [(f.chemin, nature) for f, nature in demandes] == [("film.mp4", "complete"), ("copie.mp4", "complete")]
    assert await d.groupes_identiques(ids, 10) == [] and await d.bilan_identiques(ids) == Bilan()

    for cle in ((a.id, "film.mp4"), (a.id, "copie.mp4"), (b.id, "film.mp4")):
        await d.enregistrer_empreinte(par_chemin[cle], b"p1", b"c1", 2000, T)
    lu = await d.fichier(par_chemin[(a.id, "film.mp4")])
    assert (lu.partielle, lu.complete, lu.emp_taille, lu.emp_mtime) == (b"p1", b"c1", 2000, T)
    assert lu.complete_valide and await d.fichier(999_999) is None
    assert await d.empreintes_a_calculer(a.id, ids, 1000, 10) == []

    groupe = Groupe(b"c1", 2000, (Copie(a.id, "copie.mp4"), Copie(a.id, "film.mp4"), Copie(b.id, "film.mp4")))
    assert await d.groupes_identiques(ids, 10) == [groupe] and groupe.recuperable == 4000
    assert await d.groupes_identiques(ids, 10, b.id) == [groupe]
    assert await d.groupes_identiques([a.id], 10) == [
        Groupe(b"c1", 2000, (Copie(a.id, "copie.mp4"), Copie(a.id, "film.mp4")))]
    assert await d.groupes_identiques([b.id], 10) == []
    assert await d.bilan_identiques(ids) == Bilan(4000, 1, 2)
    assert await d.recuperable_par_emplacement(ids) == {a.id: RecuperableLieu(2000, 4000),
                                                        b.id: RecuperableLieu(0, 2000)}

    # Un fichier modifié depuis n'est plus cru sur parole : son empreinte ne compte plus.
    await d.modifier(a.id, scan_a, "", [Element("film.mp4", False, 2001, T + 1)])
    assert not (await d.fichier(par_chemin[(a.id, "film.mp4")])).complete_valide
    assert await d.bilan_identiques(ids) == Bilan(2000, 1, 1)
    assert await d.recuperable_par_emplacement(ids) == {a.id: RecuperableLieu(0, 2000),
                                                        b.id: RecuperableLieu(0, 2000)}
    # Un fichier disparu sort des copies.
    await d.marquer_disparus(b.id, scan_b, "", ["film.mp4"])
    assert await d.groupes_identiques(ids, 10) == [] and await d.fichier(par_chemin[(b.id, "film.mp4")]) is None


async def test_passes_de_recherche_des_copies(banc):
    d = banc.depot
    debut = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert await d.derniere_passe() is None and await d.octets_lus_depuis(debut) == 0
    passe = await d.ouvrir_passe()
    with pytest.raises(PasseEnCours):   # une seule passe à la fois, garanti par la base
        await d.ouvrir_passe()
    await d.avancer_passe(passe, 500)
    assert (await d.derniere_passe())["octets_lus"] == 500
    await d.fermer_passe(passe, "limite", ResumePasse(octets_lus=800, nb_partielles=3, nb_completes=1,
                                                      nb_erreurs=0, nb_changes=2, nb_reportes=5), "quota atteint")
    derniere = await d.derniere_passe()
    assert (derniere["statut"], derniere["octets_lus"], derniere["nb_partielles"], derniere["nb_completes"],
            derniere["nb_changes"], derniere["nb_reportes"], derniere["message"]) == (
        "limite", 800, 3, 1, 2, 5, "quota atteint")
    assert await d.octets_lus_depuis(debut) == 800
    assert await d.octets_lus_depuis(datetime.now(timezone.utc) + timedelta(hours=1)) == 0

    suivante = await d.ouvrir_passe()
    assert await d.interrompre_passes_orphelines(24) == 0
    assert await d.interrompre_passes_orphelines(0) == 1
    assert (await d.derniere_passe())["id"] == suivante
    assert (await d.derniere_passe())["statut"] == "interrompu"


# --------------------------------------------------------------------------- #
# Postes et envois                                                             #
# --------------------------------------------------------------------------- #
async def test_postes(banc):
    d = banc.depot
    jeton, autre_jeton = await banc.jeton(), await banc.jeton()
    pc = await d.creer_poste("PC-GAME", jeton)
    assert (pc.nom, pc.actif, pc.version, pc.lecture_octets, pc.jeton_id) == ("PC-GAME", True, "", 0, jeton)
    with pytest.raises(PosteEnDouble):
        await d.creer_poste("PC-GAME", autre_jeton)       # même nom
    with pytest.raises(PosteEnDouble):
        await d.creer_poste("PORTABLE", jeton)            # même jeton
    portable = await d.creer_poste("PORTABLE")            # pas encore appairé
    assert portable.jeton_id is None
    assert [p.nom for p in await d.postes()] == ["PC-GAME", "PORTABLE"]
    assert (await d.poste_par_jeton(jeton)).id == pc.id
    assert await d.poste_par_jeton(autre_jeton) is None and await d.poste(9999) is None

    await d.contact_poste(pc.id, "1.2.3-" + "x" * 60)
    vu = await d.poste(pc.id)
    assert vu.dernier_contact is not None and len(vu.version) == 40 and vu.version.startswith("1.2.3-")
    await d.activer_poste(pc.id, False)
    assert (await d.poste(pc.id)).actif is False

    # Régénérer le jeton : l'ancien ne désigne plus personne.
    with pytest.raises(PosteEnDouble):
        await d.changer_jeton_poste(portable.id, jeton)
    await d.changer_jeton_poste(pc.id, autre_jeton)
    assert await d.poste_par_jeton(jeton) is None and (await d.poste_par_jeton(autre_jeton)).id == pc.id
    await d.changer_jeton_poste(pc.id, None)
    assert (await d.poste(pc.id)).jeton_id is None

    # Quota de lecture : cumulé dans la journée, remis à zéro le lendemain.
    await d.compter_lecture_poste(pc.id, date(2026, 10, 14), 100)
    await d.compter_lecture_poste(pc.id, date(2026, 10, 14), 50)
    assert (await d.poste(pc.id)).lecture_octets == 150
    await d.compter_lecture_poste(pc.id, date(2026, 10, 15), 7)
    vu = await d.poste(pc.id)
    assert (vu.lecture_jour, vu.lecture_octets) == (date(2026, 10, 15), 7)


async def test_envois(banc):
    d = banc.depot
    pc = await d.creer_poste("PC-GAME")
    emp = await d.creer_emplacement("Docs", "C:/Users/Thomas", "agent", pc.id)
    film = Element("film.mp4", False, 2 * 1024 * 1024, T)
    envoi = await d.ouvrir_envoi(emp.id)
    assert (await d.envoi(envoi))["statut"] == "reception" and await d.envoi(9999) is None
    await d.ajouter_dossiers_envoi(envoi, [
        DossierEnvoye("", False, (Element("Docs", True, 0, T), film)),
        DossierEnvoye("Docs", False, (Element("a.pdf", False, 10, T),))])
    # Un même dossier peut arriver en plusieurs lots : ses enfants s'ajoutent.
    await d.ajouter_dossiers_envoi(envoi, [
        DossierEnvoye("Docs", True, (Element("b.pdf", False, 20, T),), ("illisible.doc",))])
    await d.ajouter_dossiers_envoi(envoi, [])
    assert (await d.envoi(envoi))["nb_dossiers"] == 2
    docs = await d.dossier_envoi(envoi, "Docs")
    assert [e.nom for e in docs.enfants] == ["a.pdf", "b.pdf"] and docs.illisibles == ("illisible.doc",)
    assert docs.illisible is True and docs.enfants[1] == Element("b.pdf", False, 20, T)
    assert (await d.dossier_envoi(envoi, "")).enfants == (Element("Docs", True, 0, T), film)
    assert await d.dossier_envoi(envoi, "Absent") is None

    # L'agent recommence : l'envoi resté en réception est abandonné, ses listes effacées.
    second = await d.ouvrir_envoi(emp.id)
    assert (await d.envoi(envoi))["statut"] == "abandonne" and (await d.envoi(envoi))["fin"] is not None
    assert await d.dossier_envoi(envoi, "Docs") is None
    # En traitement, il occupe la place.
    await d.ajouter_dossiers_envoi(second, [DossierEnvoye("", False, (film,))])
    await d.clore_envoi(second, "traitement")
    assert (await d.envoi(second))["fin"] is None
    with pytest.raises(EnvoiEnCours):
        await d.ouvrir_envoi(emp.id)
    assert (await d.envoi(second))["statut"] == "traitement"
    assert (await d.dossier_envoi(second, "")).enfants == (film,)
    await d.clore_envoi(second, "traite")
    assert (await d.envoi(second))["fin"] is not None and await d.dossier_envoi(second, "") is None

    troisieme = await d.ouvrir_envoi(emp.id)
    await d.ajouter_dossiers_envoi(troisieme, [DossierEnvoye("", False, (film,))])
    assert await d.abandonner_envois(24) == 0
    assert await d.abandonner_envois(0) == 1
    assert (await d.envoi(troisieme))["statut"] == "abandonne" and await d.dossier_envoi(troisieme, "") is None


# --------------------------------------------------------------------------- #
# PostgreSQL seulement                                                         #
# --------------------------------------------------------------------------- #
async def test_schema_rejouable(banc):
    if banc.moteur is None:
        pytest.skip("PostgreSQL seulement")
    async with banc.moteur.begin() as conn:
        assert await appliquer_schema(conn) == 0   # tout existe : rien n'est rejoué, rien n'est verrouillé
    async with banc.moteur.begin() as conn:
        await conn.execute(text("DROP INDEX inv_entrees_tailles"))
        assert await appliquer_schema(conn) == 1   # seul l'index manquant revient


async def test_une_cle_etrangere_absente_n_est_pas_maquillee(banc):
    """Seule une violation d'UNICITÉ devient « scan en cours » : le reste remonte tel quel."""
    if banc.moteur is None:
        pytest.skip("PostgreSQL seulement")
    with pytest.raises(IntegrityError):
        await banc.depot.ouvrir_scan(9999, "manuel")
    with pytest.raises(IntegrityError):
        await banc.depot.creer_poste("PC", uuid.uuid4())   # jeton inconnu de jetons_api


async def test_jeton_supprime_le_poste_reste(banc):
    if banc.moteur is None:
        pytest.skip("PostgreSQL seulement")
    jeton = await banc.jeton()
    pc = await banc.depot.creer_poste("PC-GAME", jeton)
    async with banc.moteur.begin() as conn:
        await conn.execute(text("DELETE FROM jetons_api WHERE id = :id"), {"id": jeton})
    assert (await banc.depot.poste(pc.id)).jeton_id is None
