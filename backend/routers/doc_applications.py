"""
Router Documentation des applications — GET /api/doc-applications (UTILISATEUR)
===============================================================================
Plan « Recevoir la documentation des autres applications », étape 4.

Pour chaque règle de classement ACTIVE qui tire un tag du sous-dossier (= zone de dépôt organisée
« un sous-dossier par application »), liste les applications, leurs documents, la version annoncée
par l'en-tête (`tika_metadata.front_matter`) et la date du dernier dépôt. Une application sans
dépôt depuis `JOURS_SANS_DEPOT` jours est signalée (`en_retard`).
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.document import Document
from models.regle_classement import RegleClassement
from models.version import Version
from services.regles_classement import sous_dossier

router = APIRouter()

JOURS_SANS_DEPOT = 90


def _like(prefixe: str) -> str:
    """Motif LIKE « commence par » : `%`, `_` et `\\` du préfixe pris littéralement."""
    return prefixe.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def _aware(d: datetime | None) -> datetime | None:
    if d is not None and d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d


def regrouper(regle: RegleClassement, docs: list[Document], nb_versions: dict, maintenant: datetime) -> list[dict]:
    """Regroupe les documents d'une zone de dépôt par application (sous-dossier). Fonction PURE."""
    par_appli: dict[str, list[dict]] = defaultdict(list)
    for d in docs:
        appli = sous_dossier(d.chemin, regle.prefixe_chemin)
        if not appli:
            continue
        fm = (d.tika_metadata or {}).get("front_matter") or {}
        fm = fm if isinstance(fm, dict) else {}
        par_appli[appli].append({
            "id": str(d.id),
            "nom": d.nom,
            "titre": fm.get("titre") or d.nom,
            "version": fm.get("version"),
            "date_depot": _iso(d.date_modification_fichier or d.date_import),
            "_date": _aware(d.date_modification_fichier or d.date_import),
            "nb_versions": nb_versions.get(d.id, 0) + 1,
            "statut": d.statut,
        })
    limite = maintenant - timedelta(days=JOURS_SANS_DEPOT)
    applis = []
    for appli, liste in sorted(par_appli.items()):
        presents = [x for x in liste if x["statut"] != "absent"]
        dates = [x["_date"] for x in presents if x["_date"]]
        dernier = max(dates) if dates else None
        for x in liste:
            x.pop("_date")
        applis.append({
            "appli": appli,
            "regle": regle.libelle,
            "documents": sorted(liste, key=lambda x: x["titre"].lower()),
            "dernier_depot": _iso(dernier),
            "en_retard": dernier is None or dernier < limite,
        })
    return applis


@router.get("/doc-applications")
async def doc_applications(db: AsyncSession = Depends(get_db)) -> dict:
    regles = (await db.execute(
        select(RegleClassement).where(RegleClassement.actif.is_(True), RegleClassement.tag_depuis_sous_dossier.is_(True))
        .order_by(RegleClassement.prefixe_chemin)
    )).scalars().all()
    maintenant = datetime.now(tz=timezone.utc)
    applications: list[dict] = []
    for regle in regles:
        docs = (await db.execute(
            select(Document).where(Document.chemin.like(_like(regle.prefixe_chemin), escape="\\"),
                                   Document.doublon_de.is_(None))
        )).scalars().all()
        if not docs:
            continue
        compte = dict((await db.execute(
            select(Version.document_id, func.count()).where(Version.document_id.in_([d.id for d in docs]))
            .group_by(Version.document_id)
        )).all())
        applications.extend(regrouper(regle, docs, compte, maintenant))
    return {"applications": applications, "jours_sans_depot": JOURS_SANS_DEPOT}
