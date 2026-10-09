"""
Service Tika — Extraction de texte et métadonnées
===================================================
Client async pour Apache Tika Server.
Supporte tous les formats : PDF, DOCX, PPTX, PPSX, XLSX, ZIP.

Endpoints Tika utilisés :
  PUT /tika        → texte brut uniquement
  PUT /rmeta/text  → texte + métadonnées complètes (JSON)
  PUT /rmeta       → métadonnées uniquement

Pour les ZIP : /rmeta retourne un document par fichier dans le ZIP.
"""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from config import get_settings
from logger import get_logger

log = get_logger(__name__)
settings = get_settings()

# Taille de bloc pour l'upload en flux vers Tika (borne le pic RAM sur les gros fichiers).
_CHUNK = 1 << 20  # 1 Mo


async def _stream_file(path: Path, chunk: int = _CHUNK) -> AsyncIterator[bytes]:
    """
    Envoie un fichier à Tika PAR BLOCS (upload chunké) au lieu de le charger entièrement
    en mémoire : le pic RAM reste ~1 bloc, pas la taille du fichier (utile pour les gros
    PDF/PPTX/ZIP). Les lectures disque se font hors event-loop (`to_thread`).
    """
    f = await asyncio.to_thread(open, path, "rb")
    try:
        while True:
            data = await asyncio.to_thread(f.read, chunk)
            if not data:
                break
            yield data
    finally:
        await asyncio.to_thread(f.close)


# ─── Ne pas engorger Tika ────────────────────────────────────────────────────
#
# Mesuré le 09/10/2026 sur 2 cœurs (la prod) : un PDF scanné de 40 pages demande ~90 s d'OCR, et
# le worker pouvait envoyer 5 fichiers à la fois (2 indexations + 3 synchros) avec 60 s de délai
# et 3 essais. Chaque délai dépassé renvoyait le MÊME fichier pendant que Tika travaillait encore
# sur l'envoi précédent : 300 documents en erreur « ReadTimeout », et côté Tika 4
# `CLIENT_UNAVAILABLE_WITHIN_MS`. Trois règles, donc :
#   1. un nombre borné d'extractions à la fois par processus (`tika_concurrence`) — l'attente se
#      fait ICI, sans limite, et non dans Tika qui refuse au bout d'un moment ;
#   2. un délai de lecture à la mesure d'un gros scan (`TIKA_TIMEOUT_MS`, 10 min par défaut) ;
#   3. JAMAIS de nouvel essai sur un délai dépassé : ce serait doubler une charge déjà trop forte.
_PAS_DE_NOUVEL_ESSAI = retry_if_not_exception_type(httpx.TimeoutException)

_verrous: dict[int, asyncio.Semaphore] = {}


def _verrou_tika() -> asyncio.Semaphore:
    """Sémaphore du processus, créé dans la boucle qui s'en sert (une par worker / par test)."""
    boucle = id(asyncio.get_running_loop())
    if boucle not in _verrous:
        _verrous.clear()                       # boucle précédente terminée : son verrou ne sert plus
        _verrous[boucle] = asyncio.Semaphore(max(1, settings.tika_concurrence))
    return _verrous[boucle]


# ─── Tika principal (PC-GAME) et repli (LXC) ─────────────────────────────────
#
# Mesuré le 09/10/2026 : un scan de 10 pages prend 19 s sur PC-GAME (i9) contre 169 s sur le LXC
# (2 cœurs). Le principal est donc le Tika de PC-GAME (`tika_url`) ; mais PC-GAME s'éteint, et
# l'indexation ne doit pas tomber avec lui : `tika_url_repli` (le Tika du LXC) prend le relais.
# Décidé avec la session AIGUILLEUR : Matothèque choisit seule, la passerelle IA ne relaie pas Tika.
#   - santé du principal : GET /version, 2 s, résultat gardé 25 s (on ne paie pas un délai de
#     connexion par fichier quand PC-GAME dort) ;
#   - bascule sur échec de CONNEXION seulement : jamais au milieu d'une extraction commencée.
SANTE_CACHE_S = 25.0
CONNEXION_S = 4.0
_sante: dict[str, tuple[float, bool]] = {}


async def _repond(url: str) -> bool:
    """Ce Tika répond-il ? Mis en cache `SANTE_CACHE_S` par processus."""
    maintenant = asyncio.get_running_loop().time()
    en_cache = _sante.get(url)
    if en_cache and maintenant - en_cache[0] < SANTE_CACHE_S:
        return en_cache[1]
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            ok = (await c.get(url.rstrip("/") + "/version")).status_code == 200
    except Exception:  # noqa: BLE001 — éteint, réseau, DNS : même verdict
        ok = False
    _sante[url] = (maintenant, ok)
    return ok


