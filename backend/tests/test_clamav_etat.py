"""
Antivirus : « pas pu être scanné » n'est pas « sain ».

Défaut signalé par la session AIGUILLEUR le 06/09/2026, vérifié dans le code : `_scan_sync`
renvoyait `(True, None)` pour un fichier propre COMME pour un fichier qu'il n'avait pas pu
examiner (trop gros pour la limite INSTREAM de clamd, clamd injoignable). L'appelant ne pouvait
pas les distinguer, l'information était perdue à l'indexation — et **plus un fichier était gros,
moins il était protégé** : il suffisait de le rembourrer au-delà de `StreamMaxLength`.

La dégradation gracieuse est conservée (on n'empêche pas l'indexation), mais l'état est
désormais rendu à part et enregistré sur le document, donc retrouvable.
"""

import pytest

from services import clamav_service


class _ClientFactice:
    """Remplace `clamd` : on teste NOTRE logique, pas la sienne."""

    def __init__(self, resultat=None, exception=None):
        self._resultat, self._exception = resultat, exception

    def instream(self, _f):
        if self._exception:
            raise self._exception
        return self._resultat


@pytest.fixture
def actif(monkeypatch):
    monkeypatch.setattr(clamav_service.settings, "clamav_enabled", True, raising=False)
    monkeypatch.setattr(clamav_service.settings, "clamav_host", "clamav", raising=False)


def test_fichier_sain(monkeypatch, actif, tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"contenu")
    monkeypatch.setattr(clamav_service, "_client",
                        lambda: _ClientFactice({"stream": ("OK", None)}))

    indexable, signature, etat = clamav_service._scan_sync(str(f))
    assert (indexable, signature, etat) == (True, None, clamav_service.SAIN)


def test_fichier_infecte_bloque(monkeypatch, actif, tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"contenu")
    monkeypatch.setattr(clamav_service, "_client",
                        lambda: _ClientFactice({"stream": ("FOUND", "Eicar-Test-Signature")}))

    indexable, signature, etat = clamav_service._scan_sync(str(f))
    assert indexable is False
    assert signature == "Eicar-Test-Signature"
    assert etat == clamav_service.INFECTE


def test_trop_gros_est_NON_SCANNE_et_non_SAIN(monkeypatch, actif, tmp_path):
    """
    LE cas du défaut. Le fichier passe (dégradation gracieuse), mais il ne doit surtout pas
    être réputé propre : sinon la protection décroît avec la taille du fichier.
    """
    f = tmp_path / "enorme.zip"
    f.write_bytes(b"x" * 32)
    monkeypatch.setattr(clamav_service, "_client",
                        lambda: _ClientFactice(exception=BufferError("INSTREAM size limit exceeded")))

    indexable, signature, etat = clamav_service._scan_sync(str(f))
    assert indexable is True                      # on ne casse pas le pipeline…
    assert etat == clamav_service.NON_SCANNE      # …mais on ne ment pas non plus
    assert etat != clamav_service.SAIN


def test_clamd_injoignable_est_NON_SCANNE(monkeypatch, actif, tmp_path):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"contenu")
    monkeypatch.setattr(clamav_service, "_client",
                        lambda: _ClientFactice(exception=ConnectionRefusedError()))

    _, _, etat = clamav_service._scan_sync(str(f))
    assert etat == clamav_service.NON_SCANNE


@pytest.mark.asyncio
async def test_antivirus_desactive_a_son_propre_etat(monkeypatch, tmp_path):
    """« Éteint » et « en panne » ne se soignent pas pareil : deux états distincts."""
    monkeypatch.setattr(clamav_service.settings, "clamav_enabled", False, raising=False)
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"contenu")

    indexable, signature, etat = await clamav_service.scan_file(str(f))
    assert (indexable, signature) == (True, None)
    assert etat == clamav_service.DESACTIVE
    assert etat != clamav_service.NON_SCANNE
