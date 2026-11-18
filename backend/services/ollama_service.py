"""
Service Ollama — Client LLM et Embeddings
==========================================
Client async pour Ollama (modèles locaux).

Endpoints utilisés :
  POST /api/generate    → génération de texte (streaming ou non)
  POST /api/embeddings  → calcul de vecteurs d'embedding
  GET  /api/tags        → liste des modèles disponibles

Attention :
  - Mixtral (26 GB) est lent → timeout long configuré
  - Ne pas lancer d'embeddings pendant une génération (RAM)
  - La file d'attente (table jobs) gère l'exclusion mutuelle
"""

import asyncio
import codecs
import json
import os
import re
import unicodedata
from collections.abc import AsyncGenerator, Iterator
from contextlib import aclosing, contextmanager
from contextvars import ContextVar, Token

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings
from database import AsyncSessionLocal
from logger import get_logger
from services import ia_echecs

log = get_logger(__name__)
settings = get_settings()

# Un modèle déjà résident répond avec un `load_duration` de quelques millisecondes ; un vrai
# chargement du llama3.1 (4,9 Go) prend plusieurs secondes. 2 s sépare nettement les deux.
_SEUIL_RECHARGEMENT_S = 2.0


def entetes_projet() -> dict[str, str]:
    """
    Nomme nos appels dans le journal de la passerelle AIGUILLEUR, qui ne sait pas autrement
    distinguer ses clients. Sans effet quand on parle à Ollama en direct : un en-tête inconnu
    est ignoré. L'identité est DÉCLARÉE, pas prouvée — la passerelle le sait et journalise
    aussi l'adresse source.

    `AI_PROJECT` (env) : une pile de TEST se nomme autrement (ex. « ged-local-verif »), sinon
    son trafic se confond avec celui de la prod dans le journal de la passerelle — Docker
    réécrit l'adresse source, l'en-tête est le SEUL discriminant.

    À joindre à TOUT appel vers `ollama_url`, sondes comprises : la sonde de l'écran d'état
    partait sans, 518 appels anonymes par nuit (relevé AIGUILLEUR du 29/09/2026).
    """
    return {"X-AI-Project": os.environ.get("AI_PROJECT") or "ged-local",
            "X-AI-Priority": _PRIORITE_IA.get(),
            "X-AI-Usage": _USAGE_IA.get() or _USAGE_DEFAUT}


# Priorité déclarée à la passerelle (plan docs/plan-file-ia-priorites.md, étape 4, 02/11/2026) :
# « interactif » pour ce qu'un utilisateur attend à l'écran, « batch » pour le reste. AIGUILLEUR la
# JOURNALISE aujourd'hui sans l'appliquer (app/logs.py) ; elle servira à son ordonnancement GPU.
# Posée par le worker (selon le type de tâche) et par le middleware HTTP (une requête = interactif).
# Hors de ces contextes : « batch ». Aucun ordonnancement ici — c'est le rôle de la passerelle.
_PRIORITE_IA: ContextVar[str] = ContextVar("priorite_ia", default="batch")


def priorite_ia(valeur: str) -> Token:
    """Fixe la priorité des appels IA du contexte courant ; rend le jeton pour `_PRIORITE_IA.reset`."""
    return _PRIORITE_IA.set("interactif" if valeur == "interactif" else "batch")


# Usage déclaré à la passerelle (plan docs/plan-lots-ia-par-modele.md, étape 1) : QUELLE étape fait
# l'appel. Mêmes noms que `runtime_config.usage_model` (« embeddings », « vision », « enrichissement »,
# « rapport », « chat »…). Jamais vide : « autre » quand rien n'est posé. On DÉCLARE seulement ;
# routage et repli restent à la passerelle.
_USAGE_DEFAUT = "autre"
_USAGE_IA: ContextVar[str] = ContextVar("usage_ia", default=_USAGE_DEFAUT)


@contextmanager
def usage_ia(valeur: str) -> Iterator[None]:
    """
    Déclare l'usage des appels IA du bloc `with`, puis RESTAURE la valeur précédente (même sur
    exception) : l'usage ne déborde ni sur l'appel suivant, ni sur une autre tâche asyncio
    (chaque tâche a sa copie du contexte). Une valeur vide retombe sur « autre ».
    """
    jeton = _USAGE_IA.set((valeur or "").strip() or _USAGE_DEFAUT)
    try:
        yield
    finally:
        _USAGE_IA.reset(jeton)


def avec_usage(valeur: str):
    """
    Décorateur d'une fonction `async` qui envoie un prompt : ses appels IA portent l'usage `valeur`
    (prompts A3b, 18/11/2026 — 25 fonctions partaient en « autre »). Même effet que `with usage_ia(…)`
    autour du corps. ATTENTION : « enrichissement », « embeddings », « vision » sont des usages DE FOND,
    refusés à GECO — jamais sur une fonction servie à une demande interactive.
    """
    import functools

    def deco(fn):
        @functools.wraps(fn)
        async def enveloppe(*args, **kwargs):
            with usage_ia(valeur):
                return await fn(*args, **kwargs)
        enveloppe.usage_ia = valeur   # lu par les tests (tests/test_usage_declare.py)
        return enveloppe
    return deco


# ─── Modèles GECO (IA externe, par l'AIGUILLEUR) — plan docs/plan-liste-modeles.md, étape 5a ───
# Un modèle GECO se nomme `geco/<id>`. Il se génère en dialecte OpenAI (`/v1/chat/completions` sur
# `ollama_url`, qui est l'AIGUILLEUR) : exception voulue à la règle « jamais /v1/* », qui vaut pour
# Ollama (`num_ctx` et `keep_alive` y seraient perdus) — côté GECO ces options n'existent pas.
#
# DÉFENSE EN PROFONDEUR (rien ne sort sans que TOUT cela soit vrai, vérifié À CHAQUE envoi) :
#   1. la route interactive (ou le worker pour un job interactif marqué) a ouvert `sortie_geco_autorisee`
#      — LISTE BLANCHE, défaut REFUS : un traitement de fond n'ouvre jamais ce contexte ;
#   2. le bouton « IA GECO » (`ia_destination`) est sur `geco` DANS LA BASE (lecture directe, jamais le
#      cache du processus) ; toute erreur de lecture = refus ;
#   3. la demande tient dans 32 Mio ;
#   4. une ligne de journal `sortie_geco` a pu être écrite AVANT l'envoi (sinon : pas d'envoi).
PREFIXE_GECO = "geco/"
PLAFOND_GECO_OCTETS = 32 * 1024 * 1024   # plafond de l'AIGUILLEUR par requête
PLAFOND_LECTURE_OCTETS = 8 * 1024 * 1024   # réponse GECO : au-delà, on coupe (texte seulement)
# Usages DÉCLARÉS (`usage_ia`) refusés en plus de la liste blanche (ceinture et bretelles).
USAGES_DE_FOND = frozenset({"enrichissement", "embeddings", "vision"})
# Codes stables des refus de l'AIGUILLEUR (corps JSON : `code` ou `error.code`).
CODE_PROJET_NON_AUTORISE = "projet_non_autorise"
CODE_SORTIE_NON_DEMANDEE = "sortie_non_demandee"
CODE_SURFACE_NON_PERMISE = "surface_non_permise"


