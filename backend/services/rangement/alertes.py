"""
Ce que le Rangement signale dans la cloche (plan rangement + mails, étape 11).

Appelé par le worker À LA FIN d'une tâche de rangement (`job_worker._run`), jamais par l'API : c'est le
worker qui porte le montage du NAS (place disque) et qui vient d'écrire l'inventaire. Chaque alerte
passe par `services/notifier.py` (destinataires, préférences, silence, dédoublonnage).

- **hors plan** : après un scan, les éléments sans proposition font enfiler un calcul du plan limité à
  eux (`nouveaux_seulement`, IA comprise) ; à la fin de ce calcul, ceux qui ne sont pas à leur place
  (`_hors_plan`) sont signalés UNE fois (`plan_propositions.signale_le`), avec la proposition — le jour même ;
- **place disque** : occupation du volume de l'emplacement, comparée au seuil de chaque personne ;
- **croissance anormale** : dossiers de 1er niveau qui ont grossi entre les deux derniers instantanés ;
- **nouvelles copies** : bilan des copies sur disque avant/après une passe ;
- **fin de tâches** : échecs, et les tâches qu'une personne a lancées et attend (lots, import, copies).
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, time, timezone

from sqlalchemy import and_, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from services import notifier
from services.notifier import Evenement
from services.rangement import service
from services.rangement.depot import Depot, Emplacement

log = get_logger(__name__)

LIEN_PLAN = "/rangement?onglet=plan"
LIEN_CARTE = "/rangement?onglet=carte"
LIEN_COPIES = "/doublons"
LISTE_MAX = 30
#: Une croissance n'est examinée qu'au-delà de ce plancher (les seuils de chacun s'appliquent ensuite).
CROISSANCE_PCT_MIN = 5

LIBELLES = {
    service.JOB_SCAN: "Scan de l'inventaire",
    service.JOB_NUIT: "Tournée de nuit de l'inventaire",
    service.JOB_IMPORT: "Import d'un export WizTree",
    service.JOB_ENVOI: "Inventaire envoyé par un poste",
    service.JOB_COPIES: "Recherche des copies sur disque",
    "plan_propositions": "Calcul du plan de classement",
    "rangement_appliquer": "Rangement d'un lot",
    "rangement_annuler": "Annulation d'un lot",
    "rangement_retirer_vides": "Retrait des dossiers vidés d'un lot",
    "plan_titres_episodes": "Titres des épisodes (Plex)",
}
#: Tâches dont la RÉUSSITE est annoncée : quelqu'un les a lancées et en attend l'issue. Les scans (dont
#: le rescan automatique après un lot) et la tournée de nuit ne sont annoncés qu'en cas d'échec.
REUSSITE_ANNONCEE = {"rangement_appliquer", "rangement_annuler", "rangement_retirer_vides", "plan_titres_episodes",
                     service.JOB_IMPORT, service.JOB_COPIES}
STATUTS_ECHEC = {"echec", "refuse"}


def _octets(n: int | float) -> str:
    from services.rangement.copies import taille_lisible
    return taille_lisible(int(n))


# --------------------------------------------------------------------------- #
# Calculs PURS                                                                 #
# --------------------------------------------------------------------------- #
def croissances(recent: dict[str, int], precedent: dict[str, int]) -> list[tuple[str, int, float]]:
    """Dossiers de 1er niveau qui ont grossi : (chemin, octets gagnés, %). Un dossier vide qui se
    remplit compte pour 1000 %. Triés du plus gros gain au plus petit."""
    sortie = []
    for chemin, taille in recent.items():
        if "/" in chemin or chemin not in precedent:
            continue
        gain = taille - precedent[chemin]
        if gain <= 0:
            continue
        pct = gain * 100 / precedent[chemin] if precedent[chemin] > 0 else 1000.0
        if pct >= CROISSANCE_PCT_MIN:
            sortie.append((chemin, gain, round(pct, 1)))
    return sorted(sortie, key=lambda x: (-x[1], x[0]))


def evenement_doublons(avant: dict | None, apres: dict | None) -> Evenement | None:
    """Des groupes de copies sont-ils apparus pendant la passe ? PURE."""
    if not avant or not apres:
        return None
    nouveaux = int(apres.get("nb_groupes", 0)) - int(avant.get("nb_groupes", 0))
    if nouveaux <= 0:
        return None
    return Evenement(
        type="rangement_doublons", cle="doublons",
        titre=f"🗂️ {nouveaux} nouveau(x) groupe(s) de copies sur disque",
        contenu=(f"La dernière passe a trouvé **{nouveaux}** nouveau(x) groupe(s) de fichiers identiques.\n\n"
                 f"En tout : {apres.get('nb_groupes', 0)} groupe(s), "
                 f"**{_octets(apres.get('recuperable', 0))}** récupérables."),
        lien=LIEN_COPIES)


def evenement_tache(type_: str, job_id: str, statut: str, resultat: dict | None, erreur: str | None) -> Evenement | None:
    """La fin d'une tâche de rangement mérite-t-elle une notification ? PURE."""
    if type_ not in LIBELLES:
        return None
    libelle = LIBELLES[type_]
    r = resultat or {}
    echec = statut == "failed" or r.get("statut") in STATUTS_ECHEC
    if not echec and not (statut == "completed" and type_ in REUSSITE_ANNONCEE):
        return None
    lien = LIEN_COPIES if type_ == service.JOB_COPIES else LIEN_PLAN if type_ in (
        "plan_propositions", "rangement_appliquer", "rangement_annuler", "rangement_retirer_vides",
        "plan_titres_episodes") else LIEN_CARTE
    if echec:
        motif = erreur or r.get("message") or r.get("statut") or "raison inconnue"
        return Evenement(type="rangement_taches", cle=f"tache:{job_id}", titre=f"⚠️ {libelle} : échec",
                         contenu=f"**{libelle}** n'a pas abouti.\n\n> {str(motif)[:500]}", lien=lien)
    details = r.get("message") or ""
    if type_ == service.JOB_COPIES:
        details = details or f"{r.get('completes', 0)} empreinte(s) complète(s) calculée(s)."
    etat = {"range": "rangé", "partiel": "rangé en partie", "annule": "annulé",
            "annule_partiel": "annulé en partie"}.get(str(r.get("statut")), "terminé")
    return Evenement(type="rangement_taches", cle=f"tache:{job_id}", titre=f"✅ {libelle} : {etat}",
                     contenu=f"**{libelle}** : {etat}." + (f"\n\n{details}" if details else ""), lien=lien)


