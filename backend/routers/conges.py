"""
Router Congés de naissance — /api/dossiers/{ref}/conges
=======================================================
Le panneau « Congés de naissance » du **planning** d'un dossier qui déclare la capacité
`conges` (« Devenir parent »). Deux gestes, dans cet ordre :

  GET    /dossiers/{ref}/conges          → paramètres + plan calculé des deux parents
  PUT    /dossiers/{ref}/conges          → SIMULER : enregistre les paramètres, rend le plan
  POST   /dossiers/{ref}/conges/agenda   → VALIDER : pose dans le planning, par parent / type
  DELETE /dossiers/{ref}/conges/agenda   → retire ce qui a été validé (tout, un parent, un type)

**Les paramètres vivent dans la table `config`** (clé `conges_naissance`, JSON), lue et écrite
directement comme les réponses fiscales : une poignée de valeurs par foyer, sans relation ni
cycle de vie propre. Pas via le cache de `runtime_config`, qui est local à chaque processus —
un paramètre enregistré par un worker ne doit pas rester invisible à l'autre.

## Simuler n'écrit rien dans l'agenda, et c'est voulu

On essaie des scénarios — un mois ou deux, fractionner ou pas. Réécrire le planning à chaque
case cochée le remplirait d'hypothèses abandonnées. La validation est donc un **geste**, par
groupe (un parent × un type de congé), et chaque groupe dit son état : *simulé*, *validé*,
*modifié depuis la validation*, ou *obsolète*. Un calendrier qui diverge en silence est celui
qu'on croit.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.config import Config
from models.jalon import Jalon
from services.conges import calcul, regles

log = get_logger(__name__)
router = APIRouter()

CLE_CONFIG = "conges_naissance"
PREFIXE_ORIGINE = "conges:"


# ─── Schémas ───────────────────────────────────────────────────────────────────────────

class MereIn(BaseModel):
    salariee: bool | None = None
    report_prenatal_semaines: int | None = Field(default=None, ge=0, le=regles.REPORT_PRENATAL_MAX_SEMAINES)
    csn_mois: int | None = Field(default=None, ge=0, le=2)
    csn_fractionne: bool | None = None
    csn_debut: date | None = None
    csn_debut_2: date | None = None


class CoparentIn(BaseModel):
    salarie: bool | None = None
    solde_pris: bool | None = None
    solde_fractionne: bool | None = None
    solde_debut: date | None = None
    solde_jours_1: int | None = Field(default=None, ge=1, le=regles.PATERNITE_SOLDE_JOURS_MULTIPLES)
    solde_debut_2: date | None = None
    csn_mois: int | None = Field(default=None, ge=0, le=2)
    csn_fractionne: bool | None = None
    csn_debut: date | None = None
    csn_debut_2: date | None = None


class CongesIn(BaseModel):
    """
    Tout est facultatif et **fusionné** : envoyer seulement la durée du congé du co-parent ne
    doit pas effacer le report de prénatal réglé pour la mère. Un champ envoyé à `null`
    l'efface (retour au calcul par défaut) — c'est ainsi qu'on revient à « enchaîner ».
    """
    situation: str | None = None
    naissance_reelle: date | None = None
    mere: MereIn | None = None
    coparent: CoparentIn | None = None


# ─── Persistance ───────────────────────────────────────────────────────────────────────

async def _get_dossier(db: AsyncSession, ref: str):
    from routers.dossiers import _get_dossier as get_dossier
    return await get_dossier(db, ref)


async def _lire(db: AsyncSession) -> dict:
    ligne = await db.get(Config, CLE_CONFIG)
    if not ligne or not ligne.valeur:
        return {}
    try:
        data = json.loads(ligne.valeur)
    except json.JSONDecodeError:
        log.warning("Paramètres de congés illisibles, ignorés", cle=CLE_CONFIG)
        return {}
    return data if isinstance(data, dict) else {}


async def _ecrire(db: AsyncSession, data: dict) -> None:
    valeur = json.dumps(data, ensure_ascii=False)
    ligne = await db.get(Config, CLE_CONFIG)
    if ligne:
        ligne.valeur = valeur
    else:
        db.add(Config(cle=CLE_CONFIG, valeur=valeur))
    await db.commit()


def _d(valeur) -> date | None:
    if not valeur:
        return None
    try:
        return date.fromisoformat(str(valeur)[:10])
    except ValueError:
        return None


# ─── Calcul et sérialisation ───────────────────────────────────────────────────────────

def _plan(data: dict, terme: date) -> calcul.Plan:
    m, c = data.get("mere") or {}, data.get("coparent") or {}
    return calcul.calculer(
        terme=terme,
        naissance=_d(data.get("naissance_reelle")),
        situation=data.get("situation") or "rang_1_2",
        mere=calcul.ParamsMere(
            salariee=m.get("salariee", True),
            report_prenatal_semaines=int(m.get("report_prenatal_semaines") or 0),
            csn_mois=int(m.get("csn_mois") or 0),
            csn_fractionne=bool(m.get("csn_fractionne")),
            csn_debut=_d(m.get("csn_debut")), csn_debut_2=_d(m.get("csn_debut_2")),
        ),
        coparent=calcul.ParamsCoparent(
            salarie=c.get("salarie", True),
            solde_pris=c.get("solde_pris", True),
            solde_fractionne=bool(c.get("solde_fractionne")),
            solde_debut=_d(c.get("solde_debut")),
            solde_jours_1=c.get("solde_jours_1"),
            solde_debut_2=_d(c.get("solde_debut_2")),
            csn_mois=int(c.get("csn_mois") or 0),
            csn_fractionne=bool(c.get("csn_fractionne")),
            csn_debut=_d(c.get("csn_debut")), csn_debut_2=_d(c.get("csn_debut_2")),
        ),
    )


def _parent(p: calcul.PlanParent) -> dict:
    return {
        "periodes": [{"cle": x.cle, "libelle": x.libelle, "debut": x.debut.isoformat(),
                      "fin": x.fin.isoformat(), "jours": x.jours, "obligatoire": x.obligatoire,
                      "paye_par": x.paye_par, "note": x.note} for x in p.periodes],
        "echeances": [{"cle": e.cle, "libelle": e.libelle, "date": e.date.isoformat(),
                       "note": e.note, "obligatoire": e.obligatoire,
                       "depassee": e.date < date.today()} for e in p.echeances],
        "alertes": [{"niveau": a.niveau, "message": a.message} for a in p.alertes],
        "reprise": p.reprise.isoformat() if p.reprise else None,
    }


# ─── L'agenda : simuler, puis valider par parent et par type de congé ─────────────────
#
# SIMULER = enregistrer des paramètres et regarder le plan : rien ne s'écrit dans le planning.
# VALIDER = poser un GROUPE (un parent × un type de congé) dans le planning.
#
# On valide par groupe parce que les décisions ne se prennent pas en même temps : le congé de
# maternité se déclare au 6ᵉ mois, le congé supplémentaire du co-parent se décide souvent après
# la naissance. Tout valider d'un coup mettrait dans l'agenda des hypothèses encore ouvertes.

PARENTS = {calcul.MERE: "Mère", calcul.COPARENT: "Co-parent"}
TYPES = {
    "maternite": "Congé de maternité",
    "naissance": "Congé de naissance",
    "paternite": "Congé de paternité et d'accueil",
    "csn": "Congé supplémentaire de naissance",
    "reprise": "Reprise du travail",
}


def _type_de(cle: str) -> str:
    """Le type d'un jalon, déduit de sa clé stable (`maternite_prenatal` → `maternite`)."""
    for t in ("maternite", "paternite", "csn", "naissance", "reprise"):
        if cle == t or cle.startswith(f"{t}_"):
            return t
    return "autre"


