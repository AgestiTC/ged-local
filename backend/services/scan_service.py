"""
Service Scan — boîte à scans, profils, rangement
=================================================
Tout ce qui fait d'un scan « un document au bon endroit, avec les bons tags » :

- **nommage** : `{date}_{profil}` → `2026-09-11_facture.pdf` (placeholders bornés, nom sûr) ;
- **destination** : `smb://nas/Documents/Factures/{annee}` résolue à la date du jour ;
- **rangement** : déplacer le fichier (local ↔ SMB), sans jamais supprimer avant d'avoir
  écrit la copie, avec journal `reorg_moves` (le même que la réorganisation, donc annulable
  par les mêmes outils) et fusion des tags du profil ;
- **proposition** (mode `ia_confirme`) : quel profil ressemble le plus à ce que l'IA a déjà
  lu (catégorie, tags, texte) — déterministe, sans appel modèle, explicable ;
- **boîte** : les documents arrivés dans le dossier surveillé de la boîte deviennent des
  lignes `scans`, sans toucher au watcher ;
- **assemblage** : des pages JPEG/PDF reçues du scanner vers un PDF unique (pymupdf).

Rien ici ne parle au scanner (cf. `escl_client`) ni n'orchestre les tâches (cf.
`job_handlers`). Fonctions pures d'abord, I/O ensuite — c'est ce qui rend le rangement
testable sans NAS.
"""

from __future__ import annotations

import os
import re
import shutil
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from logger import get_logger
from models.document import Document
from models.metadata import MetadonneeIA
from models.reorg import ReorgMove
from models.scan import MODELE_NOM_DEFAUT, Scan, ScanProfil

log = get_logger(__name__)

PLACEHOLDERS = ("{date}", "{annee}", "{mois}", "{heure}", "{profil}", "{nom}", "{n}")
COLLISIONS_MAX = 50


# ─── Nommage et destination (pur) ──────────────────────────────────────────────────────

def slug(texte: str, defaut: str = "scan") -> str:
    """« Courrier administratif » → `courrier-administratif` (ASCII, sûr pour un nom de fichier)."""
    t = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()
    return t or defaut


def nom_sur(nom: str) -> str:
    """Neutralise ce qui ferait sortir d'un dossier ou casserait un chemin (`/`, `..`, contrôle)."""
    n = (nom or "").replace("\\", "/").split("/")[-1]
    n = re.sub(r"[\x00-\x1f<>:\"|?*]", "", n).strip().strip(".")
    return n or "scan"


def formater_nom(modele: str | None, *, profil_nom: str, nom_origine: str, quand: datetime | None = None,
                 n: int | None = None) -> str:
    """
    Applique le modèle de nom du profil. L'extension d'origine est conservée (un PDF reste un
    PDF). `{n}` n'apparaît que sur collision ; s'il n'est pas dans le modèle, on suffixe `_(n)`.
    """
    quand = quand or datetime.now(tz=timezone.utc)
    origine = Path(nom_sur(nom_origine))
    ext = origine.suffix.lower() or ".pdf"
    modele = (modele or MODELE_NOM_DEFAUT).strip() or MODELE_NOM_DEFAUT
    valeurs = {
        "{date}": quand.strftime("%Y-%m-%d"), "{annee}": quand.strftime("%Y"), "{mois}": quand.strftime("%m"),
        "{heure}": quand.strftime("%H%M"), "{profil}": slug(profil_nom), "{nom}": slug(origine.stem, "scan"),
        "{n}": str(n) if n else "",
    }
    base = modele
    for cle, val in valeurs.items():
        base = base.replace(cle, val)
    base = re.sub(r"[_\-]{2,}", "_", base).strip("_- ")
    if n and "{n}" not in modele:
        base = f"{base}_({n})"
    return nom_sur(base) + ext


