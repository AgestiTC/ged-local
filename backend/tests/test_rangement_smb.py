"""
Ranger et annuler par SMB (étape 6 du plan Rangement sur Sources SMB, 14/11/2026).

Le bac à sable de `test_rangement_lots`, servi par un faux NAS en mémoire (aucun réseau) : un lot
rangé puis annulé remet chaque élément à sa place (seuls restent les dossiers vides créés par le
lot : rien n'est jamais supprimé) ; un compte sans droit d'écrire, un NAS éteint, une coupure ou une
destination hors de l'emplacement ne déplacent rien en douce. Données fictives.
"""

import pytest
from fakes.depot_memoire import DepotMemoire
from smb.base import NotConnectedError
from smb.smb_structs import OperationFailure
from sqlalchemy import func, select
from test_scan_smb import ConnexionNas, NasFictif

from models.plan_classement import PlanProposition
from models.reorg import ReorgMove
from services.rangement import deplacements, emplacement_smb, plan, service
from services.rangement.deplacements_smb import nom_libre_sans_casse
from services.rangement.erreurs import InventaireRefus
from services.rangement.exclusions import Exclusions
from services.rangement.scan import Scanner
from services.rangement.source_smb import SourceSmb
from services.smb_session import SessionSmb

HOTE = "192.0.2.60"


class _Refus:
    status = 0xC0000022   # STATUS_ACCESS_DENIED


@pytest.fixture
def depot(monkeypatch) -> DepotMemoire:
    d = DepotMemoire()
    monkeypatch.setattr(service, "fabrique", lambda: d)
    return d


def _bac(extra: dict[str, bytes] | None = None) -> NasFictif:
    """Le bac de `test_rangement_lots`, sous /media dans le partage `homes`."""
    fichiers = {
        "Films/Le Film (2020)/film.mkv": b"x" * 500,
        "Films/Dark.S01E01.mkv": b"x" * 300,
        "Series/Autre/e.mkv": b"x" * 300,
        "Ebook/livre.epub": b"x" * 50,
        "roman.epub": b"r" * 40,
        "setup.exe": b"x" * 70,
        **(extra or {}),
    }
    arbre: dict[str, bytes | None] = {"/media": None}
    for rel, contenu in fichiers.items():
        parties = rel.split("/")
        for i in range(1, len(parties)):
            arbre.setdefault("/media/" + "/".join(parties[:i]), None)
        arbre["/media/" + rel] = contenu
    return NasFictif(arbre)


def _brancher(monkeypatch, n):
    async def session_de(_emp, ouvrir=None):
        return SessionSmb(HOTE, "homes", "svc", "fictif", connecter=n.connecter)
    monkeypatch.setattr(emplacement_smb, "session_de", session_de)


@pytest.fixture
def nas(monkeypatch) -> NasFictif:
    n = _bac()
    _brancher(monkeypatch, n)
    return n


async def _pret(db, depot, n):
    emp = await depot.creer_emplacement("Médiathèque", f"smb://{HOTE}/homes/media", source="smb",
                                        source_id="src-fictive", partage="homes", sous_dossier="/media")
    source = SourceSmb(SessionSmb(HOTE, "homes", "svc", "fictif", connecter=n.connecter), emp, Exclusions())
    assert (await Scanner(depot, emp, Exclusions(), source=source).executer()).statut == "termine"
    await plan.charger_modele_media(db, depot, emp)
    await plan.calculer(db, depot, emp, ia=None)
    for p in (await db.execute(select(PlanProposition).where(PlanProposition.statut == "proposee"))).scalars().all():
        await plan.decider(db, p, "validee", "tclement")
    return emp


async def _journal(db):
    return (await db.execute(select(ReorgMove))).scalars().all()


def _coupe_si_eteint(fn):
    def appel(self, *a, **kw):
        if self.srv.eteint:
            raise NotConnectedError("NAS éteint")
        return fn(self, *a, **kw)
    return appel


