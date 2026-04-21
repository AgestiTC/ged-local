"""
Service Extraction — Pipeline complet fichier → DB
====================================================
Orchestre : hash SHA256 → Tika → DB → enrichissement IA → embeddings.

Flux (nouveau fichier) :
  1. Calcul hash + détection doublon (même hash → skip)
  2. Détection version (même chemin + hash différent → archiver + mettre à jour)
  3. Insertion dans documents (statut=pending)
  4. Appel Tika → texte + métadonnées
  5. Mise à jour documents (statut=extracted)
  6. Enrichissement IA via Ollama (catégorie, tags, résumé...)
  7. Génération embeddings par chunks
  8. Statut final = enriched
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import get_settings
from logger import get_logger
from models.document import Document
from models.embedding import Embedding
from models.metadata import MetadonneeIA
from models.version import Version
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
        folder_tag: str | None = None,
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

        # 1. Hash SHA256 — doublon exact (même contenu, peu importe le chemin)
        hash_sha256 = compute_sha256(file_path)
        result = await db.execute(select(Document).where(Document.hash_sha256 == hash_sha256))
        existing_same_hash = result.scalar_one_or_none()
        if existing_same_hash:
            log.info("Document déjà indexé (doublon)", hash=hash_sha256[:8], doc_id=str(existing_same_hash.id))
            return str(existing_same_hash.id)

        # 2. Détection version — même chemin, contenu différent
        chemin_absolu = str(file_path.resolve())
        result = await db.execute(
            select(Document)
            .options(selectinload(Document.metadonnees_ia))
            .where(Document.chemin == chemin_absolu)
        )
        existing_same_path = result.scalar_one_or_none()

        version_archivee: Version | None = None
        ancien_resume: str | None = None

        if existing_same_path:
            log.info(
                "Nouvelle version détectée",
                fichier=file_path.name,
                ancien_hash=existing_same_path.hash_sha256[:8],
                nouveau_hash=hash_sha256[:8],
            )
            # Sauvegarder l'ancien résumé avant suppression des métadonnées
            if existing_same_path.metadonnees_ia:
                ancien_resume = existing_same_path.metadonnees_ia.resume
            doc, version_archivee = await self._update_version(existing_same_path, hash_sha256, file_path, db)
            doc_id = str(doc.id)
        else:
            # 3. Nouveau document — insertion en DB (statut=pending)
            stat = file_path.stat()
            doc = Document(
                chemin=chemin_absolu,
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

        # Pré-créer metadonnees_ia avec le folder_tag dès l'upload (avant l'IA)
        if folder_tag:
            existing_meta = (await db.execute(
                select(MetadonneeIA).where(MetadonneeIA.document_id == doc.id)
            )).scalar_one_or_none()
            if not existing_meta:
                db.add(MetadonneeIA(
                    document_id=doc.id,
                    tags=[folder_tag],
                    niveau_confidentialite="normal",
                ))
                await db.flush()
                log.info("Tag dossier pré-appliqué", doc_id=doc_id, tag=folder_tag)

        try:
            # 4. Extraction Tika
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
                # 5. Enrichissement IA
                await self._enrich(doc, texte, db)

                # 6. Diff résumé si c'est une mise à jour de version
                if version_archivee is not None:
                    await self._generate_diff_resume(version_archivee, ancien_resume, texte, db)

                # 7. Embeddings
                await self.embeddings.embed_document(doc_id, texte, db)

            doc.statut = "enriched"

        except Exception as e:
            doc.statut = "error"
            doc.erreur = str(e)
            log.error("Erreur pipeline extraction", doc_id=doc_id, erreur=str(e), exc_info=True)

        await db.flush()
        log.info("Traitement terminé", doc_id=doc_id, statut=doc.statut)
        return doc_id

    async def _update_version(
        self,
        doc: Document,
        nouveau_hash: str,
        file_path: Path,
        db: AsyncSession,
    ) -> tuple["Document", "Version"]:
        """
        Archive la version actuelle d'un document et prépare la mise à jour.
        Supprime les embeddings et métadonnées IA obsolètes.
        Retourne (document mis à jour, objet Version archivé).
        """
        # Déterminer le prochain numéro de version
        result = await db.execute(
            select(func.count()).select_from(Version).where(Version.document_id == doc.id)
        )
        nb_versions = result.scalar_one() or 0
        numero_version = nb_versions + 1

        # Créer l'entrée Version (archive l'état actuel avant mise à jour)
        version = Version(
            document_id=doc.id,
            numero_version=numero_version,
            hash_sha256=doc.hash_sha256,
            taille_octets=doc.taille_octets,
        )
        db.add(version)

        # Supprimer embeddings et métadonnées obsolètes (seront régénérés)
        await db.execute(delete(Embedding).where(Embedding.document_id == doc.id))
        await db.execute(delete(MetadonneeIA).where(MetadonneeIA.document_id == doc.id))

        # Mettre à jour le document avec le nouveau hash
        stat = file_path.stat()
        doc.hash_sha256 = nouveau_hash
        doc.taille_octets = stat.st_size
        doc.date_modification_fichier = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        doc.statut = "pending"
        doc.erreur = None

        await db.flush()
        log.info("Version archivée", doc_id=str(doc.id), numero_version=numero_version)
        return doc, version

    async def _generate_diff_resume(
        self,
        version: "Version",
        ancien_resume: str | None,
        nouveau_texte: str,
        db: AsyncSession,
    ) -> None:
        """
        Génère via Ollama un résumé des changements entre l'ancienne et la nouvelle version.
        Met à jour Version.diff_resume.
        """
        ancien = ancien_resume or "Aucun résumé disponible pour la version précédente."
        nouveau_texte_tronque = nouveau_texte[:8000]

        prompt = (
            "Tu es un assistant de gestion documentaire.\n"
            "Résume EN UNE SEULE PHRASE les changements entre la version précédente et la nouvelle version d'un document.\n\n"
            f"Résumé de l'ancienne version :\n{ancien}\n\n"
            f"Extrait du nouveau contenu :\n{nouveau_texte_tronque}\n\n"
            "Réponds uniquement avec la phrase de résumé, sans introduction ni ponctuation finale."
        )

        try:
            diff = await self.ollama.generate(prompt, model=settings.ollama_model_fast)
            version.diff_resume = diff.strip()
            await db.flush()
            log.info("Diff résumé généré", version_id=str(version.id), diff=diff[:80])
        except Exception as e:
            log.warning("Génération diff résumé échouée", version_id=str(version.id), erreur=str(e))

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

            # Vérifier si une metadonnee_ia existe déjà (pré-créée par folder_tag)
            existing_meta = (await db.execute(
                select(MetadonneeIA).where(MetadonneeIA.document_id == doc.id)
            )).scalar_one_or_none()

            tags_existants = existing_meta.tags or [] if existing_meta else []
            tags_ia = data.get("tags") or []
            # Tags dossier en premier, puis tags IA sans doublons
            tags_finaux = tags_existants + [t for t in tags_ia if t not in tags_existants]

            if existing_meta:
                existing_meta.categorie = data.get("categorie")
                existing_meta.sous_categorie = data.get("sous_categorie")
                existing_meta.tags = tags_finaux
                existing_meta.resume = data.get("resume")
                existing_meta.langue = data.get("langue")
                existing_meta.entites = data.get("entites")
                existing_meta.mots_cles = data.get("mots_cles") or []
                existing_meta.niveau_confidentialite = data.get("niveau_confidentialite", "normal")
                existing_meta.modele_utilise = settings.ollama_model_fast
                meta = existing_meta
            else:
                meta = MetadonneeIA(
                    document_id=doc.id,
                    categorie=data.get("categorie"),
                    sous_categorie=data.get("sous_categorie"),
                    tags=tags_finaux,
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

    async def process_zip(self, zip_path: Path, source: str = "upload", db: AsyncSession = None, folder_tag: str | None = None) -> list[str]:
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
