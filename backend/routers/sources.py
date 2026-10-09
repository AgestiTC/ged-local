"""
Router Sources — /api/sources
=============================
Gère les sources de fichiers (local monté ou SMB distant) et leur exploration.

  GET    /sources               → liste (sans secret)
  POST   /sources               → créer (secret chiffré)
  PUT    /sources/{id}          → modifier
  DELETE /sources/{id}          → supprimer
  POST   /sources/test          → tester une connexion (avant sauvegarde)
  GET    /sources/{id}/shares   → lister les partages (SMB)
  GET    /sources/{id}/browse   → parcourir (local: FS, SMB: réseau)
  POST   /sources/perimetre     → synchroniser / indexer UN dossier (clic droit dans l'arbre)
"""

import asyncio
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, get_db
from logger import get_logger
from models.document import Document
from models.source import Source
from services import crypto, smb_service

log = get_logger(__name__)
router = APIRouter()

# Progression d'une indexation EN COURS, par JOB — canal INTERNE au process worker : la tâche
# `_index_*` y compte ses fichiers, le handler (même process) le recopie en base toutes les
# secondes. ⚠️ Ne JAMAIS le lire depuis une route : l'API tourne dans d'autres process, qui
# ne voient pas ce dict (la barre restait figée sur « énumération 0/0 » — audit 28/09/2026,
# H3). La route lit la table `jobs`. Clé par job et non par source : deux jobs d'une même
# source cumulaient leurs compteurs (« 40047/34290 »).
_progression: dict[str, dict] = {}


def _prog_demarrer(cle: str) -> None:
    _progression[cle] = {"en_cours": True, "phase": "enumeration", "total": 0, "fait": 0}


def _prog_total(cle: str, total: int) -> None:
    if cle in _progression:
        _progression[cle].update({"phase": "indexation", "total": total})


def _prog_tick(cle: str) -> None:
    if cle in _progression:
        _progression[cle]["fait"] += 1


def _prog_fin(cle: str) -> None:
    if cle in _progression:
        _progression[cle].update({"en_cours": False, "phase": "termine"})


class SourceIn(BaseModel):
    libelle: str
    type: str = Field(description="local | smb")
    chemin_base: str | None = None
    hote: str | None = None
    domaine: str | None = None
    identifiant: str | None = None
    secret: str | None = Field(default=None, description="mot de passe/token en clair (sera chiffré)")


class IndexRequest(BaseModel):
    chemin: str = "/"                       # sous-dossier à indexer
    partage: str | None = None              # requis pour SMB
    recursive: bool = True


def _dt_utc(epoch: float | None):
    """Epoch SMB (flottant) → datetime UTC, ou None si le serveur ne la fournit pas."""
    from datetime import datetime, timezone
    if not epoch:
        return None
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _extraction_service():
    """Construit le pipeline d'extraction (mêmes services que le scan de dossiers)."""
    from services.embedding_service import EmbeddingService
    from services.extraction import ExtractionService
    from services.ollama_service import OllamaService
    from services.tika_service import TikaService
    ollama = OllamaService()
    return ExtractionService(TikaService(), ollama, EmbeddingService(ollama))


async def _index_local(chemin_base, chemin, recursive, cle_progression=None):
    """`cle_progression` : clé du job dans `_progression` (canal interne au worker)."""
    from services.folder_watcher import _est_cache, media_a_cataloguer
    from services import runtime_config
    exts = runtime_config.effective_extensions()
    service = _extraction_service()
    from utils.file_utils import sous_chemin
    cible = sous_chemin(chemin_base, chemin)   # refuse un `..` qui sortirait de la source

    # Parcours du système de fichiers (stat sur chaque entrée) déporté en thread :
    # sur un gros arbre, le rglob synchrone bloquerait l'event loop au démarrage.
    def _lister_fichiers() -> list[Path]:
        it = cible.rglob("*") if recursive else cible.iterdir()
        return [f for f in it if f.is_file() and not _est_cache(f)
                and f.suffix.lstrip(".").lower() in exts]

    fichiers = await asyncio.to_thread(_lister_fichiers)
    # `media_a_cataloguer` (≠ `in MEDIA_EXTENSIONS`) route l'AUDIO vers le pipeline complet
    # (→ transcription) dès qu'un serveur de transcription est configuré ; sinon catalogue léger.
    nb_media = sum(1 for f in fichiers if media_a_cataloguer(f.suffix))
    log.info("Indexation source locale", chemin=str(cible), nb=len(fichiers), nb_media_catalogue=nb_media)
    if cle_progression:
        _prog_total(cle_progression, len(fichiers))
    try:
        for f in fichiers:
            async with AsyncSessionLocal() as db:
                try:
                    if media_a_cataloguer(f.suffix):
                        # Média (hors audio transcriptible) : catalogue léger (pas de Tika/IA/embeddings)
                        await service.catalogue_media(chemin=str(f), nom=f.name, taille=f.stat().st_size, source="watch", db=db)
                    else:
                        await service.process_file(f, source="watch", db=db)
                    await db.commit()
                except Exception as e:
                    log.error("Erreur indexation", fichier=str(f), erreur=str(e))
            if cle_progression:
                _prog_tick(cle_progression)
            await asyncio.sleep(0)  # rendre la main à l'event loop entre deux fichiers
    finally:
        if cle_progression:
            _prog_fin(cle_progression)