# --------------------------------------------------------------------------- #
# Ranger puis annuler                                                          #
# --------------------------------------------------------------------------- #
async def test_ranger_puis_annuler_remet_l_arbre(db_session, depot, nas):
    emp = await _pret(db_session, depot, nas)
    avant = dict(nas.arbre)
    ops = await deplacements.apercu(db_session, depot, emp)
    assert {(o["source"], o["dossier"]) for o in ops} == {
        ("Films/Dark.S01E01.mkv", "Series/Dark/S01"), ("roman.epub", "Ebook"), ("setup.exe", "00-A-TRIER")}

    lot = await deplacements.creer_lot(db_session, depot, emp, "essai", "tclement")
    connexions = nas.connexions
    await deplacements.appliquer(db_session, lot, emp, racine_autorisee="/ne/sert/pas/en/smb")
    assert lot.statut == "range", lot.message
    assert nas.connexions - connexions == 1                     # une session pour tout le lot
    assert nas.arbre["/media/Series/Dark/S01/Dark.S01E01.mkv"] == b"x" * 300
    assert nas.arbre["/media/Ebook/roman.epub"] == b"r" * 40 and "/media/roman.epub" not in nas.arbre
    assert "/media/00-A-TRIER/setup.exe" in nas.arbre
    moves = await _journal(db_session)
    assert (f"smb://{HOTE}/homes/media/roman.epub", f"smb://{HOTE}/homes/media/Ebook/roman.epub") in {
        (m.chemin_source, m.chemin_dest) for m in moves}
    assert len(moves) == 3 and all(m.origine == "rangement" and m.document_id is None for m in moves)

    await deplacements.annuler(db_session, lot, "tclement", emp)
    assert lot.statut == "annule", lot.message
    # Chaque élément est revenu, au même contenu ; seuls restent les dossiers VIDES créés par le lot.
    assert {k: v for k, v in nas.arbre.items() if k in avant} == avant
    assert set(nas.arbre) - set(avant) == {"/media/00-A-TRIER", "/media/Series/Dark", "/media/Series/Dark/S01"}
    assert all(m.annule_le is not None and m.annule_par == "tclement" for m in await _journal(db_session))
    with pytest.raises(deplacements.RangementRefuse):
        await deplacements.annuler(db_session, lot, "tclement", emp)    # on n'annule pas deux fois


async def test_place_prise_sans_casse_donne_un_nom_suffixe(db_session, depot, monkeypatch):
    n = _bac({"Ebook/Roman.epub": b"y" * 99})     # même nom, autre casse : même place pour SMB
    _brancher(monkeypatch, n)
    emp = await _pret(db_session, depot, n)
    roman = next(o for o in await deplacements.apercu(db_session, depot, emp) if o["source"] == "roman.epub")
    assert roman["nom"] == "roman_(2).epub" and roman["renomme"]
    lot = await deplacements.creer_lot(db_session, depot, emp, "essai", None)
    await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    assert n.arbre["/media/Ebook/roman_(2).epub"] == b"r" * 40 and n.arbre["/media/Ebook/Roman.epub"] == b"y" * 99


def test_nom_libre_sans_casse():
    assert nom_libre_sans_casse("a.txt", {"A.TXT", "a_(2).TXT"}, False) == "a_(3).txt"
    assert nom_libre_sans_casse("Photos", {"photos"}, True) == "Photos_(2)"
    assert nom_libre_sans_casse("b.txt", {"a.txt"}, False) == "b.txt"


# --------------------------------------------------------------------------- #
# Rien ne bouge en douce                                                       #
# --------------------------------------------------------------------------- #
async def test_compte_sans_droit_d_ecrire_rien_ne_bouge(db_session, depot, nas, monkeypatch):
    emp = await _pret(db_session, depot, nas)
    avant = dict(nas.arbre)
    lot = await deplacements.creer_lot(db_session, depot, emp, "essai", None)
    tentatives = []

    def refuser(self, partage, chemin, *a, **kw):
        tentatives.append(chemin)
        raise OperationFailure("accès refusé", [_Refus()])

    monkeypatch.setattr(ConnexionNas, "rename", refuser)
    monkeypatch.setattr(ConnexionNas, "createDirectory", refuser)
    await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    assert lot.statut == "refuse" and "droit d'écrire" in lot.message
    assert len(tentatives) == 1                                # on s'arrête au premier refus
    assert nas.arbre == avant
    assert (await db_session.execute(select(func.count()).select_from(ReorgMove))).scalar() == 0


async def test_nas_eteint_rien_ne_bouge(db_session, depot, nas):
    emp = await _pret(db_session, depot, nas)
    lot = await deplacements.creer_lot(db_session, depot, emp, "essai", None)
    nas.eteint = True
    with pytest.raises(deplacements.RangementRefuse, match="injoignable"):
        await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    assert lot.statut == "refuse"
    assert (await db_session.execute(select(func.count()).select_from(ReorgMove))).scalar() == 0


