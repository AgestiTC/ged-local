"""
Chemins SMB — un seul aller-retour `smb://hote/partage/rel` ↔ (hôte, partage, chemin relatif)
==============================================================================================
Étape 2 du plan « Rangement sur Sources SMB » (docs/plan-rangement-sources-smb.md). Trois parseurs
copiés vivaient dans le code (réorganisation, accès aux fichiers, scans) ; ils passent par ici.
Chacun garde ses cas limites d'avant (figés par tests/test_smb_chemins.py) : seule la forme
canonique `decouper`/`composer` est à utiliser dans le code neuf.

Placé dans `services/` et non `services/rangement/` : la GED (lecture, corbeille, scans) s'en sert
autant que le Rangement.
"""

from __future__ import annotations

from typing import NamedTuple

PREFIXE = "smb://"


class CheminSmb(NamedTuple):
    hote: str
    partage: str
    rel: str  # « / » pour la racine du partage, sinon « /a/b » sans barre finale


def _morceaux(reste: str) -> tuple[str, bool, str, bool, str]:
    """`hote/partage/queue` → (hote, barre_apres_hote, partage, barre_apres_partage, queue), brut."""
    hote, s1, apres = reste.partition("/")
    partage, s2, queue = apres.partition("/")
    return hote, bool(s1), partage, bool(s2), queue


def decouper(uri: str | None) -> CheminSmb | None:
    """Forme canonique : `smb://h/p/a/b/` → (h, p, '/a/b') ; `smb://h/p` → (h, p, '/') ; None si ce
    n'est pas un chemin SMB complet (préfixe absent, hôte ou partage vide)."""
    if not uri or not uri.startswith(PREFIXE):
        return None
    hote, _, partage, _, queue = _morceaux(uri[len(PREFIXE):])
    if not hote or not partage:
        return None
    return CheminSmb(hote, partage, ("/" + queue).rstrip("/") or "/")


def composer(hote: str, partage: str, rel: str = "/") -> str:
    """(h, p, '/a/b') → `smb://h/p/a/b` ; racine → `smb://h/p`. Inverse exact de `decouper`."""
    if not hote or not partage or "/" in hote or "/" in partage:
        raise ValueError("Hôte ou partage SMB invalide")
    r = normaliser_rel(rel)
    return f"{PREFIXE}{hote}/{partage}" + ("" if r == "/" else r)


def normaliser_rel(rel: str | None) -> str:
    """Chemin relatif au partage, forme « /a/b » (« / » = racine). Accepte « \\ » ; refuse « .. »."""
    morceaux = [m for m in (rel or "").replace("\\", "/").split("/") if m and m != "."]
    if ".." in morceaux:
        raise ValueError("Chemin SMB invalide (remontée de dossier)")
    return "/" + "/".join(morceaux)


# --- Formes historiques (comportement figé, ne pas utiliser dans le code neuf) --------------------

def ancien_organize(chemin: str | None) -> tuple[str, str, str] | None:
    """Réorganisation : exige `smb://h/p/…` (une barre après le partage), garde la barre finale,
    tolère un hôte ou un partage vide."""
    if not chemin or not chemin.startswith(PREFIXE):
        return None
    hote, s1, partage, s2, queue = _morceaux(chemin[len(PREFIXE):])
    if not s1 or not s2:
        return None
    return hote, partage, "/" + queue


def ancien_acces(chemin: str) -> tuple[str, str, str]:
    """Accès aux fichiers / corbeille : lève ValueError si hôte ou partage vide ; garde la barre
    finale ; ne vérifie pas le préfixe (les appelants l'ont fait)."""
    hote, _, partage, _, queue = _morceaux(chemin[len(PREFIXE):])
    if not hote or not partage:
        raise ValueError(f"Chemin SMB invalide : {chemin}")
    return hote, partage, "/" + queue