# --------------------------------------------------------------------------- #
# Après un scan                                                                #
# --------------------------------------------------------------------------- #
def occupation(racine: str) -> tuple[float, int] | None:
    """(% occupé, octets libres) du volume qui porte `racine` ; None s'il n'est pas lisible."""
    try:
        if not os.path.isdir(racine):
            return None
        u = shutil.disk_usage(racine)
    except OSError:
        return None
    return (round(u.used * 100 / u.total, 1) if u.total else 0.0), u.free


async def _alerte_disque(db: AsyncSession, emp: Emplacement) -> None:
    if not emp.sur_serveur:
        return
    mesure = occupation(emp.racine)
    if mesure is None:
        return
    pct, libre = mesure
    await notifier.notifier(db, Evenement(
        type="rangement_disque", cle=f"disque:{emp.id}", titre=f"💽 {emp.libelle} : disque occupé à {pct:g} %",
        contenu=f"Le volume de **{emp.libelle}** est occupé à **{pct:g} %** ; il reste {_octets(libre)}.",
        lien=LIEN_CARTE, mesures={"pct": pct}))


async def _alerte_croissance(db: AsyncSession, depot: Depot, emp: Emplacement) -> None:
    scans = await depot.scans_avec_instantane(emp.id, 2)
    if len(scans) < 2:
        return
    recent, precedent = await depot.tailles_instantane(scans[0]), await depot.tailles_instantane(scans[1])
    for chemin, gain, pct in croissances(recent, precedent)[:10]:
        await notifier.notifier(db, Evenement(
            type="rangement_croissance", cle=f"croissance:{emp.id}:{chemin}",
            titre=f"📈 {emp.libelle} › {chemin} : +{_octets(gain)}",
            contenu=(f"Le dossier **{chemin}** de {emp.libelle} a grossi de **{_octets(gain)}** "
                     f"(+{pct:g} %) depuis le scan précédent ({_octets(precedent[chemin])} → "
                     f"{_octets(recent[chemin])})."),
            lien=LIEN_CARTE, mesures={"pct": pct, "octets": gain}))


