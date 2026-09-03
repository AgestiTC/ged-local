"""
Router Dossiers thématiques — /api/dossiers
===========================================
Veille documentaire par sujet : un **dossier** regroupe des **ressources externes**
(podcasts, chaînes, documentaires, livres, articles, études, associations) décrites
par leur URL, leur type et une note expliquant ce qu'elles apportent.

Un dossier peut être créé à vide, ou installé depuis un **seed** livré avec
l'application (`POST /dossiers/seed/{cle}`, idempotent — voir `services/dossier_seed`).

Le dossier est adressable par UUID **ou par slug** : `/dossiers/devenir-parent`
fonctionne comme `/dossiers/<uuid>`, ce qui rend les URLs du front lisibles.
"""

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.dossier import DossierThematique, Ressource
from models.flux_rss import FluxRss, VeilleItem
from services.dossier_seed import SEEDS, installer_seed, seed_nb_ressources, _cle_ressource
from services.dossier_import import parser_ressources
from services.dossier_resume import resumer_ressource
from services.rss_service import rafraichir_dossier

log = get_logger(__name__)
router = APIRouter()

# Liste de référence des types — sert au front (filtres, icônes) et documente le modèle.
# Volontairement sans contrainte CHECK en base : ajouter un type ne demande pas de migration.
TYPES_RESSOURCE = [
    "podcast", "chaine", "video", "documentaire", "emission", "film", "serie",
    "livre", "bd", "article", "etude", "rapport", "association", "prompt",
]


class DossierIn(BaseModel):
    titre: str = Field(min_length=1)
    slug: str | None = None          # dérivé du titre si absent
    description: str | None = None
    parent: str | None = None        # UUID ou slug du dossier parent (→ sous-dossier). null = racine.


class DossierPatch(BaseModel):
    titre: str | None = Field(default=None, min_length=1)
    description: str | None = None


class RessourceIn(BaseModel):
    titre: str = Field(min_length=1)
    auteur: str | None = None
    type: str = "article"
    url: str | None = None
    langue: str = "fr"
    groupe: str | None = None
    note: str | None = None
    contenu: str | None = None
    tags: list[str] = Field(default_factory=list)
    favori: bool = False
    active: bool = True


class RessourcePatch(BaseModel):
    titre: str | None = Field(default=None, min_length=1)
    auteur: str | None = None
    type: str | None = None
    url: str | None = None
    langue: str | None = None
    groupe: str | None = None
    note: str | None = None
    contenu: str | None = None
    tags: list[str] | None = None
    favori: bool | None = None
    active: bool | None = None
    position: int | None = None


def _slugifier(titre: str) -> str:
    """Slug ASCII-safe à partir d'un titre (accents retirés, espaces → tirets)."""
    import unicodedata
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFD", titre) if unicodedata.category(c) != "Mn"
    )
    slug = re.sub(r"[^a-z0-9]+", "-", sans_accents.lower()).strip("-")
    return slug or "dossier"


