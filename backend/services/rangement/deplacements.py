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

from smb.smb_structs import OperationFailure
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from models.plan_classement import PlanLot, PlanProposition
from models.reorg import ReorgMove
from services.rangement.deplacements_smb import Coupure, EcritureRefusee, RangeurSmb, nom_libre_sans_casse
from services.rangement.depot import Connu, Depot, Emplacement, chemin_enfant
from services.rangement.erreurs import InventaireRefus, RangementRefuse
from services.rangement.scan import contient

log = get_logger(__name__)
ORIGINE = "rangement"

__all__ = ["RangementRefuse", "annuler", "apercu", "appliquer", "creer_lot", "nom_libre", "retirer_dossiers_vides"]

#: Ce qu'un dossier « vidé » peut encore contenir sans que ce soit à l'utilisateur : l'index de vignettes
#: que le Synology dépose dans chaque dossier de médias. Il est retiré avec le dossier (DSM le recrée).
RESIDUS = frozenset({"@eadir"})


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
    deja_pris: dict[str, dict[str, Connu]] = {}
    ops: list[dict] = []
    # SMB ne distingue pas la casse : « Photo.jpg » prend la place de « photo.jpg ».
    libre = nom_libre_sans_casse if emp.est_smb else nom_libre
    for p in props:
        dest_dossier = p.destination.strip("/")
        if p.contenu:
            # Pack de série vidé dans sa saison : chaque élément qu'il contient part, sous SON nom.
            if dest_dossier == p.chemin:
                continue
            elements = [(chemin_enfant(p.chemin, nom), nom, c.est_dossier, _taille(c))
                        for nom, c in sorted((await depot.enfants(emp.id, p.chemin)).items())]
        else:
            if posixpath.dirname(p.chemin) == dest_dossier:
                continue   # déjà au bon endroit
            if dest_dossier == p.chemin or dest_dossier.startswith(p.chemin + "/"):
                continue   # un dossier ne se range pas dans lui-même
            elements = [(p.chemin, posixpath.basename(p.chemin), p.est_dossier, p.taille)]
        if dest_dossier not in deja_pris:
            deja_pris[dest_dossier] = dict(await depot.enfants(emp.id, dest_dossier))
        place = deja_pris[dest_dossier]
        for source, nom, est_dossier, taille in elements:
            if dest_dossier == source or dest_dossier.startswith(source + "/"):
                continue
            meme = next((c for n, c in place.items() if n.casefold() == nom.casefold()), None)
            if meme is not None and meme.est_dossier == est_dossier and _taille(meme) == taille:
                # Le MÊME élément est déjà là (même nom, même taille) : un doublon, pas un « nom_(2) ».
                # Il reste où il est ; la page Doublons s'en charge (cas d'Outlander, 15/11/2026).
                continue
            final = libre(nom, set(place), est_dossier)
            place[final] = Connu(final, est_dossier, taille, None)
            ops.append({"proposition_id": p.id, "source": source, "dossier": dest_dossier,
                        "nom": final, "renomme": final != nom, "est_dossier": est_dossier, "taille": taille})
    return ops


def _taille(c: Connu) -> int:
    return (c.totaux[0] if c.totaux else 0) if c.est_dossier else c.taille


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


# --------------------------------------------------------------------------- #
# Retirer les dossiers vidés (option demandée par Thomas, 15/11/2026)          #
# --------------------------------------------------------------------------- #
async def dossiers_vides(db: AsyncSession, lot: PlanLot) -> list[str]:
    """Les dossiers dont ce lot a sorti le CONTENU (packs de série, « Saison 1 »…), du plus profond au
    moins profond. Seuls eux sont candidats : le Rangement ne retire jamais un dossier qu'il n'a pas vidé."""
    ids = {op["proposition_id"] for op in lot.operations}
    chemins = set()
    for pid in ids:
        p = await db.get(PlanProposition, pid)
        if p is not None and p.contenu:
            chemins.add(p.chemin)
    return sorted(chemins, key=lambda c: (-c.count("/"), c))


