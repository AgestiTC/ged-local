"""Vigie de la boucle asyncio : un blocage synchrone doit laisser une trace dans les logs."""
import asyncio
import time

from structlog.testing import capture_logs

from services import vigie_boucle


async def test_blocage_journalise():
    with capture_logs() as logs:
        vigie_boucle.start(seuil_lent=0.5, seuil_piles=60.0)
        await asyncio.sleep(1.2)          # premier battement normal
        time.sleep(1.5)                   # code synchrone qui confisque la boucle
        await asyncio.sleep(1.2)          # laisse le battement suivant constater le retard
        await vigie_boucle.stop()
    gels = [e for e in logs if e["event"] == "Boucle asyncio bloquée"]
    assert len(gels) == 1
    # Retard = blocage moins ce qui restait du battement en cours : entre 0,5 et 1,5 s ici.
    assert 0.5 <= gels[0]["retard_s"] <= 1.6
    assert gels[0]["piles_ecrites"] is False


async def test_boucle_fluide_silencieuse():
    with capture_logs() as logs:
        vigie_boucle.start(seuil_lent=0.5, seuil_piles=60.0)
        await asyncio.sleep(2.2)
        await vigie_boucle.stop()
    assert not [e for e in logs if e["event"] == "Boucle asyncio bloquée"]


async def test_start_idempotent_et_stop_sans_start():
    await vigie_boucle.stop()             # ne doit pas lever
    vigie_boucle.start()
    tache = vigie_boucle._tache
    vigie_boucle.start()
    assert vigie_boucle._tache is tache
    await vigie_boucle.stop()
    assert vigie_boucle._tache is None
