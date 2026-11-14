"""
Contrat du dépôt de l'inventaire — ce que le scan attend d'une base, quelle qu'elle soit.

Deux implémentations : `DepotPostgres` (la vraie, `depot_postgres.py`) et `DepotMemoire`
(`tests/fakes/depot_memoire.py`). Le scan, la carte et la recherche de copies ne connaissent que
ce contrat : c'est ce qui permet de tester toute la logique sous SQLite, où les tables `inv_*`
n'existent pas (cf. `models/inventaire.py`).

Porté de l'application « rangement » (`app/inventaire/depot.py`). Deux écarts voulus :
- tout est **asynchrone** (le socle de Matothèque l'est) ;
- un poste ne porte plus l'empreinte de son jeton : il pointe un jeton de `jetons_api`
  (portée `agent`, décision d'architecture n° 2), d'où `jeton_id`.

Conventions de chemin : **relatif à la racine de l'emplacement, séparateur « / »**. La racine
elle-même est `""` ; un enfant direct a pour parent `""`.
"""

import posixpath
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

STATUTS = ("en_cours", "termine", "echec", "interrompu")

from models.inventaire import SOURCES_EMPLACEMENT  # noqa: E402,F401 — une seule liste (CHECK en base)

#: Statuts d'une passe « copies sur disque ». `limite` et `hors_fenetre` ne sont pas des échecs :
#: la passe s'est arrêtée d'elle-même et la suivante reprendra où elle en était.
STATUTS_PASSE = ("en_cours", "termine", "limite", "hors_fenetre", "echec", "interrompu")

STATUTS_ENVOI = ("reception", "traitement", "traite", "abandonne")


class ScanEnCours(RuntimeError):
    """Un scan de cet emplacement tourne déjà (un seul à la fois, garanti par la base)."""


class DoublonRacine(RuntimeError):
    """Cette racine est déjà déclarée."""


class PosteEnDouble(RuntimeError):
    """Un poste porte déjà ce nom, ou ce jeton."""


class EnvoiEnCours(RuntimeError):
    """Un envoi de cet emplacement est déjà en cours de traitement."""


class PasseEnCours(RuntimeError):
    """Une passe de recherche des copies tourne déjà (une seule à la fois)."""


@dataclass(frozen=True)
class Emplacement:
    id: int
    libelle: str
    racine: str
    actif: bool = True
    #: D'où viennent ses listes : `serveur` (disque du serveur, le NAS monté), `agent` (un
    #: poste qui envoie son inventaire), `import` (export WizTree) ou `smb` (le NAS lu par SMB
    #: avec une Source déclarée dans l'interface — plan Rangement sur Sources SMB).
    source: str = "serveur"
    #: Poste propriétaire (source `agent`) ; `None` ailleurs.
    poste_id: int | None = None
    #: Emplacement `smb` : la Source qui donne l'accès (identifiant, texte), le partage, le dossier
    #: dans le partage (« / » = tout le partage). `None` ailleurs. La racine vaut alors
    #: `smb://hote/partage/dossier` (forme canonique de `smb_chemins.composer`).
    source_id: str | None = None
    partage: str | None = None
    sous_dossier: str | None = None

    @property
    def sur_serveur(self) -> bool:
        """Seul un emplacement « serveur » se parcourt et se lit sur le DISQUE du serveur."""
        return self.source == "serveur"

    @property
    def est_smb(self) -> bool:
        """Lu par SMB avec une Source (scan, copies et rangement : étapes 4 à 6 du plan)."""
        return self.source == "smb"


@dataclass(frozen=True)
class Poste:
    """Un PC qui porte l'agent. Son jeton vit dans `jetons_api` : ici, seulement son identifiant."""

    id: int
    nom: str
    actif: bool = True
    dernier_contact: datetime | None = None
    version: str = ""
    lecture_jour: date | None = None
    lecture_octets: int = 0
    jeton_id: uuid.UUID | None = None


@dataclass(frozen=True)
class Element:
    """Ce que le parcours voit d'un fichier ou d'un dossier. Jamais son contenu."""

    nom: str
    est_dossier: bool
    taille: int
    mtime: float


@dataclass(frozen=True)
class DossierEnvoye:
    """La liste d'un dossier telle qu'un agent (ou un import) l'a envoyée."""

    chemin: str
    illisible: bool = False
    enfants: tuple[Element, ...] = ()
    illisibles: tuple[str, ...] = ()