def est_geco(modele: str | None) -> bool:
    """
    Le nom désigne-t-il un modèle GECO ? Préfixe RÉSERVÉ, comparé sur la forme normalisée (NFKC,
    casse repliée, espaces retirés) : `GECO/x`, ` geco/x` ou une variante Unicode sont GECO aussi.
    """
    return unicodedata.normalize("NFKC", modele or "").strip().casefold().startswith(PREFIXE_GECO)


# Marque « envoi GECO autorisé » : ContextVar, défaut None = REFUS. Posée UNIQUEMENT par le
# gestionnaire de contexte ci-dessous, appelé par une route interactive (après la résolution du modèle)
# ou par le worker (après le recontrôle d'un job interactif marqué). Sa valeur nomme l'origine de
# l'envoi (route ou type de job) pour le journal.
_SORTIE_GECO: ContextVar[str | None] = ContextVar("sortie_geco_autorisee", default=None)


@contextmanager
def sortie_geco_autorisee(origine: str) -> Iterator[None]:
    """
    Ouvre, le temps du bloc, l'autorisation d'envoyer vers GECO. `origine` : route (« /api/… ») ou
    « job:<type> ». Une tâche créée dans le bloc en hérite (copie du contexte) ; un générateur en flux
    doit l'ouvrir DANS son corps (il s'exécute hors du contexte de la route).
    """
    jeton = _SORTIE_GECO.set(origine)
    try:
        yield
    finally:
        try:
            _SORTIE_GECO.reset(jeton)
        except ValueError:   # reprise d'un générateur dans un autre contexte : on referme quand même
            _SORTIE_GECO.set(None)


async def destination_en_base() -> str | None:
    """
    `ia_destination` lu DIRECTEMENT EN BASE (session fraîche), jamais dans le cache du processus : un
    cache périmé (un autre processus vient de repasser sur LOCAL) ne doit pas laisser partir une requête.
    Rend la valeur normalisée, ou None si la ligne est absente ou la lecture impossible (= refus).
    """
    try:
        from models.config import Config
        async with AsyncSessionLocal() as db:
            ligne = await db.get(Config, "ia_destination")
        valeur = (ligne.valeur if ligne is not None else None) or ""
        return valeur.strip().lower() or None
    except Exception as e:  # noqa: BLE001 — jamais « ouvert » sur une erreur de lecture
        log.error("Lecture de ia_destination impossible — envoi GECO refusé", erreur=type(e).__name__)
        return None


async def authentification_en_base() -> bool:
    """
    L'authentification est-elle ACTIVE et NON SUSPENDUE, lue DIRECTEMENT EN BASE (comme
    `destination_en_base`) ? L'IA GECO est réservée à une session administrateur : sans contrôle
    d'accès en vigueur, « administrateur » ne veut plus rien dire. Pendant une suspension de secours
    toute personne qui joint l'API a tous les droits ; authentification éteinte, de même. Dans les deux
    cas rien ne sort — y compris une tâche mise en file AVANT par un administrateur.
    Lecture impossible = False (refus).
    """
    try:
        from sqlalchemy import select

        from models.config import Config
        from services.acces import CLE_SUSPENSION, lire_echeance
        from services.oidc_service import valeur_active
        async with AsyncSessionLocal() as db:
            lignes = {cle: valeur for cle, valeur in (await db.execute(
                select(Config.cle, Config.valeur).where(Config.cle.in_(("auth_active", CLE_SUSPENSION))))).all()}
        return valeur_active(lignes.get("auth_active")) and lire_echeance(lignes.get(CLE_SUSPENSION)) is None
    except Exception as e:  # noqa: BLE001 — jamais « ouvert » sur une erreur de lecture
        log.error("Lecture de l'état de l'authentification impossible — envoi GECO refusé", erreur=type(e).__name__)
        return False


class ErreurGeco(Exception):
    """
    Échec d'un envoi vers GECO, ou usage interdit d'un modèle `geco/…`. `str(exc)` est un message
    FRANÇAIS destiné à l'utilisateur ; `status_code` = code HTTP à lui rendre. Jamais de contenu
    (prompt, document) ni d'adresse dans le message.
    """

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _code_refus(corps: bytes | None) -> str | None:
    """Code stable d'un refus de l'AIGUILLEUR (`code` ou `error.code`) — le reste du corps n'est JAMAIS lu ni relayé."""
    try:
        donnees = json.loads(corps or b"")
    except ValueError:
        return None
    if not isinstance(donnees, dict):
        return None
    erreur = donnees.get("error")
    code = donnees.get("code") or (erreur.get("code") if isinstance(erreur, dict) else None)
    return code.strip().lower() if isinstance(code, str) and len(code) <= 80 else None


def erreur_http_geco(statut: int, corps: bytes | None = None) -> ErreurGeco:
    """Traduit une réponse d'erreur de l'AIGUILLEUR en message compréhensible (jamais son corps)."""
    code = _code_refus(corps)
    if statut == 403 and code == CODE_SORTIE_NON_DEMANDEE:
        log.error("AIGUILLEUR : sortie GECO sans signal du bouton — défaut de Matothèque", code=code)
        return ErreurGeco("Défaut de Matothèque : l'envoi vers GECO est parti sans le signal du bouton « IA GECO ». "
                          "Rien n'est sorti. À signaler.", 500)
    if statut == 400 and code == CODE_SURFACE_NON_PERMISE:
        log.error("AIGUILLEUR : modèle GECO envoyé par un chemin non prévu — défaut de Matothèque", code=code)
        return ErreurGeco("Défaut de Matothèque : un modèle GECO a été envoyé par un chemin non prévu. "
                          "Rien n'est sorti. À signaler.", 500)
    if statut == 403:   # `projet_non_autorise`, ou code absent / inconnu : le message historique
        return ErreurGeco("Matothèque n'est pas autorisée à sortir vers GECO : l'autorisation s'ouvre "
                          "dans l'administration de l'AIGUILLEUR.", 403)
    if statut == 400:
        return ErreurGeco("L'AIGUILLEUR a refusé la requête GECO (HTTP 400) : modèle ou format non "
                          "accepté (texte seulement, modèle `geco/…`).", 400)
    if statut == 429:
        return ErreurGeco("GECO est saturé (HTTP 429) : trop de demandes. Réessayez dans un moment.", 429)
    if statut in (408, 504):
        return ErreurGeco(f"GECO n'a pas répondu à temps (HTTP {statut}). Réessayez plus tard.", 504)
    if statut >= 500:
        return ErreurGeco(f"GECO a répondu par une erreur (HTTP {statut}) : le modèle n'a pas pu "
                          "répondre. Réessayez plus tard.", 502)
    if 300 <= statut < 400:
        return ErreurGeco(f"L'AIGUILLEUR a répondu par une redirection (HTTP {statut}) : refusée, rien n'est suivi.", 502)
    return ErreurGeco(f"L'AIGUILLEUR a refusé la requête GECO (HTTP {statut}).", 502)

