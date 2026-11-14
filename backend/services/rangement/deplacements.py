"""
Le SEUL exécutant des déplacements du Rangement (décision d'architecture n° 7) — étape 10.

Règles, chacune pour une raison :
- **Déplacer, jamais supprimer** : un déplacement est un `os.rename` dans le MÊME partage (même
  montage). Entre deux montages (ex. vers l'autre NAS), `rename` échoue : refusé, jamais « copier
  puis effacer » ici.
- **Jamais renommer ET déplacer** : le nom ne change que si la place est prise (`nom_(2)`), sinon la
  GED verrait « supprimé + nouveau » et ré-extrairait le document.
- **Aperçu obligatoire** : un lot n'est que l'aperçu validé ; à l'application, chaque ligne est
  revérifiée sur le disque (source présente, pas un lien, rien hors de l'emplacement).
- **Un seul journal** : `reorg_moves`, origine `rangement`, une ligne par déplacement, écrite et validée
  aussitôt (un arrêt brutal laisse un journal juste). **Annuler un lot désigné** remet en place ce qui
  peut l'être et date l'annulation ; **aucune ligne n'est supprimée** (décision n° 3).
- **Lecture seule respectée** : sur un montage `:ro` (la prod tant que Thomas n'a pas ouvert
  l'écriture), le lot est refusé avant le premier déplacement.
- **Emplacement SMB** (étape 6 du plan « Rangement sur Sources SMB ») : mêmes règles, par une session
  SMB avec le compte de la Source (`deplacements_smb.RangeurSmb`) ; le journal est en `smb://…`.
"""

import asyncio
import errno
import os
import posixpath
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from models.plan_classement import PlanLot, PlanProposition
from models.reorg import ReorgMove
from services.rangement.deplacements_smb import Coupure, EcritureRefusee, RangeurSmb, nom_libre_sans_casse
from services.rangement.depot import Depot, Emplacement
from services.rangement.erreurs import InventaireRefus, RangementRefuse
from services.rangement.scan import contient

log = get_logger(__name__)
ORIGINE = "rangement"

__all__ = ["RangementRefuse", "annuler", "apercu", "appliquer", "creer_lot", "nom_libre"]


def nom_libre(nom: str, pris: set[str], est_dossier: bool) -> str:
    """`nom`, ou `nom_(2)`, `nom_(3)`… si la place est prise. L'extension d'un fichier est gardée. PURE."""
    if nom not in pris:
        return nom
    base, ext = (nom, "") if est_dossier else posixpath.splitext(nom)
    n = 2
    while f"{base}_({n}){ext}" in pris:
        n += 1
    return f"{base}_({n}){ext}"


async def apercu(db: AsyncSession, depot: Depot, emp: Emplacement,
                 proposition_ids: list[int] | None = None) -> list[dict]:
    """Ce que ferait un lot : les propositions VALIDÉES (toutes, ou celles désignées), avec leur nom
    final. Calculé dans l'inventaire (l'API ne voit pas le disque) ; revérifié au moment de ranger."""
    if not (emp.sur_serveur or emp.est_smb):
        raise RangementRefuse("Seul un emplacement du NAS se range depuis le serveur.")
    q = select(PlanProposition).where(PlanProposition.emplacement_id == emp.id,
                                      PlanProposition.statut == "validee",
                                      PlanProposition.destination.is_not(None))
    if proposition_ids:
        q = q.where(PlanProposition.id.in_(proposition_ids))
    props = (await db.execute(q.order_by(PlanProposition.chemin))).scalars().all()
    deja_pris: dict[str, set[str]] = {}
    ops: list[dict] = []
    for p in props:
        dest_dossier = p.destination.strip("/")
        nom = posixpath.basename(p.chemin)
        if posixpath.dirname(p.chemin) == dest_dossier:
            continue   # déjà au bon endroit
        if dest_dossier == p.chemin or dest_dossier.startswith(p.chemin + "/"):
            continue   # un dossier ne se range pas dans lui-même
        if dest_dossier not in deja_pris:
            deja_pris[dest_dossier] = set((await depot.enfants(emp.id, dest_dossier)).keys())
        # SMB ne distingue pas la casse : « Photo.jpg » prend la place de « photo.jpg ».
        libre = nom_libre_sans_casse if emp.est_smb else nom_libre
        final = libre(nom, deja_pris[dest_dossier], p.est_dossier)
        deja_pris[dest_dossier].add(final)
        ops.append({"proposition_id": p.id, "source": p.chemin, "dossier": dest_dossier,
                    "nom": final, "renomme": final != nom, "est_dossier": p.est_dossier, "taille": p.taille})
    return ops