def _resume_dossier(d: DossierThematique, nb: int = 0, nb_sous: int = 0) -> dict:
    return {
        "id": str(d.id), "titre": d.titre, "slug": d.slug,
        "description": d.description, "origine": d.origine,
        "parent_id": str(d.parent_id) if d.parent_id else None,
        "nb_ressources": nb,
        "nb_sous_dossiers": nb_sous,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _serialiser_ressource(r: Ressource) -> dict:
    return {
        "id": str(r.id), "dossier_id": str(r.dossier_id),
        "titre": r.titre, "auteur": r.auteur, "type": r.type, "url": r.url,
        "langue": r.langue, "groupe": r.groupe, "note": r.note, "contenu": r.contenu,
        "tags": r.tags or [], "position": r.position,
        "favori": r.favori, "active": r.active,
    }


async def _get_dossier(db: AsyncSession, ref: str) -> DossierThematique:
    """Résout un dossier par UUID **ou** par slug. 404 si introuvable."""
    d = None
    try:
        d = await db.get(DossierThematique, uuid.UUID(ref))
    except ValueError:
        d = (await db.execute(
            select(DossierThematique).where(DossierThematique.slug == ref)
        )).scalar_one_or_none()
    if not d:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    return d


async def _get_ressource(db: AsyncSession, rid: str) -> Ressource:
    try:
        r = await db.get(Ressource, uuid.UUID(rid))
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")
    if not r:
        raise HTTPException(status_code=404, detail="Ressource introuvable")
    return r


# ─── Métadonnées ──────────────────────────────────────────────────────────────

@router.get("/dossiers/types", tags=["Dossiers"])
async def types_disponibles() -> dict:
    """Types de ressource reconnus + seeds installables (alimente les filtres du front)."""
    return {
        "types": TYPES_RESSOURCE,
        "seeds": [{"cle": k, "titre": v["titre"], "nb": seed_nb_ressources(v),
                   "hierarchique": bool(v.get("sous_dossiers"))} for k, v in SEEDS.items()],
    }


# ─── Dossiers ─────────────────────────────────────────────────────────────────

async def _comptes_ressources(db: AsyncSession) -> dict:
    """{dossier_id: nb ressources actives} en un seul GROUP BY."""
    return dict((await db.execute(
        select(Ressource.dossier_id, func.count())
        .where(Ressource.active.is_(True))
        .group_by(Ressource.dossier_id)
    )).all())


async def _comptes_sous_dossiers(db: AsyncSession) -> dict:
    """{parent_id: nb sous-dossiers} en un seul GROUP BY."""
    return dict((await db.execute(
        select(DossierThematique.parent_id, func.count())
        .where(DossierThematique.parent_id.is_not(None))
        .group_by(DossierThematique.parent_id)
    )).all())


@router.get("/dossiers", tags=["Dossiers"])
async def lister(db: AsyncSession = Depends(get_db)) -> dict:
    """Liste des dossiers RACINES (les sous-dossiers s'ouvrent depuis leur parent),
    chacun avec son nombre de ressources actives et de sous-dossiers."""
    dossiers = (await db.execute(
        select(DossierThematique)
        .where(DossierThematique.parent_id.is_(None))
        .order_by(DossierThematique.created_at.desc())
    )).scalars().all()

    comptes = await _comptes_ressources(db)
    sous = await _comptes_sous_dossiers(db)
    return {"dossiers": [_resume_dossier(d, comptes.get(d.id, 0), sous.get(d.id, 0)) for d in dossiers]}


@router.post("/dossiers", status_code=201, tags=["Dossiers"])
async def creer(body: DossierIn, db: AsyncSession = Depends(get_db)) -> dict:
    slug = _slugifier(body.slug or body.titre)
    # Sous-dossier : on résout le parent (UUID ou slug) et on place la nouvelle entrée en fin de fratrie.
    parent_id = None
    position = 0
    if body.parent:
        parent = await _get_dossier(db, body.parent)
        parent_id = parent.id
        position = ((await db.execute(
            select(func.max(DossierThematique.position)).where(DossierThematique.parent_id == parent_id)
        )).scalar() or 0) + 1
    d = DossierThematique(titre=body.titre, slug=slug, description=body.description,
                          origine="manuel", parent_id=parent_id, position=position)
    db.add(d)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Un dossier utilise déjà le slug « {slug} »")
    await db.refresh(d)
    log.info("Dossier thématique créé", titre=body.titre, slug=slug, sous_dossier=bool(parent_id))
    return _resume_dossier(d)


@router.get("/dossiers/{ref}", tags=["Dossiers"])
async def detail(ref: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Dossier + toutes ses ressources, ordonnées par position.

    Le filtrage (type, langue, tag, recherche) se fait côté client : un dossier de
    veille reste de l'ordre de la centaine d'entrées, inutile de payer un aller-retour
    réseau à chaque clic sur un filtre.
    """
    d = await _get_dossier(db, ref)
    ressources = (await db.execute(
        select(Ressource)
        .where(Ressource.dossier_id == d.id)
        .order_by(Ressource.position, Ressource.titre)
    )).scalars().all()

    # Ordre d'apparition des groupes = celui de la liste (stable, pas alphabétique) :
    # il porte une progression voulue, pas un classement.
    groupes: list[str] = []
    for r in ressources:
        g = r.groupe or "Sans groupe"
        if g not in groupes:
            groupes.append(g)

    # Fil d'Ariane : le parent (le cas échéant), pour remonter d'un sous-dossier.
    parent = None
    if d.parent_id:
        p = await db.get(DossierThematique, d.parent_id)
        if p:
            parent = {"id": str(p.id), "titre": p.titre, "slug": p.slug}

    # Sous-dossiers (enfants directs), ordonnés par position → chacun avec son compte de ressources.
    enfants = (await db.execute(
        select(DossierThematique)
        .where(DossierThematique.parent_id == d.id)
        .order_by(DossierThematique.position, DossierThematique.titre)
    )).scalars().all()
    comptes = await _comptes_ressources(db) if enfants else {}
    sous_comptes = await _comptes_sous_dossiers(db) if enfants else {}

    return {
        **_resume_dossier(d, sum(1 for r in ressources if r.active), len(enfants)),
        "parent": parent,
        "sous_dossiers": [_resume_dossier(e, comptes.get(e.id, 0), sous_comptes.get(e.id, 0)) for e in enfants],
        "groupes": groupes,
        "ressources": [_serialiser_ressource(r) for r in ressources],
    }


@router.patch("/dossiers/{ref}", tags=["Dossiers"])
async def modifier(ref: str, body: DossierPatch, db: AsyncSession = Depends(get_db)) -> dict:
    d = await _get_dossier(db, ref)
    for champ, valeur in body.model_dump(exclude_unset=True).items():
        setattr(d, champ, valeur)
    await db.commit()
    await db.refresh(d)
    return _resume_dossier(d)


@router.delete("/dossiers/{ref}", tags=["Dossiers"])
async def supprimer(ref: str, db: AsyncSession = Depends(get_db)) -> dict:
    d = await _get_dossier(db, ref)
    titre = d.titre
    # Compte des sous-dossiers (supprimés en cascade par la FK) pour informer l'utilisateur.
    nb_sous = (await db.execute(
        select(func.count()).select_from(DossierThematique).where(DossierThematique.parent_id == d.id)
    )).scalar() or 0
    # Suppression explicite des ressources du dossier lui-même (l'ORM ne connaît pas le CASCADE) ;
    # les sous-dossiers et LEURS ressources partent via `ON DELETE CASCADE` au `db.delete(d)`.
    await db.execute(delete(Ressource).where(Ressource.dossier_id == d.id))
    await db.delete(d)
    await db.commit()
    log.info("Dossier thématique supprimé", titre=titre, sous_dossiers_supprimes=nb_sous)
    suffixe = f" (et ses {nb_sous} sous-dossier{'s' if nb_sous > 1 else ''})" if nb_sous else ""
    return {"message": f"Dossier « {titre} » supprimé{suffixe}"}


# ─── Ressources ───────────────────────────────────────────────────────────────

@router.post("/dossiers/{ref}/ressources", status_code=201, tags=["Dossiers"])
async def ajouter_ressource(ref: str, body: RessourceIn, db: AsyncSession = Depends(get_db)) -> dict:
    d = await _get_dossier(db, ref)
    # Nouvelle entrée en fin de son groupe.
    position = ((await db.execute(
        select(func.max(Ressource.position)).where(Ressource.dossier_id == d.id)
    )).scalar() or 0) + 1

    r = Ressource(dossier_id=d.id, position=position, **body.model_dump())
    db.add(r)
    await db.commit()
    await db.refresh(r)
    log.info("Ressource ajoutée", dossier=d.slug, titre=body.titre, type=body.type)
    return _serialiser_ressource(r)


@router.patch("/dossiers/ressources/{rid}", tags=["Dossiers"])
async def modifier_ressource(rid: str, body: RessourcePatch, db: AsyncSession = Depends(get_db)) -> dict:
    r = await _get_ressource(db, rid)
    for champ, valeur in body.model_dump(exclude_unset=True).items():
        setattr(r, champ, valeur)
    await db.commit()
    await db.refresh(r)
    return _serialiser_ressource(r)


@router.post("/dossiers/ressources/{rid}/resume", tags=["Dossiers"])
async def resumer(rid: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Propose un résumé (IA LOCALE) pour la ressource — ne l'enregistre PAS.
    L'utilisateur décide ensuite de le placer (ou non) dans la note."""
    r = await _get_ressource(db, rid)
    try:
        resume = await resumer_ressource(r)
    except Exception as e:  # noqa: BLE001 — IA locale peut être injoignable
        raise HTTPException(status_code=502, detail=f"Résumé impossible (IA locale ?) : {e}")
    return {"resume": resume}


@router.delete("/dossiers/ressources/{rid}", tags=["Dossiers"])
async def supprimer_ressource(rid: str, db: AsyncSession = Depends(get_db)) -> dict:
    r = await _get_ressource(db, rid)
    titre = r.titre
    await db.delete(r)
    await db.commit()
    return {"message": f"Ressource « {titre} » supprimée"}


# ─── Import IA (coller une réponse d'IA web → ressources structurées) ──────────

class ImportParse(BaseModel):
    texte: str = Field(min_length=1, description="Réponse d'IA web collée (tableau markdown…)")


class ImportRessources(BaseModel):
    ressources: list[RessourceIn] = Field(min_length=1)


@router.post("/dossiers/importer/parse", tags=["Dossiers"])
async def importer_parse(body: ImportParse) -> dict:
    """Analyse le texte collé (via l'IA LOCALE) → APERÇU de ressources. Ne crée rien en base.
    L'IA locale ne fait qu'EXTRAIRE (jamais inventer, surtout les URL)."""
    try:
        ressources = await parser_ressources(body.texte)
    except Exception as e:  # noqa: BLE001 — l'IA locale peut être injoignable
        raise HTTPException(status_code=502, detail=f"Analyse impossible (IA locale ?) : {e}")
    return {"ressources": ressources, "nb": len(ressources)}


@router.post("/dossiers/{ref}/ressources/import", status_code=201, tags=["Dossiers"])
async def importer_ressources(ref: str, body: ImportRessources, db: AsyncSession = Depends(get_db)) -> dict:
    """Ajoute EN MASSE les ressources validées dans le dossier. Idempotent : les entrées dont
    l'URL (sinon le titre) existe déjà sont ignorées (pas de doublon)."""
    d = await _get_dossier(db, ref)
    existantes = {
        _cle_ressource(r.titre, r.url)
        for r in (await db.execute(select(Ressource).where(Ressource.dossier_id == d.id))).scalars().all()
    }
    position = ((await db.execute(
        select(func.max(Ressource.position)).where(Ressource.dossier_id == d.id)
    )).scalar() or 0)
    ajoutees = 0
    for item in body.ressources:
        if _cle_ressource(item.titre, item.url) in existantes:
            continue
        position += 1
        db.add(Ressource(dossier_id=d.id, position=position, **item.model_dump()))
        existantes.add(_cle_ressource(item.titre, item.url))
        ajoutees += 1
    await db.commit()
    log.info("Import IA — ressources ajoutées", dossier=d.slug, ajoutees=ajoutees, recus=len(body.ressources))
    return {"ajoutees": ajoutees, "ignorees": len(body.ressources) - ajoutees}


# ─── Seeds ────────────────────────────────────────────────────────────────────

@router.post("/dossiers/seed/{cle}", tags=["Dossiers"])
async def installer(cle: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Installe le dossier pré-rempli `cle` (ex. `devenir-parent`).

    Idempotent : relancé sur un dossier existant, n'ajoute que les ressources absentes.
    Les entrées modifiées ou supprimées à la main ne sont pas restaurées.
    """
    try:
        return await installer_seed(db, cle)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Seed « {cle} » inconnu")


# ─── Veille RSS ────────────────────────────────────────────────────────────────
# Un dossier peut s'abonner à des flux RSS/Atom. Le téléchargement n'est JAMAIS
# automatique : il se déclenche sur action explicite (POST …/veille/refresh) —
# cohérent avec la règle « 100 % local, sortie réseau confirmée ».

class FluxIn(BaseModel):
    url: str = Field(min_length=4, description="URL du flux RSS/Atom")
    titre: str | None = None


class ItemLu(BaseModel):
    lu: bool = True


class PromouvoirIn(BaseModel):
    type: str = "article"
    groupe: str | None = None


def _serialiser_flux(f: FluxRss, non_lus: int = 0) -> dict:
    return {
        "id": str(f.id), "url": f.url, "titre": f.titre, "actif": f.actif,
        "dernier_fetch": f.dernier_fetch.isoformat() if f.dernier_fetch else None,
        "dernier_etat": f.dernier_etat, "non_lus": non_lus,
    }


def _serialiser_item(it: VeilleItem, source: str | None = None) -> dict:
    return {
        "id": str(it.id), "flux_id": str(it.flux_id), "source": source,
        "titre": it.titre, "url": it.url, "auteur": it.auteur, "resume": it.resume,
        "date_pub": it.date_pub.isoformat() if it.date_pub else None,
        "lu": it.lu, "promu": it.promu,
    }


async def _get_flux(db: AsyncSession, fid: str) -> FluxRss:
    try:
        f = await db.get(FluxRss, uuid.UUID(fid))
    except ValueError:
        raise HTTPException(status_code=400, detail="ID de flux invalide")
    if not f:
        raise HTTPException(status_code=404, detail="Flux introuvable")
    return f


async def _get_item(db: AsyncSession, item_id: str) -> VeilleItem:
    try:
        it = await db.get(VeilleItem, uuid.UUID(item_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="ID d'item invalide")
    if not it:
        raise HTTPException(status_code=404, detail="Item de veille introuvable")
    return it


@router.get("/dossiers/{ref}/flux", tags=["Dossiers"])
async def lister_flux(ref: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Flux abonnés au dossier + nombre d'items non lus par flux."""
    d = await _get_dossier(db, ref)
    flux = (await db.execute(
        select(FluxRss).where(FluxRss.dossier_id == d.id).order_by(FluxRss.created_at)
    )).scalars().all()
    # {flux_id: non_lus} en un seul GROUP BY (items non lus et non promus).
    non_lus = dict((await db.execute(
        select(VeilleItem.flux_id, func.count())
        .where(VeilleItem.dossier_id == d.id, VeilleItem.lu.is_(False), VeilleItem.promu.is_(False))
        .group_by(VeilleItem.flux_id)
    )).all())
    total = sum(non_lus.values())
    return {"flux": [_serialiser_flux(f, non_lus.get(f.id, 0)) for f in flux], "non_lus": total}


@router.post("/dossiers/{ref}/flux", status_code=201, tags=["Dossiers"])
async def ajouter_flux(ref: str, body: FluxIn, db: AsyncSession = Depends(get_db)) -> dict:
    """Abonne le dossier à un flux RSS/Atom. Le contenu n'est PAS téléchargé ici
    (aucune sortie réseau) — l'utilisateur lance ensuite « Rafraîchir la veille »."""
    d = await _get_dossier(db, ref)
    url = body.url.strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="L'URL doit commencer par http:// ou https://")
    f = FluxRss(dossier_id=d.id, url=url, titre=(body.titre or None))
    db.add(f)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Ce flux est déjà abonné à ce dossier")
    await db.refresh(f)
    log.info("Flux RSS abonné", dossier=d.slug, url=url)
    return _serialiser_flux(f)


@router.delete("/dossiers/flux/{fid}", tags=["Dossiers"])
async def supprimer_flux(fid: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Désabonne un flux (ses items de veille partent en cascade)."""
    f = await _get_flux(db, fid)
    url = f.url
    await db.delete(f)
    await db.commit()
    return {"message": f"Flux « {f.titre or url} » désabonné"}


@router.post("/dossiers/{ref}/veille/refresh", tags=["Dossiers"])
async def rafraichir_veille(ref: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    ⚠️ SORTIE RÉSEAU (action explicite de l'utilisateur) : télécharge tous les flux
    actifs du dossier et enregistre les nouveautés. Robuste flux par flux.
    """
    d = await _get_dossier(db, ref)
    return await rafraichir_dossier(db, d.id)


@router.get("/dossiers/{ref}/veille", tags=["Dossiers"])
async def lister_veille(ref: str, non_lus: bool = False, limit: int = 100,
                        db: AsyncSession = Depends(get_db)) -> dict:
    """Items de veille du dossier (récents d'abord). `non_lus=true` → seulement à lire."""
    d = await _get_dossier(db, ref)
    q = (select(VeilleItem, FluxRss.titre)
         .join(FluxRss, VeilleItem.flux_id == FluxRss.id)
         .where(VeilleItem.dossier_id == d.id, VeilleItem.promu.is_(False)))
    if non_lus:
        q = q.where(VeilleItem.lu.is_(False))
    q = q.order_by(VeilleItem.date_pub.desc().nulls_last(), VeilleItem.created_at.desc()).limit(min(limit, 300))
    lignes = (await db.execute(q)).all()
    return {"items": [_serialiser_item(it, source) for it, source in lignes], "nb": len(lignes)}


@router.post("/dossiers/veille/{item_id}/lu", tags=["Dossiers"])
async def marquer_item_lu(item_id: str, body: ItemLu, db: AsyncSession = Depends(get_db)) -> dict:
    it = await _get_item(db, item_id)
    it.lu = body.lu
    await db.commit()
    return {"id": item_id, "lu": it.lu}


@router.post("/dossiers/{ref}/veille/lu-tout", tags=["Dossiers"])
async def marquer_tout_lu(ref: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Marque tous les items non lus du dossier comme lus."""
    from sqlalchemy import update
    d = await _get_dossier(db, ref)
    res = await db.execute(
        update(VeilleItem).where(VeilleItem.dossier_id == d.id, VeilleItem.lu.is_(False))
        .values(lu=True)
    )
    await db.commit()
    return {"marques": res.rowcount or 0}


@router.delete("/dossiers/veille/{item_id}", tags=["Dossiers"])
async def supprimer_item(item_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    it = await _get_item(db, item_id)
    await db.delete(it)
    await db.commit()
    return {"message": "Item retiré de la veille"}


@router.post("/dossiers/veille/{item_id}/promouvoir", status_code=201, tags=["Dossiers"])
async def promouvoir_item(item_id: str, body: PromouvoirIn, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Transforme un item de veille en RESSOURCE permanente du dossier, puis marque l'item
    comme promu (il quitte la liste de veille). Idempotent : si une ressource de même
    URL/titre existe déjà, on ne duplique pas — l'item est simplement marqué promu.
    """
    it = await _get_item(db, item_id)
    dossier_id = it.dossier_id

    existantes = {
        _cle_ressource(r.titre, r.url)
        for r in (await db.execute(
            select(Ressource).where(Ressource.dossier_id == dossier_id)
        )).scalars().all()
    }
    deja = _cle_ressource(it.titre, it.url) in existantes
    if not deja:
        position = ((await db.execute(
            select(func.max(Ressource.position)).where(Ressource.dossier_id == dossier_id)
        )).scalar() or 0) + 1
        db.add(Ressource(
            dossier_id=dossier_id, position=position, titre=it.titre, url=it.url,
            type=(body.type or "article"), auteur=it.auteur, note=it.resume,
            groupe=body.groupe, tags=[], langue="fr",
        ))
    it.promu = True
    it.lu = True
    await db.commit()
    log.info("Item de veille promu en ressource", item=item_id, deja_present=deja)
    return {"promu": True, "deja_present": deja}
