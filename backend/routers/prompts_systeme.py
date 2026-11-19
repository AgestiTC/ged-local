"""
Router Prompts système — /api/system/prompts (Paramètres › Prompts, étapes A4-A5)
================================================================================
Voir et modifier les prompts système du registre `services/prompts.py`, sans redéploiement.

  GET  /system/prompts                  → liste (clé, usage, sortie, variables, version active)
  GET  /system/prompts/{cle}            → détail : origine, texte actif, historique, version servie
  POST /system/prompts/{cle}/versions   → NOUVELLE version : {texte | null (= origine), commentaire}
  POST /system/prompts/{cle}/essayer    → envoie un texte candidat au modèle de l'usage (rien d'enregistré)
  POST /system/prompts/{cle}/relire     → « Faire relire par l'IA » + vérification du contrat

Les consignes de base « documents de référence » (`reference.analyse`, `reference.corrigee`) sont
au registre mais versionnées par /api/consignes : exclues de la liste, 409 sur leurs routes (A6).

Réservé à l'administrateur (`/api/system/*`, services/acces.py). Garde-fous :
  - rien n'est jamais écrasé ni supprimé : restaurer = créer une version de plus ;
  - `texte` null = revenir à l'origine du code, toujours possible ;
  - le CONTRAT de la clé est vérifié à l'enregistrement (422 sinon) : `prompts.verifier_contrat` ;
  - « Essayer » et « Relire » n'utilisent QUE l'IA locale (aucune sortie GECO ouverte ici).
"""
import os
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.prompt_version import PromptVersion
from services import prompts

log = get_logger(__name__)
router = APIRouter()

TOKENS_ESSAI_MAX = 2_000


class NouvelleVersion(BaseModel):
    texte: str | None = Field(default=None, description="null = revenir au texte d'origine (celui du code)")
    commentaire: str | None = Field(default=None, max_length=300)


class Essai(BaseModel):
    texte: str | None = Field(default=None, description="Texte candidat ; null = version active")
    variables: dict[str, str] = Field(default_factory=dict, description="Valeurs des variables (vide par défaut)")
    message: str | None = Field(default=None, max_length=8000,
                                description="Facultatif : le prompt part alors en consigne système, ce message en question")


class Relecture(BaseModel):
    texte: str | None = Field(default=None, description="Texte à faire relire ; null = version active")


#: Clés du registre versionnées ailleurs (/api/consignes, modal « Consignes de base » de la page
#: Créer) : ni listées ni modifiables ici — une seule porte d'édition, un seul historique (A6).
GEREES_AILLEURS = frozenset(prompts.GEREES_PAR_CONSIGNES.values())


def _prompt_ou_404(cle: str) -> prompts.Prompt:
    if cle in GEREES_AILLEURS:
        raise HTTPException(status_code=409, detail="Ce prompt se modifie dans Créer › documents de référence › "
                                                    "« Consignes de base » (versions et historique y sont tenus).")
    try:
        return prompts.prompt(cle)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Prompt inconnu : {cle}")


def _refuser_si_hors_contrat(cle: str, texte: str | None) -> None:
    erreurs = prompts.verifier_contrat(cle, texte)
    if erreurs:
        raise HTTPException(status_code=422, detail="Texte refusé — " + " ".join(erreurs))


def _version_dict(v: PromptVersion) -> dict:
    return {"version": v.version, "texte": v.texte, "origine": v.texte is None, "commentaire": v.commentaire,
            "auteur": v.auteur, "created_at": v.created_at.isoformat() if v.created_at else None}


def _servie(cle: str) -> dict:
    """Ce que CE processus sert pour `cle` (cache rechargé au plus toutes les 2 s)."""
    ignoree = prompts.version_ignoree(cle)
    return {"version": prompts.version_servie(cle), "texte": prompts.texte(cle), "pid": os.getpid(),
            "ignoree": {"version": ignoree[0], "raison": ignoree[1]} if ignoree else None}