def resoudre_destination(destination: str, quand: datetime | None = None) -> str:
    """Remplace `{annee}` / `{mois}` / `{date}` dans le dossier cible ; normalise les slashs."""
    quand = quand or datetime.now(tz=timezone.utc)
    d = (destination or "").strip().replace("\\", "/")
    d = d.replace("{annee}", quand.strftime("%Y")).replace("{mois}", quand.strftime("%m")).replace("{date}", quand.strftime("%Y-%m-%d"))
    d = re.sub(r"/{2,}", "/", d) if not d.startswith("smb://") else "smb://" + re.sub(r"/{2,}", "/", d[len("smb://"):])
    if "/../" in f"/{d}/" or d.startswith("../"):
        raise ValueError("Destination invalide (remontée de dossier)")
    return d.rstrip("/")


def parse_smb(chemin: str | None) -> tuple[str, str, str] | None:
    """`smb://host/share/a/b` → (host, share, '/a/b') ; `smb://host/share` → rel '/' ; None sinon."""
    if not chemin or not chemin.startswith("smb://"):
        return None
    raw = chemin[len("smb://"):]
    parts = raw.split("/", 2)
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None
    rel = "/" + parts[2] if len(parts) == 3 else "/"
    return parts[0], parts[1], rel.rstrip("/") or "/"


def local_autorise(chemin: str) -> bool:
    """Un dossier local n'est acceptable que sous la racine documents (pas de sortie du volume)."""
    racine = Path(get_settings().documents_root).resolve()
    try:
        cible = Path(chemin).resolve()
    except OSError:
        return False
    return cible == racine or racine in cible.parents


# ─── Proposition de profil (pur, déterministe) ─────────────────────────────────────────

