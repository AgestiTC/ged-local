"""
Router Passerelle — /api/passerelle (wiki multi-projets)
========================================================
Lot 2 (auth + admin) + Lot 3 (publication par manifeste).

  Dépendance `projet_authentifie`  → protège l'endpoint de PUBLICATION par jeton Bearer.
  POST   /passerelle/publish                 → publier/synchroniser un MANIFESTE (auth jeton) [Lot 3]
  POST   /passerelle/projets                 → enregistrer un projet + générer son jeton (montré 1×)
  GET    /passerelle/projets                 → lister les projets (sans le hash de jeton)
  POST   /passerelle/projets/{nom}/regenerer → rotation du jeton
  PATCH  /passerelle/projets/{nom}           → (dés)activer / modifier la liste blanche des livres

⚠️ Les endpoints d'administration reposent sur la **confiance réseau** (comme le reste de l'API) —
c'est l'endpoint de publication (Lot 3) qui exige le jeton. Le jeton en clair n'est **jamais stocké**
ni ré-affiché : à copier au moment de la création/rotation.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.publieur import ProjetPublieur
from services import publication_service, publieur_auth
from services.bookstack_service import BookStackService

log = get_logger(__name__)
router = APIRouter()

_AVERT_JETON = "Copie ce jeton MAINTENANT : il n'est jamais ré-affiché (seul son hash est conservé)."


def _projet_dict(p: ProjetPublieur) -> dict:
    """Sérialise un projet SANS jamais exposer le hash du jeton."""
    return {
        "nom": p.nom,
        "livres_autorises": p.livres_autorises,
        "actif": p.actif,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "last_used_at": p.last_used_at.isoformat() if p.last_used_at else None,
    }


async def projet_authentifie(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ProjetPublieur:
    """
    Dépendance d'authentification des endpoints de PUBLICATION : lit `Authorization: Bearer <jeton>`,
    hache et retrouve le projet actif. **401** si jeton absent/invalide/révoqué. Utilisée par le Lot 3.
    """
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    projet = await publieur_auth.authentifier(db, token)
    if not projet:
        raise HTTPException(status_code=401, detail="Jeton de publication absent, invalide ou révoqué.")
    return projet


# ─── Administration des projets publieurs ─────────────────────────────────────
class ProjetCreate(BaseModel):
    nom: str = Field(min_length=1, description="Nom du projet (ex. « sapyn »)")
    livres_autorises: list[str] = Field(default_factory=list, description="Livres BookStack où ce projet peut publier")


class ProjetUpdate(BaseModel):
    livres_autorises: list[str] | None = None
    actif: bool | None = None   # false = révoquer (le jeton cesse d'authentifier)


@router.post("/passerelle/projets", tags=["Passerelle"])
async def creer_projet(body: ProjetCreate, db: AsyncSession = Depends(get_db)) -> dict:
    """Enregistre un projet publieur et **génère son jeton** (renvoyé UNE seule fois)."""
    try:
        projet, jeton = await publieur_auth.creer_projet(db, body.nom, body.livres_autorises)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {**_projet_dict(projet), "jeton": jeton, "avertissement": _AVERT_JETON}


@router.get("/passerelle/projets", tags=["Passerelle"])
async def lister_projets(db: AsyncSession = Depends(get_db)) -> dict:
    """Liste des projets publieurs (jamais le hash de jeton)."""
    projets = await publieur_auth.lister_projets(db)
    return {"projets": [_projet_dict(p) for p in projets]}


@router.post("/passerelle/projets/{nom}/regenerer", tags=["Passerelle"])
async def regenerer_jeton(nom: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Rotation du jeton d'un projet (l'ancien cesse immédiatement de fonctionner)."""
    try:
        jeton = await publieur_auth.regenerer_jeton(db, nom)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"nom": nom, "jeton": jeton, "avertissement": _AVERT_JETON}


