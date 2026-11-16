"""
Statistiques des noms MÉMORISÉES (16/11/2026) — Rangement › Carte › « Noms de fichiers ».

Le calcul relit tous les fichiers d'un dossier : ~13 s pour les 214 000 fichiers de Home-TOM. Le
résultat est donc gardé en base (`inv_nommage`), par emplacement et par dossier, sous une CLÉ :

    <id du dernier scan>:<son statut>:<empreinte des règles et des rubriques de séries>

Tant que la clé ne change pas, l'inventaire et les règles sont ceux du calcul : on relit la ligne.
Un nouveau scan, un réglage enregistré ou une rubrique de séries ajoutée au plan change la clé, et
le calcul suivant remplace la ligne. Pendant un scan (statut `en_cours`), rien n'est mémorisé :
l'inventaire bouge encore. À la fin d'un scan réussi, la racine est recalculée d'avance
(`precalculer`) et les lignes d'avant sont oubliées.
"""

import hashlib
import json
from typing import Any

from logger import get_logger
from services.rangement import nommage
from services.rangement.depot import Depot, Emplacement

log = get_logger(__name__)


async def rubriques_series(emp: Emplacement, db: Any = None) -> frozenset[str]:
    """Les rubriques « séries » : celles de base, plus les nœuds du plan au gabarit `{serie}`. `db` :
    la session de la requête (l'API) ; sans elle (le worker), une session ouverte pour l'occasion."""
    from services.rangement import plan as plan_rangement, series
    rubriques = set(nommage.RUBRIQUES_SERIES)
    partage = plan_rangement.partage_de(emp)
    if partage:
        from sqlalchemy import select

        from models.plan_classement import PlanNoeud
        requete = select(PlanNoeud.chemin).where(PlanNoeud.partage == partage, PlanNoeud.gabarit == series.GABARIT)
        if db is not None:
            noeuds = (await db.execute(requete)).scalars().all()
        else:
            from database import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                noeuds = (await session.execute(requete)).scalars().all()
        rubriques |= {c.rsplit("/", 1)[-1].casefold() for c in noeuds}
    return frozenset(rubriques)


def cle(scan: dict[str, Any] | None, regles: dict[str, nommage.Regle], rubriques: frozenset[str]) -> str | None:
    """La clé du calcul, ou `None` s'il ne faut pas mémoriser (aucun scan, ou scan en cours). PURE."""
    if not scan or scan.get("statut") == "en_cours":
        return None
    empreinte = hashlib.sha256(json.dumps(
        [nommage.en_json(regles), sorted(rubriques)], ensure_ascii=False).encode()).hexdigest()[:16]
    return f"{scan['id']}:{scan['statut']}:{empreinte}"


async def bilan(depot: Depot, emp: Emplacement, chemin: str = "",
                rubriques: frozenset[str] | None = None) -> dict[str, Any]:
    """Le bilan des noms d'un dossier : relu s'il est à jour, sinon calculé (et mémorisé si possible)."""
    if rubriques is None:
        rubriques = await rubriques_series(emp)
    regles = nommage.lire()
    k = cle(await depot.dernier_scan(emp.id), regles, rubriques)
    if k is not None:
        memo = await depot.nommage_memorise(emp.id, chemin)
        if memo is not None and memo[0] == k:
            return memo[1]
    resultat = nommage.bilan(await depot.fichiers(emp.id, chemin), regles, rubriques)
    if k is not None:
        await depot.memoriser_nommage(emp.id, chemin, k, resultat)
    return resultat


async def precalculer(depot: Depot, emp: Emplacement) -> None:
    """Après un scan réussi : la racine d'avance, et l'oubli des calculs d'avant. Ne lève jamais —
    ce n'est qu'un gain de temps, il ne doit pas faire échouer le scan."""
    try:
        try:
            rubriques = await rubriques_series(emp)
        except Exception:  # noqa: BLE001 — plan illisible : rubriques de base (la clé le dira)
            rubriques = frozenset(nommage.RUBRIQUES_SERIES)
        await bilan(depot, emp, "", rubriques)
        k = cle(await depot.dernier_scan(emp.id), nommage.lire(), rubriques)
        if k is not None:
            await depot.oublier_nommage(emp.id, k)
    except Exception:  # noqa: BLE001
        log.warning("Statistiques des noms non précalculées", emplacement_id=emp.id, exc_info=True)
