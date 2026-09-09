"""
Router Fiscalité — /api/fiscalite
=================================
Sert l'onglet « Aide à la déclaration » d'Administration. Il **n'a aucune connaissance des
modules** : il parcourt le registre (`services/fiscalite/registre`), agrège ce que chaque
contributeur rend, et regroupe **par formulaire puis par case**.

Ce regroupement n'est pas cosmétique : on remplit une déclaration en la descendant, pas en
parcourant ses propres modules. Le module d'origine reste affiché sur la ligne comme une
*provenance*.

Quatre routes :

  GET  /fiscalite/synthese?annee=2026   → formulaires → cases → lignes (+ ce qui manque)
  POST /fiscalite/reponses              → mémorise la réponse qui tranche une case
  GET  /fiscalite/datation/{doc_id}     → années candidates POUR CETTE PIÈCE, avec preuves
  POST /fiscalite/datation/{doc_id}     → fixe l'année de la pièce (ou la relâche)

Les réponses vivent dans la table `config` (clé `fiscalite_reponses`, JSON par année)
plutôt que dans une table dédiée : il y en a une poignée par an, elles n'ont ni relation
ni cycle de vie propre, et une migration pour ça serait du poids sans contrepartie.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.config import Config
from models.document import Document
from services.fiscalite import datation, millesime
from services.fiscalite.registre import LigneFiscale, contributeurs

log = get_logger(__name__)
router = APIRouter()

CLE_REPONSES = "fiscalite_reponses"

# Bornes de saisie de l'année. Larges : une déclaration rectificative peut viser plusieurs
# années en arrière, et refuser l'année en cours empêcherait de préparer au fil de l'eau.
ANNEE_MIN, ANNEE_MAX = 2015, 2100


class ReponseIn(BaseModel):
    annee: int = Field(ge=ANNEE_MIN, le=ANNEE_MAX)
    cle: str = Field(min_length=1, max_length=100)
    valeur: str = Field(max_length=200)


class DatationIn(BaseModel):
    # `None` relâche la pièce : on retombe sur la date du fichier, marquée « déduite ».
    # Pouvoir DÉFAIRE compte autant que pouvoir trancher — une confirmation erronée qu'on ne
    # peut pas retirer est pire qu'une approximation qui s'annonce.
    annee: int | None = Field(default=None, ge=ANNEE_MIN, le=ANNEE_MAX)


def _annee_fiscale_par_defaut() -> int:
    """
    L'impôt se déclare l'année suivante : on propose **N-1**, pas N. Proposer l'année en
    cours ferait ouvrir l'écran sur une année vide, chaque printemps, pour tout le monde.
    """
    return datetime.now(tz=timezone.utc).year - 1


async def _charger_reponses(db: AsyncSession) -> dict[str, dict[str, str]]:
    result = await db.execute(select(Config).where(Config.cle == CLE_REPONSES))
    ligne = result.scalar_one_or_none()
    if not ligne or not ligne.valeur:
        return {}
    try:
        data = json.loads(ligne.valeur)
    except json.JSONDecodeError:
        # Une valeur illisible ne doit pas vider l'écran : on repart de zéro en le disant.
        log.warning("Réponses fiscales illisibles, ignorées", cle=CLE_REPONSES)
        return {}
    return data if isinstance(data, dict) else {}


async def _enregistrer_reponse(db: AsyncSession, annee: int, cle: str, valeur: str) -> None:
    toutes = await _charger_reponses(db)
    par_annee = dict(toutes.get(str(annee), {}))
    if valeur.strip():
        par_annee[cle] = valeur.strip()
    else:
        par_annee.pop(cle, None)   # une réponse effacée fait revenir la question
    toutes[str(annee)] = par_annee

    result = await db.execute(select(Config).where(Config.cle == CLE_REPONSES))
    ligne = result.scalar_one_or_none()
    if ligne:
        ligne.valeur = json.dumps(toutes, ensure_ascii=False)
    else:
        db.add(Config(cle=CLE_REPONSES, valeur=json.dumps(toutes, ensure_ascii=False)))
    await db.commit()


def _serialiser(ligne: LigneFiscale, provenance: str) -> dict:
    return {
        "formulaire": ligne.formulaire,
        "case": ligne.case,
        "libelle": ligne.libelle,
        # Le montant part en chaîne : un Decimal traversant JSON en flottant perdrait des
        # centimes, et c'est un chiffre destiné à être recopié tel quel.
        "montant": str(ligne.montant) if ligne.montant is not None else None,
        "nature": ligne.nature,
        "confiance": ligne.confiance,
        "note": ligne.note,
        "notice_url": ligne.notice_url,
        "bareme_verifie_le": ligne.bareme_verifie_le.isoformat() if ligne.bareme_verifie_le else None,
        "provenance": provenance,
        "sources": [
            {"libelle": s.libelle, "type": s.type, "ref": s.ref, "url": s.url,
             # `annee_confirmee=False` = déduit de la date du fichier. L'écran le montre
             # et propose de trancher, plutôt que d'afficher une précision qu'on n'a pas.
             "annee": s.annee, "annee_confirmee": s.annee_confirmee}
            for s in ligne.sources
        ],
        "question": None if ligne.question is None else {
            "cle": ligne.question.cle,
            "intitule": ligne.question.intitule,
            "aide": ligne.question.aide,
            "options": [{"valeur": o.valeur, "libelle": o.libelle} for o in ligne.question.options],
        },
    }


@router.get("/fiscalite/synthese", tags=["Fiscalité"])
async def synthese(
    annee: int | None = Query(default=None, ge=ANNEE_MIN, le=ANNEE_MAX),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Ce qu'il y a à reporter pour une année, **rangé comme le formulaire**.

    Chaque contributeur est cité dans `contributeurs`, **même quand il n'a rien** : un
    module silencieux se lit « je suis à jour », alors qu'il peut n'avoir simplement rien
    trouvé. Ne pas l'afficher rendrait l'écran faux par omission — le défaut qu'on cherche
    précisément à éviter ici.
    """
    an = annee or _annee_fiscale_par_defaut()
    toutes_reponses = await _charger_reponses(db)
    reponses = toutes_reponses.get(str(an), {})

    lignes: list[dict] = []
    etats: list[dict] = []
    annees: set[int] = {an, _annee_fiscale_par_defaut()}

    for contributeur in contributeurs():
        try:
            annees.update(await contributeur.annees(db))
            produites = await contributeur.contributions(db, an, reponses)
        except Exception as e:  # noqa: BLE001 — un contributeur cassé ne doit pas vider l'écran
            log.error("Contributeur fiscal en échec", cle=contributeur.cle,
                      type_erreur=type(e).__name__, erreur=str(e), exc_info=True)
            etats.append({"cle": contributeur.cle, "libelle": contributeur.libelle,
                          "etat": "erreur", "nb_lignes": 0,
                          "message": f"Indisponible ({type(e).__name__}) — les autres sources restent affichées."})
            continue

        lignes += [_serialiser(ligne, contributeur.libelle) for ligne in produites]
        etats.append({
            "cle": contributeur.cle, "libelle": contributeur.libelle,
            "etat": "ok" if produites else "vide", "nb_lignes": len(produites),
            "message": None if produites else f"Rien trouvé pour {an}.",
        })

    # Regroupement : formulaire, puis case (les lignes sans case — celles qui attendent une
    # réponse — remontent en tête de leur formulaire : c'est là qu'il y a quelque chose à faire).
    formulaires: dict[str, list[dict]] = {}
    for ligne in lignes:
        formulaires.setdefault(ligne["formulaire"], []).append(ligne)

    sortie = [
        {
            "code": code,
            "libelle": millesime.libelle_formulaire(code),
            "lignes": sorted(contenu, key=lambda x: (x["case"] is not None, x["case"] or "")),
        }
        for code, contenu in sorted(formulaires.items())
    ]

    return {
        "annee": an,
        "annees_disponibles": sorted(annees, reverse=True),
        "millesime": {
            "annee": millesime.MILLESIME,
            "verifie_le": millesime.VERIFIE_LE.isoformat(),
            "avertissement": millesime.AVERTISSEMENT,
            "url_officielle": millesime.URL_IMPOTS,
        },
        "formulaires": sortie,
        "contributeurs": etats,
        "reponses": reponses,
        "nb_lignes": len(lignes),
    }


