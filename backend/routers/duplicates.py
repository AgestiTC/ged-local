"""
Router Doublons — /api/duplicates
==================================
Détection des fichiers en double sur le volume documents + mise en quarantaine
(déplacement vers DOUBLON-MATOTEQUE), avec validation côté UI avant action.

Endpoints :
  GET  /duplicates              → groupes de fichiers en double (scan disque)
  POST /duplicates/quarantine   → déplace les fichiers choisis vers la quarantaine
"""

from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from logger import get_logger
from models.document import Document
from services import duplicate_service

log = get_logger(__name__)
settings = get_settings()
router = APIRouter()

# Plafond de documents comparés en mode IA (borne le coût du self-join vectoriel).
_IA_CAP = 1200


def _source_label(chemin: str | None) -> str:
    """Libellé lisible de la source d'un fichier (partage SMB ou local)."""
    if not chemin:
        return "?"
    if chemin.startswith("smb://"):
        parts = chemin[len("smb://"):].split("/", 2)
        host = parts[0] if parts else "?"
        share = parts[1] if len(parts) > 1 else ""
        return f"\\\\{host}\\{share}" if share else f"\\\\{host}"
    return "local"


def _fichier_dto(d: Document, garder: bool) -> dict:
    return {
        "id": str(d.id), "nom": d.nom, "chemin": d.chemin,
        "source": _source_label(d.chemin), "taille_octets": d.taille_octets or 0,
        "garder": garder,
    }


class QuarantineRequest(BaseModel):
    """Liste des chemins absolus à mettre en quarantaine."""
    chemins: list[str] = Field(default_factory=list, min_length=1)


@router.get("/duplicates", tags=["Doublons"])
async def list_duplicates() -> dict:
    """
    Scanne le volume des documents et retourne les groupes de fichiers en double
    (même contenu). Ne modifie rien. Peut prendre quelques secondes selon le volume.
    """
    root = Path(settings.documents_root)
    groups = duplicate_service.find_duplicates(root, settings.duplicates_dirname)
    nb_fichiers = sum(len(g["fichiers"]) for g in groups)
    octets_recuperables = sum(
        g["taille_octets"] * (len(g["fichiers"]) - 1) for g in groups
    )
    return {
        "groupes": groups,
        "nb_groupes": len(groups),
        "nb_fichiers": nb_fichiers,
        "octets_recuperables": octets_recuperables,
        "dossier_quarantaine": settings.duplicates_dirname,
    }


@router.get("/duplicates/blurry", tags=["Doublons"])
async def list_blurry(
    seuil: float = Query(default=100.0, ge=0, le=5000, description="Netteté minimale (variance Laplacien) ; en dessous = flou"),
    limite: int = Query(default=500, ge=1, le=5000),
) -> dict:
    """
    Repère les **images floues** du volume (faible variance du Laplacien). Ne modifie rien —
    les fichiers choisis peuvent ensuite être mis en quarantaine via `/duplicates/quarantine`.
    Peut prendre du temps (lit chaque image). Exécuté en thread pour ne pas geler l'API.
    """
    import asyncio
    root = Path(settings.documents_root)
    flous = await asyncio.to_thread(
        duplicate_service.find_blurry_images, root, settings.duplicates_dirname, seuil, limite
    )
    return {"images": flous, "nb": len(flous), "seuil": seuil,
            "dossier_quarantaine": settings.duplicates_dirname}


