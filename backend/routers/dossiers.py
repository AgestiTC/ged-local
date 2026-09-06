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

import calendar
import re
import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.dossier import DossierThematique, Ressource
from models.flux_rss import FluxRss, VeilleItem
from models.jalon import Jalon
from services.dossier_seed import SEEDS, installer_seed, seed_nb_ressources, _cle_ressource
from services.dossier_import import parser_ressources
from services.dossier_resume import resumer_ressource
from services.jalon_seed import AVERTISSEMENT, CATEGORIES
from services.rss_service import rafraichir_dossier
from services.runtime_config import effective

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


class DeplacerIn(BaseModel):
    dossier: str = Field(description="UUID ou slug du dossier de destination")


@router.get("/dossiers/{ref}/cibles-deplacement", tags=["Dossiers"])
async def cibles_deplacement(ref: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Dossiers vers lesquels une ressource de `ref` peut être déplacée = toute la « famille »
    (le dossier racine + tous ses descendants), sauf `ref` lui-même. Chaque entrée porte sa
    profondeur pour un affichage indenté côté UI.
    """
    d = await _get_dossier(db, ref)
    # Remonter jusqu'à la racine de l'arbre.
    root = d
    while root.parent_id:
        parent = await db.get(DossierThematique, root.parent_id)
        if not parent:
            break
        root = parent
    # Table de petite taille : on charge tout et on reconstruit l'arbre en mémoire.
    tous = (await db.execute(select(DossierThematique))).scalars().all()
    enfants: dict = {}
    for x in tous:
        enfants.setdefault(x.parent_id, []).append(x)
    for lst in enfants.values():
        lst.sort(key=lambda e: (e.position, e.titre or ""))

    cibles: list[dict] = []

    def _descendre(noeud, profondeur: int) -> None:
        if noeud.id != d.id:   # on ne se propose pas soi-même comme destination
            cibles.append({"id": str(noeud.id), "titre": noeud.titre, "slug": noeud.slug,
                           "profondeur": profondeur})
        for enfant in enfants.get(noeud.id, []):
            _descendre(enfant, profondeur + 1)

    _descendre(root, 0)
    return {"cibles": cibles}


@router.post("/dossiers/ressources/{rid}/deplacer", tags=["Dossiers"])
async def deplacer_ressource(rid: str, body: DeplacerIn, db: AsyncSession = Depends(get_db)) -> dict:
    """Déplace une ressource vers un autre dossier (placée en fin de destination). Le groupe est
    conservé tel quel (libre à l'utilisateur de le réajuster ensuite)."""
    r = await _get_ressource(db, rid)
    cible = await _get_dossier(db, body.dossier)
    if r.dossier_id == cible.id:
        return _serialiser_ressource(r)
    position = ((await db.execute(
        select(func.max(Ressource.position)).where(Ressource.dossier_id == cible.id)
    )).scalar() or 0) + 1
    ancien = r.dossier_id
    r.dossier_id = cible.id
    r.position = position
    await db.commit()
    await db.refresh(r)
    log.info("Ressource déplacée", ressource=rid, de=str(ancien), vers=cible.slug)
    return _serialiser_ressource(r)


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
# ─── Rétroplanning (jalons) ───────────────────────────────────────────────────
# Le temps d'un dossier est repéré par un entier signé (`jalons.mois`) : négatif avant
# la date d'ancrage, positif après. Cf. `models/jalon`.

class JalonIn(BaseModel):
    mois: int = Field(..., ge=-12, le=216, description="Négatif = avant la date d'ancrage")
    titre: str = Field(..., min_length=1, max_length=300)
    detail: str | None = None
    categorie: str = "preparation"
    echeance: str | None = None
    url: str | None = None
    sa: int | None = Field(default=None, ge=0, le=45)
    obligatoire: bool = False


class JalonPatch(BaseModel):
    """Tout est optionnel : la même route sert à cocher un jalon et à le réécrire."""
    mois: int | None = Field(default=None, ge=-12, le=216)
    titre: str | None = Field(default=None, min_length=1, max_length=300)
    detail: str | None = None
    categorie: str | None = None
    echeance: str | None = None
    url: str | None = None
    sa: int | None = Field(default=None, ge=0, le=45)
    obligatoire: bool | None = None
    fait: bool | None = None
    note_perso: str | None = None


def _ajouter_mois(base: date, n: int) -> date:
    """
    `base` décalée de `n` mois calendaires, le jour étant ramené au dernier jour du mois
    quand il n'existe pas (31 janvier + 1 mois = 28 ou 29 février).

    On raisonne en mois calendaires et non en tranches de 30 jours : un planning qui
    affiche « mars » doit tomber sur mars, pas glisser d'un jour et demi par mois.
    """
    total = base.month - 1 + n
    annee = base.year + total // 12
    mois = total % 12 + 1
    jour = min(base.day, calendar.monthrange(annee, mois)[1])
    return date(annee, mois, jour)


def _libelle_mois(m: int) -> str:
    """Nom lisible d'un mois du planning. `m` négatif = mois de grossesse."""
    if m < 0:
        rang = 10 + m          # -9 → 1ᵉʳ mois de grossesse, -1 → 9ᵉ
        return f"{rang}{'ᵉʳ' if rang == 1 else 'ᵉ'} mois de grossesse"
    if m == 0:
        return "Naissance — 1ᵉʳ mois"
    if m == 1:
        return "1 mois"
    if m < 24:
        return f"{m} mois"
    annees, reste = divmod(m, 12)
    return f"{annees} ans" if reste == 0 else f"{annees} ans et {reste} mois"


def _serialiser_jalon(j: Jalon) -> dict:
    return {
        "id": str(j.id), "dossier_id": str(j.dossier_id),
        "mois": j.mois, "sa": j.sa, "titre": j.titre, "detail": j.detail,
        "categorie": j.categorie, "echeance": j.echeance, "url": j.url,
        "obligatoire": j.obligatoire, "position": j.position, "origine": j.origine,
        "fait": j.fait,
        "fait_le": j.fait_le.isoformat() if j.fait_le else None,
        "note_perso": j.note_perso,
    }


async def _get_jalon(db: AsyncSession, jid: str) -> Jalon:
    try:
        j = await db.get(Jalon, uuid.UUID(jid))
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")
    if not j:
        raise HTTPException(status_code=404, detail="Jalon introuvable")
    return j


@router.get("/dossiers/{ref}/planning", tags=["Dossiers"])
async def planning(ref: str, date_terme: str | None = None,
                   db: AsyncSession = Depends(get_db)) -> dict:
    """
    Rétroplanning du dossier, groupé par mois.

    La date d'ancrage vient du paramètre `date_terme` s'il est fourni, sinon de la
    configuration (`parents_date_terme`, saisie dans Paramètres › Dossiers — Parents).
    **Sans elle, le planning reste utilisable** : les mois s'affichent avec leur rang
    (« 5ᵉ mois de grossesse ») mais sans dates. C'est volontaire — un rétroplanning
    qui refuse de s'ouvrir tant qu'on n'a pas saisi une date ne sert à rien pour
    quelqu'un qui vient d'abord voir de quoi il retourne.
    """
    d = await _get_dossier(db, ref)

    brut = (date_terme or "").strip() or effective("parents_date_terme")
    ancre: date | None = None
    if brut:
        try:
            ancre = date.fromisoformat(brut.strip()[:10])
        except ValueError:
            # Une date illisible en base ne doit pas rendre la page inaccessible.
            log.warning("Date de terme illisible — planning rendu sans dates", valeur=brut)

    jalons = (await db.execute(
        select(Jalon).where(Jalon.dossier_id == d.id)
        .order_by(Jalon.mois, Jalon.position, Jalon.titre)
    )).scalars().all()

    mois: list[dict] = []
    for j in jalons:
        if not mois or mois[-1]["index"] != j.mois:
            mois.append({
                "index": j.mois,
                "phase": "grossesse" if j.mois < 0 else "enfant",
                "libelle": _libelle_mois(j.mois),
                # Fenêtre du mois : [ancre + m mois, ancre + (m+1) mois[. La formule est la
                # même avant et après la naissance — c'est tout l'intérêt d'un index signé.
                "debut": _ajouter_mois(ancre, j.mois).isoformat() if ancre else None,
                "fin": _ajouter_mois(ancre, j.mois + 1).isoformat() if ancre else None,
                "jalons": [],
            })
        mois[-1]["jalons"].append(_serialiser_jalon(j))

    obligatoires = [j for j in jalons if j.obligatoire]
    return {
        "dossier": {"id": str(d.id), "slug": d.slug, "titre": d.titre},
        "date_terme": ancre.isoformat() if ancre else None,
        "avertissement": AVERTISSEMENT,
        "categories": CATEGORIES,
        "stats": {
            "total": len(jalons),
            "faits": sum(1 for j in jalons if j.fait),
            "obligatoires": len(obligatoires),
            "obligatoires_faits": sum(1 for j in obligatoires if j.fait),
        },
        "mois": mois,
    }


@router.post("/dossiers/{ref}/jalons", status_code=201, tags=["Dossiers"])
async def ajouter_jalon(ref: str, body: JalonIn, db: AsyncSession = Depends(get_db)) -> dict:
    d = await _get_dossier(db, ref)
    position = ((await db.execute(
        select(func.max(Jalon.position)).where(Jalon.dossier_id == d.id, Jalon.mois == body.mois)
    )).scalar() or 0) + 1

    j = Jalon(dossier_id=d.id, position=position, **body.model_dump())
    db.add(j)
    await db.commit()
    await db.refresh(j)
    log.info("Jalon ajouté", dossier=d.slug, mois=body.mois, titre=body.titre)
    return _serialiser_jalon(j)


@router.patch("/dossiers/jalons/{jid}", tags=["Dossiers"])
async def modifier_jalon(jid: str, body: JalonPatch, db: AsyncSession = Depends(get_db)) -> dict:
    j = await _get_jalon(db, jid)
    champs = body.model_dump(exclude_unset=True)

    # Cocher horodate, décocher efface l'horodatage : une date de réalisation qui survit
    # au décochage est un mensonge silencieux.
    if "fait" in champs:
        j.fait_le = datetime.now(UTC) if champs["fait"] else None

    for champ, valeur in champs.items():
        setattr(j, champ, valeur)
    await db.commit()
    await db.refresh(j)
    return _serialiser_jalon(j)


@router.delete("/dossiers/jalons/{jid}", tags=["Dossiers"])
async def supprimer_jalon(jid: str, db: AsyncSession = Depends(get_db)) -> dict:
    j = await _get_jalon(db, jid)
    titre = j.titre
    await db.delete(j)
    await db.commit()
    return {"message": f"Jalon « {titre} » supprimé"}
