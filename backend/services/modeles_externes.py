"""
Modèles externes (GECO) — liste, résolution du modèle, recontrôle du worker, journal
===================================================================================
Plan docs/plan-liste-modeles.md, étapes 1 et 5a.

  - `lire_externes()` — lit la liste GECO (réglage `modeles_externes_url`, vide = aucun appel).
    Jamais d'exception : toute panne devient l'état « injoignable ».
  - `resoudre_modele_interactif()` — résolution UNIQUE, côté serveur, du modèle des routes
    interactives. RÈGLE : aucun accès à GECO tant que le bouton « IA GECO » (`ia_destination`) n'est
    pas activé ; le doute refuse (503).
  - `controle_job()` — recontrôle du worker avant d'exécuter un job portant un modèle `geco/…`.
  - `journaliser_bascule()` — journal d'activité de la bascule ; l'envoi lui-même est journalisé par `OllamaService` (fail-closed).

Aucun état en mémoire : tout est relu à chaque appel (2 processus uvicorn + worker).
"""

import asyncio
import json
from contextlib import nullcontext
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from logger import get_logger
from services import audit, runtime_config
from services.ollama_service import (
    PLAFOND_GECO_OCTETS, OllamaService, authentification_en_base, destination_en_base, entetes_projet, est_geco,
    sortie_geco_autorisee,
)

log = get_logger(__name__)

ORIGINE_MATO = "MATO"
ORIGINE_GECO = "GECO"
DESTINATION_LOCAL = "local"
DESTINATION_GECO = "geco"
# Types de jobs autorisés à envoyer vers GECO : l'interactif de « Créer » (jamais musique/vidéo ni les lots).
TYPES_JOB_GECO = frozenset({"rapport", "fill_template", "comparatif", "analyse_regroupement", "presentation"})

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
    # Sélectionnable = utilisable pour de vrai : bouton « IA GECO » activé ET acteur administrateur, nom en `geco/…` (contrat de
    # l'AIGUILLEUR), et pas un modèle d'embeddings (`embedding: true` : l'interface le masque).
    actif = destination_ia() == DESTINATION_GECO and acteur_administrateur()   # IA GECO réservée aux admins
    return ETAT_DISPONIBLE, [{"name": n, "origine": ORIGINE_GECO, "embedding": est_embedding(n),
                              "selectionnable": actif and est_geco(n) and not est_embedding(n)} for n in noms]


async def tester_liste(url: str) -> dict:
    """
    Bouton « Tester » des Paramètres : lit la liste à l'adresse DONNÉE (pas forcément enregistrée) et
    dit ce qu'elle contient. Rend `{"ok", "nb", "nb_texte", "erreur"}` ; ne lève jamais.
    `nb_texte` = modèles utilisables pour du texte (`geco/…`, hors embeddings). Le message d'erreur
    ne reprend jamais le texte de l'exception : httpx y met l'adresse complète.
    """
    url = (url or "").strip()
    if not url:
        return {"ok": False, "nb": 0, "nb_texte": 0, "erreur": "aucune adresse saisie"}
    if not url_acceptable(url):
        return {"ok": False, "nb": 0, "nb_texte": 0,
                "erreur": "adresse refusée : http:// ou https://, sans identifiants ni paramètres (« ? »)"}
    try:
        noms = await asyncio.wait_for(_lire(url), timeout=DELAI_S)
    except httpx.HTTPStatusError as exc:
        erreur = f"la passerelle a répondu {exc.response.status_code}"
    except (asyncio.TimeoutError, httpx.TimeoutException):
        erreur = f"pas de réponse en {DELAI_S:g} s"
    except httpx.HTTPError:
        erreur = "adresse injoignable"
    except ValueError:
        erreur = "réponse illisible (attendu : {\"data\": [{\"id\": …}]})"
    except Exception as exc:  # noqa: BLE001 — un test ne fait jamais tomber la page
        erreur = f"échec ({type(exc).__name__})"
    else:
        texte = [n for n in noms if est_geco(n) and not est_embedding(n)]
        return {"ok": True, "nb": len(noms), "nb_texte": len(texte), "erreur": None}
    log.warning("Test de la liste des modèles GECO en échec", erreur=erreur)
    return {"ok": False, "nb": 0, "nb_texte": 0, "erreur": erreur}


def destination_ia() -> str:
    """
    Destination de l'IA interactive d'après le cache du processus : `local` (défaut, et tout ce qui
    n'est pas « geco ») ou `geco`. SERT À DÉCIDER / AFFICHER ; la barrière d'envoi, elle, relit la base
    (`ollama_service.destination_en_base`) à chaque envoi.
    """
    valeur = runtime_config.effective("ia_destination").strip().lower()
    return DESTINATION_GECO if valeur == DESTINATION_GECO else DESTINATION_LOCAL