async def _index_smb(hote, partage, chemin, identifiant, secret, domaine, cle_progression=None,
                     cancel_event=None):
    from services import runtime_config
    from services.folder_watcher import media_a_cataloguer
    service = _extraction_service()
    # `cancel_event` : rend l'ÉNUMÉRATION (walk SMB, thread non interruptible) annulable — sans
    # lui, « Annuler » ne prenait effet qu'APRÈS le walk (parfois plusieurs minutes sur 65k fichiers).
    try:
        from utils.file_utils import chemin_partage
        fichiers = await smb_service.walk_files(hote, partage, chemin_partage(chemin), identifiant,
                                                secret, domaine,
                                                runtime_config.effective_extensions(), cancel_event=cancel_event)
    except smb_service.WalkAnnule:
        log.info("Énumération SMB annulée", hote=hote, partage=partage)
        if cle_progression:
            _prog_fin(cle_progression)
        return
    try:
        taille_max = int(float(runtime_config.effective("index_taille_max_mo") or 2048)) * 1024 * 1024
    except (TypeError, ValueError):
        taille_max = 2048 * 1024 * 1024
    nb_media = sum(1 for e in fichiers if media_a_cataloguer(Path(e["rel"]).suffix))
    log.info("Indexation source SMB", hote=hote, partage=partage, nb=len(fichiers), nb_media_catalogue=nb_media)
    if cle_progression:
        _prog_total(cle_progression, len(fichiers))
    try:
        for entry in fichiers:
            rel, taille = entry["rel"], entry["taille"]
            chemin_doc = f"smb://{hote}/{partage}{rel}"
            ext = Path(rel).suffix.lstrip(".").lower()
            try:
                if media_a_cataloguer(ext) or taille > taille_max:
                    # Médias (hors audio transcriptible) : catalogue léger (nom/taille) SANS fetch ni
                    # Tika/IA/embeddings. L'audio, lui, part dans le `else` → fetch + transcription.
                    # Fichiers TROP VOLUMINEUX : idem — on les référence sans les rapatrier. Un ZIP de
                    # 8,9 Go téléchargé en /tmp avait saturé le disque du LXC et bloqué PostgreSQL
                    # (incident 21/07). Seuil = `index_taille_max_mo`.
                    if taille > taille_max and not media_a_cataloguer(ext):
                        log.warning("Fichier trop volumineux — référencé sans extraction",
                                    fichier=rel, octets=taille, max_octets=taille_max)
                    async with AsyncSessionLocal() as db:
                        await service.catalogue_media(chemin=chemin_doc, nom=Path(rel).name, taille=taille,
                                                      source="watch", date_modification=_dt_utc(entry.get("mtime")), db=db)
                        await db.commit()
                else:
                    # Documents : pipeline complet (fetch temp → extraction → IA → embeddings).
                    # `chemin_logique` fait enregistrer le chemin smb:// dès l'insertion : la
                    # détection de version compare alors au BON chemin (avant, on corrigeait le
                    # chemin après coup et un fichier modifié créait une ligne en double).
                    tmp = None
                    try:
                        tmp = await smb_service.fetch_to_temp(hote, partage, rel, identifiant, secret, domaine)
                        async with AsyncSessionLocal() as db:
                            await service.process_file(
                                Path(tmp), source="watch", db=db,
                                chemin_logique=chemin_doc,
                                mtime_fichier=_dt_utc(entry.get("mtime")),
                            )
                            await db.commit()
                    finally:
                        if tmp and os.path.exists(tmp):
                            os.unlink(tmp)
            except Exception as e:
                log.error("Erreur indexation SMB", fichier=rel, erreur=str(e))
            finally:
                if cle_progression:
                    _prog_tick(cle_progression)
                await asyncio.sleep(0)  # rendre la main à l'event loop entre deux fichiers
    finally:
        if cle_progression:
            _prog_fin(cle_progression)


