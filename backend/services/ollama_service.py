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
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
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
    ) -> str:
        """
        Génère une réponse LLM (mode non-streaming).

        Args:
            prompt: Prompt utilisateur
            model: Modèle Ollama (défaut : settings.ollama_model_default)
            system: Prompt système (optionnel)
            stream: Si True, utiliser generate_stream() à la place

        Returns:
            Texte généré complet
        """
        model = model or settings.ollama_model_default
        log.info("Génération Ollama", modele=model, nb_chars_prompt=len(prompt))

        payload: dict = {"model": model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        if format:
            payload["format"] = format  # ex. "json" → Ollama garantit une sortie JSON valide

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
    ) -> AsyncGenerator[str, None]:
        """
        Génère une réponse LLM en streaming (pour SSE).

        Yields:
            Morceaux de texte au fur et à mesure
        """
        model = model or settings.ollama_model_default
        log.info("Génération streaming Ollama", modele=model)

        payload: dict = {"model": model, "prompt": prompt, "stream": True}
        if system:
            payload["system"] = system

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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def embed(self, text: str, model: str | None = None) -> list[float]:
        """
        Calcule le vecteur d'embedding d'un texte.

        Args:
            text: Texte à encoder
            model: Modèle d'embedding (défaut : settings.ollama_model_embedding)

        Returns:
            Vecteur d'embedding (liste de floats)
        """
        model = model or settings.ollama_model_embedding
        log.debug("Calcul embedding", modele=model, nb_chars=len(text))

        async with self._get_client() as client:
            response = await client.post(
                "/api/embeddings",
                json={"model": model, "prompt": text},
            )
            response.raise_for_status()
            data = response.json()

        embedding = data.get("embedding", [])
        log.debug("Embedding OK", modele=model, dimension=len(embedding))
        return embedding

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

    async def check_update(self, name: str, local_digest: str) -> bool | None:
        """
        Compare le digest local au manifest du registre Ollama.
        Returns: True (MAJ dispo), False (à jour), None (inconnu : modèle custom,
        absent du registre, ou registre injoignable).
        """
        import hashlib

        repo, tag = self._registry_ref(name)
        url = f"https://registry.ollama.ai/v2/{repo}/manifests/{tag}"
        headers = {"Accept": "application/vnd.docker.distribution.manifest.v2+json"}
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return None  # 404 → modèle custom / hors registre
            remote_digest = hashlib.sha256(resp.content).hexdigest()
            return remote_digest != (local_digest or "")
        except Exception as exc:
            log.warning("Vérif MAJ impossible", modele=name, erreur=str(exc))
            return None

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
