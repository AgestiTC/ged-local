"""
Classement des échecs d'un appel IA — un seul endroit (plan lots IA par modèle, étape 5)
========================================================================================
Trois natures, trois conduites :

- PASSAGER : la carte est saturée, la passerelle a coupé, le réseau a flanché. Rien n'est cassé,
  mais il ne faut surtout PAS changer de modèle (un modèle de plus à charger sur une carte déjà
  pleine, mesuré le 12/11 : 27 appels `/api/embed` en 504 en 40 min) ni rejouer tout de suite :
  le job est REPORTÉ (cf. `job_worker`).
- MODÈLE ABSENT : Ollama ne connaît pas le modèle demandé. Seul cas où un autre modèle a un sens.
- DÉFINITIF : tout le reste (réponse inexploitable, fichier illisible, erreur de programmation…).
  Rejouer ne changerait rien : le job échoue, lisiblement.

Fonctions PURES, sans réseau ni base. `generate()` et `embed()` d'`OllamaService` sont décorés par
tenacity SANS `reraise` : quand leurs essais sont épuisés, l'exception qui sort est un `RetryError`
qui ENVELOPPE la vraie. On la déballe ici, sinon un 504 ressemblerait à une erreur de programmation.
"""
from __future__ import annotations

import asyncio

import httpx

PASSAGER = "passager"
MODELE_ABSENT = "modele_absent"
DEFINITIF = "definitif"

# Codes HTTP d'un incident passager : trop de demandes, panne ou saturation du serveur, de la
# passerelle ou du modèle, délai dépassé (la passerelle coupe à 300 s : HTTP 504).
CODES_PASSAGERS = frozenset({429, 500, 502, 503, 504})
# « Réessaie plus tard » de la passerelle (pause des lots, voix en cours…), quel que soit le code.
_MOTIFS_REESSAYER = ("reessaie plus tard", "réessaie plus tard", "reessayez plus tard", "réessayez plus tard",
                     r"r\u00e9essaie plus tard",        # JSON échappé par le serveur (texte brut)
                     "retry later", "try again later", "retry-after")


class EchecPassager(Exception):
    """
    Incident passager d'un appel IA, déjà décrit en clair. C'est la SEULE exception que le worker reporte
    (étape 5) : elle n'est levée qu'aux points d'appel de l'IA (enrichissement, lecture d'images,
    embeddings), jamais pour une erreur de Tika, du NAS ou de l'antivirus.
    `resume` = la cause seule (« délai dépassé à la passerelle (HTTP 504) ») ; le message complet nomme
    l'étape (« IA indisponible pour les embeddings : … »).
    """

    def __init__(self, resume: str, contexte: str | None = None):
        super().__init__(f"IA indisponible pour {contexte} : {resume}" if contexte else resume)
        self.resume = resume


class ModeleAbsent(RuntimeError):
    """Le modèle demandé n'existe pas dans Ollama. Le message nomme le modèle et dit quoi faire."""

    def __init__(self, modele: str, message: str):
        super().__init__(message)
        self.modele = modele


def cause_reelle(exc: BaseException | None) -> BaseException | None:
    """L'exception d'origine sous l'enveloppe `tenacity.RetryError` (rendue telle quelle sinon)."""
    dernier = getattr(getattr(exc, "last_attempt", None), "exception", None)
    if callable(dernier):
        try:
            interne = dernier()
        except Exception:  # noqa: BLE001 — tentative sans exception exploitable : on garde l'enveloppe
            interne = None
        if interne is not None and interne is not exc:
            return cause_reelle(interne)
    return exc


def _corps(exc: httpx.HTTPStatusError) -> str:
    try:
        return (exc.response.text or "").lower()
    except Exception:  # noqa: BLE001 — réponse en flux non lue
        return ""


def _modele_introuvable(texte: str) -> bool:
    """Le message d'Ollama dit-il que le MODÈLE n'existe pas ? (`model "x" not found, try pulling it first`)"""
    return ("model" in texte and "not found" in texte) or "try pulling it first" in texte


def classer_echec(exc: BaseException | None) -> str:
    """`PASSAGER`, `MODELE_ABSENT` ou `DEFINITIF` pour l'exception levée par un appel IA."""
    exc = cause_reelle(exc)
    if exc is None:
        return DEFINITIF
    if isinstance(exc, EchecPassager):
        return PASSAGER
    if isinstance(exc, ModeleAbsent):
        return MODELE_ABSENT
    if isinstance(exc, httpx.HTTPStatusError):
        texte = _corps(exc)
        code = exc.response.status_code
        if code == 404 and _modele_introuvable(texte):
            return MODELE_ABSENT
        # « Réessaie plus tard » : seulement sur un code d'incident (>= 429) — sinon n'importe quelle page
        # d'erreur qui contient ces mots (400, 404…) ferait passer une erreur définitive pour passagère.
        if code in CODES_PASSAGERS or (code >= 429 and any(m in texte for m in _MOTIFS_REESSAYER)):
            return PASSAGER
        return DEFINITIF
    if isinstance(exc, httpx.UnsupportedProtocol):      # URL mal formée : une faute de réglage, pas un incident
        return DEFINITIF
    if isinstance(exc, (httpx.TransportError, asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return PASSAGER                                  # délai, connexion, protocole : l'incident passe
    return DEFINITIF


def decrire_echec(exc: BaseException | None) -> str:
    """Motif COURT et lisible d'un échec, pour l'écran « Tâches » : jamais de contenu de document."""
    exc = cause_reelle(exc)
    if isinstance(exc, EchecPassager):
        return exc.resume
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 504:
            return "délai dépassé à la passerelle (HTTP 504)"
        if code == 429:
            return "IA surchargée (HTTP 429)"
        if code >= 429 and any(m in _corps(exc) for m in _MOTIFS_REESSAYER):
            return f"passerelle IA : réessayer plus tard (HTTP {code})"
        return f"erreur du serveur IA (HTTP {code})"
    if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError, TimeoutError)):
        return "délai dépassé (l'IA n'a pas répondu à temps)"
    if isinstance(exc, (httpx.ConnectError, ConnectionError)):
        return "IA injoignable"
    if isinstance(exc, httpx.TransportError):
        return "connexion à l'IA interrompue"
    if exc is None:
        return "erreur inconnue"
    return (str(exc) or type(exc).__name__)[:200]
