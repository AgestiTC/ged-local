"""
Modèles externes (GECO) — liste en LECTURE SEULE + garde-fou « modèle installé »
===============================================================================
Plan docs/plan-liste-modeles.md, étape 1.

Les modèles servis par LONG-COURRIER (IA externe de GECO) sont AFFICHÉS dans leur groupe. Ils ne
sont PAS ENCORE utilisables : Matothèque n'a aucun chemin vers LONG-COURRIER (étape 5 du plan —
choix explicite, sortie internet confirmée). D'ici là, ce module fait deux choses, et seulement :

  1. `lire_externes()` — lit la liste (forme OpenAI `{"data":[{"id": …}]}`) à l'adresse du
     réglage `modeles_externes_url` (vide = rien n'est lu, aucun appel sortant). Un GET, sans
     corps ; seuls les en-têtes de projet habituels partent. Jamais d'exception : toute panne
     devient l'état « injoignable ».
  2. `exiger_modele_installe()` — garde-fou UNIQUE des routes de génération : un modèle
     explicite absent d'Ollama est refusé en 400. Griser une option dans l'interface ne garantit
     pas qu'aucun document ne sorte ; ce contrôle, si.

Aucun état en mémoire : la liste est relue à chaque appel (uvicorn tourne avec 2 processus).
"""

import asyncio
import json
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from logger import get_logger
from services import runtime_config
from services.ollama_service import OllamaService, entetes_projet

log = get_logger(__name__)

ETAT_NON_CONFIGURE = "non_configure"
ETAT_DISPONIBLE = "disponible"
ETAT_INJOIGNABLE = "injoignable"

# Délai TOTAL (connexion + lecture) accordé à la lecture de la liste : l'écran des modèles ne doit
# jamais attendre LONG-COURRIER plus longtemps.
DELAI_S = 3.0

# Délai TOTAL du contrôle « modèle installé ». Le client Ollama a un délai de lecture de 30 min
# (les générations sont longues) : sans cette borne, un Ollama qui accepte la connexion sans
# répondre aurait suspendu chaque génération jusqu'à 30 min AVANT son premier octet.
DELAI_CONTROLE_S = 3.0


def _avec_tag(nom: str) -> str:
    """`llama3.1` et `llama3.1:latest` désignent le même modèle pour Ollama : on compare tagué.

    Le tag est ce qui suit le dernier « : » APRÈS le dernier « / » (`hf.co/org/modele` n'en a pas,
    et un hôte avec port — `hote:5000/modele` — non plus).
    """
    return nom if ":" in nom.rsplit("/", 1)[-1] else f"{nom}:latest"


# Bornes de la réponse : le délai limite la DURÉE, pas le volume — sur un réseau local rapide,
# 3 s suffisent à charger des centaines de Mo en mémoire, dans chacun des processus.
TAILLE_MAX_OCTETS = 1024 * 1024
NB_MAX_MODELES = 500
LONGUEUR_MAX_NOM = 200