class EmbedLotNonSupporte(Exception):
    """Le serveur Ollama (ou le proxy) ne connaît pas `/api/embed` : repli sur `/api/embeddings`."""


def _attente_deja_longue(exc: BaseException) -> bool:
    """
    L'appel vient-il d'attendre jusqu'au bout de son délai (délai httpx dépassé, ou HTTP 504 : la
    passerelle coupe à 300 s) ? Le rejouer sur-le-champ redoublerait une attente de plusieurs minutes
    sur une carte déjà saturée — c'est exactement la tempête que le chantier combat. Le job est REPORTÉ
    par le worker (étape 5 du plan lots IA), avec un délai qui laisse la carte souffler.
    """
    if isinstance(exc, httpx.TimeoutException):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 504


def _rejouable(exc: BaseException, rejouer_apres_attente: bool = True) -> bool:
    """
    Un essai de plus dans l'appel ? Seule une `Exception` se rejoue : `asyncio.CancelledError` (annulation
    d'un job, arrêt du conteneur, `asyncio.wait_for` de la recherche) dérive de BaseException et tenacity
    la capture — sans cette garde l'annulation serait avalée et l'appel rejoué.
    Par défaut (rapports, comparatifs, assistant…) tout le reste se rejoue comme avant ; la chaîne IA
    passe `rejouer_apres_attente=False` pour ne pas redoubler une attente de 300 s (voir ci-dessus).
    """
    if not isinstance(exc, Exception):
        return False
    # Un refus ou un échec GECO ne se rejoue JAMAIS : rejouer, ce serait renvoyer le contenu sur
    # Internet une seconde fois (et journaliser deux envois pour une seule demande).
    if isinstance(exc, ErreurGeco):
        return False
    return rejouer_apres_attente or not _attente_deja_longue(exc)


def _rejouable_par_paquet(exc: BaseException, rejouer_apres_attente: bool = True) -> bool:
    """`embed_many` : jamais pour une route inconnue (`EmbedLotNonSupporte`) ni après un délai httpx
    dépassé (contrat de l'étape 2) ; un 504 ne se rejoue que si `rejouer_apres_attente`."""
    if not isinstance(exc, Exception) or isinstance(exc, (EmbedLotNonSupporte, httpx.TimeoutException)):
        return False
    return _rejouable(exc, rejouer_apres_attente)


def _decision(predicat):
    """Adapte un prédicat `(exception, rejouer_apres_attente)` à tenacity : le paramètre est lu dans les
    arguments de l'appel (`rejouer_apres_attente=...`), « vrai » par défaut."""
    def decide(retry_state) -> bool:
        sortie = retry_state.outcome
        if sortie is None or not sortie.failed:
            return False
        return predicat(sortie.exception(), retry_state.kwargs.get("rejouer_apres_attente", True))
    return decide


