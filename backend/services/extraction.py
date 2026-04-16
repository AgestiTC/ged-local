"""
Service Extraction — Pipeline complet fichier → DB
====================================================
Orchestre : hash SHA256 → Tika → DB → enrichissement IA → embeddings.

Flux :
  1. Calcul hash + détection doublon
  2. Insertion dans documents (statut=pending)
  3. Appel Tika → texte + métadonnées
  4. Mise à jour documents (statut=extracted)
  5. Enrichissement IA via Ollama (catégorie, tags, résumé...)
  6. Génération embeddings par chunks
  7. Statut final = enriched
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from logger import get_logger
from models.document import Document
from models.metadata import MetadonneeIA
from utils.hash_utils import compute_sha256

log = get_logger(__name__)
settings = get_settings()

# Prompt système pour l'enrichissement IA
PROMPT_ENRICHISSEMENT = """Tu es un assistant spécialisé en classification documentaire.
Analyse le document fourni et retourne UNIQUEMENT un objet JSON valide (sans markdown, sans commentaires, sans texte avant ou après).

Le JSON doit avoir exactement cette structure :
{
  "categorie": "catégorie principale du document (ex: contrat, rapport, facture, présentation, note...)",
  "sous_categorie": "sous-catégorie si applicable, sinon null",
  "tags": ["tag1", "tag2", "tag3"],
  "resume": "résumé du document en 2 à 3 phrases claires",
  "langue": "code ISO 639-1 de la langue principale (fr, en, de, es...)",
  "entites": {
    "personnes": ["nom1", "nom2"],
    "dates": ["date1", "date2"],
    "lieux": ["lieu1", "lieu2"],
    "organisations": ["org1", "org2"]
  },
  "mots_cles": ["mot1", "mot2", "mot3", "mot4", "mot5"],
  "niveau_confidentialite": "normal"
}"""


def _extraire_json(reponse: str) -> dict:
    """
    Extrait un objet JSON d'une réponse LLM, même si elle contient du markdown.
    Lève json.JSONDecodeError si aucun JSON valide n'est trouvé.
    """
    texte = reponse.strip()

    # Cas 1 : JSON direct
    try:
        return json.loads(texte)
    except json.JSONDecodeError:
        pass

    # Cas 2 : JSON dans un bloc ```json ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texte, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    # Cas 3 : premier { ... } trouvé dans la réponse
    match = re.search(r"\{.*\}", texte, re.DOTALL)
    if match:
        return json.loads(match.group(0))

    raise json.JSONDecodeError("Aucun JSON trouvé", texte, 0)


class ExtractionService:
    """Pipeline d'extraction et d'enrichissement de documents."""

    def __init__(self, tika_service, ollama_service, embedding_service):
        self.tika = tika_service
        self.ollama = ollama_service
        self.embeddings = embedding_service

    async def process_file(
        self,
        file_path: Path,
        source: str = "watch",
        db: AsyncSession = None,
    ) -> str:
        """
        Traite un fichier de bout en bout : extraction → enrichissement → embeddings.

        Args:
            file_path: Chemin vers le fichier
            source: Origine du fichier (watch | upload | drag_drop)
            db: Session DB async

        Returns:
            ID (str) du document créé ou existant (si doublon)
        """
        log.info("Traitement fichier", fichier=file_path.name, source=source)

        # 1. Hash SHA256 — déduplication
        hash_sha256 = compute_sha256(file_path)
        result = await db.execute(select(Document).where(Document.hash_sha256 == hash_sha256))
        existing = result.scalar_one_or_none()
        if existing:
            log.info("Document déjà indexé (doublon)", hash=hash_sha256[:8], doc_id=str(existing.id))
            return str(existing.id)

        # 2. Insertion en DB (statut=pending)
        stat = file_path.stat()
        doc = Document(
            chemin=str(file_path.resolve()),
            nom=file_path.name,
            extension=file_path.suffix.lstrip(".").lower(),
            hash_sha256=hash_sha256,
            taille_octets=stat.st_size,
            date_modification_fichier=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            statut="pending",
            source=source,
        )
        db.add(doc)
        await db.flush()
        doc_id = str(doc.id)
        log.info("Document créé", doc_id=doc_id, fichier=file_path.name)

        try:
            # 3. Extraction Tika
            metadata_list = await self.tika.extract_metadata(file_path)
            metadata = metadata_list[0] if metadata_list else {}

            texte = metadata.pop("X-TIKA:content", "") or ""
            type_mime = (metadata.get("Content-Type") or "").split(";")[0].strip()

            doc.texte_extrait = texte
            doc.tika_metadata = metadata
            doc.type_mime = type_mime or None
            doc.statut = "extracted"
            doc.date_derniere_extraction = datetime.now(tz=timezone.utc)
            await db.flush()

            if texte.strip():
                # 4. Enrichissement IA
                await self._enrich(doc, texte, db)

                # 5. Embeddings
                await self.embeddings.embed_document(doc_id, texte, db)

            doc.statut = "enriched"

        except Exception as e:
            doc.statut = "error"
            doc.erreur = str(e)
            log.error("Erreur pipeline extraction", doc_id=doc_id, erreur=str(e), exc_info=True)

        await db.flush()
        log.info("Traitement terminé", doc_id=doc_id, statut=doc.statut)
        return doc_id

    async def _enrich(self, doc: Document, texte: str, db: AsyncSession) -> None:
        """
        Enrichit un document via Ollama : catégorie, tags, résumé, entités.
        Stocke le résultat dans metadonnees_ia.
        """
        # Tronquer pour rester dans le contexte du modèle rapide (~4k tokens ≈ 16k chars)
        texte_tronque = texte[:16000]

        prompt = f"{PROMPT_ENRICHISSEMENT}\n\nDocument à analyser :\n{texte_tronque}"

        try:
            reponse = await self.ollama.generate(prompt, model=settings.ollama_model_fast)
            data = _extraire_json(reponse)

            meta = MetadonneeIA(
                document_id=doc.id,
                categorie=data.get("categorie"),
                sous_categorie=data.get("sous_categorie"),
                tags=data.get("tags") or [],
                resume=data.get("resume"),
                langue=data.get("langue"),
                entites=data.get("entites"),
                mots_cles=data.get("mots_cles") or [],
                niveau_confidentialite=data.get("niveau_confidentialite", "normal"),
                modele_utilise=settings.ollama_model_fast,
            )
            db.add(meta)
            await db.flush()
            log.info("Enrichissement IA OK", doc_id=str(doc.id), categorie=meta.categorie)

        except json.JSONDecodeError as e:
            log.warning(
                "Réponse LLM non parseable — métadonnées IA ignorées",
                doc_id=str(doc.id),
                erreur=str(e),
            )
        except Exception as e:
            log.warning(
                "Enrichissement IA échoué — extraction conservée",
                doc_id=str(doc.id),
                erreur=str(e),
            )

    async def process_zip(self, zip_path: Path, source: str = "upload", db: AsyncSession = None) -> list[str]:
        """
        Traite un fichier ZIP via Tika /rmeta qui retourne un document par fichier.
        Chaque sous-document est inséré comme document indépendant.

        Returns:
            Liste des IDs de documents créés
        """
        log.info("Traitement ZIP", fichier=zip_path.name)

        # Tika /rmeta retourne une liste : un dict par fichier dans le ZIP
        metadata_list = await self.tika.extract_metadata(zip_path)
        log.info("ZIP extrait par Tika", nb_fichiers=len(metadata_list))

        doc_ids = []
        for i, metadata in enumerate(metadata_list):
            texte = metadata.pop("X-TIKA:content", "") or ""
            nom_fichier = (
                metadata.get("resourceName")
                or metadata.get("dc:title")
                or f"{zip_path.stem}_fichier_{i + 1}"
            )
            type_mime = (metadata.get("Content-Type") or "").split(";")[0].strip()
            extension = Path(nom_fichier).suffix.lstrip(".").lower() if "." in nom_fichier else "bin"

            # Pas de hash SHA256 fiable pour les sous-fichiers sans les extraire physiquement
            # On hash le contenu texte pour la déduplication
            import hashlib
            hash_contenu = hashlib.sha256(texte.encode("utf-8", errors="replace")).hexdigest()

            result = await db.execute(select(Document).where(Document.hash_sha256 == hash_contenu))
            if result.scalar_one_or_none():
                log.info("Sous-document ZIP déjà indexé", nom=nom_fichier)
                continue

            doc = Document(
                chemin=f"{zip_path.resolve()}::{nom_fichier}",
                nom=nom_fichier,
                extension=extension,
                type_mime=type_mime or None,
                hash_sha256=hash_contenu,
                taille_octets=len(texte.encode("utf-8")),
                texte_extrait=texte,
                tika_metadata=metadata,
                statut="extracted",
                source=source,
                date_derniere_extraction=datetime.now(tz=timezone.utc),
            )
            db.add(doc)
            await db.flush()
            doc_id = str(doc.id)

            try:
                if texte.strip():
                    await self._enrich(doc, texte, db)
                    await self.embeddings.embed_document(doc_id, texte, db)
                doc.statut = "enriched"
            except Exception as e:
                doc.statut = "error"
                doc.erreur = str(e)
                log.error("Erreur sous-document ZIP", nom=nom_fichier, erreur=str(e))

            await db.flush()
            doc_ids.append(doc_id)

        log.info("Traitement ZIP terminé", nb_documents=len(doc_ids))
        return doc_ids