def url_acceptable(url: str) -> bool:
    """
    Adresse http(s), SANS identifiants (`http://u:p@hote`) ni paramètres (`?cle=…`).

    Un jeton collé dans l'adresse ressortirait en clair dans les journaux et dans
    `GET /api/system/config`. Si la liste exige un jour une clé, elle ira dans un réglage chiffré.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    return (parts.scheme.lower() in ("http", "https") and bool(parts.hostname)
            and not parts.username and not parts.password and not parts.query)


async def _lire(url: str) -> list[str]:
    """GET de la liste ; lève une exception à la moindre anomalie (traitée par `lire_externes`)."""
    corps = bytearray()
    async with httpx.AsyncClient(timeout=DELAI_S, follow_redirects=False) as client:
        async with client.stream("GET", url, headers=entetes_projet()) as reponse:
            reponse.raise_for_status()
            async for morceau in reponse.aiter_bytes():
                corps.extend(morceau)
                if len(corps) > TAILLE_MAX_OCTETS:
                    raise ValueError("réponse trop volumineuse")
    donnees = json.loads(corps)
    if not isinstance(donnees, dict) or not isinstance(donnees.get("data"), list):
        raise ValueError("forme de réponse inattendue (attendu : {\"data\": [...]})")
    noms: set[str] = set()
    for entree in donnees["data"]:
        identifiant = entree.get("id") if isinstance(entree, dict) else None
        if isinstance(identifiant, str) and 0 < len(identifiant.strip()) <= LONGUEUR_MAX_NOM:
            noms.add(identifiant.strip())
    return sorted(noms, key=lambda n: (n.casefold(), n))[:NB_MAX_MODELES]


async def lire_externes() -> tuple[str, list[dict]]:
    """
    Liste des modèles GECO : `(état, modèles)`. Chaque modèle vaut
    `{"name", "origine": "GECO", "selectionnable": False}`, triés par nom (insensible à la casse).
    État : `non_configure` (URL vide, aucun appel) | `disponible` | `injoignable` (panne, lenteur,
    réponse malformée, adresse non http(s)). Ne lève jamais.
    """
    url = runtime_config.effective("modeles_externes_url").strip()
    if not url:
        return ETAT_NON_CONFIGURE, []
    if not url_acceptable(url):
        log.warning("Liste des modèles GECO : adresse refusée (http/https, sans identifiants ni paramètres)")
        return ETAT_INJOIGNABLE, []
    try:
        noms = await asyncio.wait_for(_lire(url), timeout=DELAI_S)
    except Exception as exc:  # noqa: BLE001 — la liste GECO est facultative : jamais bloquante
        # Jamais `str(exc)` : httpx y met l'adresse complète.
        statut = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        log.warning("Liste des modèles GECO injoignable", erreur=type(exc).__name__, statut_http=statut)
        return ETAT_INJOIGNABLE, []
    return ETAT_DISPONIBLE, [{"name": n, "origine": "GECO", "selectionnable": False} for n in noms]


async def exiger_modele_installe(demande: str | None) -> None:
    """
    Refuse (HTTP 400, message en français) un modèle EXPLICITE qui n'est pas installé sur Ollama.

    - Vide / None = « Auto » (routage par usage) : inchangé, aucun contrôle, aucun appel.
    - Modèle présent dans `OllamaService.list_models` : accepté.
    - Sinon : 400. Le message distingue un modèle GECO (affiché mais non utilisable) d'un modèle
      simplement inconnu (désinstallé, saisie périmée).
    - Ollama INJOIGNABLE au moment du contrôle : on ne peut pas affirmer que le modèle est
      inconnu, donc on ne l'invente pas — on laisse passer vers l'erreur « IA injoignable »
      existante de la route. Exception : un modèle figurant dans la liste GECO connue est refusé
      quand même (c'est lui qu'on ne doit jamais appeler, Ollama joignable ou non).
    - Un Ollama qui ne répond pas en `DELAI_CONTROLE_S` compte comme injoignable.
    - `nom` et `nom:latest` sont le même modèle (Ollama sert l'un pour l'autre).
    """
    modele = (demande or "").strip()
    if not modele:
        return
    try:
        installes: list[str] | None = await asyncio.wait_for(
            OllamaService().list_models(), timeout=DELAI_CONTROLE_S)
    except Exception as exc:  # noqa: BLE001 — Ollama injoignable ou muet : voir docstring
        log.warning("Contrôle du modèle : Ollama injoignable", modele=modele,
                    erreur=str(exc) or type(exc).__name__)
        installes = None
    if installes is not None and _avec_tag(modele) in {_avec_tag(n) for n in installes}:
        return
    _etat, externes = await lire_externes()
    if any(m["name"] == modele for m in externes):
        log.warning("Modèle GECO refusé", modele=modele)
        raise HTTPException(
            status_code=400,
            detail=f"Le modèle « {modele} » est un modèle GECO (IA externe) : il n'est pas encore "
                   "utilisable depuis Matothèque. Choisissez un modèle MATO installé sur Ollama, "
                   "ou laissez « Auto ».")
    if installes is None:
        return
    log.warning("Modèle non installé refusé", modele=modele)
    raise HTTPException(
        status_code=400,
        detail=f"Le modèle « {modele} » n'est pas installé sur Ollama. Choisissez un modèle de la "
               "liste, ou laissez « Auto ».")
