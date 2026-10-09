"""
Tests — Matothèque n'engorge plus Tika
=====================================
09/10/2026 : 300 documents en erreur « ReadTimeout ». Le worker envoyait jusqu'à 5 fichiers à la
fois à un Tika sur 2 cœurs, avec 60 s de délai et 3 essais — chaque délai dépassé renvoyait le
même fichier pendant que Tika y travaillait encore. Trois règles vérifiées ici : extractions
bornées, délai de lecture long, aucun nouvel essai sur un délai dépassé.
"""

import asyncio

import httpx
import pytest

from config import get_settings
from services import tika_service
from services.tika_service import TikaService


@pytest.fixture
def fichier(tmp_path):
    f = tmp_path / "scan.pdf"
    f.write_bytes(b"%PDF-1.4")
    return f


def _tika_simule(monkeypatch, repondre):
    """Remplace le client HTTP de TikaService par un transport simulé."""
    monkeypatch.setattr(
        TikaService, "_get_client",
        lambda self: httpx.AsyncClient(base_url="http://tika", transport=httpx.MockTransport(repondre)))
    tika_service._verrous.clear()
    return TikaService(base_url="http://tika")


@pytest.mark.asyncio
async def test_une_seule_extraction_a_la_fois(monkeypatch, fichier):
    en_cours, pic = 0, 0

    async def repondre(_requete):
        nonlocal en_cours, pic
        en_cours += 1
        pic = max(pic, en_cours)
        await asyncio.sleep(0.02)
        en_cours -= 1
        return httpx.Response(200, json=[{"tk:content": "texte"}])

    tika = _tika_simule(monkeypatch, repondre)
    resultats = await asyncio.gather(*(tika.extract_metadata(fichier) for _ in range(5)))

    assert len(resultats) == 5 and pic == get_settings().tika_concurrence == 1


@pytest.mark.asyncio
async def test_un_delai_depasse_n_est_pas_retente(monkeypatch, fichier):
    """Tika travaille encore sur le premier envoi : le renvoyer doublerait la charge."""
    appels = 0

    def repondre(requete):
        nonlocal appels
        appels += 1
        raise httpx.ReadTimeout("OCR trop long", request=requete)

    tika = _tika_simule(monkeypatch, repondre)
    with pytest.raises(httpx.ReadTimeout):
        await tika.extract_metadata(fichier)
    assert appels == 1


@pytest.mark.asyncio
async def test_une_coupure_reseau_reste_retentee(monkeypatch, fichier):
    appels = 0

    def repondre(requete):
        nonlocal appels
        appels += 1
        if appels == 1:
            raise httpx.ConnectError("Tika redémarre", request=requete)
        return httpx.Response(200, json=[{"tk:content": "texte"}])

    monkeypatch.setattr(TikaService.extract_metadata.retry, "wait", lambda *_a, **_k: 0)
    tika = _tika_simule(monkeypatch, repondre)
    assert await tika.extract_metadata(fichier) == [{"tk:content": "texte"}]
    assert appels == 2


def test_le_delai_de_lecture_laisse_le_temps_a_un_gros_scan():
    from config import Settings
    assert Settings.model_fields["tika_timeout_ms"].default >= 600_000
    delai = TikaService(base_url="http://tika")._get_client().timeout
    assert delai.connect == 10.0 and delai.read == get_settings().tika_timeout
