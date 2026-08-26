"""
Tests du service de transcription audio (`services.transcription_service`) et du routage média.

Fonctions PURES / logique de décision : extraction du texte d'une réponse (formats variés),
activation par présence d'URL, et routage `media_a_cataloguer` (audio → extraction quand la
transcription est active, sinon catalogage média). L'appel réseau lui-même n'est pas testé ici.
"""

from unittest.mock import patch

from services import transcription_service as ts
from services.folder_watcher import media_a_cataloguer


# ── Extraction du texte de la réponse ───────────────────────────────────────────

def test_extraire_texte_champ_text():
    assert ts._extraire_texte({"text": "  Bonjour le monde  "}) == "Bonjour le monde"


def test_extraire_texte_segments():
    # Chaque segment est strippé puis joint par un espace simple.
    payload = {"segments": [{"text": "Première "}, {"text": "phrase."}]}
    assert ts._extraire_texte(payload) == "Première phrase."


def test_extraire_texte_chaine_brute():
    assert ts._extraire_texte("texte simple") == "texte simple"


def test_extraire_texte_vide_ou_inconnu():
    assert ts._extraire_texte({}) == ""
    assert ts._extraire_texte({"autre": 1}) == ""
    assert ts._extraire_texte(None) == ""


# ── Activation ──────────────────────────────────────────────────────────────────

def test_desactive_si_url_vide():
    with patch("services.transcription_service.runtime_config.effective", return_value=""):
        assert ts.is_enabled() is False


def test_active_si_url_presente():
    with patch("services.transcription_service.runtime_config.effective", return_value="http://localhost:8001"):
        assert ts.is_enabled() is True
        assert ts._base_url() == "http://localhost:8001"  # slash final retiré via rstrip


# ── Routage média (audio → extraction si transcription active) ──────────────────

def test_audio_catalogue_si_transcription_off():
    with patch("services.transcription_service.is_enabled", return_value=False):
        assert media_a_cataloguer("mp3") is True   # catalogué comme un média classique


def test_audio_extrait_si_transcription_on():
    # Transcription active → l'audio n'est PAS seulement catalogué : il passe à l'extraction.
    with patch("services.transcription_service.is_enabled", return_value=True):
        assert media_a_cataloguer("mp3") is False
        assert media_a_cataloguer("m4a") is False


def test_image_toujours_cataloguee():
    with patch("services.transcription_service.is_enabled", return_value=True):
        assert media_a_cataloguer("jpg") is True    # une image reste un média catalogué


def test_document_texte_non_media():
    assert media_a_cataloguer("pdf") is False       # pas un média → traité normalement (pas « catalogué »)
