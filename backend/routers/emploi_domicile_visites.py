"""
Router Visites — /api/emploi-domicile (intervenants et entretiens)
==================================================================
Le pendant « écriture » du module : les personnes qu'on envisage d'employer, et les
rencontres qu'on a avec elles.

**La checklist appartient à l'ENTRETIEN, pas à la personne.** C'est la correction du plan
initial, et elle se voit dès le deuxième rendez-vous : on revient chez la même assistante
maternelle, certaines réponses ont changé, et les écraser ferait disparaître l'information
la plus utile — *ce qui a bougé entre les deux visites*.

Un second entretien peut **reprendre** les réponses du précédent : on ne repose pas quarante
questions, on met à jour ce qui a changé. L'entretien d'origine n'est pas modifié, donc
l'écart reste lisible.

  GET    /emploi-domicile/{ref}/intervenants        → les personnes suivies pour ce dossier
  POST   /emploi-domicile/{ref}/intervenants        → créer une fiche (nom seul obligatoire)
  GET    /emploi-domicile/intervenants/{iid}        → fiche + TOUS ses entretiens
  PATCH  /emploi-domicile/intervenants/{iid}        → statut, coordonnées, agrément…
  DELETE /emploi-domicile/intervenants/{iid}        → fiche + entretiens (cascade)
  POST   /emploi-domicile/intervenants/{iid}/entretiens  → planifier (option `reprendre_de`)
  PATCH  /emploi-domicile/entretiens/{eid}          → date, créneau, statut, impression
  POST   /emploi-domicile/entretiens/{eid}/reponse  → UNE réponse de checklist (autosave)
  DELETE /emploi-domicile/entretiens/{eid}
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from logger import get_logger
from models.dossier import DossierThematique
from models.emploi_domicile import Entretien, Intervenant
from services import crypto
from services.emploi_domicile import profils

log = get_logger(__name__)
router = APIRouter()
settings = get_settings()

HEURE = r"^([01]\d|2[0-3]):[0-5]\d$"

# Vocabulaires de référence. Volontairement sans contrainte CHECK en base, comme
# `ressources.type` : ajouter un état ne doit pas demander de migration.
STATUTS_INTERVENANT = ("a_contacter", "entretien", "retenue", "employee", "ecartee", "terminee")
TYPES_ENTRETIEN = ("telephone", "visite", "seconde_visite", "suivi")
STATUTS_ENTRETIEN = ("planifie", "fait", "annule")
AVIS = ("ok", "reserve", "non")


class IntervenantIn(BaseModel):
    nom: str = Field(min_length=1, max_length=200)
    prenom: str | None = None
    profil: str = "assmat"
    telephone: str | None = None
    email: str | None = None
    commune: str | None = None
    adresse: str | None = None
    agrement_numero: str | None = None
    agrement_echeance: date | None = None
    places: int | None = Field(default=None, ge=0, le=20)
    tarif_annonce: str | None = None
    disponibilite: str | None = None
    statut: str = "a_contacter"
    note: str | None = None


class IntervenantPatch(BaseModel):
    """Tout optionnel : la même route sert à changer un statut et à réécrire une fiche."""

    nom: str | None = Field(default=None, min_length=1, max_length=200)
    prenom: str | None = None
    profil: str | None = None
    telephone: str | None = None
    email: str | None = None
    commune: str | None = None
    adresse: str | None = None
    agrement_numero: str | None = None
    agrement_echeance: date | None = None
    places: int | None = Field(default=None, ge=0, le=20)
    tarif_annonce: str | None = None
    disponibilite: str | None = None
    statut: str | None = None
    note: str | None = None
    photo_accord: bool | None = None


class EntretienIn(BaseModel):
    type: str = "visite"
    date_prevue: date | None = None
    heure_debut: str | None = Field(default=None, pattern=HEURE)
    heure_fin: str | None = Field(default=None, pattern=HEURE)
    lieu: str | None = None
    note: str | None = None
    # Reprendre les réponses d'un entretien précédent. `"precedent"` = le dernier en date,
    # pour ne pas avoir à connaître son identifiant côté écran.
    reprendre_de: str | None = None


class EntretienPatch(BaseModel):
    type: str | None = None
    date_prevue: date | None = None
    heure_debut: str | None = Field(default=None, pattern=HEURE)
    heure_fin: str | None = Field(default=None, pattern=HEURE)
    lieu: str | None = None
    statut: str | None = None
    impression: int | None = Field(default=None, ge=1, le=5)
    note: str | None = None


class ReponseIn(BaseModel):
    cle: str = Field(min_length=1, max_length=100)
    avis: str | None = None            # 'ok' | 'reserve' | 'non' | null (efface l'avis)
    texte: str | None = Field(default=None, max_length=2000)


def _serialiser_entretien(e: Entretien) -> dict:
    reponses = e.reponses or {}
    return {
        "id": str(e.id), "intervenant_id": str(e.intervenant_id),
        "rang": e.rang, "type": e.type, "statut": e.statut,
        "date_prevue": e.date_prevue.isoformat() if e.date_prevue else None,
        "heure_debut": e.heure_debut, "heure_fin": e.heure_fin, "lieu": e.lieu,
        "impression": e.impression, "note": e.note,
        "reponses": reponses,
        "nb_repondues": sum(1 for r in reponses.values() if r.get("avis") or r.get("texte")),
        "jalon_id": str(e.jalon_id) if e.jalon_id else None,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def _apercu(chiffre: str | None, garde: int = 4) -> str | None:
    """
    Aperçu masqué d'une donnée chiffrée : `•••• 1234`, ou `None` si rien n'est enregistré.

    Les derniers caractères suffisent à **reconnaître** la bonne valeur (« c'est bien cet
    IBAN-là ») sans la divulguer. Rendre `True`/`False` obligerait à ouvrir le clair pour
    vérifier qu'on n'a pas saisi deux fois la même chose au mauvais endroit — soit exactement
    l'inverse de ce qu'on cherche.
    """
    if not chiffre:
        return None
    clair = crypto.decrypt(chiffre)
    if not clair:
        # Déchiffrement impossible (clé changée) : on ne prétend pas que le champ est vide,
        # sinon l'utilisateur le ressaisirait par-dessus sans jamais savoir ce qui a cassé.
        return "•••• (illisible)"
    fin = clair[-garde:] if len(clair) > garde else ""
    return f"•••• {fin}".strip()


def _serialiser_intervenant(i: Intervenant, nb_entretiens: int = 0,
                            prochain: Entretien | None = None) -> dict:
    return {
        "id": str(i.id), "dossier_id": str(i.dossier_id), "profil": i.profil,
        "nom": i.nom, "prenom": i.prenom, "telephone": i.telephone, "email": i.email,
        "commune": i.commune, "adresse": i.adresse,
        "agrement_numero": i.agrement_numero,
        "agrement_echeance": i.agrement_echeance.isoformat() if i.agrement_echeance else None,
        # Une échéance d'agrément dépassée doit sauter aux yeux : sans agrément valide, il n'y
        # a ni aide ni accueil légal — et c'est la date qu'on oublie de regarder.
        "agrement_perime": bool(i.agrement_echeance and i.agrement_echeance < date.today()),
        "photo": bool(i.photo), "photo_accord": i.photo_accord,
        # Identité administrative : APERÇU MASQUÉ uniquement. Le clair passe par une route
        # dédiée, un geste à la fois — un champ affiché par défaut finit dans une capture
        # d'écran, un partage de session ou une impression.
        "numero_secu": _apercu(i.numero_secu_chiffre, garde=4),
        "iban": _apercu(i.iban_chiffre, garde=4),
        "places": i.places, "tarif_annonce": i.tarif_annonce,
        "disponibilite": i.disponibilite, "statut": i.statut, "note": i.note,
        "nb_entretiens": nb_entretiens,
        "prochain_rdv": _serialiser_entretien(prochain) if prochain else None,
        "created_at": i.created_at.isoformat() if i.created_at else None,
    }


async def _get_dossier(db: AsyncSession, ref: str) -> DossierThematique:
    """Dossier par UUID ou slug — les URLs du front restent lisibles (`/dossiers/devenir-parent`)."""
    try:
        d = await db.get(DossierThematique, uuid.UUID(ref))
    except ValueError:
        d = (await db.execute(
            select(DossierThematique).where(DossierThematique.slug == ref)
        )).scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail="Dossier introuvable")
    return d


async def _get_intervenant(db: AsyncSession, iid: str) -> Intervenant:
    try:
        i = await db.get(Intervenant, uuid.UUID(iid))
    except ValueError:
        raise HTTPException(status_code=400, detail="Identifiant invalide")
    if i is None:
        raise HTTPException(status_code=404, detail="Intervenant introuvable")
    return i


async def _get_entretien(db: AsyncSession, eid: str) -> Entretien:
    try:
        e = await db.get(Entretien, uuid.UUID(eid))
    except ValueError:
        raise HTTPException(status_code=400, detail="Identifiant invalide")
    if e is None:
        raise HTTPException(status_code=404, detail="Entretien introuvable")
    return e


def _valider(valeur: str | None, autorises: tuple[str, ...], champ: str) -> None:
    if valeur is not None and valeur not in autorises:
        raise HTTPException(
            status_code=400,
            detail=f"{champ} invalide : {valeur!r} (attendu : {', '.join(autorises)})",
        )


# ─── Intervenants ─────────────────────────────────────────────────────────────────────

@router.get("/emploi-domicile/{ref}/intervenants", tags=["Emploi à domicile"])
async def lister_intervenants(ref: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Les personnes suivies pour ce dossier, avec leur nombre d'entretiens et leur **prochain
    rendez-vous** — c'est ce qu'on regarde en ouvrant l'écran : qui reste à appeler, qui on
    voit jeudi.
    """
    d = await _get_dossier(db, ref)
    intervenants = (await db.execute(
        select(Intervenant).where(Intervenant.dossier_id == d.id)
        .order_by(Intervenant.created_at)
    )).scalars().all()

    entretiens = (await db.execute(
        select(Entretien).where(Entretien.intervenant_id.in_([i.id for i in intervenants]))
        .order_by(Entretien.rang)
    )).scalars().all() if intervenants else []

    par_intervenant: dict = {}
    for e in entretiens:
        par_intervenant.setdefault(e.intervenant_id, []).append(e)

    def _prochain(liste: list[Entretien]) -> Entretien | None:
        # Le prochain rendez-vous PLANIFIÉ et daté. Un entretien sans date n'est pas un
        # rendez-vous, c'est une intention : l'afficher comme une date serait mentir.
        futurs = [e for e in liste if e.statut == "planifie" and e.date_prevue]
        return min(futurs, key=lambda e: e.date_prevue) if futurs else None

    return {
        "dossier": {"id": str(d.id), "slug": d.slug, "titre": d.titre},
        "intervenants": [
            _serialiser_intervenant(i, len(par_intervenant.get(i.id, [])),
                                    _prochain(par_intervenant.get(i.id, [])))
            for i in intervenants
        ],
        "statuts": list(STATUTS_INTERVENANT),
        "types_entretien": list(TYPES_ENTRETIEN),
    }


