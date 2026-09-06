"""
`keep_alive` : ce qui part vraiment vers Ollama.

Régression mesurée le 05/09/2026 par la capture E0 d'AIGUILLEUR sur la PRODUCTION
(192.168.42.83). `_keep_alive_for()` renvoyait la **chaîne** `"-1"` pour le modèle épinglé.
Ollama attend une durée Go (« 30m », « -1s ») ou un **nombre de secondes** : `"-1"` n'est ni
l'un ni l'autre, et part en HTTP 400 (`time: missing unit in duration "-1"`) en 1 ms.

488 refus en 7 h 30, soit 9,5 % du trafic de la carte — invisibles, parce que le repli
« même famille » prenait le relais et qu'aucun code de retour n'était regardé. Conséquence :
l'enrichissement ne tournait jamais sur llama3.1, et la chaîne de repli finissait par charger
un modèle de 41 Gio dont le débordement faisait évincer… le llama3.1 épinglé que ce code
protège.

D'où l'assertion sur le TYPE, et pas seulement sur la valeur : `-1` et `"-1"` sont deux
choses différentes pour Ollama, et c'est toute l'histoire.
"""

import pytest

from services.ollama_service import OllamaService, settings


@pytest.fixture
def epingle(monkeypatch):
    monkeypatch.setattr(settings, "ollama_pinned_model", "llama3.1:latest", raising=False)
    monkeypatch.setattr(settings, "ollama_keep_alive", "30m", raising=False)


class TestKeepAlivePourModele:
    def test_modele_epingle_recoit_un_ENTIER(self, epingle):
        """`-1` l'entier (secondes) est accepté ; `"-1"` la chaîne est refusée en 400."""
        valeur = OllamaService._keep_alive_for("llama3.1:latest")
        assert valeur == -1
        assert isinstance(valeur, int) and not isinstance(valeur, str)

    def test_comparaison_sur_la_famille_pas_le_tag(self, epingle):
        """`llama3.1` et `llama3.1:latest` désignent le même modèle épinglé."""
        assert OllamaService._keep_alive_for("llama3.1") == -1
        assert OllamaService._keep_alive_for("LLAMA3.1:8b") == -1

    def test_autres_modeles_gardent_le_defaut(self, epingle):
        """Un modèle non épinglé ne doit surtout pas rester résident indéfiniment."""
        assert OllamaService._keep_alive_for("Qwen3.6-35B:latest") == "30m"
        assert OllamaService._keep_alive_for("qwen3-embedding:8b") == "30m"
        assert OllamaService._keep_alive_for(None) == "30m"

    def test_sans_modele_epingle_configure(self, monkeypatch):
        """Aucun épinglage configuré → personne n'est traité à part."""
        monkeypatch.setattr(settings, "ollama_pinned_model", "", raising=False)
        monkeypatch.setattr(settings, "ollama_keep_alive", "30m", raising=False)
        assert OllamaService._keep_alive_for("llama3.1:latest") == "30m"
