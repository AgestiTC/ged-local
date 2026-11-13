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
from services import clamav_service, classement_echecs, ia_echecs, prompts, transcription_service
from models.embedding import Embedding
from models.metadata import MetadonneeIA
from models.version import Version
from utils.hash_utils import compute_sha256
from utils.json_ia import lire_objet

log = get_logger(__name__)
settings = get_settings()

# Prompt de l'enrichissement : registre `services/prompts.py`, clé « enrichissement ».


# ─── OCR / vision de secours (Phase 2) ────────────────────────────────────────
# Quand Tika ne rend aucun texte (image, PDF scanné), on tente une transcription via un
# modèle vision Ollama (glm-ocr). Les PDF sont rastérisés page par page (pymupdf).
_IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff"}
_OCR_EXTS = _IMAGE_EXTS | {"pdf"}
_OCR_MODEL = "glm-ocr:latest"
_VISION_MAX_AVIS_VIDES = 2  # modèles interrogés au plus quand tout revient vide
_OCR_MAX_PAGES = 10  # plafond de pages OCR par PDF (coût vision élevé)
# Consigne UNIQUE de la vision : une seule demande par image ou par page (plan lots IA, étape 2).
# Avant : une passe « transcription » puis, si rien n'en sortait, une seconde passe « description »
# sur toutes les pages — un PDF de photos coûtait 20 appels à la carte partagée. Choix de la
# consigne :
#  - la transcription passe EN PREMIER, et la description n'est demandée que « s'il n'y a aucune
#    écriture » : une page de texte reste transcrite à l'identique (pas de commentaire parasite) ;
#  - on n'impose PLUS de répondre « (aucun texte) » : sur une photo, le modèle doit directement
#    décrire. S'il écrit quand même la sentinelle (seule, ou suivie d'une description), `_propre`
#    la retire ; seule une réponse sans rien d'autre est jugée vide ;
#  - la description est bornée (3 à 5 phrases, factuelle, rien d'inventé) pour rester exploitable
#    par l'enrichissement (catégorie / tags / résumé) sans noyer un vrai texte.
# Texte de la consigne : registre `services/prompts.py`, clé « vision ».
# Sentinelle que les anciennes consignes imposaient : le modèle la produit encore parfois.
_SENTINELLE_AUCUN_TEXTE = re.compile(r"[(\[]\s*aucun\s+texte\s*[)\]]", re.IGNORECASE)


# Niveaux de confidentialité autorisés par la contrainte DB (metadonnees_ia_..._check).
# Le LLM renvoie parfois une valeur hors-liste (« public », « privé »…) → on borne à « normal »
# pour ne pas faire échouer l'insertion.
_NIVEAUX_CONF = {"normal", "confidentiel", "restreint"}


def _enrichissement_exploitable(data: object) -> bool:
    """
    Le JSON renvoyé par le LLM contient-il au moins une **catégorie** ?

    `format="json"` garantit un JSON *valide*, pas un JSON *utile*. Quand le prompt dépasse le
    contexte d'Ollama (4096 tokens par défaut), Ollama tronque le DÉBUT — donc les consignes — et
    le modèle renvoie `{}` ou des clés sans rapport. Accepté tel quel, ce vide marquait le doc
    « enrichi » sans catégorie : 1 220 docs longs relancés en boucle sans jamais bouger (16/09/2026).
    """
    if not isinstance(data, dict):
        return False
    categorie = data.get("categorie")
    return isinstance(categorie, str) and bool(categorie.strip())


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


def _sans_nul_profond(valeur):
    """`_sans_nul` appliqué à toutes les chaînes d'une structure (dict, liste), clés comprises."""
    if isinstance(valeur, str):
        return _sans_nul(valeur)
    if isinstance(valeur, list):
        return [_sans_nul_profond(v) for v in valeur]
    if isinstance(valeur, dict):
        return {_sans_nul(k) if isinstance(k, str) else k: _sans_nul_profond(v) for k, v in valeur.items()}
    return valeur


# Clé du texte dans la réponse `/rmeta` : `X-TIKA:content` jusqu'à Tika 3, `tk:content` depuis
# Tika 4. L'image `apache/tika:latest-full` est passée en 4.0.0 sans prévenir : le texte arrivait,
# mais sous un nom que personne ne lisait → documents « extraits » à vide, donc jamais analysés
# par l'IA ni recherchables (457 en prod, constat du 09/10/2026).
CLES_CONTENU_TIKA = ("X-TIKA:content", "tk:content")


