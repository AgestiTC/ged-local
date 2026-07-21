"""
Synchronisation incrémentale — état réel (NAS/disque) ↔ index
==============================================================
Compare ce qui existe **sur la source** à ce qui est **en base**, et n'agit que sur les
écarts. Contrairement à l'indexation (qui parcourt et retraite tout), une synchro ne
télécharge que les fichiers réellement nouveaux ou modifiés.

Quatre écarts, quatre traitements :

| Écart          | Détection                                    | Action                                   |
|----------------|----------------------------------------------|------------------------------------------|
| **Nouveau**    | chemin absent de l'index                     | pipeline complet (Tika → IA → embeddings)|
| **Modifié**    | taille OU date de modif différente           | ré-extraction + archivage d'une `version`|
| **Déplacé**    | même nom + même taille qu'un disparu         | simple UPDATE du chemin (aucun transfert)|
| **Absent**     | en index, plus sur la source                 | `statut='absent'` — **jamais supprimé**  |

Le walk réseau reste le coût dominant : il ne renvoie que des métadonnées (nom, taille,
date), donc **aucun octet de contenu n'est transféré pour les fichiers inchangés**.
"""

import asyncio
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from database import AsyncSessionLocal
from logger import get_logger
from models.document import Document
from services import smb_service

log = get_logger(__name__)

# Tolérance sur les dates : les systèmes de fichiers n'ont pas tous la même granularité
# (FAT arrondit à 2 s, SMB renvoie un flottant, PostgreSQL stocke à la microseconde).
# Sans marge, chaque synchro reclasserait tout le corpus en « modifié ».
TOLERANCE_MTIME_S = 5.0

# En deçà de cet écart entre `date_import` et `date_modification_fichier`, la date stockée est
# celle du FICHIER TEMPORAIRE de rapatriement SMB — un artefact des indexations antérieures à
# `chemin_logique`/`mtime_fichier`. Elle ne dit rien du fichier sur le NAS : on l'ignore et on
# se rabat sur la taille. Les documents (re)traités depuis portent la vraie date.
ARTEFACT_TEMP_S = 300.0


# ─── Énumération de la source ────────────────────────────────────────────────

async def _lister_smb(src, partage: str, chemin: str, secret: str | None, extensions) -> dict[str, dict]:
    """{chemin_logique -> {chemin, taille, mtime, rel}} pour un sous-dossier d'un partage."""
    entrees = await smb_service.walk_files(
        src.hote, partage, chemin, src.identifiant, secret, src.domaine, extensions
    )
    distants = {}
    for e in entrees:
        chemin_doc = f"smb://{src.hote}/{partage}{e['rel']}"
        distants[chemin_doc] = {"chemin": chemin_doc, "rel": e["rel"],
                                "taille": int(e["taille"]), "mtime": e.get("mtime")}
    return distants


async def _lister_local(src, chemin: str, extensions) -> dict[str, dict]:
    """Idem pour une source locale (volume monté). Le `stat` est déporté en thread."""
    from services.folder_watcher import _est_cache

    base = Path(src.chemin_base or "/")
    cible = (base / chemin.lstrip("/")) if chemin not in ("", "/") else base

    def _scan() -> dict[str, dict]:
        trouves = {}
        for f in cible.rglob("*"):
            try:
                if not f.is_file() or _est_cache(f):
                    continue
                if f.suffix.lstrip(".").lower() not in extensions:
                    continue
                st = f.stat()
                cle = str(f.resolve())
                trouves[cle] = {"chemin": cle, "rel": cle, "taille": st.st_size, "mtime": st.st_mtime}
            except OSError:
                continue  # fichier disparu/illisible en cours de scan → ignoré
        return trouves

    return await asyncio.to_thread(_scan)


def _like_prefixe(prefixe: str) -> str:
    """
    Échappe les jokers SQL du préfixe. `_` et `%` sont **courants dans les noms de fichiers**
    (`01_bebe`) et valent « n'importe quel caractère » dans un LIKE : sans échappement, la photo
    de l'index déborderait sur des dossiers voisins, qui seraient alors vus comme « absents ».
    """
    return prefixe.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


