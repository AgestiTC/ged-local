"""
Router Journal — /api/emploi-domicile/contrats/{cid}/journal
============================================================
Le mois par mois d'un contrat : ce qui a été **réellement** fait, par opposition au
prévisionnel que porte le contrat.

  GET   /emploi-domicile/contrats/{cid}/journal?annee=2026  → les 12 mois + récapitulatif
  PUT   /emploi-domicile/contrats/{cid}/journal/{annee}/{mois} → saisir ou corriger un mois
  DELETE …/{annee}/{mois}                                    → vider un mois

**Les douze mois sont toujours rendus**, saisis ou non. Ne renvoyer que les mois remplis
obligerait l'écran à reconstituer les trous, et surtout ferait disparaître la question qui
compte en ouvrant l'écran : *qu'est-ce que je n'ai pas encore déclaré ?*

⚠️ Aucun bulletin de salaire n'est produit ici : il est édité par Pajemploi ou le CESU à
partir de la déclaration, et c'est lui qui fait foi. Ce journal prépare la saisie.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.emploi_domicile import Contrat, MoisTravaille
from routers.emploi_domicile_contrats import _bareme, _calculer
from services.emploi_domicile import journal as calculs

log = get_logger(__name__)
router = APIRouter()

ANNEE_MIN, ANNEE_MAX = 2015, 2100


class MoisIn(BaseModel):
    """
    Tout est optionnel, et `None` **efface** la valeur.

    C'est voulu : on saisit un mois par petites touches — les heures en fin de mois, les
    kilomètres quand on y repense. Exiger le formulaire complet ferait renoncer à saisir.
    """

    heures: str | float | None = None
    jours_accueil: int | None = Field(default=None, ge=0, le=31)
    repas: int | None = Field(default=None, ge=0, le=200)
    km: str | float | None = None
    absences: int | None = Field(default=None, ge=0, le=31)
    declare: bool | None = None
    note: str | None = None


def _dec(valeur) -> Decimal | None:
    """
    Décimal tolérant : « 7,5 » comme « 7.5 ». Une valeur vide vaut `None`, pas zéro.

    L'arrondi à deux décimales est fait **ici** et pas laissé à la colonne : PostgreSQL
    applique l'échelle de `Numeric(7,2)`, SQLite ne l'applique pas. Sans cette normalisation,
    la même saisie ressortirait « 48.6 » en développement et « 48.60 » en production — et la
    divergence ne se verrait qu'une fois déployée.
    """
    if valeur is None or str(valeur).strip() == "":
        return None
    try:
        d = Decimal(str(valeur).strip().replace(",", ".").replace(" ", ""))
    except (InvalidOperation, ValueError):
        return None
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def _annees(db: AsyncSession, contrat_id, courante: int) -> list[int]:
    """
    Les années où basculer : celles qui portent des données, plus l'année en cours et la
    précédente. La précédente y figure toujours parce que la déclaration fiscale du printemps
    porte sur elle — c'est l'année qu'on vient chercher, et elle serait absente de la liste
    tant qu'aucun mois n'y a été saisi.
    """
    saisies = (await db.execute(
        select(MoisTravaille.annee).where(MoisTravaille.contrat_id == contrat_id).distinct()
    )).scalars().all()
    maintenant = datetime.now(tz=timezone.utc).year
    return sorted({courante, maintenant, maintenant - 1, *saisies}, reverse=True)


async def _get_contrat(db: AsyncSession, cid: str) -> Contrat:
    try:
        c = await db.get(Contrat, uuid.UUID(cid))
    except ValueError:
        raise HTTPException(status_code=400, detail="Identifiant invalide")
    if c is None:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    return c


def _serialiser(m: MoisTravaille | None, mois: int) -> dict:
    """Un mois, saisi ou non. Le vide se distingue du zéro : `None` partout, pas des 0."""
    return {
        "mois": mois,
        "nom": calculs.MOIS_NOMS[mois - 1],
        "id": str(m.id) if m else None,
        "heures": str(m.heures) if m and m.heures is not None else None,
        "jours_accueil": m.jours_accueil if m else None,
        "repas": m.repas if m else None,
        "km": str(m.km) if m and m.km is not None else None,
        "absences": m.absences if m else None,
        "declare": bool(m.declare) if m else False,
        "note": m.note if m else None,
    }


@router.get("/emploi-domicile/contrats/{cid}/journal", tags=["Emploi à domicile"])
async def lire(
    cid: str,
    annee: int | None = Query(default=None, ge=ANNEE_MIN, le=ANNEE_MAX),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Les douze mois de l'année et leur récapitulatif, comparés au contrat."""
    c = await _get_contrat(db, cid)
    an = annee or datetime.now(tz=timezone.utc).year

    lignes = (await db.execute(
        select(MoisTravaille)
        .where(MoisTravaille.contrat_id == c.id, MoisTravaille.annee == an)
        .order_by(MoisTravaille.mois)
    )).scalars().all()
    par_mois = {m.mois: m for m in lignes}
    mois = [_serialiser(par_mois.get(n), n) for n in range(1, 13)]

    # Le prévisionnel vient du contrat : on recalcule plutôt que de le stocker, pour qu'une
    # correction du contrat se reflète immédiatement dans la comparaison.
    mensualisation, _, _ = _calculer(c.champs or {}, await _bareme(db))
    recap = calculs.recapituler(
        annee=an,
        mois=[{**m, "heures": _dec(m["heures"]), "km": _dec(m["km"])} for m in mois],
        heures_mensualisees=mensualisation.heures_mensualisees if mensualisation else None,
        taux_horaire=mensualisation.taux_horaire if mensualisation else None,
        salaire_mensuel=mensualisation.salaire_mensuel if mensualisation else None,
    )

    return {
        "contrat": {"id": str(c.id), "titre": c.titre, "profil": c.profil, "statut": c.statut},
        "annee": an,
        "annees_disponibles": await _annees(db, c.id, an),
        "mois": mois,
        "recapitulatif": {
            "totaux": {
                "heures": str(recap.totaux.heures),
                "jours_accueil": recap.totaux.jours_accueil,
                "repas": recap.totaux.repas,
                "km": str(recap.totaux.km),
                "absences": recap.totaux.absences,
                "mois_saisis": recap.totaux.mois_saisis,
                "mois_declares": recap.totaux.mois_declares,
            },
            "heures_prevues": str(recap.heures_prevues) if recap.heures_prevues is not None else None,
            "ecart_heures": str(recap.ecart_heures) if recap.ecart_heures is not None else None,
            "montant_ecart": str(recap.montant_ecart) if recap.montant_ecart is not None else None,
            "salaire_annuel_prevu": (str(recap.salaire_annuel_prevu)
                                     if recap.salaire_annuel_prevu is not None else None),
            "remarques": recap.remarques,
        },
    }


