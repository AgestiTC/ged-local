"""
Cause LISIBLE d'un échec de l'IA dans le comparatif (04/11/2026 : « une réponse claire, pas juste
erreur »). Ne regarde que la FORME d'une réponse ou le TYPE d'une erreur — jamais le contenu des
offres (confidentiel) : la cause s'affiche à l'utilisateur et part dans les journaux.
"""
from __future__ import annotations

import httpx

# Au-delà, ce n'est plus un objet de valeurs courtes mais un texte rédigé (une cellule = 900 car.).
REPONSE_REDIGEE = 3_000

# Second tirage après une boucle : on pénalise la répétition et on varie un peu plus le choix.
OPTIONS_ANTI_BOUCLE = {"repeat_penalty": 1.2, "repeat_last_n": 256, "temperature": 0.5}

BOUCLE = "l'IA s'est mise à répéter le même texte en boucle (Ollama l'a coupée)"
DELAI = "délai dépassé : l'IA n'a pas répondu à temps (GPU très chargé ?)"
INJOIGNABLE = "IA injoignable (Ollama / AIGUILLEUR)"
COUPEE = ("réponse trop longue, coupée avant la fin : l'IA rédige au lieu de remplir les champs — "
          "vos consignes demandent sans doute un rapport complet ; le comparatif attend une valeur courte par critère")
REDIGEE = ("l'IA a rédigé une analyse au lieu de remplir les critères demandés — vos consignes "
           "demandent sans doute un rapport complet ; le comparatif attend une valeur courte par critère")
CLES = "l'IA a répondu en JSON, mais sous d'autres rubriques que les critères demandés"
VIDE = "réponse vide de l'IA"
ILLISIBLE = "réponse de l'IA sans JSON lisible"


def cause_erreur(e: BaseException) -> str:
    """Erreur d'APPEL (exception) → cause lisible."""
    # tenacity enveloppe la dernière erreur dans un RetryError : on la déballe d'abord
    dernier = getattr(getattr(e, "last_attempt", None), "exception", None)
    if callable(dernier) and dernier() is not None and dernier() is not e:
        return cause_erreur(dernier())
    texte = str(e).lower()
    if isinstance(e, httpx.HTTPStatusError):   # le motif d'Ollama est dans le CORPS, pas dans str(e)
        try:
            texte += " " + e.response.text.lower()
        except Exception:  # noqa: BLE001 — corps illisible : on garde str(e)
            pass
    if "repeat" in texte:   # Ollama : « prediction aborted, token repeat limit reached »
        return BOUCLE
    if isinstance(e, httpx.TimeoutException) or "timeout" in type(e).__name__.lower():
        return DELAI
    if isinstance(e, httpx.ConnectError) or "connect" in type(e).__name__.lower():
        return INJOIGNABLE
    if isinstance(e, httpx.HTTPStatusError):
        return f"l'IA a renvoyé une erreur HTTP {e.response.status_code}"
    return f"appel à l'IA impossible ({type(e).__name__})"


def cause_reponse(reponse: str | None) -> str:
    """Réponse REÇUE mais inexploitable → cause lisible (d'après sa forme seulement)."""
    texte = (reponse or "").strip()
    if not texte:
        return VIDE
    ouvert, ferme = "{" in texte, texte.rstrip("` \n").endswith("}")
    if ouvert and not ferme:
        return COUPEE
    if len(texte) > REPONSE_REDIGEE:
        return REDIGEE
    if ouvert:
        return CLES
    return ILLISIBLE


def cause_dominante(causes: list[str]) -> str | None:
    """La cause la plus fréquente (ordre d'apparition en cas d'égalité)."""
    if not causes:
        return None
    return max(dict.fromkeys(causes), key=causes.count)