@router.patch("/passerelle/projets/{nom}", tags=["Passerelle"])
async def modifier_projet(nom: str, body: ProjetUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    """(Dés)active un projet (révocation via `actif=false`) et/ou modifie sa liste blanche de livres."""
    try:
        projet = await publieur_auth.definir(db, nom, actif=body.actif, livres_autorises=body.livres_autorises)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _projet_dict(projet)


# ─── Publication (Lot 3) — endpoint MANIFESTE, protégé par jeton ───────────────
class PageManifeste(BaseModel):
    cle: str = Field(min_length=1, description="Identifiant logique du doc chez le projet (slug/chemin)")
    livre: str = Field(min_length=1)
    chapitre: str | None = None
    titre: str = Field(min_length=1)
    markdown: str
    genere_le: datetime | None = None   # horodatage de génération (ISO) — avertit si plus ancien


class Manifeste(BaseModel):
    pages: list[PageManifeste] = Field(min_length=1)
    etagere: str | None = None   # étagère BookStack où regrouper les livres (ex. « Projets AgestiTC »)


def _bandeau(projet: str, markdown: str) -> str:
    """Préfixe le contenu d'un bandeau « généré automatiquement » (§6.3) — signale aux humains que la
    page est gérée par la passerelle et qu'une édition manuelle sera écrasée à la prochaine synchro."""
    entete = (f"> ⚙️ _Page générée automatiquement depuis le projet **{projet}** via la passerelle "
              f"Matothèque — ne pas éditer à la main (toute modification sera écrasée à la prochaine "
              f"synchronisation)._\n\n")
    return entete + (markdown or "")


@router.post("/passerelle/publish", tags=["Passerelle"])
async def publier(
    body: Manifeste,
    projet: ProjetPublieur = Depends(projet_authentifie),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Publie/synchronise la doc d'un projet vers BookStack à partir de son **manifeste** (arbre complet).
    Auth par jeton (dépendance). Déroulé : autorisation des livres (liste blanche) → rapprochement
    (créer/màj/inchangées/retraits) → appels BookStack → upsert `publications`. Cf. plan § Lot 3.
    """
    service = BookStackService()
    if not service.configured:
        raise HTTPException(status_code=503, detail="BookStack non configuré (Réglages → Wiki).")

    # ① Autorisation des livres — ATOMIQUE : un seul livre non déclaré → rejet complet, aucun fantôme.
    livres_demandes = {p.livre for p in body.pages}
    interdits = sorted(livres_demandes - set(projet.livres_autorises))
    if interdits:
        raise HTTPException(
            status_code=403,
            detail=f"Livre(s) non autorisé(s) pour « {projet.nom} » : {', '.join(interdits)}. "
                   f"Autorisés : {', '.join(projet.livres_autorises) or '(aucun)'}.")

    # ② Rapprochement manifeste ↔ état publié.
    existants = await publication_service.publications_du_projet(db, projet.nom)   # {cle: Publication}
    existantes = {cle: {"contenu_hash": p.contenu_hash, "genere_le": p.genere_le} for cle, p in existants.items()}
    plan = publication_service.rapprocher([p.model_dump() for p in body.pages], existantes)

    creees, mises_a_jour, erreurs = [], [], []

    # ③ Créations : ensure_book [borné] → ensure_chapter → create_page → upsert.
    for page in plan["creer"]:
        try:
            book = await service.ensure_book(page["livre"])
            cible = {"book_id": book["id"]}
            if page.get("chapitre"):
                cible = {"chapter_id": (await service.ensure_chapter(book["id"], page["chapitre"]))["id"]}
            cree = await service.create_page(page["titre"], _bandeau(projet.nom, page.get("markdown", "")), **cible)
            url = service.page_url(cree)
            await publication_service.enregistrer_publication(
                db, projet=projet.nom, cle=page["cle"], livre=page["livre"], chapitre=page.get("chapitre"),
                page_id=cree.get("id"), url=url, contenu_hash=page["hash"], genere_le=page.get("genere_le"))
            creees.append({"cle": page["cle"], "livre": page["livre"], "page_id": cree.get("id"), "url": url})
        except Exception as e:  # noqa: BLE001 — une page en échec ne doit pas tout annuler
            log.error("Passerelle : création échouée", projet=projet.nom, cle=page["cle"], erreur=str(e))
            erreurs.append({"cle": page["cle"], "message": str(e)})

    # ④ Mises à jour : update_page sur la MÊME page (page_id mémorisé) → upsert.
    for page in plan["mettre_a_jour"]:
        try:
            pub = existants.get(page["cle"])
            if pub and pub.page_id:
                maj = await service.update_page(pub.page_id, _bandeau(projet.nom, page.get("markdown", "")), name=page["titre"])
                url = service.page_url(maj) if maj else pub.url
                await publication_service.enregistrer_publication(
                    db, projet=projet.nom, cle=page["cle"], livre=page["livre"], chapitre=page.get("chapitre"),
                    page_id=pub.page_id, url=url, contenu_hash=page["hash"], genere_le=page.get("genere_le"))
                mises_a_jour.append({"cle": page["cle"], "livre": page["livre"], "page_id": pub.page_id, "url": url})
            else:
                # Cas limite (ligne sans page_id) → on (re)crée.
                book = await service.ensure_book(page["livre"])
                cible = {"book_id": book["id"]}
                if page.get("chapitre"):
                    cible = {"chapter_id": (await service.ensure_chapter(book["id"], page["chapitre"]))["id"]}
                cree = await service.create_page(page["titre"], _bandeau(projet.nom, page.get("markdown", "")), **cible)
                url = service.page_url(cree)
                await publication_service.enregistrer_publication(
                    db, projet=projet.nom, cle=page["cle"], livre=page["livre"], chapitre=page.get("chapitre"),
                    page_id=cree.get("id"), url=url, contenu_hash=page["hash"], genere_le=page.get("genere_le"))
                mises_a_jour.append({"cle": page["cle"], "livre": page["livre"], "page_id": cree.get("id"), "url": url})
        except Exception as e:  # noqa: BLE001
            log.error("Passerelle : mise à jour échouée", projet=projet.nom, cle=page["cle"], erreur=str(e))
            erreurs.append({"cle": page["cle"], "message": str(e)})

    # ⑤ Étagère (Lot 1b) : regrouper les livres du projet dans l'étagère demandée (idempotent).
    #    ensure_book est idempotent → on récupère l'id de chaque livre du manifeste puis on l'y rattache.
    etagere_ok = None
    if body.etagere:
        try:
            shelf = await service.ensure_shelf(body.etagere)
            for livre in sorted(livres_demandes):
                book = await service.ensure_book(livre)
                await service.ensure_book_in_shelf(shelf["id"], book["id"])
            etagere_ok = body.etagere
        except Exception as e:  # noqa: BLE001 — un souci d'étagère ne doit pas perdre la publication
            log.error("Passerelle : rattachement à l'étagère échoué", projet=projet.nom,
                      etagere=body.etagere, erreur=str(e))
            erreurs.append({"cle": "(étagère)", "message": f"Rattachement à « {body.etagere} » échoué : {e}"})

    await db.commit()
    log.info("Passerelle : publication", projet=projet.nom, creees=len(creees), mises_a_jour=len(mises_a_jour),
             inchangees=len(plan["inchangees"]), retraits=len(plan["retraits_candidats"]),
             erreurs=len(erreurs), etagere=etagere_ok)
    return {
        "projet": projet.nom,
        "etagere": etagere_ok,
        "creees": creees,
        "mises_a_jour": mises_a_jour,
        "inchangees": plan["inchangees"],
        "retraits_candidats": plan["retraits_candidats"],
        "avertissements": plan["avertissements"],
        "erreurs": erreurs,
    }