async def _lister_index(prefixe: str) -> dict[str, dict]:
    """Photo de l'index sous ce préfixe : {chemin -> {id, taille, mtime, import, statut}}."""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Document.id, Document.chemin, Document.taille_octets,
                   Document.date_modification_fichier, Document.date_import, Document.statut)
            .where(Document.chemin.like(_like_prefixe(prefixe), escape="\\"))
        )).all()
    return {
        r.chemin: {"id": r.id, "chemin": r.chemin, "taille": r.taille_octets or 0,
                   "mtime": r.date_modification_fichier, "import": r.date_import, "statut": r.statut}
        for r in rows
    }


# ─── Diff ────────────────────────────────────────────────────────────────────

def _mtime_exploitable(idx: dict) -> bool:
    """La date stockée décrit-elle le fichier source (et non le temporaire de rapatriement) ?"""
    if not idx.get("mtime") or not idx.get("import"):
        return False
    return abs((idx["mtime"] - idx["import"]).total_seconds()) > ARTEFACT_TEMP_S


def _a_change(idx: dict, dist: dict) -> bool:
    """Taille différente, ou date de modif postérieure (quand elle est exploitable)."""
    if int(idx["taille"] or 0) != int(dist["taille"]):
        return True
    if dist.get("mtime") and _mtime_exploitable(idx):
        return abs(idx["mtime"].timestamp() - float(dist["mtime"])) > TOLERANCE_MTIME_S
    return False


def _apparier_deplaces(nouveaux: list[dict], absents: list[dict]) -> list[tuple[dict, dict]]:
    """
    Un fichier déplacé/renommé se présente comme « un disparu ici + un nouveau là ».
    On les rapproche sur (nom, taille) — et **seulement si l'appariement est unique des deux
    côtés**, pour ne jamais confondre deux homonymes de même taille. Un déplacement reconnu
    coûte un simple UPDATE : ni transfert, ni ré-extraction, ni doublon.
    """
    def cle(d: dict) -> tuple:
        return (Path(d["chemin"]).name.lower(), int(d["taille"] or 0))

    par_nouveau, par_absent = defaultdict(list), defaultdict(list)
    for n in nouveaux:
        par_nouveau[cle(n)].append(n)
    for a in absents:
        par_absent[cle(a)].append(a)

    return [
        (par_absent[k][0], v[0])
        for k, v in par_nouveau.items()
        if len(v) == 1 and len(par_absent.get(k, [])) == 1
    ]


def diff(distants: dict[str, dict], indexes: dict[str, dict]) -> dict:
    """Classe les écarts. Fonction PURE (aucune I/O) — c'est elle que testent les tests."""
    nouveaux, modifies, revenus, inchanges = [], [], [], 0
    for chemin, dist in distants.items():
        idx = indexes.get(chemin)
        if idx is None:
            nouveaux.append(dist)
        elif _a_change(idx, dist):
            modifies.append(dist)
        elif idx.get("statut") == "absent":
            # Réapparu à l'identique (partage remonté, dossier restauré) → simple réactivation,
            # sans re-télécharger ni ré-extraire quoi que ce soit.
            revenus.append(idx)
        else:
            inchanges += 1

    absents = [idx for chemin, idx in indexes.items()
               if chemin not in distants and idx.get("statut") != "absent"]

    deplaces = _apparier_deplaces(nouveaux, absents)
    ids_deplaces = {id(a) for a, _ in deplaces} | {id(n) for _, n in deplaces}
    return {
        "nouveaux": [n for n in nouveaux if id(n) not in ids_deplaces],
        "modifies": modifies,
        "absents": [a for a in absents if id(a) not in ids_deplaces],
        "deplaces": deplaces,
        "revenus": revenus,
        "inchanges": inchanges,
    }


# ─── Application des écarts ──────────────────────────────────────────────────