def _marquer_injoignable(url: str) -> None:
    try:
        _sante[url] = (asyncio.get_running_loop().time(), False)
    except RuntimeError:
        pass


class TikaService:
    """Client async pour Apache Tika Server."""

    def __init__(self, base_url: str | None = None):
        # URL effective : surcharge base (runtime_config) > variable d'env. Une URL imposée
        # (test de connexion d'un réglage) n'a pas de repli : on veut savoir si ELLE répond.
        self._imposee = base_url
        self.timeout = settings.tika_timeout
        self._relire_adresses()

    def _relire_adresses(self) -> None:
        """
        Relit `tika_url` / `tika_url_repli` dans la config. Appelé à CHAQUE envoi, pas seulement à
        la construction : une synchro construit son service une fois et peut durer des heures. Au
        passage de Tika sur PC-GAME (09/10/2026), deux synchros lancées avant le changement ont
        continué d'envoyer au LXC — et, une extraction à la fois par processus, bloqué derrière
        elles les tâches qui, elles, auraient été servies par PC-GAME.
        """
        from services.runtime_config import effective
        self.base_url = self._imposee or effective("tika_url")
        repli = "" if self._imposee else (effective("tika_url_repli") or "").strip()
        self.repli = repli if repli and repli.rstrip("/") != self.base_url.rstrip("/") else ""

    def _get_client(self, url: str | None = None) -> httpx.AsyncClient:
        """Retourne un client httpx configuré."""
        return httpx.AsyncClient(
            base_url=url or self.base_url,
            # Seule la LECTURE peut être longue (OCR) ; un Tika injoignable doit se voir vite.
            timeout=httpx.Timeout(self.timeout, connect=CONNEXION_S),
        )

    async def _url_active(self) -> str:
        """Le principal s'il répond, sinon le repli (quand il y en a un)."""
        self._relire_adresses()
        if not self.repli or await _repond(self.base_url):
            return self.base_url
        log.info("Tika principal injoignable — repli", principal=self.base_url, repli=self.repli)
        return self.repli

    async def _envoyer(self, chemin: str, file_path: Path, accept: str) -> httpx.Response:
        """PUT d'un fichier, avec bascule sur le repli si le principal refuse la CONNEXION."""
        url = await self._url_active()
        try:
            async with self._get_client(url) as client:
                return await client.put(chemin, content=_stream_file(file_path), headers={"Accept": accept})
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if not self.repli or url == self.repli:
                raise
            # Rien n'a été traité : la connexion n'a pas abouti. Bascule sans risque de double OCR.
            _marquer_injoignable(url)
            log.warning("Tika principal injoignable à l'envoi — repli", principal=url, repli=self.repli)
            async with self._get_client(self.repli) as client:
                return await client.put(chemin, content=_stream_file(file_path), headers={"Accept": accept})

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=_PAS_DE_NOUVEL_ESSAI,
    )
    async def extract_text(self, file_path: Path) -> str:
        """
        Extrait le texte brut d'un fichier via Tika.

        Args:
            file_path: Chemin vers le fichier à extraire

        Returns:
            Texte brut extrait
        """
        log.info("Extraction texte Tika", fichier=file_path.name)

        async with _verrou_tika():
            response = await self._envoyer("/tika", file_path, "text/plain")   # upload par blocs
            response.raise_for_status()
            texte = response.text

        log.info("Extraction texte OK", fichier=file_path.name, nb_caracteres=len(texte))
        return texte

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=_PAS_DE_NOUVEL_ESSAI,
    )
    async def extract_metadata(self, file_path: Path) -> list[dict]:
        """
        Extrait texte + métadonnées d'un fichier (ou d'un ZIP) via Tika /rmeta.
        Pour un ZIP, retourne une liste de dicts (un par fichier dans le ZIP).

        Args:
            file_path: Chemin vers le fichier

        Returns:
            Liste de dicts avec X-TIKA:content (texte) + métadonnées Tika
        """
        log.info("Extraction métadonnées Tika", fichier=file_path.name)

        async with _verrou_tika():
            response = await self._envoyer("/rmeta/text", file_path, "application/json")   # upload par blocs
            response.raise_for_status()
            metadata = response.json()

        # Tika retourne toujours une liste
        if not isinstance(metadata, list):
            metadata = [metadata]

        log.info(
            "Extraction métadonnées OK",
            fichier=file_path.name,
            nb_documents=len(metadata),
        )
        return metadata

    async def check_health(self) -> bool:
        """Vérifie qu'un Tika est disponible (le principal, ou à défaut le repli)."""
        try:
            async with self._get_client(await self._url_active()) as client:
                response = await client.get("/tika")
                return response.status_code == 200
        except Exception as e:
            log.warning("Tika non disponible", erreur=str(e))
            return False


# TODO Phase 1 : instancier et injecter via FastAPI Depends()
