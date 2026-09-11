"""
Tests — service Scan : nommer, proposer, assembler, ranger
=========================================================
Le rangement déplace des fichiers : c'est la partie du module qui peut faire mal. Ce qui
est vérifié ici, sans NAS ni scanner :

- un nom de fichier ne sort jamais du dossier (`..`, `/`) et garde son extension ;
- deux scans le même jour avec le même profil ne s'écrasent pas (`_(1)`) ;
- ranger déplace, journalise (`reorg_moves`), fusionne les tags **sans effacer** ceux de
  l'IA, et laisse au document son identité (pas de ré-extraction) ;
- une destination locale hors de la racine documents est refusée ;
- la proposition de profil n'invente rien : sans indice, pas de proposition.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from config import get_settings
from models.document import Document
from models.metadata import MetadonneeIA
from models.reorg import ReorgMove
from models.scan import Scan, ScanProfil
from services import scan_service as svc

QUAND = datetime(2026, 9, 11, 14, 5, tzinfo=timezone.utc)


# ─── Nommage ─────────────────────────────────────────────────────────────────────────

def test_nom_par_defaut_date_et_profil():
    assert svc.formater_nom(None, profil_nom="Facture", nom_origine="scan.pdf", quand=QUAND) == "2026-09-11_facture.pdf"


def test_nom_garde_extension_et_neutralise_les_chemins():
    n = svc.formater_nom("{profil}_{nom}", profil_nom="Santé", nom_origine="../../etc/passwd.PDF", quand=QUAND)
    assert "/" not in n and ".." not in n
    assert n == "sante_passwd.pdf"


def test_collision_suffixe_ou_placeholder():
    assert svc.formater_nom("{date}_{profil}", profil_nom="Facture", nom_origine="a.pdf", quand=QUAND, n=2) == "2026-09-11_facture_(2).pdf"
    assert svc.formater_nom("{date}-{n}", profil_nom="Facture", nom_origine="a.pdf", quand=QUAND, n=2) == "2026-09-11-2.pdf"


def test_destination_resolue_et_bornee():
    assert svc.resoudre_destination("smb://nas/Documents//Factures/{annee}/", QUAND) == "smb://nas/Documents/Factures/2026"
    with pytest.raises(ValueError):
        svc.resoudre_destination("/app/documents/../secret", QUAND)


def test_parse_smb():
    assert svc.parse_smb("smb://nas/Documents/Factures/2026") == ("nas", "Documents", "/Factures/2026")
    assert svc.parse_smb("smb://nas/Documents") == ("nas", "Documents", "/")
    assert svc.parse_smb("/app/documents/x") is None


# ─── Proposition ─────────────────────────────────────────────────────────────────────

def _profil(nom, mots, actif=True):
    return ScanProfil(id=uuid.uuid4(), nom=nom, destination="/x", mots_cles=mots, actif=actif, tags=[])


def test_proposition_prefere_les_indices_forts():
    facture = _profil("Facture", ["facture", "montant"])
    sante = _profil("Santé", ["ordonnance", "médecin"])
    p = svc.proposer_profil([sante, facture], categorie="facture", tags=["edf"], texte="montant total 42 €")
    assert p["nom"] == "Facture" and p["score"] == 3
    assert any("catégorie/tags" in r for r in p["raisons"])


def test_pas_de_proposition_sans_indice_ni_pour_un_profil_inactif():
    assert svc.proposer_profil([_profil("Facture", ["facture"])], categorie="photo", texte="vacances") is None
    assert svc.proposer_profil([_profil("Facture", ["facture"], actif=False)], categorie="facture") is None


# ─── Assemblage PDF ──────────────────────────────────────────────────────────────────

def _jpeg(largeur=40, hauteur=60) -> bytes:
    import fitz
    return fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, largeur, hauteur), 0).tobytes("jpeg")


def test_assemblage_jpeg_et_pdf(tmp_path):
    import fitz
    src = fitz.open()
    src.new_page()
    src.new_page()
    pdf_bytes = src.tobytes()
    sortie = tmp_path / "out.pdf"
    nb = svc.assembler_pdf([("image/jpeg", _jpeg()), ("application/pdf", pdf_bytes), ("image/jpeg", _jpeg())], sortie)
    assert nb == 4
    assert fitz.open(str(sortie)).page_count == 4


# ─── Rangement local → local, avec base ──────────────────────────────────────────────

@pytest.fixture
def racine(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "documents_root", str(tmp_path / "docs"))
    (tmp_path / "docs").mkdir()
    return tmp_path


async def _doc(db, chemin: Path, tags=None, categorie=None):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(b"%PDF-1.4 test")
    d = Document(chemin=str(chemin), nom=chemin.name, extension="pdf", hash_sha256=uuid.uuid4().hex * 2,
                 statut="enriched", source="scan", texte_extrait="Facture EDF montant 42")
    db.add(d)
    await db.flush()
    if tags is not None or categorie:
        db.add(MetadonneeIA(document_id=d.id, tags=tags or [], categorie=categorie))
        await db.flush()
    return d


async def test_ranger_deplace_journalise_et_fusionne_les_tags(db_session, racine):
    doc = await _doc(db_session, racine / "inbox" / "scan.pdf", tags=["ia-tag"], categorie="facture")
    profil = ScanProfil(nom="Facture", destination=str(racine / "docs" / "Factures" / "{annee}"), tags=["facture", "ia-tag"])
    scan = Scan(document_id=doc.id, statut="indexe", origine="escl")
    db_session.add_all([profil, scan])
    await db_session.flush()

    r = await svc.ranger(db_session, scan, profil, quand=QUAND)

    cible = racine / "docs" / "Factures" / "2026" / "2026-09-11_facture.pdf"
    assert cible.exists() and not (racine / "inbox" / "scan.pdf").exists()
    assert r["chemin"] == str(cible.resolve()) and doc.nom == cible.name
    assert scan.statut == "range" and scan.profil_id == profil.id
    meta = await db_session.get(MetadonneeIA, (await db_session.execute(
        __import__("sqlalchemy").select(MetadonneeIA.id).where(MetadonneeIA.document_id == doc.id))).scalar_one())
    assert meta.tags == ["ia-tag", "facture"]  # les tags IA restent, ceux du profil s'ajoutent
    move = (await db_session.execute(__import__("sqlalchemy").select(ReorgMove).where(ReorgMove.document_id == doc.id))).scalar_one()
    assert move.chemin_source.endswith("scan.pdf") and move.chemin_dest == r["chemin"]


async def test_ranger_ne_recouvre_pas_un_fichier_existant(db_session, racine):
    (racine / "docs" / "Factures").mkdir()
    (racine / "docs" / "Factures" / "2026-09-11_facture.pdf").write_bytes(b"deja la")
    doc = await _doc(db_session, racine / "inbox" / "scan.pdf")
    profil = ScanProfil(nom="Facture", destination=str(racine / "docs" / "Factures"), tags=[])
    scan = Scan(document_id=doc.id, statut="indexe")
    db_session.add_all([profil, scan])
    await db_session.flush()
    r = await svc.ranger(db_session, scan, profil, quand=QUAND)
    assert r["nom"] == "2026-09-11_facture_(1).pdf"
    assert (racine / "docs" / "Factures" / "2026-09-11_facture.pdf").read_bytes() == b"deja la"


async def test_ranger_avec_nom_choisi_garde_l_extension(db_session, racine):
    doc = await _doc(db_session, racine / "inbox" / "scan.pdf")
    profil = ScanProfil(nom="Facture", destination=str(racine / "docs"), tags=[])
    scan = Scan(document_id=doc.id, statut="indexe")
    db_session.add_all([profil, scan])
    await db_session.flush()
    r = await svc.ranger(db_session, scan, profil, nom="EDF septembre", quand=QUAND)
    assert r["nom"] == "EDF septembre.pdf"


async def test_destination_hors_racine_refusee(db_session, racine, tmp_path):
    doc = await _doc(db_session, racine / "inbox" / "scan.pdf")
    profil = ScanProfil(nom="Ailleurs", destination=str(tmp_path / "ailleurs"), tags=[])
    scan = Scan(document_id=doc.id, statut="indexe")
    db_session.add_all([profil, scan])
    await db_session.flush()
    with pytest.raises(RuntimeError, match="hors de la racine"):
        await svc.ranger(db_session, scan, profil, quand=QUAND)
    assert (racine / "inbox" / "scan.pdf").exists()  # rien n'a bougé


# ─── Boîte : rattacher ce qui est arrivé par le dossier surveillé ────────────────────

async def test_rattacher_nouveaux_est_idempotent(db_session, racine):
    from services import runtime_config
    runtime_config._overrides["scan_boite_chemin"] = "smb://nas/Documents/Scans/"
    for i, statut in enumerate(("enriched", "pending", "error")):
        db_session.add(Document(chemin=f"smb://nas/Documents/Scans/s{i}.pdf", nom=f"s{i}.pdf", extension="pdf",
                                hash_sha256=f"{i}" * 64, statut=statut, source="watch"))
    db_session.add(Document(chemin="smb://nas/Documents/Autre/x.pdf", nom="x.pdf", extension="pdf",
                            hash_sha256="9" * 64, statut="enriched", source="watch"))
    await db_session.flush()

    assert await svc.rattacher_nouveaux(db_session) == 3
    assert await svc.rattacher_nouveaux(db_session) == 0
    boite = await svc.lister_boite(db_session)
    statuts = sorted(s["statut"] for s in boite)
    assert statuts == ["erreur", "indexe", "recu"]
    assert all(s["origine"] == "boite" for s in boite)


async def test_lister_boite_propose_un_profil(db_session, racine):
    doc = await _doc(db_session, racine / "inbox" / "edf.pdf", tags=["edf"], categorie="facture")
    db_session.add(ScanProfil(nom="Facture", destination=str(racine / "docs"), mots_cles=["facture"], tags=[]))
    db_session.add(Scan(document_id=doc.id, statut="indexe"))
    await db_session.flush()
    boite = await svc.lister_boite(db_session)
    assert boite[0]["proposition"]["nom"] == "Facture"
    assert boite[0]["document"]["categorie"] == "facture"


async def test_rattacher_ignore_la_casse_du_partage(db_session, racine):
    """SMB ne distingue pas « scan » de « Scan » ; la boîte ne doit pas le faire non plus."""
    from services import runtime_config
    runtime_config._overrides["scan_boite_chemin"] = "smb://192.168.42.200/scan"
    db_session.add(Document(chemin="smb://192.168.42.200/Scan/facture.pdf", nom="facture.pdf", extension="pdf",
                            hash_sha256="c" * 64, statut="enriched", source="watch"))
    await db_session.flush()
    assert await svc.rattacher_nouveaux(db_session) == 1
