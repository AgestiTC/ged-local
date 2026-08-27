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

import json
from collections.abc import AsyncGenerator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings
from logger import get_logger

log = get_logger(__name__)
settings = get_settings()


class OllamaService:
    """Client async pour Ollama."""

    def __init__(self, base_url: str | None = None):
        # URL effective : surcharge base (runtime_config) > variable d'env.
        from services.runtime_config import effective
        self.base_url = base_url or effective("ollama_url")
        self.timeout = settings.ollama_timeout

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
        )

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=5, max=30),
    )
    async def generate(
        self,
        prompt: str,
        model: str | None = None,
        system: str | None = None,
        stream: bool = False,
        format: str | None = None,
        images: list[str] | None = None,
    ) -> str:
        """
        Génère une réponse LLM (mode non-streaming).

        Args:
            prompt: Prompt utilisateur
            model: Modèle Ollama (défaut : settings.ollama_model_default)
            system: Prompt système (optionnel)
            stream: Si True, utiliser generate_stream() à la place
            images: Images en base64 (modèles vision : glm-ocr, llava…) — OCR / description

        Returns:
            Texte généré complet
        """
        model = model or settings.ollama_model_default
        log.info("Génération Ollama", modele=model, nb_chars_prompt=len(prompt), nb_images=len(images or []))

        payload: dict = {"model": model, "prompt": prompt, "stream": False, "keep_alive": settings.ollama_keep_alive}
        if system:
            payload["system"] = system
        if format:
            payload["format"] = format  # ex. "json" → Ollama garantit une sortie JSON valide
        if images:
            payload["images"] = images  # base64 (sans préfixe data:) pour modèles vision

        async with self._get_client() as client:
            response = await client.post("/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()

        texte = data.get("response", "")
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
        log.info("Génération streaming Ollama", modele=model, think=think)

        # `keep_alive` était OUBLIÉ ici — seuls `generate()` et les embeddings le passaient. Le
        # modèle des RAPPORTS retombait donc sur le défaut d'Ollama (5 min) et se faisait
        # décharger entre deux usages : la requête suivante devait recharger le modèle à froid
        # (43 Go pour Qwen3.6-35B), au risque de dépasser le délai d'un proxy intermédiaire.
        # Constaté en prod le 21/07 : deux rapports réussis, puis échec ~1 h 45 plus tard.
        payload: dict = {"model": model, "prompt": prompt, "stream": True,
                         "keep_alive": settings.ollama_keep_alive}
        if system:
            payload["system"] = system
        if think is not None:
            payload["think"] = think

        async with self._get_client() as client:
            async with client.stream("POST", "/api/generate", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        data = json.loads(line)
                        if chunk := data.get("response"):
                            yield chunk
                        if data.get("done"):
                            break

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
        log.info("Chat streaming Ollama", modele=model, nb_messages=len(messages))
        payload: dict = {"model": model, "messages": messages, "stream": True,
                         "keep_alive": settings.ollama_keep_alive}
        if think is not None:
            payload["think"] = think

        async with self._get_client() as client:
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def embed(self, text: str, model: str | None = None, timeout: float | None = None) -> list[float]:
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
        log.debug("Calcul embedding", modele=model, nb_chars=len(text))

        async with self._get_client() as client:
            kw = {"timeout": timeout} if timeout is not None else {}
            response = await client.post(
                "/api/embeddings",
                json={"model": model, "prompt": text, "keep_alive": settings.ollama_keep_alive},
                **kw,
            )
            response.raise_for_status()
            data = response.json()

        embedding = data.get("embedding", [])
        log.debug("Embedding OK", modele=model, dimension=len(embedding))
        return embedding

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
        try:
            async with self._get_client() as client:
                resp = await client.post("/api/generate", json={
                    "model": model, "prompt": "", "stream": False,
                    "keep_alive": settings.ollama_keep_alive,
                    "options": {"num_predict": 0},
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
        return [m["name"] for m in data.get("models", [])]

    async def list_models_detailed(self) -> list[dict]:
        """Retourne les modèles installés avec leur taille (nom + octets + famille)."""
        async with self._get_client() as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
            data = response.json()
        modeles = []
        for m in data.get("models", []):
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
        log.info("Pull modèle Ollama", modele=name)
        # Pas de timeout court : un pull peut être long.
        async with httpx.AsyncClient(base_url=self.base_url, timeout=None) as client:
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
