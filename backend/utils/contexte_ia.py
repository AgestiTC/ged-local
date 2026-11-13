"""
Assemblage du texte de plusieurs documents dans un budget de caractères, pour un prompt.

Plan `docs/plan-prompts-et-rag-apprenant.md`, étape A2 : remplace quatre boucles écrites
séparément (rapport libre, remplissage de modèle DOCX, comparatif, grille d'analyse). Elles
faisaient la même chose — un en-tête par document, puis son texte, jusqu'à épuisement du budget —
avec des réglages différents, que chaque appelant passe désormais explicitement. Les sorties sont
identiques à l'octet à celles des anciennes boucles (`tests/test_contexte_ia.py`).

Pas concernés : la présentation et le chat avec la GED, qui assemblent des RÉSUMÉS coupés à
longueur fixe puis tronquent l'ensemble — une autre logique.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable


def assembler_documents(
    docs: Iterable[Any],
    budget: int,
    *,
    entete: Callable[[Any], str],
    marge: int = 0,
    seuil: int = 0,
    plafond_par_doc: int | None = None,
    marque_plafond: str = "",
    marque_budget: str = "",
    nettoyer: bool = False,
    vide: str = "",
) -> str:
    """
    Concatène `entete(doc) + texte` pour chaque document qui a du texte, dans `budget` caractères.

    - `nettoyer` : retire les blancs autour du texte (sinon, un texte fait de blancs est sauté,
      mais un vrai texte est gardé tel quel) ;
    - `plafond_par_doc` / `marque_plafond` : coupe chaque document AVANT de le placer ;
    - `marge` : réserve, en plus de l'en-tête, pour la marque et ce qui suit le contexte ;
    - `seuil` : on s'arrête dès qu'il reste `seuil` caractères ou moins pour le texte ;
    - `marque_budget` : ajoutée quand un texte est coupé faute de place ;
    - `vide` : rendu quand aucun document n'a de texte.
    """
    parts: list[str] = []
    reste = budget
    for doc in docs:
        brut = doc.texte_extrait or ""
        texte = brut.strip() if nettoyer else brut
        if not texte.strip():
            continue
        if plafond_par_doc is not None and len(texte) > plafond_par_doc:
            texte = texte[:plafond_par_doc] + marque_plafond
        en_tete = entete(doc)
        place = reste - len(en_tete) - marge
        if place <= seuil:
            break
        if len(texte) > place:
            texte = texte[:place] + marque_budget
        parts.append(en_tete + texte)
        reste -= len(en_tete) + len(texte)
    return "\n".join(parts) if parts else vide