def _normaliser(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()


def proposer_profil(profils: list[ScanProfil], *, categorie: str | None = None, sous_categorie: str | None = None,
                    tags: list[str] | None = None, nom: str | None = None, texte: str | None = None) -> dict | None:
    """
    Le profil dont les mots-clés se retrouvent le plus dans ce que l'IA a déjà lu. Chaque
    indice compte une fois ; la catégorie et les tags pèsent plus que le texte (ils ont déjà
    été « compris »). Rien ne correspond → None : on ne propose pas au hasard.
    """
    champs_forts = " ".join(filter(None, [categorie or "", sous_categorie or "", " ".join(tags or []), nom or ""]))
    forts = _normaliser(champs_forts)
    faible = _normaliser((texte or "")[:4000])
    meilleur: dict | None = None
    for p in profils:
        if not p.actif:
            continue
        mots = [m for m in (p.mots_cles or []) if isinstance(m, str) and m.strip()]
        if not mots:
            continue
        score, raisons = 0, []
        for m in mots:
            mn = _normaliser(m.strip())
            if not mn:
                continue
            if mn in forts:
                score += 2
                raisons.append(f"« {m.strip()} » (catégorie/tags)")
            elif mn in faible:
                score += 1
                raisons.append(f"« {m.strip()} » (texte)")
        if score and (meilleur is None or score > meilleur["score"]):
            meilleur = {"profil_id": str(p.id), "nom": p.nom, "score": score, "raisons": raisons}
    return meilleur


# ─── Assemblage PDF ────────────────────────────────────────────────────────────────────

def assembler_pdf(pages: list[tuple[str, bytes]], sortie: Path) -> int:
    """
    Pages (type MIME, octets) → un PDF. Un JPEG/PNG devient une page à sa taille ; un PDF
    reçu (chargeur) est inséré tel quel. Retourne le nombre de pages du résultat.
    """
    import fitz  # pymupdf — déjà dans les dépendances (rastérisation OCR)

    pdf = fitz.open()
    try:
        for content_type, data in pages:
            ct = (content_type or "").lower()
            if "pdf" in ct:
                src = fitz.open(stream=data, filetype="pdf")
                pdf.insert_pdf(src)
                src.close()
            else:
                img = fitz.open(stream=data, filetype="jpeg" if "jpeg" in ct or "jpg" in ct else "png")
                conv = fitz.open("pdf", img.convert_to_pdf())
                pdf.insert_pdf(conv)
                conv.close()
                img.close()
        sortie.parent.mkdir(parents=True, exist_ok=True)
        pdf.save(str(sortie))
        return pdf.page_count
    finally:
        pdf.close()


# ─── Déplacement (local ↔ SMB), jamais destructif avant écriture ───────────────────────

async def creds_smb(db: AsyncSession, hote: str) -> tuple[str | None, str | None, str | None] | None:
    """Identifiants déchiffrés de la source SMB déclarée pour cet hôte (None = aucune source)."""
    from models.source import Source
    from services import crypto
    src = (await db.execute(select(Source).where(Source.type == "smb", Source.hote == hote))).scalars().first()
    if not src:
        return None
    return src.identifiant, (crypto.decrypt(src.secret_chiffre) if src.secret_chiffre else None), src.domaine


async def _nom_libre_smb(hote, partage, dossier, nom, creds) -> str:
    from services import smb_service
    ident, secret, dom = creds
    base, dot, ext = nom.rpartition(".")
    candidat, n = nom, 0
    while await smb_service.exists(hote, partage, f"{dossier}/{candidat}", ident, secret, dom):
        n += 1
        if n > COLLISIONS_MAX:
            raise RuntimeError("Trop de fichiers du même nom à destination")
        candidat = f"{base}_({n}).{ext}" if dot else f"{nom}_({n})"
    return candidat


def _nom_libre_local(dossier: Path, nom: str) -> str:
    base, dot, ext = nom.rpartition(".")
    candidat, n = nom, 0
    while (dossier / candidat).exists():
        n += 1
        if n > COLLISIONS_MAX:
            raise RuntimeError("Trop de fichiers du même nom à destination")
        candidat = f"{base}_({n}).{ext}" if dot else f"{nom}_({n})"
    return candidat


async def deplacer(db: AsyncSession, chemin_source: str, dossier_dest: str, nom: str) -> str:
    """
    Déplace un fichier vers `dossier_dest/nom` et rend le chemin final (logique : `smb://…`
    ou absolu). Quatre cas : SMB→SMB même partage (rename), local→local (move), local→SMB
    et SMB→local (copie puis suppression de l'origine, seulement après écriture réussie).
    """
    from services import smb_service

    src_smb = parse_smb(chemin_source)
    dst_smb = parse_smb(dossier_dest)
    nom = nom_sur(nom)

    if dst_smb:
        hote, partage, rel_dir = dst_smb
        creds = await creds_smb(db, hote)
        if not creds:
            raise RuntimeError(f"Aucune source SMB déclarée pour {hote} (Paramètres → Sources de fichiers)")
        ident, secret, dom = creds
        rel_dir = "" if rel_dir == "/" else rel_dir
        if rel_dir:
            await smb_service.ensure_dir(hote, partage, rel_dir, ident, secret, dom)
        final = await _nom_libre_smb(hote, partage, rel_dir, nom, creds)
        rel_final = f"{rel_dir}/{final}"
        if src_smb and src_smb[0] == hote and src_smb[1] == partage:
            await smb_service.move_file(hote, partage, src_smb[2], rel_final, ident, secret, dom)
        else:
            local_path = chemin_source
            tmp = None
            if src_smb:
                c2 = await creds_smb(db, src_smb[0])
                if not c2:
                    raise RuntimeError(f"Aucune source SMB déclarée pour {src_smb[0]}")
                tmp = await smb_service.fetch_to_temp(src_smb[0], src_smb[1], src_smb[2], *c2)
                local_path = tmp
            try:
                await smb_service.store_file(hote, partage, rel_final, local_path, ident, secret, dom)
            finally:
                if tmp and os.path.exists(tmp):
                    os.unlink(tmp)
            # Copie écrite → on peut retirer l'origine.
            if src_smb:
                await smb_service.delete_file(src_smb[0], src_smb[1], src_smb[2], *c2)
            elif os.path.exists(chemin_source):
                os.unlink(chemin_source)
        return f"smb://{hote}/{partage}{rel_final}"

    # Destination locale — bornée à la racine documents.
    if not local_autorise(dossier_dest):
        raise RuntimeError(f"Destination locale hors de la racine documents ({get_settings().documents_root})")
    dossier = Path(dossier_dest)
    dossier.mkdir(parents=True, exist_ok=True)
    final = _nom_libre_local(dossier, nom)
    cible = dossier / final
    if src_smb:
        c2 = await creds_smb(db, src_smb[0])
        if not c2:
            raise RuntimeError(f"Aucune source SMB déclarée pour {src_smb[0]}")
        tmp = await smb_service.fetch_to_temp(src_smb[0], src_smb[1], src_smb[2], *c2)
        shutil.move(tmp, cible)
        await smb_service.delete_file(src_smb[0], src_smb[1], src_smb[2], *c2)
    else:
        shutil.move(chemin_source, cible)
    return str(cible.resolve())


# ─── Rangement d'un scan ───────────────────────────────────────────────────────────────

async def ranger(db: AsyncSession, scan: Scan, profil: ScanProfil, nom: str | None = None,
                 quand: datetime | None = None) -> dict:
    """
    Applique un profil à un scan indexé : déplacement, journal, tags, statut. Le document
    garde son identité (même id, même texte OCR, mêmes embeddings) — seul son chemin change,
    ce qui évite de tout ré-extraire.
    """
    if not scan.document_id:
        raise RuntimeError("Ce scan n'a pas encore de document indexé")
    doc = await db.get(Document, scan.document_id)
    if not doc:
        raise RuntimeError("Document du scan introuvable")
    quand = quand or datetime.now(tz=timezone.utc)
    dossier = resoudre_destination(profil.destination, quand)
    nom_final = nom_sur(nom) if nom else formater_nom(profil.modele_nom, profil_nom=profil.nom, nom_origine=doc.nom, quand=quand)
    if nom and not Path(nom_final).suffix:
        nom_final += Path(doc.nom).suffix.lower() or ".pdf"

    ancien = doc.chemin
    nouveau = await deplacer(db, ancien, dossier, nom_final)

    doc.chemin = nouveau
    doc.nom = Path(nouveau).name if not nouveau.startswith("smb://") else nouveau.rsplit("/", 1)[-1]
    db.add(ReorgMove(batch_id=scan.id, document_id=doc.id, chemin_source=ancien, chemin_dest=nouveau))

    # Tags du profil, fusionnés avec ceux de l'IA (jamais écrasés).
    meta = (await db.execute(select(MetadonneeIA).where(MetadonneeIA.document_id == doc.id))).scalar_one_or_none()
    if not meta:
        meta = MetadonneeIA(document_id=doc.id, tags=[], niveau_confidentialite="normal")
        db.add(meta)
    tags_profil = [t.strip() for t in (profil.tags or []) if isinstance(t, str) and t.strip()]
    existants = list(meta.tags or [])
    meta.tags = existants + [t for t in tags_profil if t not in existants]

    scan.profil_id = profil.id
    scan.statut = "range"
    scan.range_at = quand
    scan.erreur = None
    await db.flush()
    log.info("Scan rangé", scan=str(scan.id), doc=str(doc.id), de=ancien, vers=nouveau, profil=profil.nom)
    return {"document_id": str(doc.id), "chemin": nouveau, "nom": doc.nom, "tags": meta.tags}


# ─── Boîte à scans ─────────────────────────────────────────────────────────────────────

def boite_prefixe() -> str:
    from services import runtime_config
    return (runtime_config.effective("scan_boite_chemin") or "").strip().replace("\\", "/").rstrip("/")


async def rattacher_nouveaux(db: AsyncSession) -> int:
    """
    Les documents arrivés sous le dossier de la boîte (par synchro, watcher ou dépôt) qui
    n'ont pas encore de ligne `scans` en reçoivent une. Idempotent, appelé à l'affichage.
    """
    prefixe = boite_prefixe()
    if not prefixe:
        return 0
    deja = select(Scan.document_id).where(Scan.document_id.is_not(None))
    docs = (await db.execute(
        # ILIKE : SMB ne distingue pas la casse (« scan » = « Scan ») mais le chemin enregistré
        # reprend le nom du partage tel qu'il a été indexé ; une différence de casse dans la
        # configuration de la boîte donnerait une boîte silencieusement vide.
        select(Document).where(Document.chemin.ilike(prefixe + "/%"), Document.id.not_in(deja))
    )).scalars().all()
    for d in docs:
        statut = "indexe" if d.statut in ("extracted", "enriched", "catalogued") else ("erreur" if d.statut == "error" else "recu")
        db.add(Scan(document_id=d.id, statut=statut, origine="boite", nb_pages=0))
    if docs:
        await db.flush()
        log.info("Boîte à scans — nouveaux rattachés", nb=len(docs), prefixe=prefixe)
    return len(docs)


async def lister_boite(db: AsyncSession, tout: bool = False, limite: int = 200) -> list[dict]:
    """Les scans (non rangés par défaut), avec leur document et une proposition de profil."""
    stmt = select(Scan).order_by(Scan.created_at.desc()).limit(limite)
    if not tout:
        stmt = stmt.where(Scan.statut != "range")
    scans = (await db.execute(stmt)).scalars().all()
    profils = (await db.execute(select(ScanProfil).where(ScanProfil.actif.is_(True)).order_by(ScanProfil.position))).scalars().all()
    ids = [s.document_id for s in scans if s.document_id]
    docs: dict = {}
    metas: dict = {}
    if ids:
        for d in (await db.execute(select(Document).where(Document.id.in_(ids)))).scalars().all():
            docs[d.id] = d
        for m in (await db.execute(select(MetadonneeIA).where(MetadonneeIA.document_id.in_(ids)))).scalars().all():
            metas[m.document_id] = m
    resultat = []
    for s in scans:
        d = docs.get(s.document_id)
        m = metas.get(s.document_id) if d else None
        proposition = None
        if d and s.statut in ("indexe", "recu") and not s.profil_id:
            proposition = proposer_profil(profils, categorie=m.categorie if m else None, sous_categorie=m.sous_categorie if m else None,
                                          tags=(m.tags if m else None), nom=d.nom, texte=d.texte_extrait)
        resultat.append(serialiser(s, d, m, proposition))
    return resultat


def serialiser(s: Scan, d: Document | None = None, m: MetadonneeIA | None = None, proposition: dict | None = None) -> dict:
    return {
        "id": str(s.id), "statut": s.statut, "origine": s.origine, "nb_pages": s.nb_pages or 0,
        "erreur": s.erreur, "reglages": s.reglages or {},
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "range_at": s.range_at.isoformat() if s.range_at else None,
        "profil_id": str(s.profil_id) if s.profil_id else None,
        "scanner_id": str(s.scanner_id) if s.scanner_id else None,
        "document": None if not d else {
            "id": str(d.id), "nom": d.nom, "chemin": d.chemin, "statut": d.statut,
            "categorie": m.categorie if m else None, "tags": (m.tags or []) if m else [],
            "resume": (m.resume or "")[:300] if m else "",
        },
        "proposition": proposition,
    }


# ─── Pages en attente (vitre) ──────────────────────────────────────────────────────────

def dossier_scans() -> Path:
    return Path(get_settings().storage_uploads) / "scans"


def dossier_session(scan_id: uuid.UUID | str) -> Path:
    return dossier_scans() / "sessions" / str(scan_id)


def pages_session(scan_id: uuid.UUID | str) -> list[Path]:
    d = dossier_session(scan_id)
    if not d.exists():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.name.startswith("page_"))


def enregistrer_pages(scan_id: uuid.UUID | str, documents: list, depuis: int = 0) -> list[Path]:
    """Écrit les documents reçus du scanner dans la session, numérotés à la suite."""
    d = dossier_session(scan_id)
    d.mkdir(parents=True, exist_ok=True)
    ecrits = []
    for i, doc in enumerate(documents, start=depuis + 1):
        ext = ".pdf" if "pdf" in (doc.content_type or "") else (".png" if "png" in (doc.content_type or "") else ".jpg")
        p = d / f"page_{i:03d}{ext}"
        p.write_bytes(doc.data)
        ecrits.append(p)
    return ecrits


def type_mime(p: Path) -> str:
    return {"pdf": "application/pdf", "png": "image/png"}.get(p.suffix.lstrip(".").lower(), "image/jpeg")


def nettoyer_session(scan_id: uuid.UUID | str) -> None:
    shutil.rmtree(dossier_session(scan_id), ignore_errors=True)