async def creer_lot(db: AsyncSession, depot: Depot, emp: Emplacement, libelle: str, par: str | None,
                    proposition_ids: list[int] | None = None) -> PlanLot:
    ops = await apercu(db, depot, emp, proposition_ids)
    if not ops:
        raise RangementRefuse("Rien à ranger : aucune proposition validée à déplacer.")
    lot = PlanLot(id=uuid.uuid4(), emplacement_id=emp.id, libelle=(libelle or "").strip()[:200] or "Lot de rangement",
                  operations=ops, nb=len(ops), octets=sum(o["taille"] for o in ops), cree_par=par, statut="pret")
    db.add(lot)
    await db.commit()
    return lot


def _verifier_racine(racine: str, autorisee: str | None) -> None:
    if autorisee and not contient(os.path.realpath(autorisee), os.path.realpath(racine)):
        raise RangementRefuse("La racine de l'emplacement n'est pas sous la racine autorisée.")
    if not os.path.isdir(racine):
        raise RangementRefuse(f"Racine introuvable : {racine}")
    if not os.access(racine, os.W_OK):
        raise RangementRefuse("Le NAS est monté en LECTURE SEULE pour Matothèque : rien n'a été déplacé. "
                              "Ouvrir l'écriture est un geste séparé (étape 10, montage rw + group_add).")


def _deplacer(racine: str, op: dict) -> tuple[str, str]:
    """Un déplacement sur le disque (synchrone, dans un fil). Rend (source, destination) absolues."""
    source = os.path.join(racine, *op["source"].split("/"))
    dossier = os.path.join(racine, *op["dossier"].split("/"))
    os.lstat(source)   # FileNotFoundError : déjà bougé ou disparu
    if os.path.islink(source):
        raise RangementRefuse("lien symbolique : jamais déplacé")
    reel = os.path.realpath(racine)
    cible = os.path.realpath(dossier) if os.path.exists(dossier) else os.path.normpath(dossier)
    if not contient(reel, os.path.realpath(source)) or not contient(reel, cible):
        raise RangementRefuse("hors de l'emplacement")
    os.makedirs(dossier, exist_ok=True)
    nom = op["nom"]
    if os.path.lexists(os.path.join(dossier, nom)):   # pris depuis l'aperçu : nom suivant libre
        nom = nom_libre(nom, set(os.listdir(dossier)), os.path.isdir(source))
    destination = os.path.join(dossier, nom)
    os.rename(source, destination)   # même montage : instantané, rien n'est copié ni supprimé
    return source, destination


