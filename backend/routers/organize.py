"""
Router Réorganisation — /api/organize
=====================================
Incrément 1 : PROPOSITION + APERÇU (virtuel, lecture seule).
L'IA propose un schéma de rangement (catégorie → dossier cible) à partir des
métadonnées déjà extraites ; on mappe chaque document → dossier cible et on
renvoie l'arborescence proposée. **Aucun fichier déplacé, aucune écriture DB.**

Étapes suivantes (incrément 2, cf. docs/plan-reorganisation-arborescence.md) :
édition drag & drop + application virtuelle (vue logique) puis physique (NAS, undo).
"""

from collections import defaultdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from logger import get_logger
from models.document import Document
from services.extraction import _extraire_json
from services.ollama_service import OllamaService

settings = get_settings()

log = get_logger(__name__)
router = APIRouter()


class ProposeRequest(BaseModel):
    consigne: str | None = None          # ex. « range plutôt par client », « par année »
    inclure_annee: bool = True           # sous-dossier {dossier}/{année}


def _annee(doc: Document) -> str | None:
    d = doc.date_modification_fichier or doc.date_import
    return str(d.year) if d else None


async def _proposer_dossiers(categories: list[str], consigne: str | None) -> tuple[dict, str]:
    """Demande au LLM un mapping {catégorie: dossier cible} + une explication."""
    if not categories:
        return {}, "Aucune catégorie."
    prompt = (
        "Tu organises une GED. Voici les catégories de documents détectées :\n"
        + ", ".join(categories)
        + ".\n\nConsigne utilisateur : "
        + (consigne or "range les documents dans une arborescence claire et logique")
        + ".\n\nRéponds UNIQUEMENT en JSON : "
        '{"criteres": "<phrase expliquant le rangement>", '
        '"dossiers": {"<catégorie>": "<NomDossier>"}} '
        "où chaque catégorie reçoit un nom de dossier court et lisible (sans accent ni slash)."
    )
    try:
        reponse = await OllamaService().generate(prompt, model=settings.ollama_model_fast)
        data = _extraire_json(reponse)
        dossiers = {str(k): str(v).strip("/ ") for k, v in (data.get("dossiers") or {}).items() if v}
        criteres = data.get("criteres") or "Rangement par catégorie."
        if dossiers:
            return dossiers, criteres
    except Exception as exc:
        log.warning("Proposition IA indisponible, repli par catégorie", erreur=str(exc))
    # Repli déterministe : 1 dossier par catégorie (capitalisée)
    return {c: c.capitalize() for c in categories}, "Repli : un dossier par catégorie."


@router.post("/organize/propose", tags=["Réorganisation"])
async def propose(body: ProposeRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Propose une arborescence cible (aperçu virtuel, sans rien modifier)."""
    docs = (await db.execute(
        select(Document).options(selectinload(Document.metadonnees_ia))
        .where(Document.statut == "enriched")
    )).scalars().all()

    # Catégories distinctes
    cats = sorted({(d.metadonnees_ia.categorie if d.metadonnees_ia and d.metadonnees_ia.categorie else "non-classé")
                   for d in docs})
    dossiers_map, criteres = await _proposer_dossiers([c for c in cats if c != "non-classé"], body.consigne)
    # Normalisation insensible à la casse (le LLM ne renvoie pas toujours la clé exacte)
    dossiers_norm = {k.lower(): v for k, v in dossiers_map.items()}

    def _cible_cat(cat: str) -> str:
        if cat == "non-classé":
            return "Non classé"
        # Proposition IA si elle matche, sinon repli : un dossier par catégorie
        return dossiers_norm.get(cat.lower()) or cat.capitalize()

    # Mapping doc → dossier cible
    arbre: dict[str, list] = defaultdict(list)
    for d in docs:
        cat = d.metadonnees_ia.categorie if d.metadonnees_ia and d.metadonnees_ia.categorie else "non-classé"
        cible = _cible_cat(cat)
        if body.inclure_annee and (an := _annee(d)):
            cible = f"{cible}/{an}"
        arbre[cible].append({
            "id": str(d.id),
            "nom": d.nom,
            "categorie": cat,
            "chemin_actuel": d.chemin,
        })

    arborescence = [
        {"dossier": k, "nb": len(v), "documents": sorted(v, key=lambda x: x["nom"].lower())}
        for k, v in sorted(arbre.items())
    ]
    return {
        "criteres": criteres,
        "consigne": body.consigne,
        "nb_documents": len(docs),
        "nb_dossiers": len(arborescence),
        "arborescence": arborescence,
    }