@dataclass(frozen=True)
class Connu:
    """Ce que le dépôt sait d'un enfant encore présent au dernier passage."""

    nom: str
    est_dossier: bool
    taille: int
    mtime: float | None
    #: Dossier seulement : (taille, nb_fichiers, nb_dossiers) de tout son sous-arbre, ou
    #: `None` tant qu'aucun scan ne l'a calculé.
    totaux: tuple[int, int, int] | None = None


@dataclass
class Compteurs:
    nb_dossiers: int = 0
    nb_fichiers: int = 0
    volume_octets: int = 0
    nb_ajouts: int = 0
    nb_modifs: int = 0
    nb_disparus: int = 0
    nb_erreurs: int = 0


@dataclass(frozen=True)
class LigneInstantane:
    chemin: str
    profondeur: int
    taille_totale: int
    nb_fichiers: int
    nb_dossiers: int


@dataclass
class Fichier:
    """Un fichier candidat aux copies, avec ses empreintes connues.

    Une empreinte n'est **valable** que si elle a été calculée sur la taille et la date que
    l'inventaire connaît aujourd'hui : un fichier modifié depuis est relu, jamais cru sur parole.
    """

    id: int
    emplacement_id: int
    chemin: str
    taille: int
    mtime: float | None
    partielle: bytes | None = None
    complete: bytes | None = None
    emp_taille: int | None = None
    emp_mtime: float | None = None

    def _a_jour(self) -> bool:
        return self.mtime is not None and self.emp_taille == self.taille and self.emp_mtime == self.mtime

    @property
    def partielle_valide(self) -> bool:
        return self.partielle is not None and self._a_jour()

    @property
    def complete_valide(self) -> bool:
        return self.complete is not None and self._a_jour()


@dataclass(frozen=True)
class Copie:
    emplacement_id: int
    chemin: str


@dataclass(frozen=True)
class Groupe:
    """Des fichiers au contenu identique (même empreinte complète, même taille)."""

    empreinte: bytes
    taille: int
    copies: tuple[Copie, ...]

    @property
    def recuperable(self) -> int:
        """Ce que libérerait le fait de ne garder qu'un exemplaire."""
        return self.taille * (len(self.copies) - 1)


@dataclass(frozen=True)
class Bilan:
    recuperable: int = 0
    nb_groupes: int = 0
    nb_en_trop: int = 0


@dataclass(frozen=True)
class RecuperableLieu:
    """Pour un emplacement : `interne` = copies en trop DANS l'emplacement ; `ailleurs` =
    volume de ses fichiers qui ont aussi une copie dans un autre emplacement."""

    interne: int = 0
    ailleurs: int = 0


@dataclass
class ResumePasse:
    octets_lus: int = 0
    nb_partielles: int = 0
    nb_completes: int = 0
    nb_erreurs: int = 0
    nb_changes: int = 0
    nb_reportes: int = 0


def chemin_enfant(parent: str, nom: str) -> str:
    return f"{parent}/{nom}" if parent else nom


def extension(el: Element) -> str | None:
    """Extension d'un fichier, en minuscules et sans le point ; `None` pour un dossier ou sans."""
    if el.est_dossier:
        return None
    # posixpath et non os.path : même résultat quel que soit le système qui exécute le code.
    return posixpath.splitext(el.nom)[1].lower().lstrip(".") or None