@router.post("/emploi-domicile/{ref}/intervenants", status_code=201, tags=["Emploi à domicile"])
async def creer_intervenant(ref: str, body: IntervenantIn,
                            db: AsyncSession = Depends(get_db)) -> dict:
    """
    Crée une fiche. **Seul le nom est obligatoire** : une fiche à moitié remplie pendant un
    premier appel vaut mieux qu'un formulaire qu'on renonce à valider.
    """
    d = await _get_dossier(db, ref)
    _valider(body.statut, STATUTS_INTERVENANT, "statut")
    i = Intervenant(dossier_id=d.id, **body.model_dump())
    db.add(i)
    await db.commit()
    await db.refresh(i)
    log.info("Intervenant créé", dossier=d.slug, nom=i.nom, profil=i.profil)
    return _serialiser_intervenant(i)


@router.get("/emploi-domicile/intervenants/{iid}", tags=["Emploi à domicile"])
async def detail_intervenant(iid: str, db: AsyncSession = Depends(get_db)) -> dict:
    """La fiche et TOUS ses entretiens — c'est l'historique qui fait la valeur de l'écran."""
    i = await _get_intervenant(db, iid)
    entretiens = (await db.execute(
        select(Entretien).where(Entretien.intervenant_id == i.id).order_by(Entretien.rang)
    )).scalars().all()
    return {
        **_serialiser_intervenant(i, len(entretiens)),
        "entretiens": [_serialiser_entretien(e) for e in entretiens],
    }


