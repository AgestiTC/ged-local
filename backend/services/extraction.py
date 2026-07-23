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

import asyncio
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
from services import clamav_service
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


# ─── OCR / vision de secours (Phase 2) ────────────────────────────────────────
# Quand Tika ne rend aucun texte (image, PDF scanné), on tente une transcription via un
# modèle vision Ollama (glm-ocr). Les PDF sont rastérisés page par page (pymupdf).
_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff"}
_OCR_EXTS = _IMAGE_EXTS | {"pdf"}
_OCR_MODEL = "glm-ocr:latest"
_OCR_MAX_PAGES = 10  # plafond de pages OCR par PDF (coût vision élevé)
_OCR_PROMPT = (
    "Transcris fidèlement TOUT le texte visible dans cette image, sans commentaire ni mise en "
    "forme ajoutée. Si aucune écriture n'est présente, réponds exactement : (aucun texte)."
)
# Fallback « description » : quand l'image ne contient pas de texte (photo), on demande une
# description factuelle → elle devient le texte exploitable (catégorie/tags/résumé ensuite).
_DESCRIBE_PROMPT = (
    "Décris précisément et factuellement le contenu de cette image en français : sujet principal, "
    "objets/personnes visibles, lieu ou contexte, couleurs dominantes. 3 à 5 phrases, sans "
    "spéculation ni interprétation. N'invente rien."
)


# Niveaux de confidentialité autorisés par la contrainte DB (metadonnees_ia_..._check).
# Le LLM renvoie parfois une valeur hors-liste (« public », « privé »…) → on borne à « normal »
# pour ne pas faire échouer l'insertion.
_NIVEAUX_CONF = {"normal", "confidentiel", "restreint"}


def _niveau_conf(valeur) -> str:
    """Normalise le niveau de confidentialité IA vers une valeur autorisée (défaut « normal »)."""
    n = valeur.strip().lower() if isinstance(valeur, str) else ""
    return n if n in _NIVEAUX_CONF else "normal"


def _sans_nul(t: str) -> str:
    """
    Retire l'octet NUL (\\x00) — refusé par PostgreSQL dans une colonne `text` — ainsi que les
    autres caractères de contrôle C0 (hors \\t \\n \\r) que Tika produit parfois sur des binaires.
    Sans ça, l'écriture de `texte_extrait` échoue (asyncpg UntranslatableCharacterError).
    """
    if not t:
        return t
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", t)


def _rasteriser_pdf(chemin: str, max_pages: int, dpi: int = 150) -> list[bytes]:
    """Rend les premières pages d'un PDF en PNG (bytes). Bloquant → à appeler via to_thread."""
    import fitz  # pymupdf

    pages: list[bytes] = []
    with fitz.open(chemin) as pdf:
        for i, page in enumerate(pdf):
            if i >= max_pages:
                break
            pages.append(page.get_pixmap(dpi=dpi).tobytes("png"))
    return pages