@dataclass(frozen=True)
class ModeleResolu:
    """Résultat de la résolution : modèle à utiliser et origine (MATO | GECO). `explicite` False = « Auto »."""
    nom: str
    origine: str = ORIGINE_MATO
    explicite: bool = True

    @property
    def est_geco(self) -> bool:
        return self.origine == ORIGINE_GECO

    def sortie(self, origine: str):
        """
        Gestionnaire de contexte à ouvrir AUTOUR de l'envoi par une route interactive, APRÈS la
        résolution : ouvre l'autorisation d'envoi GECO (liste blanche) si, et seulement si, le modèle
        résolu est GECO. Sans effet pour un modèle MATO.
        """
        return sortie_geco_autorisee(origine) if self.est_geco else nullcontext()


def appelant_par_jeton() -> bool:
    """La requête (ou le job) est-elle celle d'un automate à jeton ? (l'auteur d'audit commence par « jeton: »)."""
    return (audit.auteur_courant() or "").startswith("jeton:")


def acteur_administrateur() -> bool:
    """
    L'acteur du contexte est-il une SESSION administrateur (authentification active) ? L'IA GECO lui
    est RÉSERVÉE. Automate, rôle « utilisateur », authentification inactive ou suspendue, acteur
    indéterminé : False — le doute refuse.
    """
    return audit.role_courant() == "admin" and not appelant_par_jeton()


async def _installes() -> list[str] | None:
    """Modèles installés sur Ollama ; None si Ollama est injoignable ou muet (délai `DELAI_CONTROLE_S`)."""
    try:
        return await asyncio.wait_for(OllamaService().list_models(), timeout=DELAI_CONTROLE_S)
    except Exception as exc:  # noqa: BLE001 — Ollama injoignable ou muet : voir `resoudre_modele_interactif`
        log.warning("Contrôle du modèle : Ollama injoignable", erreur=str(exc) or type(exc).__name__)
        return None


