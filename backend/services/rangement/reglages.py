"""
Réglages de l'inventaire (module Rangement), lus dans la configuration à chaud de Matothèque.

Porté de l'application « rangement » (`app/inventaire/reglages.py`, catalogue `config_store`).
Ici, les clés vivent dans `runtime_config._DEFAULTS` (préfixe `inventaire_`) et se changent par
`PUT /api/inventaire/reglages` : rien à redémarrer, le worker relit la configuration avant chaque
tâche.

Hors réglage, et c'est voulu : les exclusions verrouillées (`exclusions.py`).
"""

from dataclasses import dataclass, field

from services.rangement.exclusions import Exclusions

#: Clé de configuration → (minimum, maximum) pour les entiers. Les bornes reprennent l'original.
BORNES: dict[str, tuple[int, int]] = {
    "inventaire_intervalle_min": (0, 1440),
    "inventaire_heure_debut": (0, 23),
    "inventaire_heure_fin": (0, 23),
    "inventaire_delai_min_heures": (0, 168),
    "inventaire_profondeur_instantane": (0, 10),
    "inventaire_instantanes_gardes": (1, 3650),
    "inventaire_pause_ms": (0, 1000),
}
#: Réglages texte (longueur bornée à l'écriture).
TEXTES: tuple[str, ...] = ("inventaire_exclusions", "inventaire_pbs_chemins", "inventaire_racine_autorisee")
CLES: tuple[str, ...] = (*BORNES, *TEXTES)
LONGUEUR_TEXTE_MAX = 4000


@dataclass(frozen=True)
class ReglagesInventaire:
    heure_debut: int = 1
    heure_fin: int = 6
    delai_min_heures: int = 20
    profondeur_instantane: int = 3
    instantanes_gardes: int = 90
    pause_ms: int = 0
    exclusions: Exclusions = field(default_factory=Exclusions)
    racine_autorisee: str = "/mnt/media"
    intervalle_min: int = 60


def _entier(cle: str, brut: str) -> int:
    """Valeur entière bornée ; une saisie illisible retombe sur le défaut (jamais d'exception)."""
    from services import runtime_config
    mini, maxi = BORNES[cle]
    try:
        v = int(float(brut))
    except (TypeError, ValueError):
        v = int(runtime_config.default_value(cle))
    return max(mini, min(v, maxi))


def lire() -> ReglagesInventaire:
    from services import runtime_config
    v = runtime_config.effective
    return ReglagesInventaire(
        heure_debut=_entier("inventaire_heure_debut", v("inventaire_heure_debut")),
        heure_fin=_entier("inventaire_heure_fin", v("inventaire_heure_fin")),
        delai_min_heures=_entier("inventaire_delai_min_heures", v("inventaire_delai_min_heures")),
        profondeur_instantane=_entier("inventaire_profondeur_instantane", v("inventaire_profondeur_instantane")),
        instantanes_gardes=_entier("inventaire_instantanes_gardes", v("inventaire_instantanes_gardes")),
        pause_ms=_entier("inventaire_pause_ms", v("inventaire_pause_ms")),
        exclusions=Exclusions.depuis_reglages(v("inventaire_exclusions"), v("inventaire_pbs_chemins")),
        racine_autorisee=(v("inventaire_racine_autorisee") or "").strip(),
        intervalle_min=_entier("inventaire_intervalle_min", v("inventaire_intervalle_min")),
    )


def valider(donnees: dict[str, str]) -> dict[str, str]:
    """Contrôle une saisie avant écriture : clés connues, entiers dans leurs bornes, textes bornés.

    Lève `ValueError` avec un message lisible ; rend les valeurs normalisées (texte).
    """
    sortie: dict[str, str] = {}
    for cle, brut in donnees.items():
        if cle not in CLES:
            raise ValueError(f"Réglage inconnu : {cle}")
        texte = str(brut).strip()
        if cle in BORNES:
            mini, maxi = BORNES[cle]
            try:
                n = int(texte)
            except ValueError:
                raise ValueError(f"{cle} : nombre entier attendu") from None
            if not mini <= n <= maxi:
                raise ValueError(f"{cle} : entre {mini} et {maxi}")
            sortie[cle] = str(n)
        else:
            if len(texte) > LONGUEUR_TEXTE_MAX:
                raise ValueError(f"{cle} : {LONGUEUR_TEXTE_MAX} caractères au plus")
            if cle == "inventaire_racine_autorisee" and not texte.startswith("/"):
                raise ValueError("La racine autorisée doit être un chemin absolu (ex. /mnt/media).")
            sortie[cle] = texte
    return sortie