@router.put("/emploi-domicile/contrats/{cid}/journal/{annee}/{mois}", tags=["Emploi à domicile"])
async def enregistrer(
    cid: str,
    annee: int = Path(ge=ANNEE_MIN, le=ANNEE_MAX),
    mois: int = Path(ge=1, le=12),
    body: MoisIn = ...,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Saisit ou corrige un mois. Crée la ligne au besoin — l'écran n'a pas à savoir si le mois
    existait déjà, et le demander l'obligerait à un aller-retour de plus.

    Seuls les champs **fournis** sont modifiés : envoyer uniquement `declare` ne doit pas
    effacer les heures saisies la semaine précédente.
    """
    c = await _get_contrat(db, cid)

    ligne = (await db.execute(
        select(MoisTravaille).where(
            MoisTravaille.contrat_id == c.id,
            MoisTravaille.annee == annee,
            MoisTravaille.mois == mois,
        )
    )).scalar_one_or_none()
    if ligne is None:
        ligne = MoisTravaille(contrat_id=c.id, annee=annee, mois=mois)
        db.add(ligne)

    fournis = body.model_dump(exclude_unset=True)
    for champ in ("jours_accueil", "repas", "absences", "declare", "note"):
        if champ in fournis:
            setattr(ligne, champ, fournis[champ])
    for champ in ("heures", "km"):
        if champ in fournis:
            setattr(ligne, champ, _dec(fournis[champ]))

    await db.commit()
    log.info("Mois de journal enregistré", contrat=cid, annee=annee, mois=mois)
    return await lire(cid, annee, db)


@router.delete("/emploi-domicile/contrats/{cid}/journal/{annee}/{mois}", tags=["Emploi à domicile"])
async def vider(
    cid: str,
    annee: int = Path(ge=ANNEE_MIN, le=ANNEE_MAX),
    mois: int = Path(ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Vide un mois — il redevient **non saisi**, ce qui n'est pas la même chose qu'un mois à
    zéro : le récapitulatif cessera de le compter comme rempli.
    """
    c = await _get_contrat(db, cid)
    await db.execute(delete(MoisTravaille).where(
        MoisTravaille.contrat_id == c.id,
        MoisTravaille.annee == annee,
        MoisTravaille.mois == mois,
    ))
    await db.commit()
    return await lire(cid, annee, db)
