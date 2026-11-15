"""Ce que l'inventaire ne parcourt JAMAIS (porté de rangement, `app/inventaire/exclusions.py`).

Deux familles, dans cet ordre de priorité :

1. **Verrouillées dans le code** — aucun réglage ne peut les retirer :
   - les noms système Synology et la quarantaine de la GED, à toute profondeur ;
   - tout dossier « @… » à la racine d'un emplacement (`@appstore`, `@docker`…) — plus
     bas, « @archives » est un nom d'utilisateur comme un autre ;
   - les chemins de sauvegarde déclarés (datastore PBS) **avec tout leur contenu**.
     Le datastore vit sur le même volume que les données (relevé 2026-10-12) : le
     parcourir coûterait des heures, et le ranger casserait les sauvegardes.
2. **Ajoutées par réglage** (`INVENTAIRE_EXCLUSIONS`) : motifs `fnmatch` testés sur le nom
   ET sur le chemin relatif. Un réglage ajoute ; il ne retire rien.

Un chemin exclu peut être un chemin du serveur (`/mnt/…`) ou, pour un emplacement lu par SMB, une
URI `smb://hôte/partage/dossier` (comparée sans casse, comme SMB lui-même) : un chemin du serveur
ne désigne PAS le même dossier qu'une URI, chacun ne vaut que pour son mode de lecture.
"""

import os
import posixpath
import re
from dataclasses import dataclass, replace
from fnmatch import fnmatchcase

#: Noms exclus à toute profondeur, quoi que disent les réglages.
NOMS_VERROUILLES = frozenset({
    "@eaDir",            # vignettes et index Synology
    "#recycle",          # corbeille des partages DSM
    "#snapshot",         # instantanés Btrfs exposés dans les partages
    "DOUBLON-MATOTEQUE",  # quarantaine des doublons de la GED (Matothèque)
})
#: Comparaison sans casse : un partage SMB peut exposer « #Recycle ».
_NOMS_VERROUILLES_CF = frozenset(n.casefold() for n in NOMS_VERROUILLES)


def _liste(texte: str) -> tuple[str, ...]:
    """Découpe un réglage texte (virgules ou retours à la ligne) en éléments non vides."""
    return tuple(m.strip() for m in re.split(r"[,\n]", texte or "") if m.strip())


def _est_smb(chemin: str) -> bool:
    return chemin[:6].lower() == "smb://"


def normaliser_chemin(chemin: str) -> str:
    """Forme comparable d'un chemin exclu ou parcouru (serveur ou URI `smb://`)."""
    if _est_smb(chemin):  # ni realpath ni normpath : « smb:// » deviendrait « smb:/ »
        return "smb://" + posixpath.normpath("/" + chemin[6:].replace("\\", "/")).lstrip("/").casefold()
    return os.path.normcase(os.path.normpath(chemin))


def _sous(absolu: str, exclu: str) -> bool:
    """`absolu` est-il `exclu` ou l'un de ses descendants ? (deux formes déjà normalisées)"""
    sep = "/" if _est_smb(exclu) else os.sep
    return absolu == exclu or absolu.startswith(exclu.rstrip(sep) + sep)


@dataclass(frozen=True)
class Exclusions:
    motifs: tuple[str, ...] = ()
    chemins_absolus: tuple[str, ...] = ()
    #: Sauter les dossiers « @… » à la racine (dossiers système Synology). Vrai quand la racine de
    #: l'emplacement est celle d'un partage (montage, ou SMB sur tout le partage). Faux pour un
    #: emplacement SMB sur un SOUS-dossier : « homes/Tom/@@@-trier URGENT » est un dossier de
    #: l'utilisateur — la bascule de « Home-TOM » l'avait fait sauter (528 Go « disparus », 15/11/2026).
    arobase_racine: bool = True

    @classmethod
    def depuis_reglages(cls, motifs: str, chemins: str) -> "Exclusions":
        return cls(
            motifs=_liste(motifs),
            # `realpath` : un chemin saisi à travers un lien symbolique doit désigner le
            # même dossier que celui que voit le parcours.
            chemins_absolus=tuple(normaliser_chemin(c if _est_smb(c) else os.path.realpath(c))
                                  for c in _liste(chemins)),
        )

    def pour_smb(self, sous_dossier: str | None) -> "Exclusions":
        """Les mêmes, pour un emplacement SMB : les « @… » de tête ne sont des dossiers système qu'à la
        racine d'un partage (`sous_dossier` « / »)."""
        return replace(self, arobase_racine=(sous_dossier or "/") == "/")

    def exclut(self, nom: str, chemin_relatif: str, chemin_absolu: str,
               profondeur: int, est_dossier: bool) -> str | None:
        """Raison de l'exclusion (« système », « sauvegarde », « réglage ») ou `None`.

        `profondeur` vaut 0 pour les enfants directs de la racine de l'emplacement.
        """
        if nom.casefold() in _NOMS_VERROUILLES_CF:
            return "système"
        if est_dossier and profondeur == 0 and self.arobase_racine and nom.startswith("@"):
            return "système"
        if self.chemins_absolus:
            absolu = normaliser_chemin(chemin_absolu)
            for c in self.chemins_absolus:
                if _sous(absolu, c):
                    return "sauvegarde"
        for motif in self.motifs:
            if fnmatchcase(nom, motif) or fnmatchcase(chemin_relatif, motif):
                return "réglage"
        return None
