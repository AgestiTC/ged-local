"""
Emplacement SMB déclaré à partir d'une Source (étape 3 du plan Rangement sur Sources SMB, 14/11/2026),
et séparation des usages : une Source « Rangement » ne sert JAMAIS à la GED (S2).

Aucun réseau : la session SMB est remplacée par un faux partage. Données fictives.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fakes.depot_memoire import DepotMemoire

from models.document import Document
from models.inventaire import COLONNES_AJOUTEES, evolutions_manquantes
from models.source import USAGE_GED, USAGE_RANGEMENT, Source
from services import crypto, file_access, scan_service
from services.rangement import emplacement_smb, plan, service
from services.rangement.depot import Emplacement
from services.smb_session import EntreeSmb

HOTE = "192.0.2.20"
SECRET = "s3cr3t-fictif"


class FauxPartage:
    """Remplace SessionSmb : un partage avec des dossiers connus ; `panne` simule un NAS injoignable."""

    dossiers = {"/Tom", "/Tom/Photos"}
    panne = False
    ouvertures: list = []

    def __init__(self, hote, partage, identifiant, secret, domaine=None):
        FauxPartage.ouvertures.append((hote, partage, identifiant, secret))

    async def __aenter__(self):
        if FauxPartage.panne:
            raise ConnectionError(f"refusé pour {SECRET}")   # le secret ne doit pas ressortir
        return self

    async def __aexit__(self, *_):
        return None

    async def stat(self, chemin):
        return EntreeSmb(chemin.rsplit("/", 1)[-1], True, 0, None) if chemin in self.dossiers else None

    async def lister(self, dossier):
        return []


@pytest.fixture(autouse=True)
def faux_smb(monkeypatch):
    FauxPartage.panne = False
    FauxPartage.ouvertures = []
    monkeypatch.setattr(emplacement_smb, "SessionSmb", FauxPartage)


@pytest.fixture
def depot(monkeypatch) -> DepotMemoire:
    d = DepotMemoire()
    monkeypatch.setattr(service, "fabrique", lambda: d)
    return d


async def _sources(db, *, rangement_d_abord=True):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ranger = Source(libelle="Rangement", type="smb", hote=HOTE, identifiant="svc-rangement",
                    secret_chiffre=crypto.encrypt(SECRET), usage=USAGE_RANGEMENT,
                    created_at=t0 - timedelta(days=1) if rangement_d_abord else t0 + timedelta(days=1))
    ged = Source(libelle="GED", type="smb", hote=HOTE, identifiant="tom",
                 secret_chiffre=crypto.encrypt("a"), created_at=t0)
    db.add_all([ranger, ged])
    await db.commit()
    return ranger, ged


# --------------------------------------------------------------------------- #
# La GED n'utilise jamais une source du Rangement                              #
# --------------------------------------------------------------------------- #
async def test_la_ged_ignore_la_source_du_rangement_meme_plus_ancienne(db_session):
    await _sources(db_session, rangement_d_abord=True)
    assert (await file_access._source_smb(db_session, HOTE)).identifiant == "tom"
    ident, _, _ = await scan_service.creds_smb(db_session, HOTE)
    assert ident == "tom"


async def test_usage_expose_et_cree(client):
    r = await client.post("/api/sources", json={"libelle": "R", "type": "smb", "hote": HOTE,
                                                "identifiant": "svc", "secret": SECRET, "usage": "rangement"})
    assert r.status_code == 200, r.text
    assert r.json()["usage"] == "rangement" and SECRET not in r.text
    r = await client.post("/api/sources", json={"libelle": "G", "type": "smb", "hote": HOTE})
    assert r.json()["usage"] == USAGE_GED
    r = await client.post("/api/sources", json={"libelle": "X", "type": "smb", "hote": HOTE, "usage": "autre"})
    assert r.status_code == 422


async def test_une_source_du_rangement_n_indexe_rien(client, db_session):
    ranger, _ = await _sources(db_session)
    for route, corps in ((f"/api/sources/{ranger.id}/index", {"partage": "homes", "chemin": "/Tom"}),
                         (f"/api/sources/{ranger.id}/sync", None),
                         (f"/api/sources/{ranger.id}/reindex", None)):
        r = await client.post(route, json=corps) if corps else await client.post(route)
        assert r.status_code == 409, (route, r.text)


async def test_la_seule_source_ged_d_un_nas_indexe_ne_passe_pas_au_rangement(client, db_session):
    seule = Source(libelle="GED", type="smb", hote="192.0.2.30", identifiant="tom")
    db_session.add_all([seule, Document(chemin="smb://192.0.2.30/home/a.pdf", nom="a.pdf", extension="pdf",
                                        hash_sha256="0" * 64)])
    await db_session.commit()
    corps = {"libelle": "GED", "type": "smb", "hote": "192.0.2.30", "identifiant": "tom", "usage": "rangement"}
    r = await client.put(f"/api/sources/{seule.id}", json=corps)
    assert r.status_code == 409, r.text
    # Avec une autre source GED sur ce NAS, le passage est permis.
    db_session.add(Source(libelle="GED 2", type="smb", hote="192.0.2.30", identifiant="tom2"))
    await db_session.commit()
    assert (await client.put(f"/api/sources/{seule.id}", json=corps)).status_code == 200


# --------------------------------------------------------------------------- #
# Déclarer un emplacement SMB                                                  #
# --------------------------------------------------------------------------- #
async def test_declarer_un_emplacement_smb(client, db_session, depot):
    ranger, _ = await _sources(db_session)
    r = await client.post("/api/inventaire/emplacements/smb", json={
        "libelle": "Photos de Tom", "source_id": str(ranger.id), "partage": "homes", "sous_dossier": "Tom/Photos/"})
    assert r.status_code == 201, r.text
    corps = r.json()
    assert corps["racine"] == f"smb://{HOTE}/homes/Tom/Photos"
    assert (corps["source"], corps["partage"], corps["sous_dossier"]) == ("smb", "homes", "/Tom/Photos")
    assert corps["source_id"] == str(ranger.id) and SECRET not in r.text
    # Le compte de la Source a servi à la vérification (et seulement lui).
    assert FauxPartage.ouvertures == [(HOTE, "homes", "svc-rangement", SECRET)]

    etat = (await client.get("/api/inventaire/etat")).json()
    e = etat["emplacements"][0]
    assert (e["source"], e["partage"], e["sous_dossier"], e["source_id"]) == ("smb", "homes", "/Tom/Photos",
                                                                             str(ranger.id))
    assert SECRET not in str(etat)

    # Déclaré deux fois : refusé.
    r = await client.post("/api/inventaire/emplacements/smb", json={
        "libelle": "Encore", "source_id": str(ranger.id), "partage": "homes", "sous_dossier": "/Tom/Photos"})
    assert r.status_code == 409


async def test_tout_un_partage(client, db_session, depot):
    ranger, _ = await _sources(db_session)
    r = await client.post("/api/inventaire/emplacements/smb", json={
        "libelle": "Médias", "source_id": str(ranger.id), "partage": "media"})
    assert r.status_code == 201, r.text
    assert r.json()["racine"] == f"smb://{HOTE}/media" and r.json()["sous_dossier"] == "/"


@pytest.mark.parametrize("corps,code", [
    ({"partage": "homes", "sous_dossier": "/Tom/Absent"}, "dossier_introuvable"),
    ({"partage": "homes", "sous_dossier": "/Tom/../.."}, "dossier_invalide"),
    ({"partage": "ho/mes", "sous_dossier": "/Tom"}, "partage_invalide"),
])
async def test_declaration_smb_refusee(client, db_session, depot, corps, code):
    ranger, _ = await _sources(db_session)
    r = await client.post("/api/inventaire/emplacements/smb",
                          json={"libelle": "X", "source_id": str(ranger.id), **corps})
    assert r.status_code == 400 and r.json()["detail"]["code"] == code, r.text


async def test_la_source_de_la_ged_ne_porte_pas_d_emplacement(client, db_session, depot):
    _, ged = await _sources(db_session)
    r = await client.post("/api/inventaire/emplacements/smb",
                          json={"libelle": "X", "source_id": str(ged.id), "partage": "homes", "sous_dossier": "/Tom"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "source_pas_rangement"
    r = await client.post("/api/inventaire/emplacements/smb",
                          json={"libelle": "X", "source_id": "00000000-0000-0000-0000-000000000099",
                                "partage": "homes"})
    assert r.status_code == 404


async def test_nas_injoignable_sans_fuite_du_secret(client, db_session, depot):
    ranger, _ = await _sources(db_session)
    FauxPartage.panne = True
    r = await client.post("/api/inventaire/emplacements/smb",
                          json={"libelle": "X", "source_id": str(ranger.id), "partage": "homes", "sous_dossier": "/Tom"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "smb_illisible"
    assert SECRET not in r.text
    assert await depot.emplacements() == []


async def test_un_emplacement_smb_ne_se_scanne_pas_encore(client, db_session, depot):
    ranger, _ = await _sources(db_session)
    emp_id = (await client.post("/api/inventaire/emplacements/smb", json={
        "libelle": "Tom", "source_id": str(ranger.id), "partage": "homes", "sous_dossier": "/Tom"})).json()["id"]
    r = await client.post(f"/api/inventaire/emplacements/{emp_id}/scan")
    assert r.status_code == 400 and r.json()["detail"]["code"] == "scan_smb_a_venir"


def test_le_partage_d_un_emplacement_smb_est_son_champ():
    emp = Emplacement(1, "Tom", f"smb://{HOTE}/homes/Tom", source="smb", source_id="x", partage="homes",
                      sous_dossier="/Tom")
    assert plan.partage_de(emp) == "homes"
    assert not emp.sur_serveur and emp.est_smb


# --------------------------------------------------------------------------- #
# Évolution du schéma (sans base)                                              #
# --------------------------------------------------------------------------- #
def test_evolutions_rien_a_jouer_quand_tout_existe():
    check = "CHECK ((source = ANY (ARRAY['serveur'::text, 'agent'::text, 'import'::text, 'smb'::text])))"
    assert evolutions_manquantes({(t, c) for t, c, _ in COLONNES_AJOUTEES}, check) == []


def test_evolutions_sur_une_base_d_avant():
    ancien = "CHECK ((source = ANY (ARRAY['serveur'::text, 'agent'::text, 'import'::text])))"
    sql = evolutions_manquantes(set(), ancien)
    assert sum("ADD COLUMN IF NOT EXISTS" in s for s in sql) == len(COLONNES_AJOUTEES)
    assert any("ON DELETE RESTRICT" in s for s in sql)
    assert sql[-1].endswith("CHECK (source IN ('serveur', 'agent', 'import', 'smb'))")