async def _traiter_fichier(service, src, partage, secret, entree: dict, taille_max: int) -> None:
    """Indexe (ou ré-indexe) un fichier : catalogue léger si média/volumineux, pipeline sinon."""
    from services.folder_watcher import MEDIA_EXTENSIONS

    chemin_doc = entree["chemin"]
    nom = Path(chemin_doc).name
    ext = Path(nom).suffix.lstrip(".").lower()
    taille = int(entree["taille"])
    mtime = _dt(entree.get("mtime"))

    if ext in MEDIA_EXTENSIONS or taille > taille_max:
        # Ni transfert ni IA : on ne fait que référencer (et rafraîchir taille/date).
        async with AsyncSessionLocal() as db:
            existant = (await db.execute(
                select(Document).where(Document.chemin == chemin_doc)
            )).scalar_one_or_none()
            if existant:
                existant.taille_octets, existant.date_modification_fichier = taille, mtime
                if existant.statut == "absent":
                    existant.statut = "catalogued"
            else:
                await service.catalogue_media(chemin=chemin_doc, nom=nom, taille=taille,
                                              source="watch", date_modification=mtime, db=db)
            await db.commit()
        return

    if src.type == "local":
        async with AsyncSessionLocal() as db:
            await service.process_file(Path(chemin_doc), source="watch", db=db)
            await db.commit()
        return

    tmp = None
    try:
        tmp = await smb_service.fetch_to_temp(src.hote, partage, entree["rel"],
                                              src.identifiant, secret, src.domaine)
        async with AsyncSessionLocal() as db:
            await service.process_file(Path(tmp), source="watch", db=db,
                                       chemin_logique=chemin_doc, mtime_fichier=mtime)
            await db.commit()
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


def _dt(epoch):
    """Epoch (float) ou datetime → datetime UTC, tolérant aux valeurs absentes/aberrantes."""
    if not epoch:
        return None
    if isinstance(epoch, datetime):
        return epoch
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


async def _appliquer_deplacements(paires: list[tuple[dict, dict]]) -> int:
    """Recolle chemin et nom sur la ligne existante — le document garde son historique."""
    if not paires:
        return 0
    async with AsyncSessionLocal() as db:
        for absent, nouveau in paires:
            doc = await db.get(Document, absent["id"])
            if not doc:
                continue
            log.info("Document déplacé", ancien=doc.chemin, nouveau=nouveau["chemin"])
            doc.chemin = nouveau["chemin"]
            doc.nom = Path(nouveau["chemin"]).name
            doc.date_modification_fichier = _dt(nouveau.get("mtime")) or doc.date_modification_fichier
            if doc.statut == "absent":
                doc.statut = "catalogued"
        await db.commit()
    return len(paires)


async def _marquer_absents(absents: list[dict]) -> int:
    """
    Marque `statut='absent'` — **aucune suppression**. Un partage temporairement injoignable ou
    un dossier démonté ne doit jamais provoquer de perte : la purge reste une action explicite
    de l'utilisateur (page Doublons/Corbeille).
    """
    if not absents:
        return 0
    async with AsyncSessionLocal() as db:
        for a in absents:
            doc = await db.get(Document, a["id"])
            if doc:
                doc.statut = "absent"
        await db.commit()
    return len(absents)


async def _reactiver(revenus: list[dict]) -> int:
    """Un document réapparu à l'identique retrouve son statut normal (sans retraitement)."""
    if not revenus:
        return 0
    async with AsyncSessionLocal() as db:
        for r in revenus:
            doc = await db.get(Document, r["id"])
            if doc and doc.statut == "absent":
                doc.statut = "enriched" if doc.texte_extrait else "catalogued"
        await db.commit()
    return len(revenus)


# ─── Point d'entrée ──────────────────────────────────────────────────────────

