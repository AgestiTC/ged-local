"""
Utilitaires vecteurs — troncature Matryoshka (MRL)
==================================================
`qwen3-embedding` est entraîné en **Matryoshka Representation Learning** : le **préfixe**
d'un embedding est lui-même un embedding valide (à re-normaliser). On dérive donc un vecteur
1024-d à partir du 4096-d **sans ré-embed** — indexable ANN (pgvector plafonne à 2000 dims),
pour accélérer la 1ᵉ passe de la recherche sémantique.
"""
from __future__ import annotations

import math

# Dimension de la représentation tronquée indexable (≤ 2000 pour pgvector HNSW).
SMALL_DIM = 1024


def matryoshka_prefix(vecteur: list[float] | None, dims: int = SMALL_DIM) -> list[float] | None:
    """
    Préfixe `dims`-dimensionnel L2-normalisé d'un vecteur. Renvoie None si le vecteur est
    absent ou trop court (on ne tronque pas ce qui n'a pas la taille attendue).
    """
    if not vecteur or len(vecteur) < dims:
        return None
    prefixe = vecteur[:dims]
    norme = math.sqrt(sum(x * x for x in prefixe))
    if norme == 0:
        return None
    return [x / norme for x in prefixe]
