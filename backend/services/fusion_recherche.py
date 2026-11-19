"""
Fusion des signaux de la recherche hybride (plan prompts + RAG, étape B1).
==========================================================================
Chaque signal est une liste `(document, métadonnées, score)` triée du meilleur au moins bon :
plein texte strict (tous les mots), nom de fichier approché (trigrammes), métadonnées IA en « au
moins un mot », sens (cosinus). Deux façons de les fusionner :

- **pondérée** (historique) : chaque score est divisé par le meilleur de sa liste, puis
  texte × 0,4 + sens × 0,6. Le résultat dépend de l'écart entre les scores, donc de ce que
  contient le reste du lot — un même document change de place selon la taille de page demandée ;
- **RRF** (*reciprocal rank fusion*) : chaque liste apporte `poids / (K + rang)`. Seul le RANG
  compte : pas d'échelle à accorder entre un `ts_rank` (≈ 0,1) et un cosinus (≈ 0,8), et un
  document bien placé dans deux listes passe devant un document très bien placé dans une seule.

Fonctions pures : aucun accès à la base ni au réseau.
"""
from __future__ import annotations

from typing import Any, Sequence

PONDEREE = "ponderee"
RRF = "rrf"
METHODES = (PONDEREE, RRF)

# Constante de lissage de RRF (valeur d'usage, Cormack et al. 2009) : au-delà des premiers rangs,
# l'écart entre deux places compte peu.
K_RRF = 60

Resultat = tuple[Any, Any, float]


def _cle(doc: Any) -> str:
    return str(doc.id)


def ponderee(texte: Sequence[Resultat], sens: Sequence[Resultat],
             poids_texte: float = 0.4, poids_sens: float = 0.6) -> list[Resultat]:
    """Fusion historique : scores normalisés par le meilleur de chaque liste, puis pondérés."""
    max_t = max((s for _, _, s in texte), default=1.0) or 1.0
    max_s = max((s for _, _, s in sens), default=1.0) or 1.0
    scores: dict[str, float] = {}
    docs: dict[str, tuple[Any, Any]] = {}
    for liste, maxi, poids in ((texte, max_t, poids_texte), (sens, max_s, poids_sens)):
        for doc, meta, s in liste:
            cle = _cle(doc)
            scores[cle] = scores.get(cle, 0.0) + poids * (s / maxi)
            docs.setdefault(cle, (doc, meta))
    return [(docs[c][0], docs[c][1], sc) for c, sc in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]


def rrf(signaux: Sequence[tuple[Sequence[Resultat], float]], k: int = K_RRF) -> list[Resultat]:
    """
    `signaux` : `(liste triée, poids)`. Score = Σ poids / (k + rang), rang 1 = premier, puis
    ramené entre 0 et 1 en le divisant par le maximum possible (premier partout) : l'écran affiche
    `score × 100`, comme avec la fusion pondérée. À score égal, l'ordre d'arrivée est conservé.
    """
    plafond = sum(poids for _liste, poids in signaux) / (k + 1) or 1.0
    scores: dict[str, float] = {}
    docs: dict[str, tuple[Any, Any]] = {}
    for liste, poids in signaux:
        vus: set[str] = set()
        for rang, (doc, meta, _s) in enumerate(liste, start=1):
            cle = _cle(doc)
            if cle in vus:          # un document deux fois dans la même liste ne compte qu'une fois
                continue
            vus.add(cle)
            scores[cle] = scores.get(cle, 0.0) + poids / (k + rang)
            docs.setdefault(cle, (doc, meta))
    return [(docs[c][0], docs[c][1], sc / plafond)
            for c, sc in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]
