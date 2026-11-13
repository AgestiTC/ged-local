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
"""

import os
import re
from dataclasses import dataclass
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


def _normaliser(chemin: str) -> str:
    return os.path.normcase(os.path.normpath(chemin))


@dataclass(frozen=True)
class Exclusions:
    motifs: tuple[str, ...] = ()
    chemins_absolus: tuple[str, ...] = ()

    @classmethod
    def depuis_reglages(cls, motifs: str, chemins: str) -> "Exclusions":
        return cls(
            motifs=_liste(motifs),
            # `realpath` : un chemin saisi à travers un lien symbolique doit désigner le
            # même dossier que celui que voit le parcours.
            chemins_absolus=tuple(_normaliser(os.path.realpath(c)) for c in _liste(chemins)),
        )

    def exclut(self, nom: str, chemin_relatif: str, chemin_absolu: str,
               profondeur: int, est_dossier: bool) -> str | None:
        """Raison de l'exclusion (« système », « sauvegarde », « réglage ») ou `None`.

        `profondeur` vaut 0 pour les enfants directs de la racine de l'emplacement.
        """
        if nom.casefold() in _NOMS_VERROUILLES_CF:
            return "système"
        if est_dossier and profondeur == 0 and nom.startswith("@"):
            return "système"
        if self.chemins_absolus:
            absolu = _normaliser(chemin_absolu)
            for c in self.chemins_absolus:
                if absolu == c or absolu.startswith(c + os.sep):
                    return "sauvegarde"
        for motif in self.motifs:
            if fnmatchcase(nom, motif) or fnmatchcase(chemin_relatif, motif):
                return "réglage"
        return None
