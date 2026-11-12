"""Synchro : un document qui réapparaît retrouve le statut qu'il mérite, pas « enrichi » d'office."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from models.document import Document
from models.metadata import MetadonneeIA
from services import sync_service


def test_statut_au_retour():
    assert sync_service.statut_au_retour(True, True) == "enriched"
    assert sync_service.statut_au_retour(True, False) == "extracted"    # du texte, jamais de fiche IA
    assert sync_service.statut_au_retour(False, False) == "catalogued"  # photo, vidéo : seulement cataloguée
    assert sync_service.statut_au_retour(False, True) == "enriched"     # image décrite par la vision


def _doc(nom: str, texte: str | None, statut: str = "absent") -> Document:
    return Document(chemin=f"/fictif/{nom}", nom=nom, extension="pdf", hash_sha256=f"hash-{nom}",
                    texte_extrait=texte, statut=statut, source="smb")


@pytest.mark.asyncio
async def test_reactivation_selon_la_fiche_ia(db_session, monkeypatch):
    monkeypatch.setattr(sync_service, "AsyncSessionLocal", async_sessionmaker(db_session.bind, expire_on_commit=False))
    avec, sans, vide_cat, photo, present = (_doc("avec.pdf", "Texte fictif."), _doc("sans.pdf", "Texte fictif."),
                                            _doc("vide.pdf", "Texte fictif."), _doc("photo.jpg", None),
                                            _doc("present.pdf", "Texte fictif.", statut="error"))
    db_session.add_all([avec, sans, vide_cat, photo, present])
    await db_session.flush()
    db_session.add_all([MetadonneeIA(document_id=avec.id, categorie="Facture"),
                        MetadonneeIA(document_id=vide_cat.id, categorie=None)])   # fiche vide = pas de fiche
    await db_session.commit()

    n = await sync_service._reactiver([{"id": d.id} for d in (avec, sans, vide_cat, photo, present)])

    assert n == 5
    for d in (avec, sans, vide_cat, photo, present):
        await db_session.refresh(d)
    assert avec.statut == "enriched"
    assert sans.statut == "extracted" and vide_cat.statut == "extracted"   # repris par « Relancer l'IA »
    assert photo.statut == "catalogued"
    assert present.statut == "error"            # pas « absent » : on n'y touche pas


@pytest.mark.asyncio
async def test_reactivation_sans_rien():
    assert await sync_service._reactiver([]) == 0