class ExtractionService:
    """Pipeline d'extraction et d'enrichissement de documents."""

    def __init__(self, tika_service, ollama_service, embedding_service):
        self.tika = tika_service
        self.ollama = ollama_service
        self.embeddings = embedding_service

    async def catalogue_media(
        self,
        *,
        chemin: str,
        nom: str,
        taille: int,
        source: str = "watch",
        date_modification: datetime | None = None,
        db: AsyncSession = None,
    ) -> str | None:
        """
        Catalogue léger d'un média (image/audio/vidéo) : crée l'entrée en base à
        partir des seules métadonnées (nom/taille/chemin), SANS télécharger le
        fichier ni lancer Tika/IA/embeddings — « indexation média raisonnée ».
        Dédupliqué par chemin. Statut = 'catalogued'.
        """
        import hashlib
        import mimetypes

        # Déjà catalogué/indexé au même emplacement → on ne recrée pas
        existing = (await db.execute(select(Document).where(Document.chemin == chemin))).scalar_one_or_none()
        if existing:
            return str(existing.id)

        ext = Path(nom).suffix.lstrip(".").lower()
        # Hash déterministe (chemin+taille) : pas de contenu téléchargé, mais champ non nul + dédup
        pseudo_hash = hashlib.sha256(f"{chemin}|{taille}".encode("utf-8")).hexdigest()

        doc = Document(
            chemin=chemin,
            nom=nom,
            extension=ext,
            type_mime=mimetypes.guess_type(nom)[0],
            hash_sha256=pseudo_hash,
            taille_octets=taille,
            date_modification_fichier=date_modification,
            statut="catalogued",
            source=source,
        )
        db.add(doc)
        await db.flush()
        log.info("Média catalogué (sans fetch)", nom=nom, taille=taille)
        return str(doc.id)

    async def analyze_existing(
        self,
        doc: Document,
        file_path: Path,
        db: AsyncSession,
        *,
        recompute_hash: bool = True,
    ) -> bool:
        """
        Analyse le CONTENU d'un fichier et met à jour un document **déjà en base**
        (aucune nouvelle ligne → **zéro doublon**). Sert à « Forcer l'analyse » d'un média
        catalogué ou d'un document extrait au texte vide. `file_path` = fichier local ou
        **temporaire** (fetch SMB, supprimé par l'appelant).
        """
        log.info("Analyse contenu (doc existant)", doc_id=str(doc.id), fichier=file_path.name)

        # Antivirus avant toute extraction.
        clean, signature = await clamav_service.scan_file(str(file_path))
        if not clean:
            doc.statut = "error"
            doc.erreur = f"Menace détectée par l'antivirus : {signature}"
            await db.commit()
            log.warning("Fichier INFECTÉ — analyse annulée", doc_id=str(doc.id), signature=signature)
            return False

        # Vrai hash du contenu (le média catalogué portait un pseudo-hash chemin+taille) →
        # rend le doc dédupliquable ensuite. On garde l'ancien hash si le calcul échoue.
        if recompute_hash:
            try:
                doc.hash_sha256 = await asyncio.to_thread(compute_sha256, file_path)
            except Exception:  # noqa: BLE001
                pass
        try:
            doc.taille_octets = file_path.stat().st_size
        except OSError:
            pass

        # Extraction Tika (même logique que process_file, mais sur le doc existant).
        metadata_list = await self.tika.extract_metadata(file_path)
        metadata = metadata_list[0] if metadata_list else {}
        texte = _sans_nul(metadata.pop("X-TIKA:content", "") or "")
        type_mime = (metadata.get("Content-Type") or "").split(";")[0].strip()

        doc.texte_extrait = texte
        doc.tika_metadata = metadata
        doc.type_mime = type_mime or doc.type_mime
        doc.statut = "extracted"
        doc.erreur = None
        doc.date_derniere_extraction = datetime.now(tz=timezone.utc)
        await db.flush()

        # OCR / vision de secours : Tika n'a rien rendu → image ou PDF scanné.
        if not texte.strip() and (doc.extension or "").lower() in _OCR_EXTS:
            texte = _sans_nul(await self._ocr_fallback(file_path, doc.extension or ""))
            if texte.strip():
                doc.texte_extrait = texte
                await db.flush()

        ok = False
        if texte.strip():
            ok = await self._enrich(doc, texte, db)
            await self.embeddings.embed_document(str(doc.id), texte, db)
            doc.statut = "enriched" if ok else "extracted"
        await db.commit()
        log.info("Analyse contenu terminée", doc_id=str(doc.id), statut=doc.statut, texte_len=len(texte))
        return ok

    async def _ocr_fallback(self, file_path: Path, ext: str) -> str:
        """
        Transcription de secours quand Tika ne rend aucun texte : envoie l'image (ou chaque
        page rastérisée d'un PDF scanné) au modèle vision Ollama (glm-ocr). Robuste aux échecs
        (retourne "" si l'OCR ne donne rien d'exploitable).
        """
        import base64

        from services import runtime_config

        ext = ext.lower()
        # Modèles vision à essayer : configuré pour l'usage « vision », puis fallback sur les
        # autres modèles vision INSTALLÉS (même famille). On garde le 1er qui rend du texte.
        candidats = await runtime_config.model_candidates("vision")
        if not candidats:
            candidats = [runtime_config.usage_model("vision") or runtime_config.effective("vision_model") or _OCR_MODEL]

        def _propre(t: str) -> str:
            t = (t or "").strip()
            if not t:
                return ""
            # Retire TOUTES les occurrences de la sentinelle « (aucun texte) » (le modèle la
            # répète parfois). S'il ne reste rien de significatif → pas de contenu exploitable.
            net = re.sub(r"[(\[]?\s*aucun\s+texte\s*[)\]]?", "", t, flags=re.IGNORECASE)
            net = re.sub(r"\s+", " ", net).strip()
            return t if len(net) >= 3 else ""

        try:
            if ext in _IMAGE_EXTS:
                b64 = base64.b64encode(await asyncio.to_thread(file_path.read_bytes)).decode()
                # 1) OCR : transcription du texte visible (scans, captures d'écran…).
                for model in candidats:
                    try:
                        log.info("OCR image (vision)", fichier=file_path.name, modele=model)
                        t = _propre(await self.ollama.generate(_OCR_PROMPT, model=model, images=[b64]))
                        if t:
                            return t
                    except Exception as e:  # noqa: BLE001 — modèle KO → suivant
                        log.warning("OCR image — bascule modèle suivant", fichier=file_path.name, modele=model, erreur=str(e))
                # 2) Aucun texte → DESCRIPTION visuelle (photo) : rend la fiche exploitable.
                for model in candidats:
                    try:
                        log.info("Description image (vision)", fichier=file_path.name, modele=model)
                        d = (await self.ollama.generate(_DESCRIBE_PROMPT, model=model, images=[b64]) or "").strip()
                        if len(d) >= 10:
                            return d
                    except Exception as e:  # noqa: BLE001 — modèle KO → suivant
                        log.warning("Description image — bascule modèle suivant", fichier=file_path.name, modele=model, erreur=str(e))
                return ""

            if ext == "pdf":
                pages = await asyncio.to_thread(_rasteriser_pdf, str(file_path), _OCR_MAX_PAGES)
                b64s = [base64.b64encode(png).decode() for png in pages]
                # 1) OCR : transcription du texte de chaque page (PDF scanné classique).
                for model in candidats:
                    try:
                        log.info("OCR PDF scanné (vision)", fichier=file_path.name, nb_pages=len(pages), modele=model)
                        morceaux: list[str] = []
                        for b64 in b64s:
                            t = _propre(await self.ollama.generate(_OCR_PROMPT, model=model, images=[b64]))
                            if t:
                                morceaux.append(t)
                        if morceaux:
                            return "\n\n".join(morceaux).strip()
                    except Exception as e:  # noqa: BLE001 — modèle KO → suivant
                        log.warning("OCR PDF — bascule modèle suivant", fichier=file_path.name, modele=model, erreur=str(e))
                # 2) Aucun texte → DESCRIPTION des pages (PDF « image » : photos, plans scannés…).
                for model in candidats:
                    try:
                        log.info("Description PDF (vision)", fichier=file_path.name, nb_pages=len(pages), modele=model)
                        morceaux = []
                        for b64 in b64s:
                            d = (await self.ollama.generate(_DESCRIBE_PROMPT, model=model, images=[b64]) or "").strip()
                            if len(d) >= 10:
                                morceaux.append(d)
                        if morceaux:
                            return "\n\n".join(morceaux).strip()
                    except Exception as e:  # noqa: BLE001 — modèle KO → suivant
                        log.warning("Description PDF — bascule modèle suivant", fichier=file_path.name, modele=model, erreur=str(e))
                return ""
        except Exception as e:  # noqa: BLE001 — l'OCR est un « best effort »
            log.warning("OCR fallback échoué", fichier=file_path.name, erreur=str(e))
        return ""

    async def process_file(
        self,
        file_path: Path,
        source: str = "watch",
        db: AsyncSession = None,
        folder_tag: str | None = None,
        chemin_logique: str | None = None,
        mtime_fichier: datetime | None = None,
    ) -> str:
        """
        Traite un fichier de bout en bout : extraction → enrichissement → embeddings.

        Args:
            file_path: Chemin vers le fichier **à lire** (peut être un temporaire)
            source: Origine du fichier (watch | upload | drag_drop)
            db: Session DB async
            chemin_logique: chemin à ENREGISTRER s'il diffère du fichier lu — cas SMB, où le
                contenu est rapatrié dans `/tmp` mais doit être indexé sous `smb://hote/partage/…`.
                ⚠️ Sans lui, la détection de version (étape 2, « même chemin, contenu différent »)
                comparait au chemin du **temporaire** : elle ne matchait jamais, et modifier un
                fichier sur le NAS créait une **2ᵉ ligne** au même `chemin` au lieu d'une version.
            mtime_fichier: date de modification RÉELLE de la source (le temporaire porte la date
                du rapatriement, inexploitable pour détecter un changement au scan suivant).

        Returns:
            ID (str) du document créé ou existant (si doublon)
        """
        log.info("Traitement fichier", fichier=file_path.name, source=source)

        # 1. Hash SHA256 — doublon exact (même contenu, peu importe le chemin).
        #    Lecture/hash déportés en thread : sinon la lecture synchrone d'un gros
        #    fichier bloquerait l'event loop (API gelée pendant l'indexation).
        hash_sha256 = await asyncio.to_thread(compute_sha256, file_path)
        result = await db.execute(select(Document).where(Document.hash_sha256 == hash_sha256))
        existing_same_hash = result.scalar_one_or_none()
        if existing_same_hash:
            log.info("Document déjà indexé (doublon)", hash=hash_sha256[:8], doc_id=str(existing_same_hash.id))
            return str(existing_same_hash.id)

        # 2. Détection version — même chemin, contenu différent
        chemin_absolu = chemin_logique or str(file_path.resolve())
        nom_fichier = Path(chemin_logique).name if chemin_logique else file_path.name
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
            doc, version_archivee = await self._update_version(
                existing_same_path, hash_sha256, file_path, db, mtime_fichier=mtime_fichier
            )
            doc_id = str(doc.id)
        else:
            # 3. Nouveau document — insertion en DB (statut=pending)
            stat = file_path.stat()
            doc = Document(
                chemin=chemin_absolu,
                nom=nom_fichier,
                extension=Path(nom_fichier).suffix.lstrip(".").lower(),
                hash_sha256=hash_sha256,
                taille_octets=stat.st_size,
                date_modification_fichier=mtime_fichier or datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
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
            # 3bis. Antivirus — refuse les fichiers infectés AVANT toute extraction/indexation
            clean, signature = await clamav_service.scan_file(str(file_path))
            if not clean:
                doc.statut = "error"
                doc.erreur = f"Menace détectée par l'antivirus : {signature}"
                await db.flush()
                log.warning("Fichier INFECTÉ — non indexé", doc_id=doc_id, fichier=file_path.name, signature=signature)
                return doc_id

            # 4. Extraction Tika
            metadata_list = await self.tika.extract_metadata(file_path)
            metadata = metadata_list[0] if metadata_list else {}

            texte = _sans_nul(metadata.pop("X-TIKA:content", "") or "")
            type_mime = (metadata.get("Content-Type") or "").split(";")[0].strip()

            doc.texte_extrait = texte
            doc.tika_metadata = metadata
            doc.type_mime = type_mime or None
            doc.statut = "extracted"
            doc.date_derniere_extraction = datetime.now(tz=timezone.utc)
            await db.flush()

            if texte.strip():
                # 5. Enrichissement IA
                enrich_ok = await self._enrich(doc, texte, db)

                # 6. Diff résumé si c'est une mise à jour de version
                if version_archivee is not None:
                    await self._generate_diff_resume(version_archivee, ancien_resume, texte, db)

                # 7. Embeddings
                await self.embeddings.embed_document(doc_id, texte, db)

                # Statut final : « enrichi » seulement si l'IA a produit des métadonnées,
                # sinon « extracted » (texte présent mais pas de méta → re-enrichissable, visible).
                doc.statut = "enriched" if enrich_ok else "extracted"
            else:
                doc.statut = "extracted"  # aucun texte → rien à enrichir

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
        *,
        mtime_fichier: datetime | None = None,
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
        doc.date_modification_fichier = mtime_fichier or datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
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
            from services import runtime_config
            diff = await self.ollama.generate(prompt, model=runtime_config.model_for("enrichissement"))
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

        # Le NOM DU FICHIER est souvent le signal le plus fiable pour classer (ex.
        # « TC-Carburant.pdf » → note de frais), surtout quand un scan rend peu de texte OCR.
        prompt = (
            f"{PROMPT_ENRICHISSEMENT}\n\n"
            f"Nom du fichier : {doc.nom or '(inconnu)'}\n\n"
            f"Document à analyser :\n{texte_tronque}"
        )

        # Modèles à essayer pour l'usage « enrichissement » : modèle configuré, puis fallback
        # sur les autres modèles texte INSTALLÉS (même famille). Évite l'échec si le modèle
        # configuré est absent/en erreur.
        from services import runtime_config
        candidats = await runtime_config.model_candidates("enrichissement")
        if not candidats:
            candidats = [runtime_config.model_for("enrichissement")]

        # Pour chaque modèle : format="json" → Ollama garantit un JSON valide ; 1 retry si le
        # parse échoue. Appel LLM en erreur (modèle absent, Ollama KO) → on bascule au suivant.
        data, modele = None, candidats[0]
        for cand in candidats:
            reponse_ok = False
            for tentative in (1, 2):
                try:
                    reponse = await self.ollama.generate(prompt, model=cand, format="json")
                    data = _extraire_json(reponse)
                    modele, reponse_ok = cand, True
                    break
                except json.JSONDecodeError as e:
                    log.warning("Réponse LLM non-JSON", doc_id=str(doc.id), modele=cand, tentative=tentative, erreur=str(e))
                except Exception as e:  # noqa: BLE001 — appel LLM KO → modèle suivant
                    log.warning("Appel LLM échoué — bascule modèle suivant", doc_id=str(doc.id), modele=cand, erreur=str(e))
                    break
            if reponse_ok:
                if cand != candidats[0]:
                    log.info("Enrichissement via modèle de secours", doc_id=str(doc.id), modele=cand)
                break
        if data is None:
            log.warning("Enrichissement abandonné — aucun modèle n'a produit de JSON valide",
                        doc_id=str(doc.id), candidats=candidats)
            return False

        try:
            # Vérifier si une metadonnee_ia existe déjà (pré-créée par folder_tag)
            existing_meta = (await db.execute(
                select(MetadonneeIA).where(MetadonneeIA.document_id == doc.id)
            )).scalar_one_or_none()

            tags_existants = existing_meta.tags or [] if existing_meta else []
            tags_ia = data.get("tags") or []
            # Tag d'extension (pdf, xlsx, docx…) — pour filtrer par type de fichier.
            ext_tag = (doc.extension or "").strip().lower()
            # Tags dossier + IA sans doublons, puis le tag extension (en tête, dédupliqué).
            tags_finaux = tags_existants + [t for t in tags_ia if t not in tags_existants]
            if ext_tag and ext_tag not in tags_finaux:
                tags_finaux = [ext_tag] + tags_finaux

            if existing_meta:
                existing_meta.categorie = data.get("categorie")
                existing_meta.sous_categorie = data.get("sous_categorie")
                existing_meta.tags = tags_finaux
                existing_meta.resume = data.get("resume")
                existing_meta.langue = data.get("langue")
                existing_meta.entites = data.get("entites")
                existing_meta.mots_cles = data.get("mots_cles") or []
                existing_meta.niveau_confidentialite = _niveau_conf(data.get("niveau_confidentialite"))
                existing_meta.modele_utilise = modele
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
                    niveau_confidentialite=_niveau_conf(data.get("niveau_confidentialite")),
                    modele_utilise=modele,
                )
                db.add(meta)
            await db.flush()
            log.info("Enrichissement IA OK", doc_id=str(doc.id), categorie=meta.categorie)
            return True
        except Exception as e:
            log.warning("Stockage métadonnées IA échoué", doc_id=str(doc.id), erreur=str(e))
            return False

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
            texte = _sans_nul(metadata.pop("X-TIKA:content", "") or "")
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
                    # `enriched` seulement si l'IA a produit des métadonnées (comme le pipeline
                    # principal) ; sinon `extracted` (re-enrichissable, non trompeur). Avant, on
                    # marquait `enriched` inconditionnellement → des docs `enriched` sans
                    # `metadonnees_ia`.
                    enrich_ok = await self._enrich(doc, texte, db)
                    await self.embeddings.embed_document(doc_id, texte, db)
                    doc.statut = "enriched" if enrich_ok else "extracted"
                else:
                    doc.statut = "extracted"
            except Exception as e:
                doc.statut = "error"
                doc.erreur = str(e)
                log.error("Erreur sous-document ZIP", nom=nom_fichier, erreur=str(e))

            await db.flush()
            doc_ids.append(doc_id)

        log.info("Traitement ZIP terminé", nb_documents=len(doc_ids))
        return doc_ids
