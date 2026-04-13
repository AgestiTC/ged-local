"""
Service GED — Logique de la Gestion Électronique de Documents
=============================================================
Gère les opérations CRUD sur les documents, les tags, les versions.
Encapsule la logique métier pour une réutilisation dans les routers et les tests.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from logger import get_logger

log = get_logger(__name__)


class GEDService:
    """Service principal de la GED."""

    async def get_documents(
        self,
        db: AsyncSession,
        page: int = 1,
        per_page: int = 20,
        statut: str | None = None,
        extension: str | None = None,
        source: str | None = None,
        q: str | None = None,
    ) -> dict:
        """
        Retourne une liste paginée de documents avec leurs métadonnées.

        Returns:
            {documents: [...], total: int, page: int, per_page: int, pages: int}
        """
        from models.document import Document
        from models.metadata import MetadonneeIA

        stmt = select(Document).options(selectinload(Document.metadonnees_ia))

        if statut:
            stmt = stmt.where(Document.statut == statut)
        if extension:
            stmt = stmt.where(Document.extension == extension)
        if source:
            stmt = stmt.where(Document.source == source)
        if q:
            stmt = stmt.where(Document.nom.ilike(f"%{q}%"))

        # Compter le total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await db.execute(count_stmt)).scalar_one()

        # Pagination
        offset = (page - 1) * per_page
        stmt = stmt.order_by(Document.date_import.desc()).offset(offset).limit(per_page)
        result = await db.execute(stmt)
        documents = result.scalars().all()

        return {
            "documents": [self._document_to_dict(d) for d in documents],
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, -(-total // per_page)),  # ceil division
        }

    async def get_document(self, document_id: str, db: AsyncSession) -> dict | None:
        """Retourne un document avec toutes ses métadonnées, ou None si inexistant."""
        from models.document import Document

        try:
            uid = uuid.UUID(document_id)
        except ValueError:
            return None

        result = await db.execute(
            select(Document)
            .options(selectinload(Document.metadonnees_ia))
            .where(Document.id == uid)
        )
        doc = result.scalar_one_or_none()
        return self._document_to_dict(doc) if doc else None

    async def update_tags(
        self, document_id: str, tags: list[str], db: AsyncSession
    ) -> bool:
        """
        Met à jour les tags d'un document (édition manuelle).

        Returns:
            True si mis à jour, False si document non trouvé
        """
        from models.metadata import MetadonneeIA

        try:
            uid = uuid.UUID(document_id)
        except ValueError:
            return False

        result = await db.execute(
            select(MetadonneeIA).where(MetadonneeIA.document_id == uid)
        )
        meta = result.scalar_one_or_none()

        if not meta:
            return False

        meta.tags = tags
        await db.commit()
        log.info("Tags mis à jour", document_id=document_id, nb_tags=len(tags))
        return True

    async def delete_document(self, document_id: str, db: AsyncSession) -> bool:
        """
        Supprime un document de l'index (pas le fichier source).

        Returns:
            True si supprimé, False si non trouvé
        """
        from models.document import Document

        try:
            uid = uuid.UUID(document_id)
        except ValueError:
            return False

        result = await db.execute(select(Document).where(Document.id == uid))
        doc = result.scalar_one_or_none()

        if not doc:
            return False

        nom = doc.nom
        await db.delete(doc)
        await db.commit()

        log.info("Document supprimé de l'index", id=document_id, nom=nom)
        return True

    async def detect_duplicate(self, hash_sha256: str, db: AsyncSession) -> str | None:
        """
        Vérifie si un document avec ce hash existe déjà.

        Returns:
            document_id (str) si doublon, None sinon
        """
        from models.document import Document

        result = await db.execute(
            select(Document.id).where(Document.hash_sha256 == hash_sha256)
        )
        row = result.scalar_one_or_none()
        return str(row) if row else None

    async def get_stats(self, db: AsyncSession) -> dict:
        """Retourne des statistiques sur la GED."""
        from models.document import Document
        from models.metadata import MetadonneeIA

        # Total documents par statut
        result = await db.execute(
            select(Document.statut, func.count(Document.id))
            .group_by(Document.statut)
        )
        statuts = {row[0]: row[1] for row in result}

        # Total taille
        result = await db.execute(select(func.sum(Document.taille_octets)))
        taille_totale = result.scalar_one() or 0

        # Catégories
        result = await db.execute(
            select(MetadonneeIA.categorie, func.count(MetadonneeIA.id))
            .where(MetadonneeIA.categorie.isnot(None))
            .group_by(MetadonneeIA.categorie)
            .order_by(func.count(MetadonneeIA.id).desc())
            .limit(10)
        )
        categories = [{"categorie": row[0], "nb_documents": row[1]} for row in result]

        return {
            "total_documents": sum(statuts.values()),
            "par_statut": statuts,
            "taille_totale_octets": taille_totale,
            "categories": categories,
        }

    def _document_to_dict(self, doc) -> dict:
        """Convertit un objet Document SQLAlchemy en dict sérialisable."""
        data = {
            "id": str(doc.id),
            "chemin": doc.chemin,
            "nom": doc.nom,
            "extension": doc.extension,
            "type_mime": doc.type_mime,
            "hash_sha256": doc.hash_sha256,
            "taille_octets": doc.taille_octets,
            "date_import": doc.date_import.isoformat() if doc.date_import else None,
            "date_modification_fichier": (
                doc.date_modification_fichier.isoformat()
                if doc.date_modification_fichier else None
            ),
            "statut": doc.statut,
            "source": doc.source,
            "erreur": doc.erreur,
        }

        if hasattr(doc, "metadonnees_ia") and doc.metadonnees_ia:
            meta = doc.metadonnees_ia
            data["metadonnees_ia"] = {
                "id": str(meta.id),
                "categorie": meta.categorie,
                "sous_categorie": meta.sous_categorie,
                "tags": meta.tags or [],
                "resume": meta.resume,
                "langue": meta.langue,
                "entites": meta.entites or {},
                "mots_cles": meta.mots_cles or [],
                "niveau_confidentialite": meta.niveau_confidentialite,
                "modele_utilise": meta.modele_utilise,
            }
        else:
            data["metadonnees_ia"] = None

        return data
