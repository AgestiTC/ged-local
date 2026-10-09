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
        lambda self, *_a, **_k: httpx.AsyncClient(base_url="http://tika", transport=httpx.MockTransport(repondre)))
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
    assert delai.connect == tika_service.CONNEXION_S and delai.read == get_settings().tika_timeout


# ─── Principal (PC-GAME) et repli (LXC) ─────────────────────────────────────
# 09/10/2026 : 19 s sur PC-GAME contre 169 s sur le LXC pour le même scan. PC-GAME s'éteint :
# le LXC prend le relais, sans jamais renvoyer un fichier dont l'extraction a commencé.

def _deux_tika(monkeypatch, principal, repli):
    """TikaService avec réglages `tika_url` / `tika_url_repli`, chaque hôte simulé à part."""
    from services import runtime_config
    monkeypatch.setitem(runtime_config._overrides, "tika_url", "http://pc-game:9997")
    monkeypatch.setitem(runtime_config._overrides, "tika_url_repli", "http://lxc:9998")
    vrai = httpx.AsyncClient

    def router(requete):
        return (principal if requete.url.host == "pc-game" else repli)(requete)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: vrai(transport=httpx.MockTransport(router), **kw))
    tika_service._verrous.clear()
    tika_service._sante.clear()
    return TikaService()


def _ok(requete):
    if requete.url.path == "/version":
        return httpx.Response(200, text="Apache Tika 4.0.0")
    return httpx.Response(200, json=[{"tk:content": requete.url.host}])


def _eteint(requete):
    raise httpx.ConnectError("hôte éteint", request=requete)


@pytest.mark.asyncio
async def test_le_principal_est_utilise_quand_il_repond(monkeypatch, fichier):
    tika = _deux_tika(monkeypatch, _ok, _ok)
    assert await tika.extract_metadata(fichier) == [{"tk:content": "pc-game"}]


@pytest.mark.asyncio
async def test_principal_eteint_le_repli_prend_le_relais(monkeypatch, fichier):
    tika = _deux_tika(monkeypatch, _eteint, _ok)
    assert await tika.extract_metadata(fichier) == [{"tk:content": "lxc"}]
    assert await tika.check_health() is True


@pytest.mark.asyncio
async def test_principal_qui_tombe_entre_sonde_et_envoi(monkeypatch, fichier):
    """La sonde l'a vu vivant, la connexion échoue : rien n'a été traité, on bascule."""
    def sonde_ok_envoi_ko(requete):
        return _ok(requete) if requete.url.path == "/version" else _eteint(requete)

    tika = _deux_tika(monkeypatch, sonde_ok_envoi_ko, _ok)
    assert await tika.extract_metadata(fichier) == [{"tk:content": "lxc"}]


@pytest.mark.asyncio
async def test_une_extraction_commencee_n_est_jamais_renvoyee_au_repli(monkeypatch, fichier):
    """Délai de lecture dépassé sur le principal : il TRAVAILLE — renvoyer doublerait l'OCR."""
    repli_appele = []

    def lent(requete):
        if requete.url.path == "/version":
            return httpx.Response(200, text="ok")
        raise httpx.ReadTimeout("OCR trop long", request=requete)

    def repli(requete):
        repli_appele.append(requete)
        return _ok(requete)

    tika = _deux_tika(monkeypatch, lent, repli)
    with pytest.raises(httpx.ReadTimeout):
        await tika.extract_metadata(fichier)
    assert repli_appele == []


def test_une_url_imposee_n_a_pas_de_repli(monkeypatch):
    """« Tester la connexion » d'un réglage doit dire si CETTE adresse répond."""
    from services import runtime_config
    monkeypatch.setitem(runtime_config._overrides, "tika_url_repli", "http://lxc:9998")
    assert TikaService(base_url="http://pc-game:9997").repli == ""