async def _enfiler_plan(db: AsyncSession, depot: Depot, emp: Emplacement) -> str | None:
    """Des éléments nouveaux attendent une proposition : un calcul limité à eux, s'il n'y en a pas déjà un."""
    from models.job import Job
    from services import job_worker
    from services.rangement import plan

    nouveaux = await plan.nouveaux_elements(db, depot, emp)
    if not nouveaux:
        return None
    en_vol = (await db.execute(select(Job.parametres).where(
        Job.type == "plan_propositions", Job.statut.in_(("pending", "running"))))).scalars().all()
    if any(int((p or {}).get("emplacement_id", -1)) == emp.id for p in en_vol):
        return None
    job_id = await job_worker.enqueue(db, "plan_propositions", {
        "emplacement_id": emp.id, "nouveaux_seulement": True, "cible": f"emplacement:{emp.id}"})
    log.info("Plan de classement : nouveaux éléments à placer", emplacement_id=emp.id, nb=len(nouveaux))
    return job_id


async def apres_scan(db: AsyncSession, depot: Depot, emp: Emplacement) -> None:
    for etape in (_alerte_disque(db, emp), _alerte_croissance(db, depot, emp), _enfiler_plan(db, depot, emp)):
        try:
            await etape
        except Exception:  # noqa: BLE001 — une alerte manquée ne bloque pas les suivantes
            log.warning("Alerte du rangement impossible", emplacement_id=emp.id, exc_info=True)


# --------------------------------------------------------------------------- #
# Hors plan                                                                    #
# --------------------------------------------------------------------------- #
def _hors_plan():
    """Est hors plan : ce que le plan veut déplacer (`proposee`), et ce qui traîne à la racine du partage
    sans place trouvée. Un élément déjà DANS une rubrique sur lequel le plan n'a pas d'avis (`sans_place`
    sous un nœud) est là où quelqu'un l'a mis : il n'est pas signalé."""
    from models.plan_classement import PlanProposition
    return or_(PlanProposition.statut == "proposee",
               and_(PlanProposition.statut == "sans_place", not_(PlanProposition.chemin.contains("/"))))


def _debut_du_jour_utc() -> datetime:
    local = service.maintenant_local()
    return datetime.combine(local.date(), time(0), tzinfo=local.tzinfo).astimezone(timezone.utc)


