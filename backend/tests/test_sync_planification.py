"""
Tests de la règle d'échéance des synchros automatiques (`job_worker.synchro_due`).

Cette règle décide seule si une source est re-scannée. Trop laxiste, elle relance un walk
réseau de dizaines de milliers de fichiers à chaque tick ; trop stricte, la synchro « auto »
ne se déclenche jamais.
"""

from datetime import datetime, timedelta, timezone

import pytest

from services.job_worker import synchro_due

MAINTENANT = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("intervalle", [None, 0, -5])
def test_intervalle_absent_ou_nul_desactive_la_synchro(intervalle):
    assert synchro_due(MAINTENANT - timedelta(days=30), intervalle, MAINTENANT) is False


def test_jamais_synchronisee_est_due_immediatement():
    assert synchro_due(None, 360, MAINTENANT) is True


def test_pas_due_avant_l_echeance():
    """Sans cette borne, chaque tick (5 min) relancerait un walk complet du NAS."""
    assert synchro_due(MAINTENANT - timedelta(hours=2), 360, MAINTENANT) is False


def test_due_une_fois_l_intervalle_ecoule():
    assert synchro_due(MAINTENANT - timedelta(hours=6), 360, MAINTENANT) is True


def test_due_pile_a_l_echeance():
    assert synchro_due(MAINTENANT - timedelta(minutes=60), 60, MAINTENANT) is True


def test_desactivation_prime_sur_une_echeance_depassee():
    """Passer l'intervalle à 0 doit couper la synchro, même très en retard."""
    assert synchro_due(MAINTENANT - timedelta(days=365), 0, MAINTENANT) is False