@router.patch("/emploi-domicile/intervenants/{iid}", tags=["Emploi à domicile"])
async def modifier_intervenant(iid: str, body: IntervenantPatch,
                               db: AsyncSession = Depends(get_db)) -> dict:
    i = await _get_intervenant(db, iid)
    champs = body.model_dump(exclude_unset=True)
    _valider(champs.get("statut"), STATUTS_INTERVENANT, "statut")
    for champ, valeur in champs.items():
        setattr(i, champ, valeur)
    await db.commit()
    await db.refresh(i)
    return _serialiser_intervenant(i)


@router.delete("/emploi-domicile/intervenants/{iid}", tags=["Emploi à domicile"])
async def supprimer_intervenant(iid: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Supprime la fiche ET ses entretiens : pas de visite orpheline.

    La suppression des entretiens est EXPLICITE, alors qu'un `ON DELETE CASCADE` existe en
    base. Deux raisons, et la première a été trouvée par un test : la cascade dépend de
    l'application des clés étrangères, que SQLite n'active pas par défaut — le comportement
    aurait donc différé entre les tests et la production. La seconde est qu'un `db.delete()`
    de l'ORM ne connaît pas ce CASCADE : la même précaution existe déjà pour les ressources
    d'un dossier.
    """
    i = await _get_intervenant(db, iid)
    nom = i.nom
    # Le portrait part avec la fiche : une donnée personnelle qu'on croit supprimée et qui
    # reste sur le disque est le pire des deux mondes.
    chemin = _chemin_photo(i)
    if chemin and chemin.exists():
        chemin.unlink()
    await db.execute(delete(Entretien).where(Entretien.intervenant_id == i.id))
    await db.delete(i)
    await db.commit()
    log.info("Intervenant supprimé", nom=nom)
    return {"supprime": True, "nom": nom}


# ─── Entretiens ───────────────────────────────────────────────────────────────────────

@router.post("/emploi-domicile/intervenants/{iid}/entretiens", status_code=201,
             tags=["Emploi à domicile"])
async def creer_entretien(iid: str, body: EntretienIn,
                          db: AsyncSession = Depends(get_db)) -> dict:
    """
    Planifie un entretien. Son `rang` (1ᵉʳ, 2ᵉ…) se déduit seul.

    `reprendre_de` copie les réponses d'un entretien précédent (`"precedent"` = le dernier).
    C'est ce qui rend un second rendez-vous supportable : on garde ce qui a été dit, on ne
    met à jour que ce qui a changé — et comme l'entretien d'origine n'est pas modifié,
    l'écart entre les deux reste lisible.
    """
    i = await _get_intervenant(db, iid)
    _valider(body.type, TYPES_ENTRETIEN, "type")

    precedents = (await db.execute(
        select(Entretien).where(Entretien.intervenant_id == i.id).order_by(Entretien.rang)
    )).scalars().all()
    rang = max((e.rang for e in precedents), default=0) + 1

    reponses: dict = {}
    if body.reprendre_de:
        if body.reprendre_de == "precedent":
            source = precedents[-1] if precedents else None
        else:
            source = next((e for e in precedents if str(e.id) == body.reprendre_de), None)
            if source is None:
                raise HTTPException(
                    status_code=404,
                    detail="Entretien à reprendre introuvable pour cette personne",
                )
        if source is not None:
            reponses = dict(source.reponses or {})

    e = Entretien(intervenant_id=i.id, rang=rang, reponses=reponses,
                  **body.model_dump(exclude={"reprendre_de"}))
    db.add(e)
    # Un rendez-vous pris fait avancer le suivi : rester « à contacter » alors qu'une visite
    # est calée obligerait à un second geste que personne ne pense à faire.
    if i.statut == "a_contacter":
        i.statut = "entretien"
    await db.commit()
    await db.refresh(e)
    log.info("Entretien créé", intervenant=i.nom, rang=rang, type=e.type, repris=bool(reponses))
    return _serialiser_entretien(e)


@router.patch("/emploi-domicile/entretiens/{eid}", tags=["Emploi à domicile"])
async def modifier_entretien(eid: str, body: EntretienPatch,
                             db: AsyncSession = Depends(get_db)) -> dict:
    e = await _get_entretien(db, eid)
    champs = body.model_dump(exclude_unset=True)
    _valider(champs.get("type"), TYPES_ENTRETIEN, "type")
    _valider(champs.get("statut"), STATUTS_ENTRETIEN, "statut")
    for champ, valeur in champs.items():
        setattr(e, champ, valeur)
    await db.commit()
    await db.refresh(e)
    return _serialiser_entretien(e)


@router.post("/emploi-domicile/entretiens/{eid}/reponse", tags=["Emploi à domicile"])
async def repondre(eid: str, body: ReponseIn, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Enregistre **une** réponse de la checklist, au fil de la saisie.

    Une par une, et non le formulaire entier : la fiche se remplit debout, pendant la visite,
    souvent au bout d'un VPN sur données mobiles. Perdre vingt réponses sur une coupure
    serait le scénario le plus probable — et le plus coûteux.

    Une réponse vidée (ni avis ni texte) est **retirée** plutôt que stockée vide, pour que le
    compte de questions traitées reste juste.
    """
    e = await _get_entretien(db, eid)
    _valider(body.avis, AVIS, "avis")

    reponses = dict(e.reponses or {})
    texte = (body.texte or "").strip()
    if body.avis or texte:
        reponses[body.cle] = {"avis": body.avis, "texte": texte or None}
    else:
        reponses.pop(body.cle, None)
    e.reponses = reponses
    await db.commit()
    await db.refresh(e)
    return _serialiser_entretien(e)


@router.delete("/emploi-domicile/entretiens/{eid}", tags=["Emploi à domicile"])
async def supprimer_entretien(eid: str, db: AsyncSession = Depends(get_db)) -> dict:
    e = await _get_entretien(db, eid)
    await db.delete(e)
    await db.commit()
    return {"supprime": True}


# ─── Portrait ─────────────────────────────────────────────────────────────────────────
# Stocké dans `storage/intervenants/`, **hors GED** et c'est délibéré : un portrait n'est pas
# un document à retrouver. L'indexer ferait remonter un visage dans les résultats de recherche
# et l'enverrait en extraction, enrichissement IA et embeddings — pour rien.

import mimetypes
from pathlib import Path

# Formats que TOUS les navigateurs savent afficher. Le HEIC des iPhone en est absent : il
# arrive parfois tel quel, et un fichier accepté mais illisible serait pire qu'un refus —
# on croirait la photo enregistrée jusqu'à ouvrir la fiche.
FORMATS_PHOTO = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
TAILLE_MAX_PHOTO = 8 * 1024 * 1024   # 8 Mo : large, le client redimensionne déjà


def _dossier_photos() -> Path:
    dossier = Path(settings.storage_intervenants)
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def _chemin_photo(i: Intervenant) -> Path | None:
    if not i.photo:
        return None
    # `name` seul : le nom stocké ne doit jamais pouvoir désigner un fichier hors du dossier,
    # même si la base a été modifiée à la main.
    return _dossier_photos() / Path(i.photo).name


@router.post("/emploi-domicile/intervenants/{iid}/photo", tags=["Emploi à domicile"])
async def envoyer_photo(iid: str, fichier: UploadFile = File(...),
                        db: AsyncSession = Depends(get_db)) -> dict:
    """
    Dépose le portrait. Trois gestes côté écran — glisser-déposer, import, appareil photo —
    convergent ici : c'est le même envoi.

    Le type est vérifié **sur le contenu déclaré ET sur l'extension** : un `.heic` d'iPhone
    passe parfois entre les mailles du type MIME, et un fichier accepté mais illisible par le
    navigateur serait pire qu'un refus — on croirait la photo enregistrée jusqu'à rouvrir
    la fiche.
    """
    i = await _get_intervenant(db, iid)

    extension = FORMATS_PHOTO.get((fichier.content_type or "").lower())
    if extension is None:
        raise HTTPException(
            status_code=400,
            detail=f"Format non accepté ({fichier.content_type or 'inconnu'}). Formats lisibles "
                   "par tous les navigateurs : JPEG, PNG, WebP. Les photos iPhone au format "
                   "HEIC doivent être converties — votre téléphone le fait en général au partage.",
        )

    contenu = await fichier.read()
    if not contenu:
        raise HTTPException(status_code=400, detail="Fichier vide.")
    if len(contenu) > TAILLE_MAX_PHOTO:
        raise HTTPException(
            status_code=400,
            detail=f"Photo trop lourde ({len(contenu) // 1024} Ko). Maximum {TAILLE_MAX_PHOTO // 1024} Ko.",
        )

    ancienne = _chemin_photo(i)
    nom = f"{i.id}{extension}"
    (_dossier_photos() / nom).write_bytes(contenu)
    # L'ancienne n'est retirée que si elle portait une AUTRE extension : sinon on vient de
    # l'écraser, et la supprimer effacerait la nouvelle.
    if ancienne and ancienne.name != nom and ancienne.exists():
        ancienne.unlink()

    i.photo = nom
    await db.commit()
    await db.refresh(i)
    log.info("Portrait déposé", intervenant=i.nom, octets=len(contenu), type=fichier.content_type)
    return _serialiser_intervenant(i)


@router.get("/emploi-domicile/intervenants/{iid}/photo", tags=["Emploi à domicile"])
async def lire_photo(iid: str, db: AsyncSession = Depends(get_db)):
    """Sert le portrait. 404 explicite s'il n'y en a pas — l'écran affiche alors ses initiales."""
    i = await _get_intervenant(db, iid)
    chemin = _chemin_photo(i)
    if chemin is None or not chemin.exists():
        raise HTTPException(status_code=404, detail="Aucun portrait pour cette personne")
    type_mime = mimetypes.guess_type(chemin.name)[0] or "application/octet-stream"
    return FileResponse(chemin, media_type=type_mime)


@router.delete("/emploi-domicile/intervenants/{iid}/photo", tags=["Emploi à domicile"])
async def supprimer_photo(iid: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Retire le portrait **et le fichier**. Une donnée personnelle qu'on croit avoir supprimée
    et qui reste sur le disque est le pire des deux mondes.
    """
    i = await _get_intervenant(db, iid)
    chemin = _chemin_photo(i)
    if chemin and chemin.exists():
        chemin.unlink()
    i.photo = None
    i.photo_accord = False
    await db.commit()
    return {"supprime": True}


# ─── Poser un entretien dans le planning ──────────────────────────────────────────────
# Un rendez-vous vit à deux endroits légitimes : la **fiche** de la personne (c'est là qu'on
# prépare la visite) et le **planning** du dossier (c'est là qu'on regarde sa semaine). Les
# dupliquer à la main, c'est se garantir qu'ils divergeront — et c'est toujours celui du
# calendrier qu'on croit.

@router.post("/emploi-domicile/entretiens/{eid}/planning", tags=["Emploi à domicile"])
async def poser_au_planning(eid: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Crée (ou met à jour) le jalon correspondant à cet entretien.

    **Idempotent** : `entretiens.jalon_id` garde le lien, donc rappuyer sur le bouton
    *déplace* le rendez-vous existant au lieu d'en semer un second. Un planning qui accumule
    trois fois le même rendez-vous parce qu'on a cliqué trois fois est un planning qu'on
    cesse de regarder.

    Le jalon reçoit la **date réelle** : c'est un rendez-vous pris, pas un repère de période
    (cf. `models/jalon`). Sans date prévue, il n'y a rien à poser — et le dire vaut mieux que
    d'inventer un jour.
    """
    from models.jalon import Jalon
    from routers.dossiers import _ancre_courante, _mois_depuis_date, _serialiser_jalon

    e = await _get_entretien(db, eid)
    if e.date_prevue is None:
        raise HTTPException(
            status_code=400,
            detail="Cet entretien n'a pas de date : renseignez-la avant de le poser au planning.",
        )
    i = await _get_intervenant(db, str(e.intervenant_id))
    qui = " ".join(x for x in (i.prenom, i.nom) if x) or "intervenant"
    profil = profils.profil(i.profil)

    titre = f"{'Visite' if e.type == 'visite' else 'Entretien'} — {qui}"
    detail = " · ".join(x for x in (profil.libelle, e.lieu, i.telephone) if x) or None

    jalon = await db.get(Jalon, e.jalon_id) if e.jalon_id else None
    ancre = _ancre_courante()
    mois = _mois_depuis_date(e.date_prevue, ancre) if ancre else 0

    if jalon is None:
        position = ((await db.execute(
            select(func.max(Jalon.position)).where(Jalon.dossier_id == i.dossier_id,
                                                   Jalon.mois == mois)
        )).scalar() or 0) + 1
        jalon = Jalon(dossier_id=i.dossier_id, mois=mois, position=position,
                      categorie="garde", titre=titre)
        db.add(jalon)

    # Les champs du rendez-vous sont réécrits à chaque fois ; le SUIVI (`fait`, `note_perso`)
    # ne l'est jamais — c'est la saisie de l'utilisateur, et un reposage ne doit pas décocher
    # un rendez-vous déjà honoré.
    jalon.titre = titre
    jalon.detail = detail
    jalon.date_reelle = e.date_prevue
    jalon.heure_debut = e.heure_debut
    jalon.heure_fin = e.heure_fin
    jalon.mois = mois

    await db.flush()
    e.jalon_id = jalon.id
    await db.commit()
    await db.refresh(jalon)
    log.info("Entretien posé au planning", entretien=eid, jalon=str(jalon.id), date=str(e.date_prevue))
    return {"entretien": _serialiser_entretien(e), "jalon": _serialiser_jalon(jalon, ancre)}


@router.delete("/emploi-domicile/entretiens/{eid}/planning", tags=["Emploi à domicile"])
async def retirer_du_planning(eid: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Retire le jalon du planning et **coupe le lien**.

    Le supprimer sans effacer `jalon_id` laisserait la fiche croire que le rendez-vous est
    toujours au calendrier — et le bouton proposerait de le « déplacer » vers un jalon qui
    n'existe plus.
    """
    from models.jalon import Jalon

    e = await _get_entretien(db, eid)
    if e.jalon_id:
        jalon = await db.get(Jalon, e.jalon_id)
        if jalon is not None:
            await db.delete(jalon)
        e.jalon_id = None
        await db.commit()
    return {"entretien": _serialiser_entretien(e)}


# ─── Identité administrative : n° de sécurité sociale et IBAN ─────────────────────────
# Les deux seules données de cette fiche dont la fuite ferait un vrai dégât. Elles sont
# **chiffrées au repos** (Fernet, même mécanisme que les secrets des sources SMB/cloud) et
# ne transitent en clair que sur demande explicite, une donnée à la fois.
#
# Pourquoi des routes séparées plutôt que deux champs de plus dans le PATCH : parce que le
# PATCH sert à tout — cocher un statut, corriger un téléphone — et que son corps se retrouve
# dans les journaux d'accès, les outils de développement et les rejeux. Un secret n'a rien à
# faire sur un chemin banalisé.

class IdentiteIn(BaseModel):
    """`None` **efface** la donnée ; une chaîne vide aussi. Pouvoir retirer compte autant."""

    numero_secu: str | None = Field(default=None, max_length=30)
    iban: str | None = Field(default=None, max_length=40)


def _normaliser(valeur: str | None) -> str | None:
    """Espaces retirés : un IBAN se recopie avec, se compare sans."""
    if valeur is None:
        return None
    compact = "".join(valeur.split()).upper()
    return compact or None


@router.put("/emploi-domicile/intervenants/{iid}/identite", tags=["Emploi à domicile"])
async def enregistrer_identite(iid: str, body: IdentiteIn,
                               db: AsyncSession = Depends(get_db)) -> dict:
    """
    Enregistre (ou efface) le numéro de sécurité sociale et l'IBAN, **chiffrés**.

    Seuls les champs **fournis** sont touchés : renseigner l'IBAN n'efface pas le numéro de
    sécurité sociale saisi la semaine d'avant.
    """
    i = await _get_intervenant(db, iid)
    fournis = body.model_dump(exclude_unset=True)

    for champ, colonne in (("numero_secu", "numero_secu_chiffre"), ("iban", "iban_chiffre")):
        if champ not in fournis:
            continue
        clair = _normaliser(fournis[champ])
        setattr(i, colonne, crypto.encrypt(clair) if clair else None)

    await db.commit()
    await db.refresh(i)
    # Le journal dit QUE ça a changé, jamais QUOI : un secret écrit dans un log n'est plus
    # un secret, et ces journaux partent dans journald.
    log.info("Identité administrative enregistrée", intervenant=iid,
             champs=sorted(fournis.keys()))
    return _serialiser_intervenant(i)


@router.post("/emploi-domicile/intervenants/{iid}/identite/reveler", tags=["Emploi à domicile"])
async def reveler_identite(iid: str, champ: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Rend **une** donnée en clair, à la demande.

    En POST et non en GET, délibérément : un GET se met en cache, se retrouve dans
    l'historique du navigateur et se rejoue en rechargeant la page. On révèle un secret
    quand on le décide, pas parce qu'on a appuyé sur F5.
    """
    if champ not in ("numero_secu", "iban"):
        raise HTTPException(status_code=400, detail="Champ inconnu")
    i = await _get_intervenant(db, iid)
    chiffre = i.numero_secu_chiffre if champ == "numero_secu" else i.iban_chiffre
    if not chiffre:
        raise HTTPException(status_code=404, detail="Rien d'enregistré pour ce champ")

    clair = crypto.decrypt(chiffre)
    if not clair:
        raise HTTPException(
            status_code=500,
            detail="Donnée illisible : la clé de chiffrement a changé depuis la saisie. "
                   "Ressaisissez-la — elle n'est pas récupérable.",
        )
    log.info("Identité administrative révélée", intervenant=iid, champ=champ)
    return {"champ": champ, "valeur": clair}