def _jalons_attendus(plan: calcul.Plan) -> list[dict]:
    """
    Ce que le plan pose dans l'agenda : chaque congé à sa date de début, chaque préavis, et la
    reprise du travail. L'`origine` (`conges:<parent>:<clé>`) est la CLÉ STABLE du jalon — c'est
    elle qui permet de déplacer un congé quand ses dates changent au lieu d'en semer un second.
    """
    attendus: list[dict] = []
    for p in (plan.mere, plan.coparent):
        qui = PARENTS[p.parent]
        for x in p.periodes:
            attendus.append({
                "parent": p.parent, "type": _type_de(x.cle),
                "origine": f"{PREFIXE_ORIGINE}{p.parent}:{x.cle}",
                "titre": f"{qui} — {x.libelle}",
                "date": x.debut,
                "detail": f"Du {x.debut.strftime('%d/%m/%Y')} au {x.fin.strftime('%d/%m/%Y')} "
                          f"({x.jours} jours) · {x.paye_par}." + (f" {x.note}" if x.note else ""),
                "obligatoire": x.obligatoire, "echeance": None,
            })
        for e in p.echeances:
            attendus.append({
                "parent": p.parent, "type": _type_de(e.cle),
                "origine": f"{PREFIXE_ORIGINE}{p.parent}:{e.cle}",
                "titre": f"{qui} — {e.libelle}",
                "date": e.date, "detail": e.note, "obligatoire": e.obligatoire,
                "echeance": f"Au plus tard le {e.date.strftime('%d/%m/%Y')}",
            })
        if p.reprise:
            attendus.append({
                "parent": p.parent, "type": "reprise",
                "origine": f"{PREFIXE_ORIGINE}{p.parent}:reprise",
                "titre": f"{qui} — Reprise du travail",
                "date": p.reprise,
                "detail": "Fin de tous les congés prévus"
                          + (" (prévisionnel)." if plan.previsionnel else "."),
                "obligatoire": False, "echeance": None,
            })
    return attendus