@router.get("/system/prompts")
async def lister(db: AsyncSession = Depends(get_db)):
    """Tous les prompts du registre, avec leur version active en base."""
    lignes = (await db.execute(
        select(PromptVersion.cle, PromptVersion.version, PromptVersion.texte.is_(None))
        .order_by(PromptVersion.cle, PromptVersion.version)
    )).all()
    par_cle: dict[str, dict] = {}
    for cle, version, origine in lignes:
        d = par_cle.setdefault(cle, {"nb": 0})
        d["nb"] += 1
        d["version"], d["origine"] = version, bool(origine)   # trié par version : la dernière gagne
    resultat = []
    for cle in prompts.cles():
        if cle in GEREES_AILLEURS:
            continue
        p = prompts.prompt(cle)
        d = par_cle.get(cle, {})
        ignoree = prompts.version_ignoree(cle)
        resultat.append({
            "cle": cle, "usage": p.usage, "sortie": p.sortie, "description": p.description,
            "variables": list(p.variables), "nb_versions": d.get("nb", 0),
            "version_active": d.get("version", 0), "modifie": bool(d) and not d.get("origine", True),
            "ignoree": {"version": ignoree[0], "raison": ignoree[1]} if ignoree else None,
        })
    return {"prompts": resultat}


@router.get("/system/prompts/{cle}")
async def detail(cle: str, db: AsyncSession = Depends(get_db)):
    """Origine, version active, historique (le plus récent d'abord) et ce que ce processus sert."""
    p = _prompt_ou_404(cle)
    versions = (await db.execute(select(PromptVersion).where(PromptVersion.cle == cle)
                                 .order_by(PromptVersion.version.desc()))).scalars().all()
    active = versions[0] if versions else None
    return {
        "cle": cle, "usage": p.usage, "sortie": p.sortie, "description": p.description,
        "variables": list(p.variables), "origine": p.texte,
        # Consignes communes que toute version doit garder (refus à l'enregistrement sinon).
        "garde_fous": [{"nom": g.nom, "libelle": g.libelle} for g in prompts.garde_fous_de(cle)],
        "active": _version_dict(active) if active else None,
        "texte_actif": active.texte if active is not None and active.texte is not None else p.texte,
        "versions": [_version_dict(v) for v in versions],
        "servie": _servie(cle),
        "longueur_min": prompts.LONGUEUR_MIN, "longueur_max": prompts.LONGUEUR_MAX,
    }


@router.post("/system/prompts/{cle}/versions", status_code=201)
async def enregistrer(cle: str, body: NouvelleVersion, db: AsyncSession = Depends(get_db)):
    """Nouvelle version (jamais d'écrasement). `texte` null = revenir à l'origine du code."""
    from services.audit import auteur_courant

    _prompt_ou_404(cle)
    if body.texte is not None:
        _refuser_si_hors_contrat(cle, body.texte)
    derniere = (await db.execute(select(func.max(PromptVersion.version))
                                 .where(PromptVersion.cle == cle))).scalar() or 0
    v = PromptVersion(cle=cle, version=derniere + 1, texte=body.texte,
                      commentaire=(body.commentaire or "").strip() or None, auteur=auteur_courant())
    db.add(v)
    await db.commit()
    await prompts.recharger(db)   # ce processus la sert tout de suite ; les autres sous 2 s
    log.info("Prompt système : nouvelle version", cle=cle, version=v.version, origine=body.texte is None)
    return _version_dict(v)


def _valeurs(p: prompts.Prompt, saisies: dict[str, str], numeriques: bool) -> dict:
    valeurs: dict = {}
    for nom in p.variables:
        brut = saisies.get(nom, "")
        if numeriques:
            try:
                brut = int(brut) if brut.strip().lstrip("-").isdigit() else float(brut)
            except ValueError:
                pass
        valeurs[nom] = brut
    return valeurs


def _rendu_essai(p: prompts.Prompt, texte: str, saisies: dict[str, str]) -> str:
    """Le texte candidat rempli avec les valeurs saisies (vides par défaut). 422 si impossible."""
    inconnues = sorted(set(saisies) - set(p.variables))
    if inconnues:
        raise HTTPException(status_code=422, detail=f"Variable(s) inconnue(s) pour ce prompt : {', '.join(inconnues)}")
    if not p.variables:
        return texte
    for numeriques in (False, True):   # un format numérique ({note_max:g}) attend un nombre
        try:
            return texte.format_map(_valeurs(p, saisies, numeriques))
        except (ValueError, TypeError):
            continue
    raise HTTPException(status_code=422, detail="Valeur de variable incompatible avec son format (un nombre est attendu ?)")