async def appliquer(db: AsyncSession, lot: PlanLot, emp: Emplacement, *, racine_autorisee: str | None,
                    arret=None) -> PlanLot:
    """Range le lot. Une ligne de journal par déplacement réussi, validée aussitôt."""
    if lot.statut != "pret":
        raise RangementRefuse(f"Ce lot est « {lot.statut} » : il ne se range qu'une fois.")
    if emp.est_smb:
        return await _appliquer_smb(db, lot, emp, arret)
    try:
        await asyncio.to_thread(_verifier_racine, emp.racine, racine_autorisee)
    except RangementRefuse as exc:
        lot.statut, lot.message = "refuse", str(exc)
        await db.commit()
        raise
    lot.statut = "en_cours"
    await db.commit()
    reussis, erreurs = 0, []
    for op in lot.operations:
        if arret is not None and arret():
            erreurs.append("arrêté à la demande")
            break
        try:
            source, destination = await asyncio.to_thread(_deplacer, emp.racine, op)
        except (OSError, RangementRefuse) as exc:
            if isinstance(exc, OSError) and exc.errno in (errno.EROFS, errno.EACCES, errno.EPERM):
                erreurs.append(f"{op['source']} : écriture refusée par le NAS")
            elif isinstance(exc, OSError) and exc.errno == errno.EXDEV:
                erreurs.append(f"{op['source']} : autre disque, jamais copié puis effacé ici")
            else:
                erreurs.append(f"{op['source']} : {exc}")
            continue
        await _journaliser(db, lot, op, source, destination)
        reussis += 1
    return await _clore_lot(db, lot, reussis, erreurs)


async def _clore_lot(db: AsyncSession, lot: PlanLot, reussis: int, erreurs: list[str]) -> PlanLot:
    lot.statut = "range" if not erreurs else ("partiel" if reussis else "refuse")
    lot.message = (f"{reussis} déplacé(s)" + (f", {len(erreurs)} en échec : " + " ; ".join(erreurs[:10]) if erreurs else ""))[:2000]
    lot.range_le = datetime.now(timezone.utc)
    await db.commit()
    log.info("Lot de rangement appliqué", lot=str(lot.id), reussis=reussis, erreurs=len(erreurs))
    return lot


async def _journaliser(db: AsyncSession, lot: PlanLot, op: dict, source: str, destination: str) -> None:
    db.add(ReorgMove(batch_id=lot.id, document_id=None, chemin_source=source, chemin_dest=destination,
                     origine=ORIGINE, est_dossier=op["est_dossier"]))
    p = await db.get(PlanProposition, op["proposition_id"])
    if p is not None:
        p.statut = "rangee"
    await db.commit()   # chaque déplacement journalisé aussitôt


async def _session_ouverte(emp: Emplacement) -> Any:
    """La session SMB de l'emplacement, OUVERTE ; refus lisible si la Source ou le NAS manque."""
    from services.rangement import emplacement_smb

    try:
        session = await emplacement_smb.session_de(emp)
    except InventaireRefus as exc:
        raise RangementRefuse(exc.message) from exc
    try:
        await session.__aenter__()
    except Exception as exc:  # noqa: BLE001 — NAS éteint, compte refusé
        raise RangementRefuse(f"Le partage « {emp.partage} » est injoignable ({type(exc).__name__}) : "
                              "rien n'a été déplacé.") from exc
    return session


_ECRITURE_REFUSEE = ("Le compte de la Source n'a pas le droit d'écrire sur ce partage (droit DSM en lecture "
                     "seule) : rien de plus n'a bougé. Donner l'écriture est un geste séparé, dans DSM.")


async def _appliquer_smb(db: AsyncSession, lot: PlanLot, emp: Emplacement, arret) -> PlanLot:
    """`appliquer` pour un emplacement SMB : une session pour tout le lot, mêmes règles."""
    try:
        session = await _session_ouverte(emp)
    except RangementRefuse as exc:
        lot.statut, lot.message = "refuse", str(exc)
        await db.commit()
        raise
    try:
        rangeur = RangeurSmb(session, emp)
        try:
            await rangeur.verifier()
        except Exception as exc:  # noqa: BLE001
            message = str(exc) if isinstance(exc, RangementRefuse) else (
                f"Le partage « {emp.partage} » est illisible ({type(exc).__name__}) : rien n'a été déplacé.")
            lot.statut, lot.message = "refuse", message
            await db.commit()
            raise RangementRefuse(message) from exc
        lot.statut = "en_cours"
        await db.commit()
        reussis, erreurs = 0, []
        for op in lot.operations:
            if arret is not None and arret():
                erreurs.append("arrêté à la demande")
                break
            try:
                source, destination = await rangeur.deplacer(op)
            except RangementRefuse as exc:
                erreurs.append(f"{op['source']} : {exc}")
                continue
            except EcritureRefusee:
                erreurs.append(_ECRITURE_REFUSEE)
                break
            except Coupure as exc:
                erreurs.append(f"{op['source']} : NAS injoignable ({exc}), le lot s'arrête ici")
                break
            await _journaliser(db, lot, op, source, destination)
            reussis += 1
        return await _clore_lot(db, lot, reussis, erreurs)
    finally:
        await session.__aexit__(None, None, None)