def _to_dict(s: Source) -> dict:
    """Sérialise une source SANS jamais exposer le secret."""
    return {
        "id": str(s.id),
        "libelle": s.libelle,
        "type": s.type,
        "chemin_base": s.chemin_base,
        "hote": s.hote,
        "domaine": s.domaine,
        "identifiant": s.identifiant,
        "secret_defini": bool(s.secret_chiffre),  # ne révèle que la présence
        "actif": s.actif,
        "sync_intervalle_minutes": s.sync_intervalle_minutes,
        "dernier_sync": s.dernier_sync.isoformat() if s.dernier_sync else None,
        "dernier_sync_recap": s.dernier_sync_recap,
        "sync_dossiers": s.sync_dossiers or {},
    }


class SyncConfigIn(BaseModel):
    intervalle_minutes: int | None = Field(
        default=None, ge=0, le=10080,
        description="0 ou null = synchro automatique désactivée ; max 7 jours",
    )


@router.patch("/sources/{source_id}/sync-config", tags=["Sources"])
async def set_sync_config(source_id: str, body: SyncConfigIn, db: AsyncSession = Depends(get_db)) -> dict:
    """Règle la synchro automatique d'une source (intervalle en minutes ; 0 = désactivée)."""
    src = await _get(db, source_id)
    src.sync_intervalle_minutes = body.intervalle_minutes or None
    await db.flush()
    log.info("Synchro auto configurée", source=src.libelle, intervalle_min=src.sync_intervalle_minutes)
    return _to_dict(src)


class SyncDossierIn(BaseModel):
    cle: str = Field(min_length=1, max_length=1024, description="« partage/dossier » (cf. GET sync-dossiers)")
    minutes: int | None = Field(
        default=None, ge=0, le=10080,
        description="0 = jamais ; null = suivre l'intervalle de la source ; max 7 jours",
    )


def _chemin_arbre(src: Source, partage: str | None, chemin: str) -> str:
    """Chemin d'un dossier tel que les arbres de documents l'affichent (préfixe des documents)."""
    if src.type == "smb":
        return f"smb://{src.hote}/{partage}{chemin.rstrip('/')}"
    return ((src.chemin_base or "").rstrip("/") + chemin).rstrip("/") or "/"


