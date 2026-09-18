"""
Paramètres — vider un champ le vide vraiment (audit du 18/09/2026).

`PUT /system/config` ignorait toute chaîne vide : l'interface annonce « URL vide = désactivé »
pour la transcription, et vider le champ ne changeait rien. Une chaîne vide garde son sens
« conserver » pour les SEULS secrets (l'interface ne connaît que leur masque et renvoie vide).
"""

import pytest

from services import runtime_config


def _defaut(cle: str) -> str:
    d = runtime_config._DEFAULTS.get(cle)
    return d() if d else ""


class TestViderUnReglage:
    @pytest.mark.asyncio
    async def test_champ_vide_retire_la_surcharge(self, client):
        await client.put("/api/system/config", json={"transcription_url": "http://transcription.lan:8011"})
        r = await client.put("/api/system/config", json={"transcription_url": ""})

        assert r.status_code == 200
        assert r.json()["reinitialises"] == ["transcription_url"]
        entree = r.json()["config"]["transcription_url"]
        assert entree["valeur"] == _defaut("transcription_url")
        assert entree["source"] == "env"

    @pytest.mark.asyncio
    async def test_secret_vide_est_conserve(self, client):
        await client.put("/api/system/config", json={"ha_token": "jeton-secret"})
        r = await client.put("/api/system/config", json={"ha_token": ""})

        assert r.json()["reinitialises"] == []
        assert r.json()["config"]["ha_token"]["defini"] is True
        assert r.json()["config"]["ha_token"]["valeur"] == "••••••••"   # jamais exposé

    @pytest.mark.asyncio
    async def test_champ_absent_n_est_pas_touche(self, client):
        await client.put("/api/system/config", json={"transcription_url": "http://transcription.lan:8011"})
        r = await client.put("/api/system/config", json={"backup_retention": "6"})

        assert r.json()["reinitialises"] == []
        assert r.json()["config"]["transcription_url"]["valeur"] == "http://transcription.lan:8011"