class Depot(Protocol):
    #: Nombre de lignes d'entrées écrites (ajout, modification, disparition, totaux) — sert à
    #: vérifier qu'un rescan sans changement n'écrit rien.
    ecritures_entrees: int

    # Emplacements
    async def emplacements(self, actifs_seulement: bool = False) -> list[Emplacement]: ...
    async def emplacement(self, emplacement_id: int) -> Emplacement | None: ...
    async def creer_emplacement(self, libelle: str, racine: str, source: str = "serveur",
                                poste_id: int | None = None, *, source_id: str | None = None,
                                partage: str | None = None, sous_dossier: str | None = None) -> Emplacement: ...
    async def activer_emplacement(self, emplacement_id: int, actif: bool) -> None: ...

    # Scans
    async def ouvrir_scan(self, emplacement_id: int, declencheur: str) -> int: ...
    async def fermer_scan(self, scan_id: int, statut: str, compteurs: Compteurs, message: str = "") -> None: ...
    async def interrompre_scans_orphelins(self, age_heures: int) -> int: ...
    async def dernier_scan(self, emplacement_id: int, termine_seulement: bool = False) -> dict[str, Any] | None: ...
    async def scan_en_cours(self) -> bool: ...

    # Entrées — toujours par dossier : la mémoire du scan reste bornée.
    async def a_des_entrees(self, emplacement_id: int) -> bool: ...
    async def enfants(self, emplacement_id: int, parent: str) -> dict[str, Connu]: ...
    async def ajouter(self, emplacement_id: int, scan_id: int, parent: str, elements: list[Element]) -> None: ...
    async def modifier(self, emplacement_id: int, scan_id: int, parent: str, elements: list[Element]) -> None: ...
    async def marquer_disparus(self, emplacement_id: int, scan_id: int, parent: str, noms: list[str]) -> int: ...
    async def mettre_a_jour_totaux(self, emplacement_id: int, parent: str,
                                   totaux: list[tuple[str, int, int, int]]) -> None: ...

    # Instantanés
    async def enregistrer_instantane(self, scan_id: int, lignes: list[LigneInstantane]) -> None: ...
    async def purger_instantanes(self, emplacement_id: int, garder: int) -> int: ...
    async def scans_avec_instantane(self, emplacement_id: int, n: int) -> list[int]: ...
    async def tailles_instantane(self, scan_id: int) -> dict[str, int]: ...

    # Lecture de la carte. `prefixe` : chemin d'un dossier, `""` pour tout l'emplacement.
    async def dossier(self, emplacement_id: int, chemin: str) -> Connu | None: ...
    async def enfants_tries(self, emplacement_id: int, parent: str, limite: int) -> tuple[list[Connu], int]: ...
    async def repartition_types(self, emplacement_id: int, prefixe: str) -> list[tuple[str | None, int, int]]: ...
    async def plus_gros_fichiers(self, emplacement_id: int, prefixe: str, limite: int) -> list[tuple[str, int]]: ...

    # Copies sur disque. `emplacements` : identifiants des emplacements pris en compte (les
    # actifs) — une copie se cherche d'un emplacement à l'autre, pas seulement dedans.
    async def tailles_en_double(self, emplacements: list[int], taille_min: int, sous: int | None,
                                limite: int) -> list[int]: ...
    async def fichiers_de_taille(self, emplacements: list[int], taille: int) -> list[Fichier]: ...
    async def fichier(self, entree_id: int) -> Fichier | None: ...
    async def enregistrer_empreinte(self, entree_id: int, partielle: bytes, complete: bytes | None,
                                    taille: int, mtime: float | None) -> None: ...
    async def groupes_identiques(self, emplacements: list[int], limite: int,
                                 emplacement_id: int | None = None) -> list[Groupe]: ...
    async def bilan_identiques(self, emplacements: list[int]) -> Bilan: ...
    async def recuperable_par_emplacement(self, emplacements: list[int]) -> dict[int, RecuperableLieu]: ...
    async def empreintes_a_calculer(self, emplacement_id: int, emplacements: list[int], taille_min: int,
                                    limite: int) -> list[tuple[Fichier, str]]: ...
    async def ouvrir_passe(self) -> int: ...
    async def avancer_passe(self, passe_id: int, octets_lus: int) -> None: ...
    async def fermer_passe(self, passe_id: int, statut: str, resume: ResumePasse, message: str = "") -> None: ...
    async def interrompre_passes_orphelines(self, age_heures: int) -> int: ...
    async def octets_lus_depuis(self, moment: datetime) -> int: ...
    async def derniere_passe(self) -> dict[str, Any] | None: ...

    # Postes et envois. Un envoi = les listes de dossiers d'UN emplacement, déposées par lots
    # puis relues par le scan, puis effacées.
    async def creer_poste(self, nom: str, jeton_id: uuid.UUID | None = None) -> Poste: ...
    async def postes(self) -> list[Poste]: ...
    async def poste(self, poste_id: int) -> Poste | None: ...
    async def poste_par_jeton(self, jeton_id: uuid.UUID) -> Poste | None: ...
    async def contact_poste(self, poste_id: int, version: str) -> None: ...
    async def activer_poste(self, poste_id: int, actif: bool) -> None: ...
    async def changer_jeton_poste(self, poste_id: int, jeton_id: uuid.UUID | None) -> None: ...
    async def compter_lecture_poste(self, poste_id: int, jour: date, octets: int) -> None: ...
    async def ouvrir_envoi(self, emplacement_id: int) -> int: ...
    async def envoi(self, envoi_id: int) -> dict[str, Any] | None: ...
    async def ajouter_dossiers_envoi(self, envoi_id: int, dossiers: list[DossierEnvoye]) -> None: ...
    async def dossier_envoi(self, envoi_id: int, chemin: str) -> DossierEnvoye | None: ...
    async def clore_envoi(self, envoi_id: int, statut: str) -> None: ...
    async def abandonner_envois(self, age_heures: int) -> int: ...