def _groupe(parent: str, type_: str) -> str:
    return f"{parent}:{type_}"


def _groupe_de_origine(origine: str) -> str:
    """`conges:mere:maternite_prenatal` → `mere:maternite`."""
    _, parent, cle = (origine.split(":", 2) + ["", ""])[:3]
    return _groupe(parent, _type_de(cle))


def _empreinte(attendus: list[dict]) -> str:
    """Empreinte du contenu posé — change dès qu'une date, un titre ou un détail change."""
    brut = json.dumps(sorted([a["origine"], a["titre"], a["date"].isoformat(), a["detail"] or ""]
                             for a in attendus), ensure_ascii=False)
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()[:16]


def _par_groupe(attendus: list[dict]) -> dict[str, list[dict]]:
    groupes: dict[str, list[dict]] = {}
    for a in attendus:
        groupes.setdefault(_groupe(a["parent"], a["type"]), []).append(a)
    return groupes


async def _poses(db: AsyncSession, dossier_id) -> list[Jalon]:
    return list((await db.execute(
        select(Jalon).where(Jalon.dossier_id == dossier_id,
                            Jalon.origine.like(f"{PREFIXE_ORIGINE}%"))
    )).scalars().all())


def _dans_portee(groupe: str, parents: list[str] | None, types: list[str] | None) -> bool:
    parent, type_ = groupe.split(":", 1)
    if parents and parent not in parents:
        return False
    # La reprise du travail suit TOUJOURS son parent : elle résume ses congés, elle n'est pas
    # un choix à part — la valider seule, ou oublier de la valider, n'aurait pas de sens.
    if types and type_ not in types and type_ != "reprise":
        return False
    return True