class OllamaService:
    """Client async pour Ollama."""

    def __init__(self, base_url: str | None = None):
        # URL effective : surcharge base (runtime_config) > variable d'env.
        from services.runtime_config import effective
        self.base_url = base_url or effective("ollama_url")
        self.timeout = settings.ollama_timeout

    @staticmethod
    def _keep_alive_for(model: str | None) -> str | int:
        """
        `keep_alive` à envoyer pour un modèle donné. Le modèle ÉPINGLÉ partagé (llama3.1) reste
        résident en permanence (`-1`) ; les autres gardent le défaut.

        Pourquoi : `keep_alive` d'Ollama est un attribut du **chargement en cours**, réécrit à CHAQUE
        requête (le dernier appelant gagne). En envoyant 30 min sur llama3.1, Matothèque écrasait le
        verrou `-1` posé par JARVIS (Home Assistant) sur le GPU partagé → JARVIS repayait le chargement
        (mesuré, note VRAM PC-GAME 04/09/2026). On aligne donc llama3.1 sur `-1`.

        🔴 **L'entier, pas la chaîne.** Ollama attend une durée Go (« 30m », « -1s ») **ou un nombre
        de secondes**. `"-1"` n'est ni l'un ni l'autre : il est refusé en **HTTP 400**
        (`time: missing unit in duration "-1"`), en 1 ms. Mesuré par la capture E0 d'AIGUILLEUR sur
        la PRODUCTION le 05/09/2026 : **488 refus en 7 h 30, 9,5 % du trafic de la carte**. Personne
        ne le voyait — le refus est instantané, le repli « même famille » prenait le relais, et
        l'utilisateur obtenait sa classification. Sauf que l'enrichissement ne tournait JAMAIS sur
        llama3.1, et que la chaîne de repli finissait par charger un modèle de 41 Gio qui débordait
        en RAM et faisait évincer par Ollama… le llama3.1 épinglé que ce code protège. Le correctif
        censé aider JARVIS lui coûtait ses 61 s de latence vocale.
        """
        pinned = settings.ollama_pinned_model or ""
        if model and pinned and model.split(":")[0].lower() == pinned.split(":")[0].lower():
            return -1

        # Même garde sur la valeur d'environnement : `OLLAMA_KEEP_ALIVE=-1` dans un `.env`
        # rejouerait le même 400 par le même chemin. `-1`, `"-1s"` et `"-1"` se ressemblent
        # à l'œil et ne font pas du tout la même chose — on retire donc le piège plutôt que
        # de compter sur la vigilance (suggestion de la session AIGUILLEUR, 06/09/2026).
        brut = str(settings.ollama_keep_alive or "").strip()
        if not brut:
            return "30m"                              # une valeur vide serait refusée aussi
        return int(brut) if re.fullmatch("-?[0-9]+", brut) else brut

    @staticmethod
    def _options(**extra: int | float | str) -> dict[str, int | float | str]:
        """
        `options` Ollama communes à toutes les générations : `num_ctx` explicite, pour ne plus
        dépendre de `OLLAMA_CONTEXT_LENGTH` sur le PC-GAME. Avec le défaut serveur (4096), un
        prompt long était tronqué par le DÉBUT — les consignes disparaissaient et l'enrichissement
        rendait un JSON vide (1 220 docs, 16/09/2026). Envoyé aussi au pré-chargement : un
        `num_ctx` qui varie d'un appel à l'autre force Ollama à recharger le modèle.
        """
        options = dict(extra)
        if settings.ollama_num_ctx > 0:
            options.setdefault("num_ctx", settings.ollama_num_ctx)   # un num_ctx explicite gagne
        return options

    @staticmethod
    def _signaler_rechargement(model: str | None, data: dict) -> bool:
        """
        Le modèle ÉPINGLÉ vient-il d'être rechargé ? Il est censé rester résident (`keep_alive -1`) :
        un chargement long pendant une génération veut presque toujours dire qu'un autre client l'a
        chargé avec un autre `num_ctx` (Ollama recharge à chaque changement). Seul symptôme visible
        d'une divergence OLLAMA_NUM_CTX ≠ OLLAMA_CONTEXT_LENGTH — autrement silencieuse.
        """
        pinned = (settings.ollama_pinned_model or "").split(":")[0].lower()
        if not model or not pinned or model.split(":")[0].lower() != pinned:
            return False
        secondes = (data.get("load_duration") or 0) / 1e9
        if secondes < _SEUIL_RECHARGEMENT_S:
            return False
        log.warning("Modèle épinglé rechargé pendant une génération — contexte divergent ?",
                    modele=model, chargement_s=round(secondes, 1), num_ctx=settings.ollama_num_ctx,
                    action="Aligner OLLAMA_NUM_CTX (Matothèque) et OLLAMA_CONTEXT_LENGTH (machine Ollama)")
        return True

    def _get_client(self) -> httpx.AsyncClient:
        """
        Client HTTP vers Ollama, avec des délais **dissociés** :

        - `connect` court (10 s) : un hôte injoignable doit échouer vite, pas au bout d'une heure ;
        - `read` long (`ollama_timeout`) : c'est le silence AVANT le premier octet qui compte. Le
          chargement à froid d'un gros modèle (43 Go pour Qwen3.6-35B) ne renvoie rien pendant
          plusieurs minutes ; avec un `read` unique de 5 min, on abandonnait juste avant que le
          modèle soit prêt — `ReadTimeout('')`, message vide, constaté en prod le 21/07. Une fois
          les tokens partis, chaque morceau réarme le compteur : ce délai ne borne pas la durée
          totale de génération.
        """
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout, connect=10.0),
            headers=entetes_projet(),   # identité auprès de la passerelle AIGUILLEUR
        )

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=5, max=30),
        retry=_decision(_rejouable),
    )
    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        stream: bool = False,
        format: str | None = None,
        images: list[str] | None = None,
        num_predict: int | None = None,
        keep_alive: int | str | None = None,
        options: dict | None = None,
        rejouer_apres_attente: bool = True,
    ) -> str:
        """
        Génère une réponse LLM (mode non-streaming).
        `options` : réglages Ollama en plus (ex. pénalité de répétition après une boucle).

        Args:
            prompt: Prompt utilisateur
            model: Modèle Ollama (défaut : settings.ollama_model_default)
            system: Prompt système (optionnel)
            stream: Si True, utiliser generate_stream() à la place
            images: Images en base64 (modèles vision : glm-ocr, llava…) — OCR / description
            num_predict: plafond de tokens produits. Sans lui, un prompt qui remplit presque le
                contexte fait « glisser » la fenêtre et le modèle peut écrire sans fin, en bloquant
                la file d'Ollama (grille d'analyse, 01/10/2026 : 300 s puis 504, à chaque appel).

        Returns:
            Texte généré complet
        """
        model = model or settings.ollama_model_default
        if est_geco(model):
            if images:
                raise ErreurGeco("GECO ne traite que du texte : les images ne peuvent pas lui être envoyées.", 400)
            return await self._generate_geco(prompt, model, system, num_predict)
        log.info("Génération Ollama", modele=model, nb_chars_prompt=len(prompt), nb_images=len(images or []))

        payload: dict = {"model": model, "prompt": prompt, "stream": False,
                         "keep_alive": self._keep_alive_for(model) if keep_alive is None else keep_alive}
        reglages = dict(self._options() or {})
        reglages.update(options or {})
        if num_predict:
            reglages["num_predict"] = num_predict
        if reglages:
            payload["options"] = reglages
        if system:
            payload["system"] = system
        if format:
            payload["format"] = format  # ex. "json" → Ollama garantit une sortie JSON valide
        if images:
            payload["images"] = images  # base64 (sans préfixe data:) pour modèles vision

        try:
            async with self._get_client() as client:
                response = await client.post("/api/generate", json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            await ia_echecs.noter(model, "generate", e, base_url=self.base_url)
            raise

        texte = data.get("response", "")
        self._signaler_rechargement(model, data)
        log.info("Génération OK", modele=model, nb_chars_reponse=len(texte))
        return texte

    async def generate_stream(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        think: bool | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Génère une réponse LLM en streaming (pour SSE).

        `think` : contrôle Ollama du **raisonnement visible**. `False` demande une réponse
        directe, sans « chain-of-thought ». Utile pour les modèles de raisonnement (Qwen3.6-35B…)
        qui déversent sinon leur réflexion — souvent en anglais — dans la sortie. **Agnostique du
        modèle** : Ollama l'ignore pour les modèles qui n'en ont pas (vérifié sur llama3.1 /
        ministral-3, aucune erreur), donc il reste valable si l'on change de modèle dans les
        Paramètres. `None` = on ne transmet rien (comportement Ollama par défaut).

        Yields:
            Morceaux de texte au fur et à mesure
        """
        model = model or settings.ollama_model_default
        if est_geco(model):
            async with aclosing(self._stream_geco(self._messages_geco(prompt, system), model)) as flux:
                async for morceau in flux:
                    yield morceau
            return
        log.info("Génération streaming Ollama", modele=model, think=think)

        # `keep_alive` était OUBLIÉ ici — seuls `generate()` et les embeddings le passaient. Le
        # modèle des RAPPORTS retombait donc sur le défaut d'Ollama (5 min) et se faisait
        # décharger entre deux usages : la requête suivante devait recharger le modèle à froid
        # (43 Go pour Qwen3.6-35B), au risque de dépasser le délai d'un proxy intermédiaire.
        # Constaté en prod le 21/07 : deux rapports réussis, puis échec ~1 h 45 plus tard.
        payload: dict = {"model": model, "prompt": prompt, "stream": True,
                         "keep_alive": self._keep_alive_for(model)}
        if options := self._options():
            payload["options"] = options
        if system:
            payload["system"] = system
        if think is not None:
            payload["think"] = think

        try:
            async with self._get_client() as client:
                async with client.stream("POST", "/api/generate", json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line:
                            data = json.loads(line)
                            if chunk := data.get("response"):
                                yield chunk
                            if data.get("done"):
                                self._signaler_rechargement(model, data)   # stats sur le dernier morceau
                                break
        except Exception as e:   # l'arrêt d'un flux par l'appelant (GeneratorExit) n'est pas un échec
            await ia_echecs.noter(model, "stream", e, base_url=self.base_url)
            raise

    async def chat_stream(
        self,
        messages: list[dict],
        model: str | None = None,
        think: bool | None = None,
    ) -> AsyncGenerator[str, None]:
        """
        Dialogue LIBRE en streaming (Ollama `/api/chat`, multi-tours) — sans lien avec la GED.
        `messages` = [{role: 'system'|'user'|'assistant', content: str}, …]. Yield les morceaux
        de réponse au fil de l'eau. `think=False` évite le raisonnement déversé (modèles Qwen…).
        """
        model = model or settings.ollama_model_default
        if est_geco(model):
            async with aclosing(self._stream_geco(list(messages), model, usage="chat")) as flux:
                async for morceau in flux:
                    yield morceau
            return
        log.info("Chat streaming Ollama", modele=model, nb_messages=len(messages))
        payload: dict = {"model": model, "messages": messages, "stream": True,
                         "keep_alive": self._keep_alive_for(model)}
        if options := self._options():
            payload["options"] = options
        if think is not None:
            payload["think"] = think

        try:
            with usage_ia("chat"):   # le client lit l'usage à sa création : rien ne reste posé entre deux yield
                client_cm = self._get_client()
            async with client_cm as client:
                async with client.stream("POST", "/api/chat", json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        if chunk := (data.get("message") or {}).get("content"):
                            yield chunk
                        if data.get("done"):
                            break
        except Exception as e:
            await ia_echecs.noter(model, "chat", e, base_url=self.base_url)
            raise

    # ─── Envoi vers GECO (dialecte OpenAI, via l'AIGUILLEUR) ──────────────────────

    @staticmethod
    def _messages_geco(prompt: str, system: str | None) -> list[dict]:
        """Un prompt simple devient un message `user`, le prompt système un message `system`."""
        messages = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt})
        return messages

    @staticmethod
    def _exiger_methode_locale(model: str | None, methode: str) -> None:
        """Les méthodes qui ne parlent qu'à Ollama (embeddings, préchauffage…) refusent un `geco/…`."""
        if est_geco(model):
            raise ErreurGeco(f"{methode} : un modèle GECO ne peut pas être utilisé ici "
                             "(texte seulement, Ollama local requis).", 400)

    @staticmethod
    def _delai_geco() -> float:
        """Délai de lecture GECO (réglage `geco_timeout_s`, défaut 300 s, borné [10, 3600])."""
        from services.runtime_config import effective
        try:
            return max(10.0, min(float(effective("geco_timeout_s") or 300), 3600.0))
        except (TypeError, ValueError):
            return 300.0

    async def _preparer_geco(self, messages: list[dict], model: str, stream: bool, num_predict: int | None,
                             usage: str | None) -> tuple[bytes, float]:
        """
        Toutes les barrières, dans l'ordre, puis le journal. Rend `(corps JSON en octets UTF-8, délai)`.
        Lève `ErreurGeco` AVANT tout envoi si une condition manque.
        """
        origine = _SORTIE_GECO.get()
        if not origine:     # liste blanche : seul un contexte ouvert par une route interactive / le worker
            raise ErreurGeco("Envoi vers GECO refusé : ce traitement n'est pas une demande interactive "
                             "(les traitements de fond restent sur l'IA locale).", 403)
        declare = usage or _USAGE_IA.get()
        if declare in USAGES_DE_FOND:
            raise ErreurGeco(f"Un modèle GECO ne peut pas servir à l'usage « {declare} » : les traitements "
                             "de fond restent sur l'IA locale.", 400)
        if await destination_en_base() != "geco":
            raise ErreurGeco("Les modèles GECO ne sont utilisables que lorsque le bouton « IA GECO » est "
                             "activé : rien n'a été envoyé.", 403)
        if not await authentification_en_base():
            raise ErreurGeco("L'IA GECO exige l'authentification active : elle est éteinte ou suspendue, "
                             "rien n'a été envoyé.", 403)
        corps: dict = {"model": model, "messages": messages, "stream": stream}
        if num_predict:
            corps["max_tokens"] = num_predict
        texte = json.dumps(corps, ensure_ascii=False)
        octets = texte.encode("utf-8")        # sérialisé UNE fois : on mesure ET on poste ces octets
        if len(octets) > PLAFOND_GECO_OCTETS:
            raise ErreurGeco("La demande dépasse 32 Mio : l'AIGUILLEUR la refuserait. Réduisez le nombre "
                             "ou la taille des documents.", 413)
        # Fail-closed : pas de trace, pas d'envoi. Jamais de contenu ni de nom de document.
        from services import audit
        try:
            await audit.emit_strict(
                "sortie_geco", "info", acteur="worker" if origine.startswith("job:") else "api", cible=origine,
                message=f"Envoi vers GECO ({model}) : {len(messages)} message(s), {len(texte)} caractère(s)",
                detail={"origine": origine, "modele": model, "usage": declare, "nb_messages": len(messages),
                        "nb_caracteres": len(texte), "nb_octets": len(octets)})
        except Exception as e:  # noqa: BLE001
            log.error("Journal d'envoi GECO impossible — envoi refusé", erreur=type(e).__name__)
            raise ErreurGeco("Le journal d'activité est indisponible : l'envoi vers GECO est refusé "
                             "(aucune sortie sans trace).", 503) from None
        return octets, self._delai_geco()

    def _client_geco(self, delai: float, usage: str | None) -> httpx.AsyncClient:
        """Client propre à GECO : délais dédiés, jamais de redirection, signal de sortie `X-AI-Sortie: geco`."""
        if usage:
            with usage_ia(usage):   # le client lit l'usage à sa création
                entetes = entetes_projet()
        else:
            entetes = entetes_projet()
        entetes["X-AI-Sortie"] = "geco"    # posé ICI seulement : jamais dans `entetes_projet()`
        return httpx.AsyncClient(base_url=self.base_url, headers=entetes, follow_redirects=False,
                                 timeout=httpx.Timeout(connect=10.0, read=delai, write=delai, pool=10.0))

    @staticmethod
    def _echec_reseau(exc: Exception) -> ErreurGeco:
        log.warning("Envoi GECO impossible", erreur=type(exc).__name__)   # jamais str(exc) : httpx y met l'adresse
        if isinstance(exc, httpx.TimeoutException):
            return ErreurGeco("GECO n'a pas répondu à temps : la requête a été abandonnée.", 504)
        return ErreurGeco("L'AIGUILLEUR ne répond pas : la requête GECO n'a pas abouti.", 503)

    @staticmethod
    async def _noter_echec_geco(model: str, operation: str, exc: ErreurGeco, base_url: str) -> None:
        """Échec GECO dans `ia_echecs` comme les échecs locaux (message français, jamais de contenu)."""
        nature = {504: "delai", 503: "connexion"}.get(exc.status_code, "http" if exc.status_code != 413 else "autre")
        await ia_echecs.noter(model, operation, nature=nature, message=str(exc), base_url=base_url)

    @staticmethod
    def _texte_reponse(donnees) -> str:
        """Texte d'une réponse NON-flux (`choices[0].message.content`) ; clé `error` ou vide → ErreurGeco 502."""
        if not isinstance(donnees, dict):
            raise ErreurGeco("Réponse inattendue de l'AIGUILLEUR (GECO).", 502)
        if donnees.get("error"):
            raise ErreurGeco("GECO a répondu par une erreur : le modèle n'a pas pu répondre. Réessayez plus tard.", 502)
        choix = (donnees.get("choices") or [None])[0]
        if not isinstance(choix, dict):
            raise ErreurGeco("Réponse inattendue de l'AIGUILLEUR (GECO).", 502)
        if choix.get("finish_reason") in ("length", "content_filter"):
            log.warning("Réponse GECO tronquée ou filtrée", finish_reason=choix.get("finish_reason"))
        contenu = (choix.get("message") or {}).get("content")
        if not isinstance(contenu, str) or not contenu:
            raise ErreurGeco("Réponse vide de GECO.", 502)
        return contenu

    @staticmethod
    async def _corps_erreur(response: httpx.Response) -> bytes:
        """Début (64 Kio max) du corps d'un refus : sert à lire le CODE, jamais relayé."""
        morceaux = bytearray()
        try:
            async for m in response.aiter_bytes():
                morceaux.extend(m)
                if len(morceaux) > 65536:
                    break
        except Exception:  # noqa: BLE001 — le code est un plus
            pass
        return bytes(morceaux)

    async def _generate_geco(self, prompt: str, model: str, system: str | None, num_predict: int | None) -> str:
        octets, delai = await self._preparer_geco(self._messages_geco(prompt, system), model, False, num_predict, None)
        log.info("Génération GECO", modele=model, nb_chars_prompt=len(prompt))
        try:
            async with asyncio.timeout(delai):     # délai TOTAL = le réglage
                async with self._client_geco(delai, None) as client:
                    async with client.stream("POST", "/v1/chat/completions", content=octets,
                                             headers={"Content-Type": "application/json"}) as response:
                        if response.status_code != 200:
                            raise erreur_http_geco(response.status_code, await self._corps_erreur(response))
                        corps = bytearray()
                        async for m in response.aiter_bytes():
                            corps.extend(m)
                            if len(corps) > PLAFOND_LECTURE_OCTETS:
                                raise ErreurGeco("Réponse de GECO trop volumineuse : abandon.", 502)
            try:
                texte = self._texte_reponse(json.loads(bytes(corps)))
            except ValueError:
                raise ErreurGeco("Réponse illisible de l'AIGUILLEUR (GECO).", 502) from None
        except ErreurGeco as e:
            await self._noter_echec_geco(model, "generate", e, self.base_url)
            raise
        except (httpx.HTTPError, httpx.StreamError, httpx.InvalidURL, TimeoutError) as e:
            erreur = self._echec_reseau(e if not isinstance(e, TimeoutError) else httpx.ReadTimeout("délai total"))
            await self._noter_echec_geco(model, "generate", erreur, self.base_url)
            raise erreur from None
        log.info("Génération GECO OK", modele=model, nb_chars_reponse=len(texte))
        return texte

    async def _stream_geco(self, messages: list[dict], model: str,
                           usage: str | None = None) -> AsyncGenerator[str, None]:
        """
        Flux SSE OpenAI (`data: {...}` puis `data: [DONE]`) relayé en morceaux de texte. Lecture par
        OCTETS, décodage UTF-8 incrémental, découpe sur `\n` SEULEMENT (U+2028 & co. restent dans le
        texte). Statut ≠ 200 = erreur ; content-type ≠ event-stream = réponse non-flux ; ligne `error`,
        flux sans texte, octets cumulés > 8 Mio = ErreurGeco.
        """
        octets, delai = await self._preparer_geco(messages, model, True, None, usage)
        log.info("Génération streaming GECO", modele=model, nb_messages=len(messages))
        recu = 0
        decodeur = codecs.getincrementaldecoder("utf-8")(errors="replace")
        tampon = ""
        yield_total = 0

        def lire_ligne(ligne: str) -> tuple[str | None, bool]:
            """(texte, fin) d'une ligne SSE."""
            ligne = ligne.rstrip("\r")
            if not ligne.startswith("data:"):
                return None, False
            brut = ligne[5:].strip()
            if brut == "[DONE]":
                return None, True
            try:
                donnees = json.loads(brut)
            except ValueError:
                return None, False
            if not isinstance(donnees, dict):
                return None, False
            if donnees.get("error"):
                raise ErreurGeco("GECO a répondu par une erreur en cours de réponse : le modèle n'a pas pu "
                                 "répondre. Réessayez plus tard.", 502)
            choix = (donnees.get("choices") or [None])[0]
            if not isinstance(choix, dict):
                return None, False
            if choix.get("finish_reason") in ("length", "content_filter"):
                log.warning("Réponse GECO tronquée ou filtrée", finish_reason=choix.get("finish_reason"))
            contenu = (choix.get("delta") or {}).get("content")
            if not isinstance(contenu, str):
                contenu = (choix.get("message") or {}).get("content")
            return (contenu if isinstance(contenu, str) and contenu else None), False

        try:
            async with asyncio.timeout(delai * 2):    # délai TOTAL d'un flux : 2 × le délai de lecture
                async with self._client_geco(delai, usage) as client:
                    async with client.stream("POST", "/v1/chat/completions", content=octets,
                                             headers={"Content-Type": "application/json"}) as response:
                        if response.status_code != 200:
                            raise erreur_http_geco(response.status_code, await self._corps_erreur(response))
                        en_flux = "text/event-stream" in response.headers.get("content-type", "").lower()
                        corps = bytearray()
                        fini = False
                        async for morceau_octets in response.aiter_bytes():
                            recu += len(morceau_octets)
                            if recu > PLAFOND_LECTURE_OCTETS:
                                raise ErreurGeco("Réponse de GECO trop volumineuse : abandon.", 502)
                            if not en_flux:
                                corps.extend(morceau_octets)
                                continue
                            tampon += decodeur.decode(morceau_octets)
                            while "\n" in tampon and not fini:
                                ligne, tampon = tampon.split("\n", 1)
                                texte, fini = lire_ligne(ligne)
                                if texte:
                                    yield_total += 1
                                    yield texte
                            if fini:
                                break
                        if not en_flux:
                            try:
                                texte_complet = self._texte_reponse(json.loads(bytes(corps)))
                            except ValueError:
                                raise ErreurGeco("Réponse illisible de l'AIGUILLEUR (GECO).", 502) from None
                            yield_total += 1
                            yield texte_complet
                        elif not fini:
                            tampon += decodeur.decode(b"", final=True)
                            if tampon.strip():      # dernière ligne sans `\n` final
                                texte, _ = lire_ligne(tampon)
                                if texte:
                                    yield_total += 1
                                    yield texte
            if yield_total == 0:
                raise ErreurGeco("Réponse vide de GECO.", 502)
        except ErreurGeco as e:
            await self._noter_echec_geco(model, "chat" if usage == "chat" else "stream", e, self.base_url)
            raise
        except (httpx.HTTPError, httpx.StreamError, httpx.InvalidURL, TimeoutError) as e:
            erreur = self._echec_reseau(e if not isinstance(e, TimeoutError) else httpx.ReadTimeout("délai total"))
            await self._noter_echec_geco(model, "chat" if usage == "chat" else "stream", erreur, self.base_url)
            raise erreur from None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=_decision(_rejouable),
    )
    async def embed(self, text: str, model: str | None = None, timeout: float | None = None,
                    rejouer_apres_attente: bool = True) -> list[float]:
        """
        Calcule le vecteur d'embedding d'un texte.

        Args:
            text: Texte à encoder
            model: Modèle d'embedding (défaut : settings.ollama_model_embedding)
            timeout: plafond (s) pour CET appel — court côté recherche (fail-fast → repli texte) ;
                     None = timeout long par défaut (indexation, où l'on veut attendre le modèle).

        Returns:
            Vecteur d'embedding (liste de floats)
        """
        model = model or settings.ollama_model_embedding
        self._exiger_methode_locale(model, "embed")
        log.debug("Calcul embedding", modele=model, nb_chars=len(text))

        try:
            with usage_ia("embeddings"):   # le client lit l'usage à sa création
                client_cm = self._get_client()
            async with client_cm as client:
                kw = {"timeout": timeout} if timeout is not None else {}
                response = await client.post(
                    "/api/embeddings",
                    json={"model": model, "prompt": text, "keep_alive": self._keep_alive_for(model)},
                    **kw,
                )
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            await ia_echecs.noter(model, "embed", e, base_url=self.base_url)
            raise

        embedding = data.get("embedding", [])
        if not embedding:
            # Vecteur vide : l'appelant tente le modèle de repli (audit M12) — sans ce témoin, un
            # modèle d'embedding muet ne se voyait nulle part.
            await ia_echecs.noter(model, "embed", nature="vide", message="vecteur vide renvoyé",
                                  base_url=self.base_url)
        log.debug("Embedding OK", modele=model, dimension=len(embedding))
        return embedding

    @staticmethod
    def _lot_refuse(response: httpx.Response) -> bool:
        """
        Le serveur ne connaît-il PAS `/api/embed` (Ollama ancien, proxy qui ne relaie pas la route) ?
        405 : sans ambiguïté. 404 : ambigu — Ollama répond AUSSI 404 quand c'est le MODÈLE qui est
        absent (`{"error":"model ... not found"}`) ; ce cas-là est un vrai échec (repli de modèle
        côté appelant), pas une route inconnue (repli sur l'appel unitaire).
        """
        if response.status_code == 405:
            return True
        if response.status_code != 404:
            return False
        try:
            erreur = str((response.json() or {}).get("error", "")).lower()
        except Exception:  # noqa: BLE001 — corps non JSON (« 404 page not found ») = route inconnue
            return True
        return not ("model" in erreur and "not found" in erreur)

    # Un paquet rejoué, c'est jusqu'à 32 textes recalculés d'un coup : DEUX essais au plus (trois
    # pour l'appel unitaire), et AUCUN rejeu sur un délai dépassé NI sur un HTTP 504 — l'un comme
    # l'autre veut dire carte saturée ou modèle en cours de chargement (la passerelle coupe à 300 s et
    # répond 504 : 27 paquets le 12/11), et rejouer le paquet aggrave exactement ce que ce chantier
    # combat (même règle que pour Tika). Une route inconnue ne se rejoue pas non plus.
    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=_decision(_rejouable_par_paquet),
    )
    async def embed_many(self, textes: list[str], model: str | None = None,
                         timeout: float | None = None, rejouer_apres_attente: bool = True) -> list[list[float]]:
        """
        Calcule les vecteurs d'un PAQUET de textes en un seul appel (`POST /api/embed`, champ
        `input` = liste). Remplace N appels `/api/embeddings` : c'est le volume d'appels qui
        saturait la carte (plan lots IA, étape 2). Même `keep_alive`, même usage « embeddings »,
        même délai que `embed` ; nouveaux essais plus prudents (voir le décorateur).

        ⚠️ `/api/embed` renvoie des vecteurs NORMALISÉS (norme 1), l'ancien `/api/embeddings` non.
        Sans effet sur la distance cosinus (`<=>`) utilisée partout pour la recherche.

        Raises:
            EmbedLotNonSupporte: le serveur ne connaît pas `/api/embed` → l'appelant retombe sur
                l'appel unitaire. Pas de nouvel essai.

        Returns:
            Les vecteurs, dans l'ordre des textes. La COHÉRENCE (autant de vecteurs que de textes,
            aucun vide) est vérifiée par l'appelant : on rend ici ce que le serveur a répondu.
        """
        if not textes:
            return []
        model = model or settings.ollama_model_embedding
        self._exiger_methode_locale(model, "embed_many")
        log.debug("Calcul embeddings par paquet", modele=model, nb_textes=len(textes))

        try:
            with usage_ia("embeddings"):   # le client lit l'usage à sa création
                client_cm = self._get_client()
            async with client_cm as client:
                kw = {"timeout": timeout} if timeout is not None else {}
                response = await client.post(
                    "/api/embed",
                    json={"model": model, "input": textes, "keep_alive": self._keep_alive_for(model)},
                    **kw,
                )
                if self._lot_refuse(response):
                    raise EmbedLotNonSupporte(f"/api/embed refusé (HTTP {response.status_code})")
                response.raise_for_status()
                data = response.json()
        except EmbedLotNonSupporte:
            raise                                  # route inconnue : pas un échec du modèle, rien à consigner
        except Exception as e:
            await ia_echecs.noter(model, "embed", e, base_url=self.base_url)
            raise

        vecteurs = data.get("embeddings") or []
        if len(vecteurs) != len(textes) or not all(vecteurs):
            await ia_echecs.noter(model, "embed", nature="vide", base_url=self.base_url,
                                  message=f"{len(vecteurs)} vecteur(s) pour {len(textes)} texte(s), "
                                          "ou vecteur vide")
        log.debug("Embeddings par paquet OK", modele=model, nb_vecteurs=len(vecteurs))
        return vecteurs

    async def is_loaded(self, model: str) -> bool:
        """Le modèle est-il déjà résident en mémoire ? (via /api/ps)."""
        try:
            async with self._get_client() as client:
                resp = await client.get("/api/ps")
                resp.raise_for_status()
                charges = {m.get("name") for m in resp.json().get("models", [])}
            return model in charges
        except Exception:  # noqa: BLE001 — l'absence d'info ne doit pas bloquer le prewarm
            return False

    async def warm(self, model: str) -> bool:
        """
        Charge le modèle en mémoire et l'y maintient (`keep_alive`), sans rien générer d'utile
        (`num_predict=0` → Ollama charge le modèle puis rend la main). Sert au pré-chargement du
        gros modèle de rapport pour éviter un rechargement à froid au 1er usage. Best effort.
        """
        self._exiger_methode_locale(model, "warm")
        try:
            async with self._get_client() as client:
                resp = await client.post("/api/generate", json={
                    "model": model, "prompt": "", "stream": False,
                    "keep_alive": self._keep_alive_for(model),
                    "options": self._options(num_predict=0),
                })
                resp.raise_for_status()
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("Pré-chargement du modèle échoué", modele=model, erreur=str(e) or type(e).__name__)
            return False

    async def list_models(self) -> list[str]:
        """Retourne la liste des noms de modèles Ollama disponibles."""
        async with self._get_client() as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
            data = response.json()
        return [m["name"] for m in data.get("models", []) if not self._modele_geco_dans_tags(m.get("name"))]

    @staticmethod
    def _modele_geco_dans_tags(nom: str | None) -> bool:
        """
        `/api/tags` ne doit JAMAIS porter un modèle GECO (l'AIGUILLEUR s'y engage). S'il en renvoie un,
        on l'écarte — jamais « installé », jamais candidat — et on le dit fort.
        """
        if est_geco(nom):
            log.error("Modèle GECO renvoyé par /api/tags : écarté (l'AIGUILLEUR ne devrait jamais en renvoyer)",
                      modele=nom)
            return True
        return False

    async def list_models_detailed(self) -> list[dict]:
        """Retourne les modèles installés avec leur taille (nom + octets + famille)."""
        async with self._get_client() as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
            data = response.json()
        modeles = []
        for m in data.get("models", []):
            if self._modele_geco_dans_tags(m.get("name")):
                continue
            details = m.get("details") or {}
            modeles.append({
                "name": m.get("name"),
                "size": m.get("size", 0),
                "digest": m.get("digest", ""),
                "famille": details.get("family"),
                "parametres": details.get("parameter_size"),
            })
        modeles.sort(key=lambda x: x["name"] or "")
        return modeles

    @staticmethod
    def _registry_ref(name: str) -> tuple[str, str]:
        """Décompose 'mistral:latest' → ('library/mistral', 'latest')."""
        repo, _, tag = name.partition(":")
        tag = tag or "latest"
        if "/" not in repo:
            repo = f"library/{repo}"
        return repo, tag

    async def check_update(self, name: str, local_digest: str) -> bool | str:
        """
        Compare le digest local au manifest du registre Ollama.
        Returns:
          - True         → mise à jour disponible
          - False        → à jour
          - "absent"     → modèle hors registre (import perso, hf.co/…) : pas de version de référence
          - "injoignable"→ registre Ollama non joignable (réseau)
        (On distingue « absent » de « injoignable » pour un affichage clair côté UI.)
        """
        import hashlib

        repo, tag = self._registry_ref(name)
        url = f"https://registry.ollama.ai/v2/{repo}/manifests/{tag}"
        headers = {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return "absent"  # 404 → modèle custom / hors registre
            remote_digest = hashlib.sha256(resp.content).hexdigest()
            return remote_digest != (local_digest or "")
        except Exception as exc:
            log.warning("Vérif MAJ impossible", modele=name, erreur=str(exc))
            return "injoignable"

    async def pull_stream(self, name: str):
        """
        Télécharge / met à jour un modèle (ollama pull) en streaming.
        Yield les lignes de progression brutes (NDJSON) renvoyées par Ollama.
        """
        from services.runtime_config import effective

        # Le pull NE PASSE PAS par la passerelle : AIGUILLEUR ne relaie pas `/api/pull` (404), le
        # téléchargement de modèles appartenant à un updater dédié à egress restreint. On vise donc
        # Ollama en direct, par un réglage distinct — modifiable depuis Paramètres, et dont le
        # défaut est l'adresse d'environnement, donc juste même si personne ne le renseigne.
        url_directe = effective("ollama_direct_url") or self.base_url
        log.info("Pull modèle Ollama", modele=name, url=url_directe)
        # Pas de timeout court : un pull peut être long.
        async with httpx.AsyncClient(base_url=url_directe, timeout=None) as client:
            async with client.stream("POST", "/api/pull", json={"model": name, "stream": True}) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip():
                        yield line

    async def check_health(self) -> bool:
        """Vérifie qu'Ollama est disponible."""
        try:
            async with self._get_client() as client:
                response = await client.get("/api/tags")
                return response.status_code == 200
        except Exception as e:
            log.warning("Ollama non disponible", erreur=str(e))
            return False