async def synchroniser(src, partage: str | None, chemin: str, secret: str | None,
                       ctx=None) -> dict:
    """
    Synchronise un périmètre (source + partage + sous-dossier) et renvoie le récapitulatif
    `{nouveaux, modifies, absents, deplaces, inchanges}`.

    `ctx` (JobContext) est optionnel : progression et annulation quand on tourne en job durable.
    """
    from services import runtime_config

    extensions = runtime_config.effective_extensions()
    try:
        taille_max = int(float(runtime_config.effective("index_taille_max_mo") or 2048)) * 1024 * 1024
    except (TypeError, ValueError):
        taille_max = 2048 * 1024 * 1024

    if ctx:
        await ctx.report(progress=0, message="Énumération de la source…")

    if src.type == "smb":
        if not partage:
            raise ValueError("partage requis pour une source SMB")
        distants = await _lister_smb(src, partage, chemin, secret, extensions)
        prefixe = f"smb://{src.hote}/{partage}{chemin.rstrip('/')}".rstrip("/") + "/"
    else:
        distants = await _lister_local(src, chemin, extensions)
        base = Path(src.chemin_base or "/")
        cible = (base / chemin.lstrip("/")) if chemin not in ("", "/") else base
        prefixe = str(cible).rstrip("/") + "/"

    indexes = await _lister_index(prefixe)

    # 🔴 GARDE-FOU : un walk qui ne renvoie RIEN alors que l'index contient des documents
    # signifie presque toujours un incident (partage démonté, droits perdus, dossier renommé),
    # pas une suppression massive. On refuse alors de toucher au statut de quoi que ce soit.
    if not distants and indexes:
        log.error("Synchro ABANDONNÉE — la source ne renvoie aucun fichier alors que l'index en "
                  "contient : partage injoignable ou dossier renommé ?",
                  source=src.libelle, chemin=chemin, en_index=len(indexes))
        raise RuntimeError(
            f"Synchro abandonnée : aucun fichier trouvé sur la source alors que {len(indexes)} "
            f"document(s) sont indexés sous ce chemin. Vérifie que le partage est joignable et "
            f"que le dossier n'a pas été renommé — aucun document n'a été modifié."
        )

    ecarts = diff(distants, indexes)

    a_traiter = ecarts["nouveaux"] + ecarts["modifies"]
    log.info("Synchro — écarts détectés", source=src.libelle, chemin=chemin,
             nouveaux=len(ecarts["nouveaux"]), modifies=len(ecarts["modifies"]),
             absents=len(ecarts["absents"]), deplaces=len(ecarts["deplaces"]),
             revenus=len(ecarts["revenus"]), inchanges=ecarts["inchanges"])

    # Écarts « gratuits » d'abord : ils n'impliquent aucun transfert.
    nb_deplaces = await _appliquer_deplacements(ecarts["deplaces"])
    nb_absents = await _marquer_absents(ecarts["absents"])
    nb_revenus = await _reactiver(ecarts["revenus"])

    if not a_traiter:
        # Rien à extraire → on ne réveille NI Tika NI Ollama. Une synchro à vide doit être
        # quasi gratuite, sinon on ne peut pas la planifier fréquemment.
        if ctx:
            await ctx.report(progress=100, message="Aucun écart de contenu")
        return {"nouveaux": 0, "modifies": 0, "absents": nb_absents, "deplaces": nb_deplaces,
                "revenus": nb_revenus, "inchanges": ecarts["inchanges"], "traites": 0, "annule": False}

    from routers.sources import _extraction_service
    service = _extraction_service()

    traites, annule = 0, False
    for i, entree in enumerate(a_traiter, start=1):
        if ctx and ctx.cancelled:
            annule = True
            break
        try:
            await _traiter_fichier(service, src, partage, secret, entree, taille_max)
            traites += 1
        except Exception as e:  # noqa: BLE001 — un fichier en erreur ne doit pas arrêter la synchro
            log.error("Synchro — échec sur un fichier", fichier=entree["chemin"], erreur=str(e))
        if ctx:
            await ctx.report(progress=round(i / len(a_traiter) * 100),
                             message=f"{i}/{len(a_traiter)} fichier(s) à jour")
        await asyncio.sleep(0)  # rend la main : l'annulation reste réactive

    return {"nouveaux": len(ecarts["nouveaux"]), "modifies": len(ecarts["modifies"]),
            "absents": nb_absents, "deplaces": nb_deplaces, "revenus": nb_revenus,
            "inchanges": ecarts["inchanges"], "traites": traites, "annule": annule}