@router.get("/duplicates/indexed", tags=["Doublons"])
async def duplicates_indexed(
    prefixe: str | None = Query(default=None, description="Limiter à un préfixe de chemin (dossier)"),
    mode: str = Query(default="both", description="hash | ia | both"),
    seuil: float = Query(default=0.92, ge=0.5, le=1.0, description="Seuil de similarité IA (cosinus)"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Doublons parmi les fichiers **INDEXÉS** (pas le disque) : contenu identique
    (hash SHA-256) et/ou **quasi-doublons sémantiques** (embeddings). Périmètre optionnel
    par préfixe de chemin (dossier). Ne modifie rien — l'action « corbeille » se fait via
    `POST /corbeille/envoyer/{id}` sur les fichiers choisis.
    """
    like = (prefixe.strip().rstrip("/") + "%") if prefixe and prefixe.strip() else None
    groupes: list[dict] = []
    vus: set = set()          # docs déjà en doublon exact → exclus de l'IA
    note: str | None = None

    # ── 1) Doublons EXACTS (hash SHA-256) ──
    if mode in ("hash", "both"):
        stmt = select(Document).where(Document.hash_sha256.isnot(None))
        if like:
            stmt = stmt.where(Document.chemin.like(like))
        docs = (await db.execute(stmt)).scalars().all()
        par_hash: dict[str, list[Document]] = defaultdict(list)
        for d in docs:
            par_hash[d.hash_sha256].append(d)
        for h, lst in par_hash.items():
            if len(lst) < 2:
                continue
            lst.sort(key=lambda x: len(x.chemin or ""))   # on garde le chemin le plus court
            for d in lst:
                vus.add(d.id)
            groupes.append({
                "type": "hash", "cle": h[:12], "score": 1.0,
                "fichiers": [_fichier_dto(d, garder=(i == 0)) for i, d in enumerate(lst)],
            })

    # ── 2) Quasi-doublons SÉMANTIQUES (embeddings, cosinus ≥ seuil) ──
    if mode in ("ia", "both"):
        maxdist = 1.0 - seuil
        params: dict = {"maxdist": maxdist}
        scope = ""
        if like:
            scope = "AND d.chemin LIKE :like"
            params["like"] = like
        else:
            note = "IA sur tout l'index borné à 1200 fichiers — choisis un dossier pour une analyse complète."
        sql = text(f"""
            WITH rep AS (
                SELECT DISTINCT ON (e.document_id) e.document_id AS id, e.embedding AS emb
                FROM embeddings e JOIN documents d ON d.id = e.document_id
                WHERE e.chunk_index = 0 {scope}
                ORDER BY e.document_id, e.chunk_index
                LIMIT {_IA_CAP}
            )
            SELECT a.id AS a, b.id AS b, 1 - (a.emb <=> b.emb) AS sim
            FROM rep a JOIN rep b ON a.id < b.id
            WHERE (a.emb <=> b.emb) <= :maxdist
            ORDER BY sim DESC
            LIMIT 3000
        """)
        rows = (await db.execute(sql, params)).all()
        adj: dict = defaultdict(set)
        sims: dict = {}
        for a, b, sim in rows:
            if a in vus or b in vus:
                continue
            adj[a].add(b); adj[b].add(a)
            sims[(a, b)] = sims[(b, a)] = sim
        seen_ia: set = set()
        for start in list(adj.keys()):
            if start in seen_ia:
                continue
            comp: list = []
            stack = [start]
            while stack:
                n = stack.pop()
                if n in seen_ia:
                    continue
                seen_ia.add(n); comp.append(n)
                stack.extend(adj[n] - seen_ia)
            if len(comp) < 2:
                continue
            docs_comp = (await db.execute(select(Document).where(Document.id.in_(comp)))).scalars().all()
            docs_comp.sort(key=lambda x: len(x.chemin or ""))
            score = min((sims.get((comp[0], o), 1.0) for o in comp[1:]), default=1.0)
            groupes.append({
                "type": "ia", "cle": f"sim-{len(groupes)}", "score": round(float(score), 3),
                "fichiers": [_fichier_dto(d, garder=(i == 0)) for i, d in enumerate(docs_comp)],
            })

    nb_fichiers = sum(len(g["fichiers"]) for g in groupes)
    octets_recuperables = sum(f["taille_octets"] for g in groupes for f in g["fichiers"] if not f["garder"])
    return {
        "groupes": groupes, "nb_groupes": len(groupes), "nb_fichiers": nb_fichiers,
        "octets_recuperables": octets_recuperables, "note": note,
    }


@router.post("/duplicates/quarantine", tags=["Doublons"])
async def quarantine_duplicates(
    body: QuarantineRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Déplace les fichiers sélectionnés vers DOUBLON-MATOTEQUE (jamais de suppression
    définitive) et retire les entrées correspondantes de l'index Matothèque.
    """
    root = Path(settings.documents_root)
    result = duplicate_service.quarantine(body.chemins, root, settings.duplicates_dirname)

    # Nettoie l'index : retire les documents dont le fichier vient d'être déplacé
    index_retires = 0
    for moved in result["deplaces"]:
        chemin = moved["chemin"]
        docs = (
            await db.execute(select(Document).where(Document.chemin == chemin))
        ).scalars().all()
        for doc in docs:
            await db.delete(doc)
            index_retires += 1
    if index_retires:
        await db.flush()

    log.info(
        "Quarantaine doublons terminée",
        deplaces=len(result["deplaces"]),
        erreurs=len(result["erreurs"]),
        index_retires=index_retires,
    )
    return {
        "deplaces": result["deplaces"],
        "erreurs": result["erreurs"],
        "nb_deplaces": len(result["deplaces"]),
        "nb_erreurs": len(result["erreurs"]),
        "index_retires": index_retires,
        "dossier_quarantaine": settings.duplicates_dirname,
    }