async def test_source_retiree_du_rangement(db_session, depot, nas, monkeypatch):
    emp = await _pret(db_session, depot, nas)
    lot = await deplacements.creer_lot(db_session, depot, emp, "essai", None)

    async def refus(_emp, ouvrir=None):
        raise InventaireRefus("Cette source sert à la GED.", code="source_pas_rangement")

    monkeypatch.setattr(emplacement_smb, "session_de", refus)
    with pytest.raises(deplacements.RangementRefuse, match="GED"):
        await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    assert lot.statut == "refuse"


async def test_fichier_disparu_depuis_l_apercu(db_session, depot, nas):
    emp = await _pret(db_session, depot, nas)
    lot = await deplacements.creer_lot(db_session, depot, emp, "essai", None)
    del nas.arbre["/media/roman.epub"]
    await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    assert lot.statut == "partiel" and "roman.epub" in lot.message
    assert "/media/00-A-TRIER/setup.exe" in nas.arbre


async def test_coupure_pendant_un_renommage_abouti_est_journalise(db_session, depot, nas, monkeypatch):
    emp = await _pret(db_session, depot, nas)
    lot = await deplacements.creer_lot(db_session, depot, emp, "essai", None)
    renommer = ConnexionNas.rename
    coupures = []

    def renommer_puis_couper(self, partage, src, dst, **kw):
        renommer(self, partage, src, dst, **kw)
        if not coupures:
            coupures.append(src)
            raise NotConnectedError("coupure juste après le renommage")

    monkeypatch.setattr(ConnexionNas, "rename", renommer_puis_couper)
    await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    assert lot.statut == "range", lot.message
    assert len(await _journal(db_session)) == 3                 # le renommage abouti est journalisé


async def test_nas_coupe_pendant_le_lot_s_arrete_journal_juste(db_session, depot, nas, monkeypatch):
    emp = await _pret(db_session, depot, nas)
    lot = await deplacements.creer_lot(db_session, depot, emp, "essai", None)
    renommer = ConnexionNas.rename

    def renommer_puis_eteindre(self, partage, src, dst, **kw):
        renommer(self, partage, src, dst, **kw)
        self.srv.eteint = True
        raise NotConnectedError("coupure")

    monkeypatch.setattr(ConnexionNas, "rename", renommer_puis_eteindre)
    monkeypatch.setattr(ConnexionNas, "getAttributes", _coupe_si_eteint(ConnexionNas.getAttributes))
    await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    assert lot.statut == "refuse" and "injoignable" in lot.message
    assert "peut-être fait, à vérifier" in lot.message          # dit, puisqu'on ne peut pas le savoir
    assert await _journal(db_session) == []        # on ne sait pas : rien d'inventé au journal


@pytest.mark.parametrize("dossier", ["../autre", "../../homes2/x"])
async def test_une_destination_hors_de_l_emplacement_est_refusee(db_session, depot, nas, dossier):
    emp = await _pret(db_session, depot, nas)
    avant = dict(nas.arbre)
    lot = await deplacements.creer_lot(db_session, depot, emp, "essai", None)
    lot.operations = [{**lot.operations[0], "dossier": dossier}]
    await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    assert lot.statut == "refuse" and "hors de l'emplacement" in lot.message
    assert nas.arbre == avant


async def test_annuler_hors_du_partage_refuse_la_ligne(db_session, depot, nas):
    emp = await _pret(db_session, depot, nas)
    lot = await deplacements.creer_lot(db_session, depot, emp, "essai", None)
    await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    m = (await _journal(db_session))[0]
    m.chemin_dest = f"smb://{HOTE}/autre-partage/x"
    await db_session.commit()
    await deplacements.annuler(db_session, lot, None, emp)
    assert lot.statut == "annule_partiel" and "pas dans le partage" in lot.message


async def test_un_lot_smb_ne_s_annule_pas_sans_son_emplacement_smb(db_session, depot, nas):
    emp = await _pret(db_session, depot, nas)
    lot = await deplacements.creer_lot(db_session, depot, emp, "essai", None)
    await deplacements.appliquer(db_session, lot, emp, racine_autorisee=None)
    with pytest.raises(deplacements.RangementRefuse, match="SMB"):
        await deplacements.annuler(db_session, lot, None)
    assert all(m.annule_le is None for m in await _journal(db_session))


async def test_le_plan_saute_un_emplacement_smb_imbrique(depot):
    emp = await depot.creer_emplacement("Médiathèque", f"smb://{HOTE}/homes/media", source="smb",
                                        source_id="s", partage="homes", sous_dossier="/media")
    await depot.creer_emplacement("Films", f"smb://{HOTE}/homes/media/Films", source="smb",
                                  source_id="s", partage="homes", sous_dossier="/media/Films")
    assert await plan._racines_imbriquees(depot, emp) == {"Films"}
