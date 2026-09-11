"""
Tests — /api/scan : scanners, profils, boîte, travaux
=====================================================
Ce que l'API doit garantir avant qu'un scanner soit branché :

- un profil ne peut pas viser n'importe où (destination locale hors racine → 400) ;
- lancer un scan crée une ligne de boîte ET une tâche durable, avec les réglages du profil
  surchargés par ceux de la modale ; sur un chargeur on finalise d'un coup, sur une vitre non ;
- le test d'un scanner mémorise ses capacités (ou son erreur) sur la fiche, sans lever ;
- ranger exige un profil ; retirer une ligne ne touche pas au document.
"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from config import get_settings
from models.document import Document
from models.job import Job
from models.scan import Scan
from services import escl_client


@pytest.fixture
def racine(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "documents_root", str(tmp_path / "docs"))
    monkeypatch.setattr(get_settings(), "storage_uploads", str(tmp_path / "uploads"))
    (tmp_path / "docs").mkdir()
    return tmp_path


async def test_scanner_crud_et_test_memorise(client, monkeypatch):
    r = await client.post("/api/scan/scanners", json={"nom": "Canon", "url": "192.168.42.50"})
    assert r.status_code == 201
    s = r.json()
    assert s["url"] == "http://192.168.42.50/eSCL" and s["capacites"] is None

    caps = escl_client.Capacites(modele="Canon G3570", vitre=True, resolutions=[300], couleurs=["RGB24"], formats=["image/jpeg"])
    monkeypatch.setattr(escl_client.ESCLClient, "capacites", AsyncMock(return_value=caps))
    monkeypatch.setattr(escl_client.ESCLClient, "statut", AsyncMock(return_value=escl_client.Statut(etat="Idle")))
    t = (await client.post(f"/api/scan/scanners/{s['id']}/test")).json()
    assert t["ok"] and t["capacites"]["vitre"] and t["statut"]["etat"] == "Idle"
    assert t["scanner"]["dernier_etat"] == "ok"

    monkeypatch.setattr(escl_client.ESCLClient, "capacites", AsyncMock(side_effect=escl_client.ESCLError("injoignable")))
    t = (await client.post(f"/api/scan/scanners/{s['id']}/test")).json()
    assert not t["ok"] and "injoignable" in t["erreur"]
    assert t["scanner"]["dernier_etat"].startswith("erreur")
    # Les capacités du dernier test réussi restent sur la fiche.
    assert (await client.get("/api/scan/scanners")).json()["scanners"][0]["capacites"]["vitre"]

    r = await client.put(f"/api/scan/scanners/{s['id']}", json={"nom": "Canon salon", "url": "http://192.168.42.51"})
    assert r.json()["capacites"] is None  # nouvelle adresse → à re-tester
    assert (await client.delete(f"/api/scan/scanners/{s['id']}")).json()["supprime"]
    assert (await client.get("/api/scan/scanners")).json()["scanners"] == []


async def test_profil_destination_bornee(client, racine):
    ok = await client.post("/api/scan/profils", json={"nom": "Facture", "destination": str(racine / "docs" / "Factures" / "{annee}"),
                                                      "tags": ["facture", " "], "mots_cles": ["facture"]})
    assert ok.status_code == 201 and ok.json()["tags"] == ["facture"]
    smb = await client.post("/api/scan/profils", json={"nom": "Santé", "destination": "smb://nas/Documents/Sante"})
    assert smb.status_code == 201
    ko = await client.post("/api/scan/profils", json={"nom": "Ailleurs", "destination": str(racine / "ailleurs")})
    assert ko.status_code == 400
    ko2 = await client.post("/api/scan/profils", json={"nom": "X", "destination": "smb://nas"})
    assert ko2.status_code == 400
    ko3 = await client.post("/api/scan/profils", json={"nom": "X", "destination": "smb://nas/D", "classement": "auto"})
    assert ko3.status_code == 400
    assert len((await client.get("/api/scan/profils")).json()["profils"]) == 2


async def test_lancer_un_scan_cree_boite_et_tache(client, db_session, racine):
    sc = (await client.post("/api/scan/scanners", json={"nom": "Canon", "url": "192.168.42.50"})).json()
    pr = (await client.post("/api/scan/profils", json={"nom": "Facture", "destination": "smb://nas/Documents/Factures",
                                                       "reglages": {"source": "vitre", "couleur": "gris", "dpi": 300}})).json()
    r = await client.post("/api/scan/jobs", json={"scanner_id": sc["id"], "profil_id": pr["id"], "reglages": {"dpi": 600}})
    assert r.status_code == 202
    body = r.json()
    assert body["finaliser"] is False  # vitre : on attend « page suivante » / « terminer »

    scan = await db_session.get(Scan, __import__("uuid").UUID(body["scan_id"]))
    assert scan.statut == "en_cours" and scan.reglages == {"source": "vitre", "couleur": "gris", "dpi": 600}
    job = await db_session.get(Job, __import__("uuid").UUID(body["job_id"]))
    assert job.type == "scan_capture" and job.statut == "pending" and job.parametres["finaliser"] is False

    # Chargeur : tout d'un coup.
    r2 = await client.post("/api/scan/jobs", json={"scanner_id": sc["id"], "reglages": {"source": "chargeur"}})
    assert r2.json()["finaliser"] is True

    # Sans page capturée, « terminer » refuse ; « page suivante » enfile une capture.
    assert (await client.post(f"/api/scan/{body['scan_id']}/terminer")).status_code == 409
    assert (await client.post(f"/api/scan/{body['scan_id']}/page-suivante")).status_code == 202
    d = (await client.get(f"/api/scan/{body['scan_id']}")).json()
    assert d["statut"] == "en_cours" and d["pages_capturees"] == 0 and d["document"] is None


async def test_scanner_sans_chargeur_refuse_le_chargeur(client, monkeypatch):
    sc = (await client.post("/api/scan/scanners", json={"nom": "Canon", "url": "192.168.42.50"})).json()
    monkeypatch.setattr(escl_client.ESCLClient, "capacites", AsyncMock(return_value=escl_client.Capacites(vitre=True, chargeur=False)))
    monkeypatch.setattr(escl_client.ESCLClient, "statut", AsyncMock(return_value=escl_client.Statut(etat="Idle")))
    await client.post(f"/api/scan/scanners/{sc['id']}/test")
    r = await client.post("/api/scan/jobs", json={"scanner_id": sc["id"], "reglages": {"source": "chargeur"}})
    assert r.status_code == 400


async def test_boite_ranger_et_retirer(client, db_session, racine):
    from services import runtime_config
    runtime_config._overrides["scan_boite_chemin"] = "smb://nas/Documents/Scans"
    db_session.add(Document(chemin="smb://nas/Documents/Scans/facture-edf.pdf", nom="facture-edf.pdf", extension="pdf",
                            hash_sha256="a" * 64, statut="enriched", source="watch", texte_extrait="facture montant"))
    await db_session.flush()
    pr = (await client.post("/api/scan/profils", json={"nom": "Facture", "destination": "smb://nas/Documents/Factures",
                                                       "mots_cles": ["facture"]})).json()

    boite = (await client.get("/api/scan/inbox")).json()
    assert boite["nouveaux"] == 1 and boite["boite_chemin"] == "smb://nas/Documents/Scans"
    item = boite["scans"][0]
    assert item["origine"] == "boite" and item["statut"] == "indexe"
    assert item["proposition"]["nom"] == "Facture"
    assert (await client.post(f"/api/scan/{item['id']}/proposer")).json()["proposition"]["profil_id"] == pr["id"]

    # Ranger sans profil → 400 ; avec → tâche durable enfilée, profil mémorisé.
    assert (await client.post(f"/api/scan/{item['id']}/ranger", json={})).status_code == 400
    r = await client.post(f"/api/scan/{item['id']}/ranger", json={"profil_id": pr["id"], "nom": "EDF"})
    assert r.status_code == 202
    job = await db_session.get(Job, __import__("uuid").UUID(r.json()["job_id"]))
    assert job.type == "scan_ranger" and job.parametres["nom"] == "EDF"

    # Retirer la ligne ne supprime pas le document.
    assert (await client.delete(f"/api/scan/{item['id']}")).json()["supprime"]
    assert (await client.get(f"/api/scan/{item['id']}")).status_code == 404
    assert (await db_session.execute(select(Document))).scalars().one().nom == "facture-edf.pdf"


async def test_config_boite(client, racine):
    r = await client.put("/api/scan/config", json={"boite_chemin": "smb://nas/Documents/Scans/"})
    assert r.json()["boite_chemin"] == "smb://nas/Documents/Scans"
    assert (await client.get("/api/scan/config")).json()["boite_chemin"] == "smb://nas/Documents/Scans"
    assert (await client.put("/api/scan/config", json={"boite_chemin": str(racine / "ailleurs")})).status_code == 400
    assert (await client.put("/api/scan/config", json={"boite_chemin": ""})).json()["boite_chemin"] == ""