async def _reponse(db: AsyncSession, data: dict, dossier_id) -> dict:
    from routers.dossiers import _ancre_courante

    terme = _ancre_courante()
    base = {
        "parametres": {k: v for k, v in data.items() if k != "agenda_empreintes"},
        "terme": terme.isoformat() if terme else None,
        "situations": [{"cle": k, "libelle": v.libelle, "aide": v.aide}
                       for k, v in regles.SITUATIONS.items()],
        "regles": {"verifie_le": regles.VERIFIE_LE.isoformat(), "sources": regles.SOURCES,
                   "avertissement": regles.AVERTISSEMENT},
    }
    if terme is None:
        # Sans terme rien n'est datable : on le DIT, au lieu de rendre un plan vide qui se
        # lirait « aucun congé ».
        return {**base, "plan": None, "agenda": {"a_jour": False, "groupes": []},
                "message": "Renseignez la date du terme (bouton « Modifier » du planning) : "
                           "tous les congés se calculent depuis elle."}

    plan = _plan(data, terme)
    attendus = _par_groupe(_jalons_attendus(plan))
    empreintes = data.get("agenda_empreintes") or {}

    comptes: dict[str, int] = {}
    for j in await _poses(db, dossier_id):
        g = _groupe_de_origine(j.origine)
        comptes[g] = comptes.get(g, 0) + 1

    tous = []
    for g in list(attendus) + [g for g in comptes if g not in attendus]:
        parent, type_ = g.split(":", 1)
        prevu = attendus.get(g)
        pose = comptes.get(g, 0) > 0
        tous.append({
            "parent": parent, "type": type_, "libelle": TYPES.get(type_, type_),
            "etat": ("obsolete" if prevu is None                      # posé, mais plus au plan
                     else "simule" if not pose                        # jamais validé
                     else "valide" if empreintes.get(g) == _empreinte(prevu)
                     else "modifie"),                                 # validé, puis changé
            "nb_poses": comptes.get(g, 0),
        })
    # La reprise du travail n'a pas de bouton à elle (elle suit son parent), mais elle COMPTE
    # pour dire si l'agenda est à jour : une date de reprise périmée est une date fausse.
    groupes = [g for g in tous if g["type"] != "reprise"]

    return {
        **base,
        "plan": {
            "naissance": plan.naissance.isoformat() if plan.naissance else None,
            "previsionnel": plan.previsionnel,
            "alertes": [{"niveau": a.niveau, "message": a.message} for a in plan.alertes],
            "mere": _parent(plan.mere),
            "coparent": _parent(plan.coparent),
        },
        "agenda": {
            # « À jour » = quelque chose a été validé, et rien de validé n'a divergé depuis.
            "a_jour": any(g["etat"] == "valide" for g in groupes)
                      and not any(g["etat"] in ("modifie", "obsolete") for g in tous),
            "groupes": groupes,
        },
    }


# ─── Routes ────────────────────────────────────────────────────────────────────────────

class ValiderIn(BaseModel):
    """Sans rien préciser : tout est validé. Sinon, seulement les parents et types indiqués."""
    parents: list[str] | None = None
    types: list[str] | None = None


@router.get("/dossiers/{ref}/conges", tags=["Dossiers"])
async def lire(ref: str, db: AsyncSession = Depends(get_db)) -> dict:
    d = await _get_dossier(db, ref)
    return await _reponse(db, await _lire(db), d.id)


@router.put("/dossiers/{ref}/conges", tags=["Dossiers"])
async def simuler(ref: str, body: CongesIn, db: AsyncSession = Depends(get_db)) -> dict:
    """
    SIMULER : enregistre les paramètres et rend le plan. **Rien ne s'écrit dans l'agenda** — on
    peut essayer un mois puis deux, fractionner puis non, sans remplir le planning d'hypothèses.
    """
    d = await _get_dossier(db, ref)
    data = await _lire(db)
    fournis = body.model_dump(exclude_unset=True, mode="json")

    if "situation" in fournis and fournis["situation"] not in regles.SITUATIONS:
        raise HTTPException(status_code=422, detail="Situation inconnue")

    for cle in ("situation", "naissance_reelle"):
        if cle in fournis:
            data[cle] = fournis[cle]
    for parent in PARENTS:
        if fournis.get(parent) is not None:
            data[parent] = {**(data.get(parent) or {}), **fournis[parent]}

    await _ecrire(db, data)
    log.info("Congés simulés", champs=sorted(fournis.keys()))
    return await _reponse(db, data, d.id)