def _refus(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


MESSAGE_BOUTON = ("Les modèles GECO ne sont utilisables que lorsque le bouton « IA GECO » est activé "
                  "(Paramètres, administrateur).")
MESSAGE_AUTOMATES = "Les automates n'utilisent pas l'IA GECO."
MESSAGE_ADMIN = "L'IA GECO est réservée à l'administrateur."


def est_embedding(nom: str | None) -> bool:
    """Modèle d'embeddings (même règle que le filtre de l'interface : « embed », insensible à la casse)."""
    return "embed" in (nom or "").lower()


async def _resoudre_geco(modele: str) -> ModeleResolu:
    """
    Nom `geco/…` en mode GECO : doit figurer dans la liste GECO et ne pas être un modèle d'embeddings.
    (En mode local, il est refusé avant d'arriver ici : aucune sortie sans le bouton « IA GECO ».)
    """
    etat, externes = await lire_externes()
    if etat == ETAT_DISPONIBLE:
        if any(m["name"] == modele for m in externes):
            if est_embedding(modele):
                raise _refus(400, f"Le modèle « {modele} » est un modèle d'embeddings : il ne génère pas de "
                                  "texte. Choisissez un modèle de texte.")
            return ModeleResolu(modele, ORIGINE_GECO)
        raise _refus(400, f"Le modèle « {modele} » n'est pas dans la liste des modèles GECO. "
                          "Choisissez un modèle de la liste, ou laissez « Auto ».")
    if etat == ETAT_NON_CONFIGURE:
        raise _refus(400, f"Le modèle « {modele} » est un modèle GECO, mais la liste des modèles GECO "
                          "n'est pas configurée : aucune sortie possible.")
    raise _refus(503, "La liste des modèles GECO ne répond pas : impossible de vérifier le modèle "
                      f"« {modele} ». Rien n'est envoyé ; réessayez plus tard.")


async def resoudre_modele_interactif(demande: str | None, usage: str = "rapport") -> ModeleResolu:
    """
    Résolution UNIQUE, côté serveur, du modèle d'une route INTERACTIVE (chat, rapport, remplissage,
    comparatif, regroupement, assistant, relecture, présentation). La destination se décide d'après
    l'ORIGINE résolue (liste d'Ollama, liste GECO), jamais d'après le seul nom envoyé par le client.

    RÈGLE : aucun accès à GECO tant que le bouton « IA GECO » (`ia_destination`) n'est pas activé.
    - mode local : « Auto » → routage habituel (`model_for(usage)`, aucun appel réseau, et JAMAIS la
      liste GECO lue) ; un nom `geco/…` est REFUSÉ (400, sans rien lire) ; un modèle configuré pour
      l'usage qui serait GECO est refusé aussi ;
    - mode GECO : « Auto » → `geco_modele` (dans la liste GECO, jamais un modèle d'embeddings) ; un nom
      `geco/…` de la liste est accepté ; un modèle local installé reste local (listes Ollama et GECO
      lues EN PARALLÈLE) ;
    - RÉSERVÉ AUX SESSIONS ADMINISTRATEUR : tout autre acteur (rôle « utilisateur », automate à jeton,
      authentification inactive ou suspendue, acteur indéterminé) ne sort jamais. « Auto » → routage
      local ; `geco/…` explicite → 403 ;
    - préfixe `geco/` RÉSERVÉ (comparé normalisé) : un nom `geco/…` installé sur Ollama reste refusé ;
    - nom inconnu → 400 (« non installé ») ; en mode GECO, un nom de la liste GECO sans préfixe → 400 ;
    - LE DOUTE REFUSE : Ollama ou la liste GECO muets alors qu'une sortie GECO est possible (nom en
      `geco/`, ou mode GECO) → 503. Mode local + nom simple + Ollama muet : on laisse passer vers
      l'erreur « IA injoignable » de la route (aucune sortie n'est possible).
    """
    modele = (demande or "").strip()
    jeton = appelant_par_jeton()
    admin = acteur_administrateur()
    mode_geco = destination_ia() == DESTINATION_GECO and admin   # tout autre acteur : jamais GECO, « Auto » reste local

    if est_geco(modele) and not admin:
        raise _refus(403, MESSAGE_AUTOMATES if jeton else MESSAGE_ADMIN)

    if not modele:
        if not mode_geco:
            configure = runtime_config.model_for(usage)
            if est_geco(configure):
                log.error("Modèle GECO configuré pour un usage — refusé", usage=usage)
                raise _refus(400, f"Le modèle configuré pour l'usage « {usage} » est un modèle GECO : refusé "
                                  "(les réglages « Auto » restent sur un modèle MATO). Corrigez-le dans les Paramètres.")
            return ModeleResolu(configure, ORIGINE_MATO, explicite=False)
        choisi = runtime_config.effective("geco_modele").strip()
        if not choisi:
            raise _refus(503, "L'IA est sur GECO mais aucun modèle GECO n'est choisi : "
                              "choisissez-en un dans les Paramètres.")
        etat, externes = await lire_externes()
        if etat != ETAT_DISPONIBLE:
            raise _refus(503, "L'IA est sur GECO mais la liste des modèles GECO ne répond pas : "
                              "rien n'est envoyé. Réessayez plus tard.")
        if not est_geco(choisi) or est_embedding(choisi) or not any(m["name"] == choisi for m in externes):
            raise _refus(503, f"Le modèle GECO « {choisi} » n'est plus utilisable (absent de la liste GECO ou "
                              "modèle d'embeddings) : choisissez-en un autre dans les Paramètres.")
        return ModeleResolu(choisi, ORIGINE_GECO, explicite=False)

    if est_geco(modele):
        if not mode_geco:
            log.warning("Modèle GECO refusé : bouton « IA GECO » désactivé", modele=modele)
            raise _refus(400, MESSAGE_BOUTON)
        return await _resoudre_geco(modele)

    # Nom simple. Mode GECO : Ollama et liste GECO EN PARALLÈLE ; mode local : Ollama seul (jamais la liste GECO).
    if mode_geco:
        installes, (_etat, externes) = await asyncio.gather(_installes(), lire_externes())
    else:
        installes, externes = await _installes(), []
    if installes is not None and _avec_tag(modele) in {_avec_tag(n) for n in installes}:
        return ModeleResolu(modele, ORIGINE_MATO)
    if installes is None:
        if mode_geco:
            raise _refus(503, f"Ollama ne répond pas : impossible de vérifier le modèle « {modele} » alors que "
                              "l'IA est sur GECO. Rien n'est envoyé ; réessayez plus tard.")
        return ModeleResolu(modele, ORIGINE_MATO)   # mode local, Ollama muet : erreur « IA injoignable » en aval
    if any(m["name"] == modele for m in externes):
        log.warning("Modèle GECO sans préfixe refusé", modele=modele)
        raise _refus(400, f"Le modèle « {modele} » est un modèle GECO dont le nom ne porte pas le préfixe "
                          "« geco/ » : il n'est pas utilisable. Choisissez un modèle MATO ou un modèle "
                          "« geco/… ».")
    log.warning("Modèle non installé refusé", modele=modele)
    raise _refus(400, f"Le modèle « {modele} » n'est pas installé sur Ollama. Choisissez un modèle de la "
                      "liste, ou laissez « Auto ».")


def modele_a_envoyer(resolu: ModeleResolu, demande: str | None) -> str | None:
    """Ce que la route transmet en aval : le modèle GECO résolu, sinon la demande d'origine (inchangée)."""
    return resolu.nom if resolu.est_geco else demande


def marque_origine(resolu: ModeleResolu) -> dict:
    """Marque posée dans les paramètres d'un job : le worker la recontrôle (`controle_job`)."""
    return {"origine": ORIGINE_GECO} if resolu.est_geco else {}


async def controle_job(type_job: str, parametres: dict | None, modele_effectif: str | None = None) -> str | None:
    """
    Recontrôle du worker avant d'exécuter un job portant un modèle `geco/…`. Rend le message d'échec
    (français), ou None si tout est en règle. Exige : type interactif, marque d'origine posée par la
    route, job NON lancé par un automate, et bouton « IA GECO » sur `geco` EN BASE (lecture directe,
    pas le cache). `modele_effectif` : modèle réellement utilisé quand il peut venir d'ailleurs que
    des paramètres (ex. modèle préféré d'un regroupement).
    """
    params = parametres or {}
    for modele in (params.get("model"), modele_effectif):
        if not est_geco(modele):
            continue
        if type_job not in TYPES_JOB_GECO:
            return (f"Tâche « {type_job} » refusée : un modèle GECO n'est autorisé que pour les demandes "
                    "interactives ; les traitements de fond restent sur l'IA locale.")
        if params.get("origine") != ORIGINE_GECO:
            return ("Tâche refusée : le modèle GECO n'a pas été confirmé à la demande "
                    "(sortie internet sans autorisation enregistrée).")
        if str(params.get("proprietaire") or "").startswith("jeton:"):
            return "Tâche refusée : " + MESSAGE_AUTOMATES
        if params.get("proprietaire_role") != "admin":   # auteur enregistré à l'enqueue ; absent = refus
            return "Tâche refusée : " + MESSAGE_ADMIN
        if await destination_en_base() != DESTINATION_GECO:
            return ("Tâche refusée : le bouton « IA GECO » est revenu sur LOCAL depuis la demande — "
                    "aucun envoi vers GECO. Relancez la demande.")
        # Le rôle de l'auteur est figé à la mise en file : on relit donc que le contrôle d'accès,
        # lui, est toujours en vigueur au moment d'exécuter.
        if not await authentification_en_base():
            return ("Tâche refusée : l'authentification a été éteinte ou suspendue depuis la demande — "
                    "aucun envoi vers GECO.")
    return None


def refuser_geco_enregistre(nom: str | None, quoi: str) -> None:
    """
    Un modèle ENREGISTRÉ (modèle préféré d'un prompt, modèle d'un regroupement) reste un modèle local :
    il sert plus tard, à d'autres personnes, bouton sur LOCAL comme sur GECO. Refus à l'écriture (422),
    comme pour `default_model` — sinon n'importe qui bloque l'objet pour tout le monde avec un nom `geco/…`.
    """
    if est_geco(nom):
        raise HTTPException(status_code=422, detail=(
            f"{quoi} : « {(nom or '').strip()} » est un modèle GECO (IA externe). Un modèle enregistré reste "
            "un modèle MATO (Ollama local) ; l'IA GECO se choisit par le bouton « IA GECO » de l'en-tête."))


async def journaliser_bascule(ancienne: str, nouvelle: str, modele: str) -> None:
    """Une ligne d'activité à chaque changement de `ia_destination` (qui : auteur du contexte ; quand : horodatage)."""
    log.warning("Destination de l'IA modifiée", ancienne=ancienne, nouvelle=nouvelle)
    await audit.emit("ia_destination", "info", acteur="api", cible="ia_destination",
                     message=f"Destination de l'IA : {ancienne} → {nouvelle}",
                     detail={"ancienne": ancienne, "nouvelle": nouvelle, "geco_modele": modele})


def exiger_taille(nb_octets: int) -> None:
    """Refuse en 413, AVANT envoi, une requête GECO de plus de 32 Mio (plafond de l'AIGUILLEUR)."""
    if nb_octets > PLAFOND_GECO_OCTETS:
        raise HTTPException(status_code=413, detail="La demande dépasse 32 Mio : l'AIGUILLEUR la refuserait. "
                                                    "Réduisez le nombre ou la taille des documents.")
