"""
Service BookStack — Publication de tutos sur le wiki externe
=============================================================
Client async pour l'API REST de BookStack (https://wiki.agesti.fr/api).

Endpoints utilisés :
  GET  /api/books            → liste des livres (cibles de publication)
  GET  /api/chapters         → liste des chapitres
  POST /api/books            → créer un livre  {name}
  POST /api/chapters         → créer un chapitre  {book_id, name}
  POST /api/pages            → créer une page (tuto)  {book_id|chapter_id, name, markdown}
  PUT  /api/pages/{id}       → mettre à jour une page existante (republication)

Authentification : header `Authorization: Token <token_id>:<token_secret>`.
Le secret est stocké chiffré en base (Fernet) ; il est déchiffré ici à la lecture.
"""

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config import get_settings
from logger import get_logger

log = get_logger(__name__)
settings = get_settings()


class BookStackService:
    """Client async pour l'API BookStack."""

    def __init__(
        self,
        base_url: str | None = None,
        token_id: str | None = None,
        token_secret: str | None = None,
    ):
        # Valeurs effectives : surcharge base (runtime_config) > variable d'env.
        from services.runtime_config import effective
        from services.crypto import decrypt

        self.base_url = (base_url if base_url is not None else effective("bookstack_url")).rstrip("/")
        self.token_id = token_id if token_id is not None else effective("bookstack_token_id")
        # Le secret stocké est chiffré (enc::…) ; decrypt() est tolérant si déjà en clair
        # (cas d'un override passé tel quel depuis le formulaire de test).
        raw_secret = token_secret if token_secret is not None else effective("bookstack_token_secret")
        self.token_secret = decrypt(raw_secret) if raw_secret else ""
        self.timeout = settings.bookstack_timeout

    @property
    def configured(self) -> bool:
        """Vrai si l'URL et le jeton complet sont renseignés."""
        return bool(self.base_url and self.token_id and self.token_secret)

    def _get_client(self) -> httpx.AsyncClient:
        """Retourne un client httpx avec l'en-tête d'authentification."""
        headers = {"Accept": "application/json"}
        if self.token_id and self.token_secret:
            headers["Authorization"] = f"Token {self.token_id}:{self.token_secret}"
        return httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, headers=headers)

    async def check_health(self) -> bool:
        """Vérifie la connectivité + l'authentification (appel léger)."""
        if not self.configured:
            return False
        try:
            async with self._get_client() as client:
                response = await client.get("/api/books", params={"count": 1})
                return response.status_code == 200
        except Exception as e:
            log.warning("BookStack non disponible", erreur=str(e))
            return False

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def list_books(self) -> list[dict]:
        """Liste les livres (id, name, slug)."""
        async with self._get_client() as client:
            response = await client.get("/api/books", params={"count": 200, "sort": "name"})
            response.raise_for_status()
            data = response.json().get("data", [])
        return [{"id": b["id"], "name": b["name"], "slug": b.get("slug")} for b in data]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def list_chapters(self) -> list[dict]:
        """Liste les chapitres (id, name, book_id)."""
        async with self._get_client() as client:
            response = await client.get("/api/chapters", params={"count": 500, "sort": "name"})
            response.raise_for_status()
            data = response.json().get("data", [])
        return [{"id": c["id"], "name": c["name"], "book_id": c.get("book_id")} for c in data]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def create_book(self, name: str, description: str | None = None) -> dict:
        """Crée un livre (id, name, slug renvoyés par BookStack)."""
        payload: dict = {"name": name}
        if description:
            payload["description"] = description
        log.info("BookStack : création livre", nom=name)
        async with self._get_client() as client:
            response = await client.post("/api/books", json=payload)
            response.raise_for_status()
            data = response.json()
        log.info("BookStack : livre créé", id=data.get("id"), slug=data.get("slug"))
        return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def create_chapter(self, book_id: int, name: str, description: str | None = None) -> dict:
        """Crée un chapitre dans un livre (id, name, book_id renvoyés)."""
        payload: dict = {"book_id": book_id, "name": name}
        if description:
            payload["description"] = description
        log.info("BookStack : création chapitre", nom=name, book_id=book_id)
        async with self._get_client() as client:
            response = await client.post("/api/chapters", json=payload)
            response.raise_for_status()
            data = response.json()
        log.info("BookStack : chapitre créé", id=data.get("id"), book_id=book_id)
        return data

    async def ensure_book(self, name: str) -> dict:
        """
        Renvoie le livre nommé `name`, en le créant s'il n'existe pas (idempotence).
        Comparaison insensible à la casse/aux espaces.
        """
        cible = name.strip().casefold()
        for b in await self.list_books():
            if b["name"].strip().casefold() == cible:
                log.info("BookStack : livre existant réutilisé", id=b["id"], nom=name)
                return b
        return await self.create_book(name.strip())

    async def ensure_chapter(self, book_id: int, name: str) -> dict:
        """
        Renvoie le chapitre nommé `name` dans `book_id`, en le créant au besoin.
        Comparaison insensible à la casse/aux espaces, restreinte au livre cible.
        """
        cible = name.strip().casefold()
        for c in await self.list_chapters():
            if c.get("book_id") == book_id and c["name"].strip().casefold() == cible:
                log.info("BookStack : chapitre existant réutilisé", id=c["id"], nom=name)
                return c
        return await self.create_chapter(book_id, name.strip())

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def create_page(
        self,
        name: str,
        markdown: str,
        book_id: int | None = None,
        chapter_id: int | None = None,
    ) -> dict:
        """
        Crée une page (tuto) dans un livre OU un chapitre.

        Args:
            name: Titre de la page.
            markdown: Contenu Markdown.
            book_id: Livre cible (exclusif avec chapter_id).
            chapter_id: Chapitre cible (exclusif avec book_id).

        Returns:
            Dict de la page créée (id, slug, book_id, …) renvoyé par BookStack.
        """
        if not (book_id or chapter_id):
            raise ValueError("Une cible est requise : book_id ou chapter_id.")

        payload: dict = {"name": name, "markdown": markdown}
        if chapter_id:
            payload["chapter_id"] = chapter_id
        else:
            payload["book_id"] = book_id

        log.info("BookStack : création page", titre=name, book_id=book_id, chapter_id=chapter_id)
        async with self._get_client() as client:
            response = await client.post("/api/pages", json=payload)
            response.raise_for_status()
            data = response.json()
        log.info("BookStack : page créée", id=data.get("id"), slug=data.get("slug"))
        return data

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def update_page(self, page_id: int, markdown: str, name: str | None = None) -> dict:
        """Met à jour le contenu d'une page existante (crée une révision côté BookStack)."""
        payload: dict = {"markdown": markdown}
        if name:
            payload["name"] = name
        log.info("BookStack : mise à jour page", id=page_id)
        async with self._get_client() as client:
            response = await client.put(f"/api/pages/{page_id}", json=payload)
            response.raise_for_status()
            return response.json()

    def page_url(self, page: dict) -> str:
        """Construit l'URL publique d'une page à partir de la réponse API."""
        slug = page.get("slug", "")
        book_slug = page.get("book_slug")
        if book_slug and slug:
            return f"{self.base_url}/books/{book_slug}/page/{slug}"
        # Repli : lien direct par identifiant (BookStack redirige).
        return f"{self.base_url}/link/{page.get('id', '')}"