# Au-delà, le texte est TRONQUÉ. La colonne de recherche plein texte (`documents.tsv`, générée)
# est limitée à 1 Mo : un texte de 1,8 Mo faisait échouer l'INSERT (« string is too long for
# tsvector »), puis le traitement de l'erreur échouait à son tour sur la transaction annulée —
# le document n'était jamais indexé (`sgt-map.txt`, 09/10/2026). Et un tel texte, ce sont des
# milliers de morceaux à vectoriser pour un fichier de codes ou un journal.
TEXTE_MAX = 800_000

# Plan lots IA, étape 3. Quand une nouvelle version d'un fichier arrive, sa fiche IA obsolète est
# supprimée (`_update_version`) alors que l'ancien résumé sert encore à décrire les changements —
# or ce résumé est maintenant produit plus tard, par le job `ia_enrich` (un autre modèle, un autre
# moment). On le met donc à l'abri DANS LA LIGNE DE VERSION (colonne `diff_resume`, qui recevra de
# toute façon le résumé des changements), précédé de cette marque : ni extrait de contenu dans les
# paramètres du job, ni nouvelle colonne. `ia_enrich` le lit puis l'écrase ; si l'étape n'a jamais
# lieu, l'API des versions masque la marque (jamais montrée comme un « résumé des changements »).
MARQUE_ANCIEN_RESUME = "\u2063ancien-resume\u2063"


def _contenu_tika(metadata: dict) -> str:
    """RETIRE le texte des métadonnées Tika (quelle que soit la clé) et le renvoie nettoyé, borné."""
    texte = ""
    for cle in CLES_CONTENU_TIKA:
        valeur = metadata.pop(cle, None)
        if isinstance(valeur, str) and valeur.strip() and not texte:
            texte = valeur
    texte = _sans_nul(texte)
    # Les AUTRES métadonnées aussi : un PDF peut porter un NUL dans son titre ou son auteur, et
    # PostgreSQL refuse `\u0000` dans du JSONB → la fiche échouait (« UntranslatableCharacterError »,
    # puis « transaction annulée »), alors que Tika avait fait tout l'OCR (09/10/2026).
    for cle, valeur in list(metadata.items()):
        metadata[cle] = _sans_nul_profond(valeur)
    if len(texte) > TEXTE_MAX:
        metadata["matotheque:texte_tronque"] = {"longueur_origine": len(texte), "conserve": TEXTE_MAX}
        log.warning("Texte tronqué (trop long pour l'index de recherche)",
                    longueur_origine=len(texte), conserve=TEXTE_MAX)
        texte = texte[:TEXTE_MAX]
    return texte