def _est_smb(chemin: str) -> bool:
    return chemin[:6].lower() == "smb://"


def _remettre(source: str, destination: str) -> None:
    if not os.path.lexists(destination):
        raise RangementRefuse("introuvable à sa nouvelle place (déplacé depuis ?)")
    if os.path.lexists(source):
        raise RangementRefuse("l'ancienne place est reprise par un autre fichier")
    os.makedirs(os.path.dirname(source), exist_ok=True)
    os.rename(destination, source)


async def annuler(db: AsyncSession, lot: PlanLot, par: str | None, emp: Emplacement | None = None) -> PlanLot:
    """Annule CE lot (et lui seul) : chaque déplacement est défait en sens inverse. Les lignes du journal
    restent, datées de leur annulation ; ce qui ne peut pas revenir est signalé, jamais forcé."""
    if lot.statut not in ("range", "partiel", "annule_partiel"):
        raise RangementRefuse(f"Ce lot est « {lot.statut} » : rien à annuler.")
    moves = (await db.execute(select(ReorgMove).where(
        ReorgMove.batch_id == lot.id, ReorgMove.origine == ORIGINE, ReorgMove.annule_le.is_(None))
        .order_by(ReorgMove.applied_at.desc(), ReorgMove.id))).scalars().all()
    erreurs: list[str] = []
    rangeur: RangeurSmb | None = None
    session: Any = None
    if any(_est_smb(m.chemin_dest) for m in moves):
        # Journal en smb:// : l'annulation passe par la session de l'emplacement DU LOT.
        if emp is None or not emp.est_smb:
            raise RangementRefuse("Ce lot a été rangé par SMB, mais son emplacement n'est plus lu par SMB.")
        session = await _session_ouverte(emp)
        rangeur = RangeurSmb(session, emp)
    try:
        for m in reversed(sorted(moves, key=lambda x: x.applied_at or datetime.min.replace(tzinfo=timezone.utc))):
            try:
                if rangeur is not None and _est_smb(m.chemin_dest):
                    await rangeur.remettre(m.chemin_source, m.chemin_dest)
                else:
                    await asyncio.to_thread(_remettre, m.chemin_source, m.chemin_dest)
            except (OSError, RangementRefuse) as exc:
                erreurs.append(f"{m.chemin_dest} : {exc}")
                continue
            except EcritureRefusee:
                erreurs.append(_ECRITURE_REFUSEE)
                break
            except Coupure as exc:
                erreurs.append(f"NAS injoignable ({exc}) : l'annulation s'arrête ici, à reprendre")
                break
            m.annule_le, m.annule_par = datetime.now(timezone.utc), par
            await db.commit()
    finally:
        if session is not None:
            await session.__aexit__(None, None, None)
    for op in lot.operations:
        p = await db.get(PlanProposition, op["proposition_id"])
        if p is not None and p.statut == "rangee":
            p.statut = "validee"
    lot.statut = "annule" if not erreurs else "annule_partiel"
    lot.annule_le, lot.annule_par = datetime.now(timezone.utc), par
    remis = sum(m.annule_le is not None for m in moves)
    lot.message = (f"{remis} remis à leur place" + (" ; annulation incomplète : " + " ; ".join(erreurs[:10]) if erreurs else ""))[:2000]
    await db.commit()
    log.info("Lot de rangement annulé", lot=str(lot.id), erreurs=len(erreurs))
    return lot
