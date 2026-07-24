"""
Service Liens documentaires — détection BC ↔ facture (et devis, commandes…)
===========================================================================
Repère les documents qui **partagent une référence** (n° de commande, de facture,
de devis…) présente dans leur texte extrait, et propose de les **lier**.

Approche **hybride** (demande utilisateur 01/07) :
  1. Extraction de références par motifs FR (label « Facture n° », « BC », « Commande »…).
  2. Détection du *type* de chaque document (bon de commande / facture / devis) par
     mots-clés → un lien entre types **distincts** (BC + facture) est plus fiable qu'entre
     deux documents de même nature.
  3. Regroupement des documents par référence → paires candidates, **à valider** par l'utilisateur.

Purement heuristique et sans IA : rapide, local, déterministe. Les suggestions ne
modifient rien tant qu'elles ne sont pas validées.
"""

import re

from logger import get_logger

log = get_logger(__name__)

# ── Détection du type documentaire (par mots-clés, sur le début du texte + le nom) ──
_KIND_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("facture", ("facture", "invoice", "avoir")),
    ("bc", ("bon de commande", "bon de cde", "purchase order", "commande n")),
    ("devis", ("devis", "proforma", "pro forma", "quotation")),
    ("bl", ("bon de livraison", "delivery note", "packing list")),
]

# Libellés introduisant une référence, suivis éventuellement de « n° / no / # / : ».
_LABEL = (
    r"(?:facture|fact\.?|bon\s+de\s+commande|bon\s+de\s+cde|commande|cmd|devis|"
    r"b\.?c\.?|b\.?l\.?|r[ée]f(?:[ée]rence)?|ref|n[°ºo])"
)
_REF_RE = re.compile(
    _LABEL + r"[\s:.\-]*(?:n[°ºo]\.?|#|:)?[\s:.\-]*([A-Za-z0-9][A-Za-z0-9\-/_.]{3,24})",
    re.IGNORECASE,
)

# Tokens à ne jamais retenir comme référence (bruit courant).
_STOP_TOKENS = {"date", "total", "montant", "page", "client", "tva", "euros", "http", "https"}


def detect_kind(texte: str | None, nom: str | None = None) -> str | None:
    """Type documentaire probable : 'facture' | 'bc' | 'devis' | 'bl' | None."""
    hay = f"{(nom or '')} {(texte or '')[:800]}".lower()
    for kind, kws in _KIND_KEYWORDS:
        if any(kw in hay for kw in kws):
            return kind
    return None


def _normalise(token: str) -> str | None:
    """Normalise une référence (MAJUSCULES, ponctuation de bord retirée). None si trop faible."""
    t = token.strip(" .,-/_").upper()
    if not t or t.lower() in _STOP_TOKENS:
        return None
    if not any(c.isdigit() for c in t):
        return None  # une vraie référence contient au moins un chiffre
    # Rejette les années nues (2000–2099) et les nombres courts sans structure.
    if t.isdigit() and (len(t) < 5 or (2000 <= int(t) <= 2099 and len(t) == 4)):
        return None
    if len(t) < 4:
        return None
    return t


def extract_references(texte: str | None) -> set[str]:
    """Ensemble des références normalisées trouvées dans le texte (labels FR)."""
    if not texte:
        return set()
    refs: set[str] = set()
    for m in _REF_RE.finditer(texte):
        norme = _normalise(m.group(1))
        if norme:
            refs.add(norme)
    return refs


def _type_lien(k1: str | None, k2: str | None) -> tuple[str, float]:
    """Nature + score d'un lien selon les types des deux documents."""
    paire = {k1, k2}
    paire.discard(None)
    # Types distincts et complémentaires → lien « métier » fort.
    if len(paire) == 2:
        if paire <= {"bc", "facture", "devis", "bl"}:
            return "bc_facture", 0.95
        return "reference", 0.85
    # Même type ou types inconnus → simple partage de référence.
    return "reference", 0.7


def find_link_suggestions(
    docs: list[dict],
    max_par_reference: int = 8,
) -> list[dict]:
    """
    À partir de documents `{id, nom, texte}`, retourne les paires candidates :
      [{source_document_id, cible_document_id, reference, type_lien, score}]

    - Une référence partagée par plus de `max_par_reference` documents est ignorée
      (trop générique = bruit, ex. un en-tête récurrent).
    - Chaque paire n'apparaît qu'une fois (source = plus petit id).
    """
    # 1) référence → [(id, kind)]
    par_ref: dict[str, list[tuple[str, str | None]]] = {}
    kinds: dict[str, str | None] = {}
    for d in docs:
        did = str(d["id"])
        kind = detect_kind(d.get("texte"), d.get("nom"))
        kinds[did] = kind
        for ref in extract_references(d.get("texte")):
            par_ref.setdefault(ref, []).append((did, kind))

    # 2) paires candidates, dédupliquées, meilleure (score, cross-type) conservée par paire
    best: dict[tuple[str, str], dict] = {}
    for ref, membres in par_ref.items():
        # Un même document peut apparaître plusieurs fois pour une réf → unicité par id.
        uniques = {}
        for did, kind in membres:
            uniques.setdefault(did, kind)
        if len(uniques) < 2 or len(uniques) > max_par_reference:
            continue
        ids = list(uniques.items())
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                (a, ka), (b, kb) = ids[i], ids[j]
                type_lien, score = _type_lien(ka, kb)
                s, c = (a, b) if a < b else (b, a)
                cle = (s, c)
                cand = {
                    "source_document_id": s, "cible_document_id": c,
                    "reference": ref, "type_lien": type_lien, "score": score,
                }
                prev = best.get(cle)
                if prev is None or score > prev["score"]:
                    best[cle] = cand

    # Meilleures suggestions en premier (score décroissant).
    return sorted(best.values(), key=lambda x: x["score"], reverse=True)