def _retirer_local(racine: str, relatif: str) -> bool:
    """Retire `racine/relatif` s'il ne contient plus que des résidus (`@eaDir`). Vrai si retiré."""
    import shutil
    dossier = os.path.join(racine, *relatif.split("/"))
    if not os.path.isdir(dossier) or os.path.islink(dossier):
        return False
    reel = os.path.realpath(racine)
    if not contient(reel, os.path.realpath(dossier)) or os.path.realpath(dossier) == reel:
        raise RangementRefuse("hors de l'emplacement")
    restes = os.listdir(dossier)
    if any(n.casefold() not in RESIDUS for n in restes):
        return False
    for n in restes:
        shutil.rmtree(os.path.join(dossier, n))
    os.rmdir(dossier)
    return True


async def _vider_residu_smb(session: Any, chemin: str) -> None:
    for e in await session.lister(chemin):
        sous = posixpath.join(chemin, e.nom)
        if e.est_dossier:
            await _vider_residu_smb(session, sous)
            await session.supprimer_dossier_vide(sous)
        else:
            await session.supprimer_fichier(sous)


async def _retirer_smb(session: Any, rangeur: RangeurSmb, relatif: str) -> bool:
    try:
        chemin = rangeur.dans_le_partage(relatif)
    except ValueError as exc:
        raise RangementRefuse("hors de l'emplacement") from exc
    if chemin == rangeur.base:
        raise RangementRefuse("la racine de l'emplacement ne se retire pas")
    e = await session.stat(chemin)
    if e is None or not e.est_dossier:
        return False
    restes = await session.lister(chemin)
    if any(x.nom.casefold() not in RESIDUS for x in restes):
        return False
    for x in restes:
        sous = posixpath.join(chemin, x.nom)
        await _vider_residu_smb(session, sous)
        await session.supprimer_dossier_vide(sous)
    await session.supprimer_dossier_vide(chemin)
    return True


async def retirer_dossiers_vides(db: AsyncSession, lot: PlanLot, emp: Emplacement) -> dict:
    """Retire les dossiers que ce lot a VIDÉS, s'ils ne contiennent plus rien (ou seulement `@eaDir`).
    Un dossier où il reste quoi que ce soit est gardé. Réversible : annuler le lot recrée le dossier
    d'origine de chaque fichier remis à sa place."""
    if lot.statut not in ("range", "partiel"):
        raise RangementRefuse(f"Ce lot est « {lot.statut} » : rien à retirer.")
    chemins = await dossiers_vides(db, lot)
    retires: list[str] = []
    gardes: list[str] = []
    erreurs: list[str] = []
    if emp.est_smb:
        session = await _session_ouverte(emp)
        try:
            rangeur = RangeurSmb(session, emp)
            for c in chemins:
                try:
                    (retires if await _retirer_smb(session, rangeur, c) else gardes).append(c)
                except (RangementRefuse, OperationFailure) as exc:
                    erreurs.append(f"{c} : {exc if isinstance(exc, RangementRefuse) else 'refusé par le NAS'}")
        finally:
            await session.__aexit__(None, None, None)
    else:
        for c in chemins:
            try:
                (retires if await asyncio.to_thread(_retirer_local, emp.racine, c) else gardes).append(c)
            except (OSError, RangementRefuse) as exc:
                erreurs.append(f"{c} : {exc}")
    bilan = f"{len(retires)} dossier(s) vidé(s) retiré(s)" + (f", {len(gardes)} gardé(s) (pas vides)" if gardes else "") \
        + (f", {len(erreurs)} en échec : " + " ; ".join(erreurs[:5]) if erreurs else "")
    lot.message = (f"{lot.message} — {bilan}" if lot.message else bilan)[:2000]
    await db.commit()
    log.info("Dossiers vidés retirés", lot=str(lot.id), retires=len(retires), gardes=len(gardes), erreurs=len(erreurs))
    return {"statut": "termine" if not erreurs else "partiel", "message": bilan, "retires": len(retires),
            "gardes": len(gardes)}


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