async def signaler_hors_plan(db: AsyncSession, emp: Emplacement) -> int:
    """Marque les éléments hors plan pas encore signalés, puis (re)écrit LA notification du jour de
    l'emplacement avec tous ceux signalés aujourd'hui et toujours hors plan. Rend le nombre de nouveaux."""
    from models.plan_classement import PlanProposition

    maintenant = datetime.now(timezone.utc)
    nouveaux = list((await db.execute(select(PlanProposition).where(
        PlanProposition.emplacement_id == emp.id, _hors_plan(),
        PlanProposition.signale_le.is_(None)))).scalars().all())
    if not nouveaux:
        return 0
    for p in nouveaux:
        p.signale_le = maintenant
    await db.flush()
    du_jour = list((await db.execute(select(PlanProposition).where(
        PlanProposition.emplacement_id == emp.id, _hors_plan(),
        PlanProposition.signale_le >= _debut_du_jour_utc()).order_by(PlanProposition.chemin))).scalars().all())
    lignes = []
    for p in du_jour[:LISTE_MAX]:
        if p.destination:
            lignes.append(f"- `{p.chemin}` → irait dans **{p.destination}**"
                          + (f" — {p.raison}" if p.raison else ""))
        else:
            lignes.append(f"- `{p.chemin}` — aucune place proposée" + (f" ({p.raison})" if p.raison else ""))
    if len(du_jour) > LISTE_MAX:
        lignes.append(f"- … et {len(du_jour) - LISTE_MAX} autre(s)")
    jour = service.maintenant_local().date().isoformat()
    await notifier.notifier(db, Evenement(
        type="rangement_hors_plan", cle=f"hors_plan:{emp.id}:{jour}",
        titre=f"📂 {emp.libelle} : {len(du_jour)} élément(s) hors du plan de classement",
        contenu=("Ces éléments ne sont pas à la place que le plan prévoit. Rien n'est déplacé sans "
                 "votre validation (*Rangement › Plan de classement*).\n\n" + "\n".join(lignes)),
        lien=LIEN_PLAN))
    return len(nouveaux)


# --------------------------------------------------------------------------- #
# Point d'entrée du worker                                                     #
# --------------------------------------------------------------------------- #
TYPES_SUIVIS = set(LIBELLES)


async def _emplacements_scannes(depot: Depot, resultat: dict) -> list[Emplacement]:
    """Emplacements dont la tournée vient de terminer un scan."""
    ids = {s.get("scan_id") for s in (resultat.get("scans") or []) if s.get("statut") == "termine"}
    sortie = []
    for emp in await depot.emplacements(actifs_seulement=True):
        dernier = await depot.dernier_scan(emp.id)
        if dernier and dernier.get("id") in ids:
            sortie.append(emp)
    return sortie


async def apres_tache(type_: str, job_id: str, statut: str, parametres: dict | None,
                      resultat: dict | None, erreur: str | None) -> None:
    """Fin d'une tâche de rangement : notifications et suites. N'échoue jamais."""
    if type_ not in TYPES_SUIVIS:
        return
    from database import AsyncSessionLocal

    p, r = parametres or {}, resultat or {}
    try:
        async with AsyncSessionLocal() as db:
            ev = evenement_tache(type_, job_id, statut, r, erreur)
            if ev is not None:
                await notifier.notifier(db, ev, proprietaire=p.get("proprietaire"))
            if statut == "completed":
                depot = service.fabrique()
                if depot is not None:
                    await _suites(db, depot, type_, p, r)
            await db.commit()
    except Exception:  # noqa: BLE001 — la cloche ne fait jamais échouer une tâche
        log.warning("Notifications du rangement impossibles", type=type_, job_id=job_id, exc_info=True)


async def _suites(db: AsyncSession, depot: Depot, type_: str, p: dict, r: dict) -> None:
    if type_ in (service.JOB_SCAN, service.JOB_ENVOI) and r.get("statut") == "termine":
        emp = await depot.emplacement(int(p["emplacement_id"]))
        if emp is not None:
            await apres_scan(db, depot, emp)
    elif type_ == service.JOB_NUIT:
        for emp in await _emplacements_scannes(depot, r):
            await apres_scan(db, depot, emp)
        copies = r.get("copies") or {}
        ev = evenement_doublons(copies.get("bilan_avant"), copies.get("bilan_apres"))
        if ev is not None:
            await notifier.notifier(db, ev)
    elif type_ == service.JOB_COPIES:
        ev = evenement_doublons(r.get("bilan_avant"), r.get("bilan_apres"))
        if ev is not None:
            await notifier.notifier(db, ev)
    elif type_ == "plan_propositions" and r.get("statut") == "termine":
        emp = await depot.emplacement(int(p["emplacement_id"]))
        if emp is not None:
            await signaler_hors_plan(db, emp)