@router.post("/fiscalite/reponses", tags=["Fiscalité"])
async def repondre(body: ReponseIn, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Mémorise la réponse qui tranche une case (rang de l'enfant, type d'organisme…), pour
    **une année donnée** : la situation change d'une année sur l'autre, et reconduire
    silencieusement la réponse de l'an dernier serait une erreur qu'on ne verrait pas.

    Une valeur vide efface la réponse, et la question revient.
    """
    await _enregistrer_reponse(db, body.annee, body.cle, body.valeur)
    log.info("Réponse fiscale enregistrée", annee=body.annee, cle=body.cle)
    return await synthese(annee=body.annee, db=db)


@router.get("/fiscalite/disponible", tags=["Fiscalité"])
async def disponible() -> dict:
    """
    Y a-t-il de quoi afficher l'onglet ? Interrogé par la barre latérale.

    Elle n'affichait « Administration » que si des liens externes existaient : livrer
    l'onglet fiscal sans corriger cela l'aurait rendu **invisible pour une raison sans
    rapport** — la leçon v1.84.3, déjà payée une fois.
    """
    noms = [c.cle for c in contributeurs()]
    return {"disponible": bool(noms), "contributeurs": noms}


# ─── Datation d'une pièce ─────────────────────────────────────────────────────────────
# ⚠️ **Aucune sortie réseau ici, et ce n'est pas un manque.** L'année d'une attestation est
# écrite dans l'attestation, dont Tika a déjà extrait le texte à l'indexation. Il n'y a rien
# à demander à Internet — et poser une confirmation de sortie réseau devant une lecture
# locale apprendrait à l'utilisateur que ces confirmations ne veulent rien dire. On garde la
# fenêtre pour ce qui sort vraiment.


async def _document(db: AsyncSession, doc_id: str) -> Document:
    try:
        ident = uuid.UUID(doc_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Identifiant de document invalide")
    doc = (await db.execute(select(Document).where(Document.id == ident))).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return doc


def _etat_datation(doc: Document) -> dict:
    deduite = doc.date_modification_fichier or doc.date_import
    return {
        "document_id": str(doc.id),
        "nom": doc.nom,
        "annee": doc.annee_fiscale or (deduite.year if deduite else None),
        "confirmee": bool(doc.annee_fiscale),
        "annee_deduite": deduite.year if deduite else None,
        "origine_deduite": "date de modification du fichier" if doc.date_modification_fichier
                           else "date d'import dans la GED",
    }


@router.get("/fiscalite/datation/{doc_id}", tags=["Fiscalité"])
async def annees_candidates(doc_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Les années plausibles pour cette pièce, **la plus probable en tête**, chacune avec
    l'extrait de texte qui la justifie.

    L'extrait n'est pas décoratif : une proposition qu'on ne peut pas vérifier d'un coup
    d'œil ne vaut pas mieux qu'une devinette, et c'est justement ce qu'on cherche à
    remplacer. Une pièce sans texte extrait (image non océrisée) rend une liste vide plutôt
    qu'une proposition en l'air — la saisie manuelle reste ouverte.
    """
    doc = await _document(db, doc_id)
    trouves = datation.candidats(doc.texte_extrait, doc.nom)
    return {
        **_etat_datation(doc),
        "texte_disponible": bool(doc.texte_extrait),
        "candidats": [
            {"annee": c.annee, "score": c.score, "occurrences": c.occurrences,
             "extrait": c.extrait, "motif": c.motif}
            for c in trouves
        ],
    }


@router.post("/fiscalite/datation/{doc_id}", tags=["Fiscalité"])
async def dater(doc_id: str, body: DatationIn, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Fixe l'année de revenus de cette pièce — ou la relâche si `annee` est absente.

    L'année confirmée prime **définitivement** sur la date du fichier : une pièce datée à la
    main ne doit pas se faire re-déduire au prochain scan parce que le fichier a été recopié.
    """
    doc = await _document(db, doc_id)
    doc.annee_fiscale = body.annee
    await db.commit()
    log.info("Pièce datée", document_id=doc_id, annee=body.annee)
    return _etat_datation(doc)