def _modele_local(usage: str) -> str:
    """Modèle LOCAL de l'usage (routage habituel). Un réglage pointant vers GECO est refusé."""
    from services import runtime_config
    from services.ollama_service import est_geco

    modele = runtime_config.model_for(usage)
    if est_geco(modele):
        raise HTTPException(status_code=400, detail=f"Le modèle configuré pour l'usage « {usage} » est un modèle "
                                                    "GECO : l'essai n'utilise que l'IA locale.")
    return modele


@router.post("/system/prompts/{cle}/essayer")
async def essayer(cle: str, body: Essai):
    """
    Envoie le texte candidat (ou la version active) au modèle de l'usage de la clé, sous cet usage,
    et rend la réponse brute + la durée. Rien n'est enregistré. IA locale uniquement.
    """
    from services.ollama_service import OllamaService, usage_ia

    p = _prompt_ou_404(cle)
    texte = body.texte if body.texte is not None else prompts.texte(cle)
    _refuser_si_hors_contrat(cle, texte)
    rendu = _rendu_essai(p, texte, body.variables)
    message = (body.message or "").strip()
    modele = _modele_local(p.usage)
    debut = time.perf_counter()
    try:
        with usage_ia(p.usage):
            if message:
                reponse = await OllamaService().generate(message, model=modele, system=rendu,
                                                         num_predict=TOKENS_ESSAI_MAX)
            else:
                reponse = await OllamaService().generate(rendu, model=modele, num_predict=TOKENS_ESSAI_MAX)
    except Exception as e:  # noqa: BLE001 — Ollama injoignable, délai dépassé…
        log.warning("Essai de prompt impossible", cle=cle, erreur=str(e) or type(e).__name__)
        raise HTTPException(status_code=503, detail="L'IA locale ne répond pas (Ollama ?) — réessayez plus tard")
    return {"cle": cle, "usage": p.usage, "model": modele, "reponse": reponse,
            "duree_ms": round((time.perf_counter() - debut) * 1000), "prompt_envoye": rendu,
            "message": message or None}


@router.post("/system/prompts/{cle}/relire")
async def relire(cle: str, body: Relecture):
    """
    « Faire relire par l'IA » (services/relecture_prompt.py), puis vérification du CONTRAT de la clé
    sur la proposition : si elle le casse (variable perdue…), `contrat_ok` est faux et `erreurs` dit
    pourquoi — l'interface ne la propose alors pas à l'enregistrement telle quelle.
    """
    from services.ollama_service import OllamaService
    from services.relecture_prompt import MAX_CHARS_PROMPT, relire_prompt

    p = _prompt_ou_404(cle)
    texte = body.texte if body.texte is not None else prompts.texte(cle)
    if not texte.strip():
        raise HTTPException(status_code=422, detail="Rien à relire : le texte est vide.")
    modele = _modele_local("rapport")   # même usage de modèle que la relecture de la page Créer
    mode = "systeme_variables" if p.variables else "systeme"
    try:
        resultat = await relire_prompt(texte, mode, modele, OllamaService())
    except Exception as e:  # noqa: BLE001
        log.warning("Relecture de prompt système impossible", cle=cle, erreur=str(e) or type(e).__name__)
        raise HTTPException(status_code=503, detail="L'IA locale ne répond pas (Ollama ?) — réessayez plus tard")
    if resultat is None:
        raise HTTPException(status_code=502, detail="L'IA n'a pas rendu de proposition exploitable — réessayez")
    erreurs = prompts.verifier_contrat(cle, resultat["prompt"])
    return {**resultat, "model": modele, "contrat_ok": not erreurs, "erreurs": erreurs,
            "tronque": len(texte) > MAX_CHARS_PROMPT}
