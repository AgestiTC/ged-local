"""
Mesure de la récupération (plan `docs/plan-prompts-et-rag-apprenant.md`, étape B0).

Sans jeu de questions de référence, on ne peut pas savoir si le RAG « apprend » ou régresse.
Ce module calcule, à partir des résultats de recherche et des documents attendus :

- **rappel@k** : part des questions dont au moins un document attendu sort dans les k premiers ;
- **MRR** : moyenne de 1 / rang du premier document attendu (0 s'il n'apparaît pas) ;
- **couverture@k** : part de TOUS les documents attendus retrouvés dans les k premiers.

Fonctions pures, sans réseau ni base : le lanceur (`scripts/mesurer_rag.py`) les nourrit.
Un document attendu se désigne par son identifiant (`{"id": "…"}`) ou par son nom de fichier
(chaîne, comparée sans tenir compte de la casse).
"""
from __future__ import annotations

from typing import Any


def _correspond(resultat: dict, attendu: Any) -> bool:
    if isinstance(attendu, dict) and attendu.get("id"):
        return str(resultat.get("id")) == str(attendu["id"])
    nom = attendu if isinstance(attendu, str) else (attendu or {}).get("nom", "")
    return bool(nom) and str(resultat.get("nom", "")).casefold() == str(nom).casefold()


def rangs(resultats: list[dict], attendus: list[Any]) -> list[int | None]:
    """Pour chaque document attendu, son rang (1 = premier) dans `resultats`, ou None."""
    sortie: list[int | None] = []
    for a in attendus:
        sortie.append(next((i + 1 for i, r in enumerate(resultats) if _correspond(r, a)), None))
    return sortie


def mesurer(cas: list[dict], ks: tuple[int, ...] = (5, 10)) -> dict:
    """
    `cas` : une entrée par question, `{"id", "resultats": [...], "attendus": [...]}`.
    Rend les indicateurs globaux et le détail par question.
    """
    detail = []
    for c in cas:
        r = rangs(c.get("resultats") or [], c.get("attendus") or [])
        trouves = [x for x in r if x is not None]
        detail.append({
            "id": c.get("id"),
            "rangs": r,
            "premier": min(trouves) if trouves else None,
        })
    n = len(detail)
    indicateurs: dict[str, float | int] = {"questions": n}
    if n == 0:
        return {"indicateurs": indicateurs, "detail": detail}
    for k in ks:
        indicateurs[f"rappel@{k}"] = round(sum(1 for d in detail if d["premier"] and d["premier"] <= k) / n, 4)
        total = sum(len(d["rangs"]) for d in detail)
        dedans = sum(1 for d in detail for x in d["rangs"] if x is not None and x <= k)
        indicateurs[f"couverture@{k}"] = round(dedans / total, 4) if total else 0.0
    indicateurs["mrr"] = round(sum(1 / d["premier"] for d in detail if d["premier"]) / n, 4)
    return {"indicateurs": indicateurs, "detail": detail}