def _original_utilisable(memes: list) -> "Document | None":
    """
    Parmi les fiches de même empreinte, celle dont une copie peut reprendre le contenu : une
    fiche aboutie (pas en erreur ni en attente — sinon la copie hériterait d'un échec et ne serait
    jamais retraitée), de préférence un original plutôt qu'une copie.
    """
    aboutis = [d for d in memes if d.statut in ("enriched", "extracted", "catalogued", "absent")]
    return next((d for d in aboutis if d.doublon_de is None), aboutis[0] if aboutis else None)


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

    async def extraire_contenu(
        self,
        doc: Document,
        file_path: Path,
        db: AsyncSession,
        *,
        recompute_hash: bool = True,
    ) -> bool:
        """
        Étape « contenu » (job `ia_contenu`) : lit le CONTENU d'un fichier et met à jour un document
        **déjà en base** (aucune nouvelle ligne → **zéro doublon**) — antivirus, hash, Tika, puis
        vision si Tika n'a rien rendu (image ou PDF scanné). Sert aussi à « Forcer l'analyse » d'un
        média catalogué ou d'un document extrait au texte vide. `file_path` = fichier local ou
        **temporaire** (fetch SMB, supprimé par l'appelant).

        N'enrichit pas et ne vectorise pas : ce sont les étapes suivantes, chacune avec SON modèle.
        Ne commite pas : l'appelant écrit le résultat ET met la suite en file dans la même
        transaction. Renvoie True s'il y a du texte ; fichier infecté → statut `error` + `erreur`
        posés, renvoie False.
        """
        log.info("Lecture du contenu (doc existant)", doc_id=str(doc.id), fichier=file_path.name)

        # Antivirus avant toute extraction.
        clean, signature, etat_av = await clamav_service.scan_file(str(file_path))
        doc.antivirus = etat_av
        if not clean:
            doc.statut = "error"
            doc.erreur = f"Menace détectée par l'antivirus : {signature}"
            await db.flush()
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
        texte = _contenu_tika(metadata)
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

        log.info("Lecture du contenu terminée", doc_id=str(doc.id), statut=doc.statut, texte_len=len(texte))
        return bool(texte.strip())

    async def reprendre_contenu_stocke(self, doc: Document, db: AsyncSession) -> bool | None:
        """
        Rattrape un document resté SANS texte alors que Tika l'avait bien extrait : le contenu
        dormait dans `tika_metadata` sous une clé que le pipeline ne lisait pas (Tika 4). On le
        remet à sa place — sans retélécharger le fichier, sans rappeler Tika, et SANS IA :
        l'enrichissement et les embeddings suivent comme jobs distincts (`ia_enrich`, `ia_embed`).
        Renvoie True si le texte a été repris, None s'il n'y a rien à reprendre. Ne commite pas.
        """
        metadata = dict(doc.tika_metadata or {})
        texte = _contenu_tika(metadata)
        if (doc.texte_extrait or "").strip() or not texte.strip():
            return None

        doc.texte_extrait = texte
        doc.tika_metadata = metadata
        await db.flush()
        log.info("Texte repris des métadonnées Tika", doc_id=str(doc.id), texte_len=len(texte))
        return True

    async def _ocr_fallback(self, file_path: Path, ext: str) -> str:
        """Usage « vision » déclaré à la passerelle pour tous les appels de l'OCR/description."""
        from services.ollama_service import usage_ia
        with usage_ia("vision"):
            return await self._ocr_fallback_sans_usage(file_path, ext)

    async def _ocr_fallback_sans_usage(self, file_path: Path, ext: str) -> str:
        """
        Texte de secours quand Tika ne rend rien : envoie l'image (ou chaque page rastérisée d'un
        PDF scanné) au modèle vision Ollama, en UNE demande par image/page — transcription du
        texte visible, sinon description (cf. clé « vision » de `services/prompts.py`). Robuste aux
        échecs (retourne "" si rien d'exploitable). Pages jointes par deux sauts de ligne.

        Un modèle ABSENT (404) ou une erreur définitive fait basculer sur le suivant (document entier
        rejoué) ; un incident PASSAGER (délai dépassé, 504…) lève `EchecPassager` sans appeler d'autre
        modèle (plan lots IA, étape 5). Un modèle qui
        répond VIDE sur toutes les pages fait essayer UN autre modèle, pas plus : sans cela, un
        modèle mal choisi (non-vision) laisserait tous les scans sans texte, en silence ; mais
        rejouer un document réellement vide sur chaque modèle installé chargerait autant de modèles
        sur la carte partagée pour un résultat qui ne viendra pas.
        """
        import base64

        from services import runtime_config

        ext = ext.lower()
        # Modèles vision à essayer : configuré pour l'usage « vision », puis fallback sur les
        # autres modèles vision INSTALLÉS (même famille). On garde le 1er qui répond sans erreur.
        candidats = await runtime_config.model_candidates("vision")
        if not candidats:
            candidats = [runtime_config.usage_model("vision") or runtime_config.effective("vision_model") or _OCR_MODEL]

        def _propre(t: str) -> str:
            t = (t or "").strip()
            if not t:
                return ""
            # Retire la sentinelle « (aucun texte) » (le modèle la répète parfois, seule ou avant
            # une description). S'il ne reste rien de significatif → pas de contenu exploitable.
            # Seule la forme entre parenthèses est retirée du texte rendu : une phrase légitime
            # contenant « aucun texte » reste intacte, et la mise en page de la transcription aussi.
            net = _SENTINELLE_AUCUN_TEXTE.sub("", t).strip()
            lache = re.sub(r"[(\[]?\s*aucun\s+texte\s*[)\]]?", "", t, flags=re.IGNORECASE)
            if len(re.sub(r"\s+", " ", lache).strip()) < 3:
                return ""
            return net

        try:
            if ext in _IMAGE_EXTS:
                images = [base64.b64encode(await asyncio.to_thread(file_path.read_bytes)).decode()]
            elif ext == "pdf":
                pages = await asyncio.to_thread(_rasteriser_pdf, str(file_path), _OCR_MAX_PAGES)
                images = [base64.b64encode(png).decode() for png in pages][:_OCR_MAX_PAGES]
            else:
                return ""

            vides = 0
            for model in candidats:
                try:
                    log.info("Vision (une passe)", fichier=file_path.name, nb_pages=len(images), modele=model)
                    morceaux: list[str] = []
                    for b64 in images:
                        t = _propre(await self.ollama.generate(prompts.texte("vision"), model=model, images=[b64],
                                                               rejouer_apres_attente=False))
                        if t:
                            morceaux.append(t)
                    if morceaux:
                        return "\n\n".join(morceaux).strip()
                    # Tout est vide : un second avis, un seul (cf. docstring).
                    vides += 1
                    if vides >= _VISION_MAX_AVIS_VIDES:
                        return ""
                    log.info("Vision — réponse vide partout, essai d'un autre modèle",
                             fichier=file_path.name, modele=model)
                except Exception as e:  # noqa: BLE001 — conduite selon la nature de l'échec
                    nature = classement_echecs.classer_echec(e)
                    if nature == classement_echecs.PASSAGER:
                        # Délai dépassé, 504, connexion… : AUCUN autre modèle (un de plus à charger sur une
                        # carte saturée). Le job `ia_contenu` est reporté par le worker.
                        raise classement_echecs.EchecPassager(
                            classement_echecs.decrire_echec(e), "la lecture d'images") from e
                    # Modèle absent OU erreur définitive : modèle suivant, comme avant l'étape 5.
                    log.warning("Vision — bascule modèle suivant", fichier=file_path.name, modele=model,
                                nature=nature, erreur=str(e))
        except classement_echecs.EchecPassager:
            raise                                            # à reporter, pas « rien d'exploitable »
        except Exception as e:  # noqa: BLE001 — la vision est un « best effort »
            log.warning("OCR fallback échoué", fichier=file_path.name, erreur=str(e))
        return ""

    async def _enregistrer_copie(self, original: Document, chemin: str, nom: str, file_path: Path,
                                 mtime_fichier: datetime | None, source: str,
                                 folder_tag: str | None, db: AsyncSession) -> Document:
        """
        Crée la fiche d'une COPIE : même contenu qu'`original`, autre emplacement. Elle reprend son
        texte et ses métadonnées IA, mais PAS ses embeddings : la recherche continue de renvoyer
        l'original une seule fois, et rien n'est recalculé.
        """
        stat = file_path.stat()
        meta = original.metadonnees_ia
        if original.statut == "catalogued":
            statut = "catalogued"
        else:
            statut = "enriched" if (meta and meta.categorie) else ("extracted" if original.texte_extrait else "catalogued")
        copie = Document(
            chemin=chemin, nom=nom, extension=Path(nom).suffix.lstrip(".").lower(),
            type_mime=original.type_mime, hash_sha256=original.hash_sha256, taille_octets=stat.st_size,
            date_modification_fichier=mtime_fichier or datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            date_derniere_extraction=original.date_derniere_extraction,
            texte_extrait=original.texte_extrait, tika_metadata=original.tika_metadata,
            statut=statut, antivirus=original.antivirus, source=source,
            doublon_de=original.doublon_de or original.id,
        )
        db.add(copie)
        await db.flush()
        if meta is not None:
            tags = list(meta.tags or [])
            if folder_tag and folder_tag not in tags:
                tags.append(folder_tag)
            champs = dict(
                document_id=copie.id, categorie=meta.categorie, sous_categorie=meta.sous_categorie,
                tags=tags, resume=meta.resume, langue=meta.langue, mots_cles=meta.mots_cles,
                niveau_confidentialite=meta.niveau_confidentialite or "normal",
                modele_utilise=meta.modele_utilise,
            )
            # ⚠️ Ne PAS passer `entites=None` : SQLAlchemy l'écrirait comme le JSON `null`, et le
            # déclencheur de recherche (`jsonb_each`) refuse un non-objet → l'INSERT échouait
            # (vu en vérification sur PostgreSQL ; invisible sous SQLite). Absent = NULL SQL.
            if meta.entites is not None:
                champs["entites"] = meta.entites
            db.add(MetadonneeIA(**champs))
            await db.flush()
        log.info("Copie enregistrée (contenu déjà indexé)", doc_id=str(copie.id), original=str(copie.doublon_de),
                 fichier=nom, hash=original.hash_sha256[:8])
        return copie

    async def process_file(
        self,
        file_path: Path,
        source: str = "watch",
        db: AsyncSession = None,
        folder_tag: str | None = None,
        chemin_logique: str | None = None,
        mtime_fichier: datetime | None = None,
        differer_ia: bool = True,
    ) -> str:
        """
        Traite un fichier : extraction (Tika, antivirus, transcription, versions, copies), puis
        enrichissement et embeddings — en deux temps (plan lots IA, étape 3, `differer_ia`).

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
            differer_ia: vrai (défaut) → AUCUN appel Ollama ici : le document reste `extracted` et
                un job `ia_enrich` (suivi de `ia_embed`) est mis en file dans la session de
                l'appelant, donc visible au commit de l'appelant. Chaque étape ne charge qu'un
                modèle ; la file les groupe. Faux → IA immédiate, comme avant (finalisation d'un
                scan : l'utilisateur attend sa fiche).

        Returns:
            ID (str) du document créé ou existant (si doublon)
        """
        log.info("Traitement fichier", fichier=file_path.name, source=source)

        # 1. Hash SHA256 — doublon exact (même contenu, peu importe le chemin).
        #    Lecture/hash déportés en thread : sinon la lecture synchrone d'un gros
        #    fichier bloquerait l'event loop (API gelée pendant l'indexation).
        hash_sha256 = await asyncio.to_thread(compute_sha256, file_path)
        chemin_absolu = chemin_logique or str(file_path.resolve())
        nom_fichier = Path(chemin_logique).name if chemin_logique else file_path.name

        # Un même contenu peut exister en PLUSIEURS fiches (copies, page Doublons) : on les lit
        # toutes. `scalar_one_or_none` plantait dès la 2ᵉ (53 échecs par synchro, 09/10/2026).
        memes = (await db.execute(
            select(Document).options(selectinload(Document.metadonnees_ia))
            .where(Document.hash_sha256 == hash_sha256).order_by(Document.date_import)
        )).scalars().all()
        if memes:
            ici = next((d for d in memes if d.chemin == chemin_absolu), None)
            if ici is not None:
                # Même emplacement, même contenu : rien à refaire, on rafraîchit seulement la date.
                if mtime_fichier and ici.date_modification_fichier != mtime_fichier:
                    ici.date_modification_fichier = mtime_fichier
                    await db.flush()
                log.info("Fichier inchangé (hash identique) — ré-extraction évitée",
                         fichier=file_path.name, hash=hash_sha256[:8])
                return str(ici.id)
            original = _original_utilisable(memes)
            if source == "watch" and original is not None:
                # Source surveillée : on ENREGISTRE l'emplacement de la copie. Avant, on la sautait
                # sans rien noter → redécouverte, retéléchargée et recomptée « nouvelle » à chaque
                # synchro (6 692 fichiers toutes les heures). Ni Tika, ni IA, ni embeddings.
                copie = await self._enregistrer_copie(
                    original, chemin_absolu, nom_fichier, file_path, mtime_fichier, source, folder_tag, db)
                return str(copie.id)
            if original is not None or source != "watch":
                # Dépôt manuel (upload, glisser-déposer) : dédoublonnage inchangé, pas de 2ᵉ fiche.
                log.info("Document déjà indexé (doublon)", hash=hash_sha256[:8], doc_id=str(memes[0].id))
                return str((original or memes[0]).id)
            # Sinon : seules des fiches en erreur / en attente portent ce contenu → on traite ce
            # fichier normalement, il n'y a rien d'abouti à reprendre.

        # 2. Détection version — même chemin, contenu différent
        result = await db.execute(
            select(Document)
            .options(selectinload(Document.metadonnees_ia))
            .where(Document.chemin == chemin_absolu)
        )
        existing_same_path = result.scalar_one_or_none()

        # 🛡️ Garde anti-effacement (audit 03/09/2026) : si un document au MÊME chemin existe déjà
        # avec le MÊME hash, le contenu est IDENTIQUE — le fichier a seulement changé de DATE
        # (sauvegarde/restore/touch/heure d'été côté NAS). NE PAS le re-extraire : `_update_version`
        # supprimerait `metadonnees_ia` et remettrait le statut à `extracted`, effaçant catégorie,
        # tags et résumé pour rien (c'est ce qui a fait bondir « Relancer l'IA » de 150 à 1226).
        # On se contente de rafraîchir la date stockée pour que la synchro ne le re-détecte plus.
        if existing_same_path and existing_same_path.hash_sha256 == hash_sha256:
            maj_date = bool(mtime_fichier) and existing_same_path.date_modification_fichier != mtime_fichier
            if maj_date:
                existing_same_path.date_modification_fichier = mtime_fichier
                await db.flush()
            log.info("Fichier inchangé (hash identique) — ré-extraction évitée",
                     fichier=file_path.name, hash=hash_sha256[:8], date_maj=maj_date)
            return str(existing_same_path.id)

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
            clean, signature, etat_av = await clamav_service.scan_file(str(file_path))
            doc.antivirus = etat_av
            if not clean:
                doc.statut = "error"
                doc.erreur = f"Menace détectée par l'antivirus : {signature}"
                await db.flush()
                log.warning("Fichier INFECTÉ — non indexé", doc_id=doc_id, fichier=file_path.name, signature=signature)
                return doc_id

            # 4. Extraction Tika
            metadata_list = await self.tika.extract_metadata(file_path)
            metadata = metadata_list[0] if metadata_list else {}

            texte = _contenu_tika(metadata)
            type_mime = (metadata.get("Content-Type") or "").split(";")[0].strip()

            doc.texte_extrait = texte
            doc.tika_metadata = metadata
            doc.type_mime = type_mime or None
            doc.statut = "extracted"
            doc.date_derniere_extraction = datetime.now(tz=timezone.utc)
            await db.flush()

            # Transcription audio : Tika ne rend pas la parole → on transcrit (parole → texte)
            # via le serveur configuré, pour rendre l'audio recherchable comme un document texte.
            if not texte.strip() and (doc.extension or "").lower() in transcription_service.AUDIO_EXTENSIONS \
                    and transcription_service.is_enabled():
                try:
                    texte = _sans_nul(await transcription_service.transcribe(file_path))
                except transcription_service.TranscriptionError as exc:
                    log.warning("Transcription audio échouée", doc_id=doc_id, fichier=file_path.name, erreur=str(exc))
                if texte.strip():
                    doc.texte_extrait = texte
                    await db.flush()
                    log.info("Audio transcrit", doc_id=doc_id, fichier=file_path.name, nb_chars=len(texte))

            if texte.strip() and differer_ia:
                # 5-7. L'IA est repoussée dans des jobs d'étape (un modèle chacun). La fiche IA
                # obsolète d'une version précédente vient d'être retirée : on garde son résumé
                # dans la ligne de version (cf. MARQUE_ANCIEN_RESUME) pour `ia_enrich`.
                doc.statut = "extracted"
                params = {"document_id": doc_id, "embed": True, "cible": doc.nom}
                if version_archivee is not None:
                    if ancien_resume:
                        version_archivee.diff_resume = MARQUE_ANCIEN_RESUME + ancien_resume
                    await db.flush()
                    params["version_id"] = str(version_archivee.id)
                await self._mettre_ia_en_file(db, doc_id, params)
            elif texte.strip():
                # 5-7. IA immédiate (finalisation d'un scan) : enrichissement, diff résumé, embeddings.
                # Un incident passager ne met pas le document en erreur : voir `_ia_immediate`.
                await self._ia_immediate(doc, texte, db, doc_id, version_archivee, ancien_resume)
            else:
                doc.statut = "extracted"  # aucun texte → rien à enrichir

        except Exception as e:
            doc.statut = "error"
            doc.erreur = str(e)
            log.error("Erreur pipeline extraction", doc_id=doc_id, erreur=str(e), exc_info=True)

        await db.flush()
        log.info("Traitement terminé", doc_id=doc_id, statut=doc.statut)
        return doc_id

    async def _ia_immediate(self, doc: Document, texte: str, db: AsyncSession, doc_id: str,
                            version_archivee, ancien_resume, cible: str | None = None) -> None:
        """
        IA immédiate (`differer_ia=False`, finalisation d'un scan) : enrichissement, résumé des changements,
        embeddings. Sur un incident PASSAGER (`EchecPassager` : carte saturée, passerelle qui coupe), le
        document n'est PAS mis en `error` : il reste `extracted` (ou `enriched` si la fiche est déjà
        écrite) et la suite part en file comme dans le chemin différé (`ia_enrich`, ou `ia_embed` si seul
        le calcul des vecteurs a échoué — l'enrichissement n'est pas refait). Le worker la reportera
        lui-même si l'incident dure. Toute autre erreur reste une erreur du document.
        """
        enrich_ok = False
        try:
            enrich_ok = await self._enrich(doc, texte, db, lever_passager=True)
            if version_archivee is not None:
                await self._generate_diff_resume(version_archivee, ancien_resume, texte, db)
            await self.embeddings.embed_document(doc_id, texte, db)
            # « enrichi » seulement si l'IA a produit des métadonnées, sinon « extracted » (re-enrichissable).
            doc.statut = "enriched" if enrich_ok else "extracted"
        except classement_echecs.EchecPassager as e:
            log.warning("IA immédiate interrompue par un incident passager — suite mise en file",
                        doc_id=doc_id, motif=e.resume, enrichi=enrich_ok)
            doc.statut = "enriched" if enrich_ok else "extracted"
            params: dict = {"document_id": doc_id, "cible": cible or doc.nom}
            if enrich_ok:
                await self._mettre_ia_en_file(db, doc_id, params, type_job="ia_embed")
                return
            params["embed"] = True
            if version_archivee is not None:
                if ancien_resume:
                    version_archivee.diff_resume = MARQUE_ANCIEN_RESUME + ancien_resume
                await db.flush()
                params["version_id"] = str(version_archivee.id)
            await self._mettre_ia_en_file(db, doc_id, params)

    @staticmethod
    async def _mettre_ia_en_file(db: AsyncSession, doc_id: str, params: dict, type_job: str = "ia_enrich") -> None:
        """Met `ia_enrich` (ou `type_job`) en file dans la session de l'appelant (rejouable : jamais deux jobs en attente).

        Dans un SAVEPOINT : une erreur de mise en file ne doit pas invalider la transaction de
        l'appelant (sur PostgreSQL, le flush suivant échouerait et tout le lot avec). Le document
        reste alors `extracted` sans job — « Relancer l'IA » (lot de ré-enrichissement) le rattrape."""
        from services import job_handlers   # import local : job_handlers dépend du worker
        try:
            async with db.begin_nested():
                await job_handlers.enfiler_suivant(db, type_job, doc_id, params)
        except Exception as e:  # noqa: BLE001 — la mise en file est secondaire, jamais fatale au document
            log.error("Mise en file de l'enrichissement impossible", doc_id=doc_id, erreur=str(e))

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

    async def _enrich(self, doc: Document, texte: str, db: AsyncSession, *, lever_passager: bool = False) -> bool:
        """Usage « enrichissement » déclaré à la passerelle pour tous les appels du bloc."""
        from services.ollama_service import usage_ia
        with usage_ia("enrichissement"):
            return await self._enrich_sans_usage(doc, texte, db, lever_passager=lever_passager)

    async def _enrich_sans_usage(self, doc: Document, texte: str, db: AsyncSession, *,
                                 lever_passager: bool = False) -> bool:
        """
        Enrichit un document via Ollama : catégorie, tags, résumé, entités.
        Stocke le résultat dans metadonnees_ia.

        Un autre modèle est essayé si le modèle demandé est ABSENT (404 « model … not found »), en erreur
        définitive (HTTP 400…) ou si sa réponse est inexploitable (sans catégorie : ancien contrat). Un incident PASSAGER
        (délai dépassé, 504, connexion…) n'en déclenche AUCUN : un modèle de plus à charger sur une
        carte saturée aggraverait l'incident (plan lots IA, étape 5). `lever_passager=True` (job
        `ia_enrich`) lève alors `EchecPassager`, que le worker reporte ; sinon (process_file,
        process_zip) l'enrichissement est abandonné et rend False, comme avant.
        """
        # Tronquer à ~16k chars (≈ 4-5k tokens) : tient largement dans `ollama_num_ctx` (16384),
        # consignes comprises — au-delà, Ollama couperait le DÉBUT du prompt.
        texte_tronque = texte[:16000]

        # Le NOM DU FICHIER est souvent le signal le plus fiable pour classer (ex.
        # « TC-Carburant.pdf » → note de frais), surtout quand un scan rend peu de texte OCR.
        prompt = (
            f"{prompts.texte('enrichissement')}\n\n"
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
        # parse échoue OU si le JSON est vide (sans catégorie). Appel LLM en erreur (modèle
        # absent, Ollama KO) → on bascule au suivant.
        data, modele, abandon = None, candidats[0], False
        for cand in candidats:
            reponse_ok = False
            for tentative in (1, 2):
                try:
                    reponse = await self.ollama.generate(prompt, model=cand, format="json",
                                                         rejouer_apres_attente=False)
                    candidat_data = lire_objet(reponse)
                    if candidat_data is None:
                        raise json.JSONDecodeError("Aucun objet JSON dans la réponse", reponse, 0)
                    if not _enrichissement_exploitable(candidat_data):
                        log.warning("Réponse LLM sans catégorie — ignorée", doc_id=str(doc.id), modele=cand,
                                    tentative=tentative, nb_chars_prompt=len(prompt), reponse=reponse[:200])
                        await ia_echecs.noter(cand, "enrichissement", nature="inexploitable",
                                              message=f"réponse sans catégorie : {reponse[:200]}")
                        continue
                    data, modele, reponse_ok = candidat_data, cand, True
                    break
                except json.JSONDecodeError as e:
                    log.warning("Réponse LLM non-JSON", doc_id=str(doc.id), modele=cand, tentative=tentative, erreur=str(e))
                    await ia_echecs.noter(cand, "enrichissement", nature="non_json", message=str(e))
                except Exception as e:  # noqa: BLE001 — conduite selon la nature de l'échec
                    nature = classement_echecs.classer_echec(e)
                    if nature == classement_echecs.PASSAGER:
                        # Seul l'incident PASSAGER interdit un autre modèle : en charger un de plus sur une
                        # carte saturée aggraverait l'incident.
                        log.warning("Enrichissement interrompu par un incident passager — aucun autre modèle",
                                    doc_id=str(doc.id), modele=cand, erreur=classement_echecs.decrire_echec(e))
                        if lever_passager:
                            raise classement_echecs.EchecPassager(
                                classement_echecs.decrire_echec(e), "l'enrichissement") from e
                        abandon = True
                        break
                    # Modèle absent OU erreur définitive (HTTP 400…) : modèle suivant, comme avant l'étape 5.
                    log.warning("Appel LLM échoué — bascule modèle suivant", doc_id=str(doc.id), modele=cand,
                                nature=nature, erreur=str(e))
                    break
            if abandon:
                break
            if reponse_ok:
                if cand != candidats[0]:
                    log.info("Enrichissement via modèle de secours", doc_id=str(doc.id), modele=cand)
                break
        if data is None:
            log.warning("Enrichissement abandonné — aucun modèle n'a produit de JSON exploitable",
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

    async def process_zip(self, zip_path: Path, source: str = "upload", db: AsyncSession = None,
                          folder_tag: str | None = None, differer_ia: bool = True) -> list[str]:
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
            texte = _contenu_tika(metadata)
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

            result = await db.execute(select(Document.id).where(Document.hash_sha256 == hash_contenu).limit(1))
            if result.first():
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
                if texte.strip() and differer_ia:
                    doc.statut = "extracted"   # l'IA suit, par étapes (jobs `ia_enrich` puis `ia_embed`)
                    await self._mettre_ia_en_file(
                        db, doc_id, {"document_id": doc_id, "embed": True, "cible": nom_fichier})
                elif texte.strip():
                    # `enriched` seulement si l'IA a produit des métadonnées (comme le pipeline
                    # principal) ; sinon `extracted` (re-enrichissable, non trompeur). Avant, on
                    # marquait `enriched` inconditionnellement → des docs `enriched` sans
                    # `metadonnees_ia`.
                    await self._ia_immediate(doc, texte, db, doc_id, None, None, cible=nom_fichier)
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