@router.get("/sources/dossiers-surveilles", tags=["Sources"])
async def dossiers_surveilles(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Tous les dossiers **surveillés** (synchro automatique active), toutes sources confondues,
    sous la forme de chemins d'arbre. Sert à poser le même repère visuel dans chaque explorateur
    (« Parcourir », « Dossiers indexés »…) sans que chacun refasse le calcul.
    """
    from services.job_worker import cle_dossier, intervalle_dossier

    sources = (await db.execute(
        select(Source).where(Source.actif.is_(True), Source.type.in_(("smb", "local")))
    )).scalars().all()
    dossiers = []
    for src in sources:
        reglages = src.sync_dossiers or {}
        if not (src.sync_intervalle_minutes or 0) > 0 and not reglages:
            continue
        for sc in await _scopes_indexes(db, src):
            minutes = intervalle_dossier(cle_dossier(sc["partage"], sc["chemin"]),
                                         src.sync_intervalle_minutes, reglages)
            if minutes > 0:
                dossiers.append({"chemin": _chemin_arbre(src, sc["partage"], sc["chemin"]),
                                 "minutes": minutes, "source": src.libelle})
    return {"dossiers": dossiers}


@router.get("/sources/{source_id}/sync-dossiers", tags=["Sources"])
async def lire_sync_dossiers(source_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Surveillance automatique **dossier par dossier** : pour chaque dossier indexé de la source,
    son réglage propre (`minutes`, null = suit la source), l'intervalle réellement appliqué et la
    date de sa dernière synchro. Sert au réglage dans « Dossiers indexés ».
    """
    from services.job_worker import cle_dossier, etats_synchro, intervalle_dossier

    src = await _get(db, source_id)
    if src.type not in ("smb", "local"):       # connecteurs cloud : pas de synchro par dossier
        return {"defaut_minutes": 0, "dossiers": []}
    reglages = src.sync_dossiers or {}
    etats = await etats_synchro(db, str(src.id))
    dossiers = []
    for sc in await _scopes_indexes(db, src):
        cle = cle_dossier(sc["partage"], sc["chemin"])
        dernier, actif = etats.get(cle, (None, False))
        dossiers.append({
            "cle": cle, "partage": sc["partage"], "chemin": sc["chemin"],
            "chemin_arbre": _chemin_arbre(src, sc["partage"], sc["chemin"]),
            "minutes": reglages.get(cle),
            "effectif_minutes": intervalle_dossier(cle, src.sync_intervalle_minutes, reglages),
            "dernier": dernier.isoformat() if dernier else None,
            "en_cours": actif,
        })
    return {"defaut_minutes": src.sync_intervalle_minutes or 0, "dossiers": dossiers}


@router.patch("/sources/{source_id}/sync-dossiers", tags=["Sources"])
async def regler_sync_dossier(source_id: str, body: SyncDossierIn, db: AsyncSession = Depends(get_db)) -> dict:
    """Règle la fréquence d'UN dossier (0 = jamais, null = revenir au réglage de la source)."""
    src = await _get(db, source_id)
    reglages = dict(src.sync_dossiers or {})       # nouvel objet : une mutation en place passerait inaperçue
    if body.minutes is None:
        reglages.pop(body.cle, None)
    else:
        reglages[body.cle] = body.minutes
    src.sync_dossiers = reglages or None
    await db.flush()
    log.info("Synchro auto d'un dossier réglée", source=src.libelle, dossier=body.cle, minutes=body.minutes)
    return {"cle": body.cle, "minutes": body.minutes, "sync_dossiers": reglages}


def _secret_clair(src: Source) -> str | None:
    """
    Mot de passe en clair d'une source, ou None si aucun secret n'est stocké.

    ⚠️ `crypto.decrypt` retourne `""` **sans lever** quand la clé Fernet ne correspond pas à
    celle qui a chiffré le secret (ex. clé rotée). Sans garde, on se connecterait alors avec un
    mot de passe VIDE → le NAS n'expose aucun partage → « Aucun partage » muet et trompeur. On
    détecte ce cas (token chiffré présent mais déchiffré vide) et on le dit clairement.
    """
    if not src.secret_chiffre:
        return None
    clair = crypto.decrypt(src.secret_chiffre)
    if crypto.is_encrypted(src.secret_chiffre) and not clair:
        raise HTTPException(status_code=400, detail=(
            "Mot de passe illisible : la clé de chiffrement diffère de celle utilisée à "
            "l'enregistrement. Modifie la source et re-saisis le mot de passe."
        ))
    return clair


async def _get(db: AsyncSession, source_id: str) -> Source:
    try:
        sid = uuid.UUID(source_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")
    src = await db.get(Source, sid)
    if not src:
        raise HTTPException(status_code=404, detail="Source introuvable")
    return src


@router.get("/sources", tags=["Sources"])
async def list_sources(db: AsyncSession = Depends(get_db)) -> dict:
    rows = (await db.execute(select(Source).order_by(Source.created_at))).scalars().all()
    return {"sources": [_to_dict(s) for s in rows]}


@router.post("/sources", tags=["Sources"])
async def create_source(body: SourceIn, db: AsyncSession = Depends(get_db)) -> dict:
    if body.type not in ("local", "smb"):
        raise HTTPException(status_code=422, detail="type doit être 'local' ou 'smb'")
    src = Source(
        libelle=body.libelle, type=body.type, chemin_base=body.chemin_base,
        hote=body.hote, domaine=body.domaine, identifiant=body.identifiant,
        secret_chiffre=crypto.encrypt(body.secret) if body.secret else None,
    )
    db.add(src)
    await db.flush()
    return _to_dict(src)


@router.put("/sources/{source_id}", tags=["Sources"])
async def update_source(source_id: str, body: SourceIn, db: AsyncSession = Depends(get_db)) -> dict:
    src = await _get(db, source_id)
    src.libelle = body.libelle
    src.type = body.type
    src.chemin_base = body.chemin_base
    src.hote = body.hote
    src.domaine = body.domaine
    src.identifiant = body.identifiant
    if body.secret:  # ne ré-écrit le secret que s'il est fourni
        src.secret_chiffre = crypto.encrypt(body.secret)
    await db.flush()
    return _to_dict(src)


@router.delete("/sources/{source_id}", tags=["Sources"])
async def delete_source(source_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    src = await _get(db, source_id)
    await db.delete(src)
    return {"message": "Source supprimée", "id": source_id}


@router.post("/sources/test", tags=["Sources"])
async def test_source(body: SourceIn) -> dict:
    """Teste une source AVANT sauvegarde (secret en clair fourni dans le body)."""
    if body.type == "local":
        p = Path(body.chemin_base or "")
        return {"ok": p.exists() and p.is_dir(), "chemin": str(p)}
    if body.type == "smb":
        if not body.hote:
            raise HTTPException(status_code=422, detail="hôte requis pour une source SMB")
        return await smb_service.test_connexion(body.hote, body.identifiant, body.secret, body.domaine)
    raise HTTPException(status_code=422, detail="type inconnu")


@router.get("/sources/{source_id}/shares", tags=["Sources"])
async def list_shares(source_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    src = await _get(db, source_id)
    if src.type != "smb":
        raise HTTPException(status_code=400, detail="Source non-SMB")
    secret = _secret_clair(src)
    try:
        partages = await smb_service.list_shares(src.hote, src.identifiant, secret, src.domaine)
        return {"partages": partages}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SMB : {exc}")


@router.post("/sources/{source_id}/index", tags=["Sources"])
async def index_source(
    source_id: str,
    body: IndexRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Indexe un dossier d'une source (local ou SMB) comme **tâche durable** (worker) : renvoie
    un `job_id` immédiatement. La progression fine reste consultable via
    `GET /sources/{id}/progression` (barre UI) et le job via `GET /api/jobs/{id}`.
    """
    src = await _get(db, source_id)
    if src.type not in ("local", "smb"):
        raise HTTPException(status_code=422, detail="type de source inconnu")
    if src.type == "smb" and not body.partage:
        raise HTTPException(status_code=422, detail="partage requis pour une source SMB")

    # La barre s'affiche dès l'enfilement : la route de progression voit le job `pending`.
    from services import job_worker
    job_id = await job_worker.enqueue(db, "indexation", {
        "source_id": str(src.id), "chemin": body.chemin, "partage": body.partage, "recursive": body.recursive,
    })
    await db.commit()
    log.info("Indexation mise en file (job durable)", source=src.libelle, job_id=job_id)
    return {"job_id": job_id, "statut": "pending", "message": "Indexation lancée (tâche durable)",
            "source": src.libelle, "chemin": body.chemin}


async def _scopes_indexes(db: AsyncSession, src: Source) -> list[dict]:
    """
    Périmètres à re-scanner : les dossiers de 1er niveau qui contiennent DÉJÀ des documents.
    On ne parcourt pas les partages entiers ni les dossiers vides — ciblage du travail réel,
    et un job par périmètre (donc parallélisables et annulables séparément).
    """
    if src.type == "local":
        return [{"chemin": "/", "partage": None, "recursive": True}]

    prefix = f"smb://{src.hote}/"
    chemins = (await db.execute(
        select(Document.chemin).where(Document.chemin.like(prefix.replace("%", "") + "%"))
    )).scalars().all()
    scopes, vus = [], set()
    for ch in chemins:
        parts = ch[len(prefix):].split("/")          # [partage, dossier1, dossier2, …, fichier]
        if len(parts) < 2:
            continue
        partage, dossier = parts[0], "/" + parts[1]
        if (partage, dossier) in vus:
            continue
        vus.add((partage, dossier))
        scopes.append({"chemin": dossier, "partage": partage, "recursive": True})
    return scopes


@router.post("/sources/{source_id}/sync", tags=["Sources"])
async def sync_source(source_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    **Synchronisation incrémentale** : compare la source à l'index et ne traite que les écarts
    (nouveaux, modifiés, déplacés, disparus). À préférer à « Réindexer » — sans changement, elle
    ne télécharge aucun fichier et n'appelle ni Tika ni Ollama. Un job durable par périmètre.
    """
    src = await _get(db, source_id)
    if src.type not in ("local", "smb"):
        raise HTTPException(status_code=422, detail="type de source inconnu")

    from services import job_worker

    scopes = await _scopes_indexes(db, src)
    if not scopes:
        return {"job_ids": [], "nb": 0,
                "message": "Rien d'indexé à synchroniser — indexe d'abord un dossier."}

    job_ids = [
        await job_worker.enqueue(db, "sync_source",
                                 {"source_id": str(src.id), "chemin": sc["chemin"], "partage": sc["partage"]})
        for sc in scopes
    ]
    await db.commit()
    log.info("Synchronisation lancée", source=src.libelle, nb_scopes=len(scopes))
    return {"job_ids": job_ids, "nb": len(scopes),
            "message": f"Synchronisation lancée — {len(scopes)} dossier(s) comparés à l'index"}


class PerimetreRequest(BaseModel):
    chemin: str = Field(description="chemin d'un dossier tel que l'arbre des documents l'affiche")
    action: str = Field(default="sync", description="sync (écarts seulement) | index (tout reparcourir)")


async def _resoudre_perimetre(db: AsyncSession, chemin: str) -> tuple[Source, str | None, str]:
    """
    Dossier de l'arbre des documents → (source, partage, chemin relatif à la source).

    L'arbre ne connaît que des chemins de documents (`smb://hôte/partage/dossier`, ou un chemin
    local absolu) : c'est ici qu'on retrouve la source qui sait y accéder. Lève 422 avec un
    message affichable quand le dossier ne peut pas être traité seul.
    """
    chemin = chemin.strip().rstrip("/")
    sources = (await db.execute(select(Source))).scalars().all()

    if chemin.startswith("smb://"):
        hote, _, reste = chemin[len("smb://"):].partition("/")
        src = next((s for s in sources if s.type == "smb" and s.hote == hote), None)
        if not src:
            raise HTTPException(status_code=422, detail=f"Aucune source réseau ne correspond à {hote}.")
        partage, _, dossier = reste.partition("/")
        if not partage:
            raise HTTPException(status_code=422, detail="Choisis un partage ou un dossier : ici, c'est "
                                "toute la source (utilise Paramètres › Sources pour la traiter en entier).")
        if ".." in dossier.split("/"):
            raise HTTPException(status_code=422, detail="Chemin invalide.")
        return src, partage, "/" + dossier if dossier else "/"

    if chemin.startswith("/"):
        from utils.file_utils import sous_chemin
        for s in sources:
            base = (s.chemin_base or "").rstrip("/")
            if s.type != "local" or not base:
                continue
            if chemin == base or chemin.startswith(base + "/"):
                relatif = chemin[len(base):] or "/"
                try:
                    sous_chemin(base, relatif)        # refuse un `..` qui sortirait de la source
                except ValueError:
                    raise HTTPException(status_code=422, detail="Chemin invalide.")
                return s, None, relatif
        raise HTTPException(status_code=422, detail="Ce dossier n'appartient à aucune source locale "
                            "(il est au-dessus du dossier configuré, ou la source a été supprimée).")

    raise HTTPException(status_code=422, detail="Cette source ne se synchronise pas dossier par dossier.")


@router.post("/sources/perimetre", tags=["Sources"])
async def lancer_perimetre(body: PerimetreRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Synchronise ou indexe **un seul dossier**, désigné par son chemin dans l'arbre des documents
    (clic droit dans « Parcourir »). Évite de relancer toute la source pour un besoin ponctuel.

    Un seul job durable ; si le même périmètre est déjà en file ou en cours, on le renvoie au
    lieu d'en empiler un second (un double clic ne double pas le travail).
    """
    if body.action not in ("sync", "index"):
        raise HTTPException(status_code=422, detail="action doit être sync | index")
    src, partage, chemin = await _resoudre_perimetre(db, body.chemin)

    from models.job import Job
    from services import job_worker

    type_job = "sync_source" if body.action == "sync" else "indexation"
    libelle = "Synchronisation" if body.action == "sync" else "Indexation"
    actifs = (await db.execute(
        select(Job).where(Job.type == type_job, Job.statut.in_(("pending", "running")))
    )).scalars().all()
    for j in actifs:
        p = j.parametres or {}
        if (p.get("source_id"), p.get("partage"), p.get("chemin")) == (str(src.id), partage, chemin):
            return {"job_id": str(j.id), "deja_en_cours": True, "source": src.libelle,
                    "partage": partage, "chemin": chemin,
                    "message": f"{libelle} déjà en cours pour ce dossier"}

    parametres = {"source_id": str(src.id), "chemin": chemin, "partage": partage}
    if body.action == "index":
        parametres["recursive"] = True
    job_id = await job_worker.enqueue(db, type_job, parametres)
    await db.commit()
    log.info("Périmètre lancé depuis l'arbre", action=body.action, source=src.libelle,
             partage=partage, chemin=chemin, job_id=job_id)
    return {"job_id": job_id, "deja_en_cours": False, "source": src.libelle,
            "partage": partage, "chemin": chemin,
            "message": f"{libelle} lancée — suis-la dans « Tâches »"}


@router.post("/sources/{source_id}/reindex", tags=["Sources"])
async def reindex_source(source_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Ré-indexe (re-scanne) **les dossiers DÉJÀ indexés** de la source, pour rattraper les fichiers
    ajoutés ou modifiés depuis. Idempotent (dédup par hash SHA256) : les inchangés sont sautés,
    seuls les nouveaux/modifiés sont traités. Un job durable par dossier de 1er niveau (partage +
    dossier) → visibles dans « Tâches ». Évite d'avoir à re-naviguer manuellement à chaque nouveauté.
    """
    src = await _get(db, source_id)
    if src.type not in ("local", "smb"):
        raise HTTPException(status_code=422, detail="type de source inconnu")

    from services import job_worker

    scopes = await _scopes_indexes(db, src)
    if not scopes:
        return {"job_ids": [], "nb": 0, "message": "Rien d'indexé à ré-scanner pour cette source."}

    job_ids: list[str] = []
    for sc in scopes:
        jid = await job_worker.enqueue(db, "indexation", {"source_id": str(src.id), **sc})
        job_ids.append(jid)
    await db.commit()
    log.info("Ré-indexation lancée", source=src.libelle, nb_scopes=len(scopes))
    return {"job_ids": job_ids, "nb": len(scopes),
            "message": f"Ré-indexation lancée — {len(scopes)} dossier(s) re-scannés (nouveautés ajoutées)"}


@router.get("/sources/{source_id}/progression", tags=["Sources"])
async def progression_source(source_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    État d'avancement de l'indexation d'une source (pour la barre de progression), **lu en
    base** : les jobs `indexation` actifs de la source, et ce que le worker y écrit chaque
    seconde (`resultat` = `{phase, total, fait}`). N'importe quel process API répond donc la
    même chose — avant, la route lisait un dict du process, jamais alimenté par le worker.

    Plusieurs jobs d'une même source (un par dossier re-scanné) s'ADDITIONNENT : chacun
    compte ses propres fichiers, le total est la somme des totaux.
    """
    from models.job import Job

    actifs = [
        j for j in (await db.execute(
            select(Job).where(Job.type == "indexation", Job.statut.in_(("pending", "running")))
        )).scalars().all()
        # Peu de jobs actifs à la fois : filtrer ici reste portable (JSONB en prod, JSON en test).
        if (j.parametres or {}).get("source_id") == source_id
    ]
    if not actifs:
        return {"en_cours": False, "phase": "aucune", "total": 0, "fait": 0, "pct": 0,
                "nb_jobs": 0}

    en_cours = [j for j in actifs if j.statut == "running"]
    comptes = [j.resultat or {} for j in en_cours if (j.resultat or {}).get("phase") == "indexation"]
    total = sum(int(r.get("total") or 0) for r in comptes)
    fait = sum(min(int(r.get("fait") or 0), int(r.get("total") or 0)) for r in comptes)
    if comptes:
        phase = "indexation"
    elif en_cours:
        phase = "enumeration"
    else:
        phase = "attente"          # en file : le worker ne l'a pas encore pris
    pct = max(0, min(100, round(fait / total * 100))) if total else 0
    return {"en_cours": True, "phase": phase, "total": total, "fait": fait, "pct": pct,
            "nb_jobs": len(actifs)}


def _prefixe_source(src: Source) -> str:
    """Préfixe de chemin des documents indexés d'une source (pour l'arbre « Dossiers indexés »)."""
    if src.type == "smb":
        return f"smb://{src.hote}/"
    # Connecteurs cloud (gdrive, synology…) : les docs ont un chemin `{type}://{source_id}{rel}`
    # (cf. connector_jobs). Sans ce cas, l'arbre indexé d'un Drive cherchait sous « root/ » → vide.
    from services.connectors import types_supportes
    if src.type in types_supportes():
        return f"{src.type}://{src.id}/"
    return (src.chemin_base or "/").rstrip("/") + "/"


@router.get("/sources/{source_id}/indexed", tags=["Sources"])
async def indexed_tree(source_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Arbre des dossiers réellement indexés pour cette source (dérivé des documents)."""
    from collections import defaultdict
    src = await _get(db, source_id)
    prefix = _prefixe_source(src)
    base = prefix.rstrip("/")
    chemins = (await db.execute(
        select(Document.chemin).where(Document.chemin.like(prefix.replace("%", "") + "%"))
    )).scalars().all()

    direct: dict[str, int] = defaultdict(int)
    for ch in chemins:
        folder = ch.rsplit("/", 1)[0] if "/" in ch[len(base):] else base
        direct[folder] += 1

    total: dict[str, int] = defaultdict(int)
    allpaths: set[str] = set()
    for folder, n in direct.items():
        p = folder
        while True:
            total[p] += n
            allpaths.add(p)
            if p == base or len(p) <= len(base):
                break
            p = p.rsplit("/", 1)[0]

    children: dict[str, list[str]] = defaultdict(list)
    for p in allpaths:
        if p == base:
            continue
        parent = p.rsplit("/", 1)[0]
        if len(parent) >= len(base):
            children[parent].append(p)

    def build(p: str) -> dict:
        return {
            "chemin": p,
            "nom": p[len(base):].strip("/") .split("/")[-1] or p.split("/")[-1] or p,
            "nb": total.get(p, 0),
            "enfants": [build(c) for c in sorted(set(children.get(p, [])))],
        }

    arbre = [build(c) for c in sorted(set(children.get(base, [])))]
    return {"racine": base, "nb_documents": len(chemins), "arbre": arbre}


class DeindexRequest(BaseModel):
    chemins: list[str] = Field(default_factory=list, min_length=1)


@router.post("/sources/{source_id}/deindex", tags=["Sources"])
async def deindex(source_id: str, body: DeindexRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Retire de l'index (GED) les documents des dossiers donnés. Ne touche PAS aux fichiers."""
    from sqlalchemy import or_
    await _get(db, source_id)  # valide l'existence
    retires = 0
    for folder in body.chemins:
        f = folder.rstrip("/")
        docs = (await db.execute(
            select(Document).where(or_(Document.chemin == f, Document.chemin.like(f + "/%")))
        )).scalars().all()
        for d in docs:
            await db.delete(d)
            retires += 1
    await db.flush()
    log.info("Désindexation", source=source_id, dossiers=len(body.chemins), docs_retires=retires)
    return {"retires": retires}


@router.get("/sources/{source_id}/absents", tags=["Sources"])
async def list_absents(source_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Documents passés `statut='absent'` sous cette source : disparus du NAS lors d'une synchro,
    mais **jamais supprimés d'office** de l'index. À proposer à la purge (réversible côté NAS,
    l'index se reconstruit par ré-indexation si les fichiers reviennent).
    """
    src = await _get(db, source_id)
    prefix = _prefixe_source(src)
    rows = (await db.execute(
        select(Document.id, Document.nom, Document.chemin, Document.date_modification_fichier)
        .where(Document.statut == "absent",
               Document.chemin.like(prefix.replace("%", "") + "%"))
        .order_by(Document.chemin)
    )).all()
    docs = [{"id": str(r.id), "nom": r.nom, "chemin": r.chemin,
             "date": r.date_modification_fichier.isoformat() if r.date_modification_fichier else None}
            for r in rows]
    return {"total": len(docs), "documents": docs}


class PurgeAbsentsRequest(BaseModel):
    ids: list[str] = Field(default_factory=list)
    tout: bool = Field(default=False, description="true = purge TOUS les absents de la source")


@router.post("/sources/{source_id}/purge-absents", tags=["Sources"])
async def purge_absents(source_id: str, body: PurgeAbsentsRequest,
                        db: AsyncSession = Depends(get_db)) -> dict:
    """Retire de l'index les documents `absent` sélectionnés (ou tous). Ne touche à aucun fichier."""
    src = await _get(db, source_id)
    prefix = _prefixe_source(src)
    base = select(Document).where(Document.statut == "absent",
                                  Document.chemin.like(prefix.replace("%", "") + "%"))
    if not body.tout:
        try:
            uids = [uuid.UUID(i) for i in body.ids]
        except ValueError:
            raise HTTPException(status_code=400, detail="ID invalide")
        if not uids:
            return {"retires": 0}
        base = base.where(Document.id.in_(uids))
    docs = (await db.execute(base)).scalars().all()
    for d in docs:
        await db.delete(d)
    await db.flush()
    log.info("Purge des absents", source=src.libelle, retires=len(docs), tout=body.tout)
    return {"retires": len(docs)}


@router.get("/sources/{source_id}/browse", tags=["Sources"])
async def browse_source(
    source_id: str,
    chemin: str = Query(default="/"),
    partage: str | None = Query(default=None, description="partage SMB (requis pour SMB)"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    src = await _get(db, source_id)
    if src.type == "local":
        from utils.file_utils import sous_chemin
        try:
            cible = sous_chemin(src.chemin_base, chemin)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if not cible.exists() or not cible.is_dir():
            raise HTTPException(status_code=404, detail="Dossier introuvable")
        entries = []
        for e in sorted(cible.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            entries.append({"nom": e.name, "dossier": e.is_dir(), "taille": e.stat().st_size if e.is_file() else 0})
        return {"chemin": str(cible), "entries": entries}
    # SMB
    if not partage:
        raise HTTPException(status_code=422, detail="partage requis pour une source SMB")
    secret = _secret_clair(src)
    try:
        from utils.file_utils import chemin_partage
        entries = await smb_service.browse(src.hote, partage, chemin_partage(chemin),
                                           src.identifiant, secret, src.domaine)
        return {"partage": partage, "chemin": chemin, "entries": entries}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SMB : {exc}")