@router.post("/dossiers/{ref}/conges/agenda", tags=["Dossiers"])
async def valider(ref: str, body: ValiderIn | None = None,
                  db: AsyncSession = Depends(get_db)) -> dict:
    """
    VALIDER : pose dans le planning les congés des parents et types choisis — **idempotent**.

    Un jalon déjà posé est **déplacé** (même `origine`), jamais dupliqué. Un jalon de la portée
    devenu sans objet (on renonce au congé supplémentaire) est retiré — **sauf s'il a été coché
    fait** : le suivi de l'utilisateur ne s'efface pas parce qu'un scénario a changé. Ce qui est
    hors de la portée n'est pas touché.
    """
    from routers.dossiers import _ancre_courante, _mois_depuis_date

    d = await _get_dossier(db, ref)
    terme = _ancre_courante()
    if terme is None:
        raise HTTPException(status_code=400,
                            detail="Renseignez d'abord la date du terme : rien n'est datable sans elle.")
    parents = (body.parents if body else None) or None
    types = (body.types if body else None) or None
    for p in parents or []:
        if p not in PARENTS:
            raise HTTPException(status_code=422, detail=f"Parent inconnu : {p}")
    for t in types or []:
        if t not in TYPES:
            raise HTTPException(status_code=422, detail=f"Type de congé inconnu : {t}")

    data = await _lire(db)
    attendus = _par_groupe(_jalons_attendus(_plan(data, terme)))
    existants = {j.origine: j for j in await _poses(db, d.id)}
    empreintes = dict(data.get("agenda_empreintes") or {})

    crees = maj = retires = 0
    vus: set[str] = set()
    for groupe, jalons in attendus.items():
        if not _dans_portee(groupe, parents, types):
            continue
        for a in jalons:
            vus.add(a["origine"])
            mois = _mois_depuis_date(a["date"], terme)
            j = existants.get(a["origine"])
            if j is None:
                position = ((await db.execute(
                    select(func.max(Jalon.position)).where(Jalon.dossier_id == d.id,
                                                           Jalon.mois == mois)
                )).scalar() or 0) + 1
                j = Jalon(dossier_id=d.id, origine=a["origine"], categorie="conges",
                          position=position, mois=mois, titre=a["titre"])
                db.add(j)
                crees += 1
            else:
                maj += 1
            # Le rendez-vous est réécrit ; le SUIVI (fait, note perso) ne l'est jamais.
            j.titre, j.detail, j.date_reelle, j.mois = a["titre"], a["detail"], a["date"], mois
            j.obligatoire, j.echeance, j.categorie = a["obligatoire"], a["echeance"], "conges"
        empreintes[groupe] = _empreinte(jalons)

    for origine, j in existants.items():
        groupe = _groupe_de_origine(origine)
        if origine in vus or not _dans_portee(groupe, parents, types):
            continue
        if not j.fait:
            await db.delete(j)
            retires += 1
        if groupe not in attendus:
            empreintes.pop(groupe, None)

    data["agenda_empreintes"] = empreintes
    await _ecrire(db, data)
    log.info("Congés validés dans l'agenda", dossier=d.slug, parents=parents, types=types,
             crees=crees, maj=maj, retires=retires)
    return {"crees": crees, "mis_a_jour": maj, "retires": retires,
            **(await _reponse(db, data, d.id))}


@router.delete("/dossiers/{ref}/conges/agenda", tags=["Dossiers"])
async def retirer(ref: str, parent: str | None = None, type: str | None = None,
                  db: AsyncSession = Depends(get_db)) -> dict:
    """
    Retire de l'agenda ce qui a été validé — tout, ou un parent, ou un type de congé. Ce qui a
    été coché fait reste : c'est un fait, pas une hypothèse.
    """
    d = await _get_dossier(db, ref)
    parents = [parent] if parent else None
    types = [type] if type else None
    data = await _lire(db)
    empreintes = dict(data.get("agenda_empreintes") or {})
    retires = 0
    for j in await _poses(db, d.id):
        groupe = _groupe_de_origine(j.origine)
        if not _dans_portee(groupe, parents, types):
            continue
        # Retirer UN type de congé n'emporte pas la reprise du travail : elle ne part qu'avec
        # son parent tout entier.
        if types and groupe.endswith(":reprise"):
            continue
        empreintes.pop(groupe, None)
        if not j.fait:
            await db.delete(j)
            retires += 1
    data["agenda_empreintes"] = empreintes
    await _ecrire(db, data)
    return {"retires": retires, **(await _reponse(db, data, d.id))}
