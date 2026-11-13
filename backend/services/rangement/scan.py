"""
Le scan d'un emplacement : parcours, comparaison, instantané — et la tâche de nuit.

Porté de l'application « rangement » (`app/inventaire/scan.py`), passé en **asynchrone** : le dépôt
l'est, et le parcours du disque (`os.scandir`, bloquant) part dans un fil, **un dossier à la fois**
(`asyncio.to_thread`), pour ne jamais geler la boucle du worker.

Trois principes, chacun pour une raison mesurée :

- **Métadonnées seulement** (`os.scandir` + `stat`) : aucun octet de contenu n'est lu. Un scan de
  15 To reste une affaire de noms, de tailles et de dates.
- **Comparaison dossier par dossier** : pour chaque dossier, ce qu'on voit est comparé à ce que le
  dépôt connaît de CE dossier. La mémoire reste bornée et un rescan sans changement **n'écrit
  aucune ligne**.
- **Jamais « disparu » sur un doute** : un dossier illisible, un fichier dont le `stat` échoue, une
  racine vide alors que l'inventaire connaît des fichiers (partage démonté, droits perdus) — dans
  tous ces cas, rien n'est marqué disparu.

D'où viennent les listes de dossiers : d'une **source**. `SourceDisque` lit le disque du serveur
(le NAS monté dans le worker) ; `SourceEnvoi` relit ce qu'un agent de poste ou un import WizTree a
déposé en base. Le reste — comparaison, prudence, totaux, instantané — est le même pour tous.
"""

import asyncio
import inspect
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from logger import get_logger
from services.rangement.depot import (
    Compteurs,
    Connu,
    Depot,
    Element,
    Emplacement,
    LigneInstantane,
    ScanEnCours,
    chemin_enfant,
)
from services.rangement.exclusions import Exclusions
from services.rangement.reglages import ReglagesInventaire

log = get_logger(__name__)

#: Garde-fou contre une arborescence pathologique (boucle de montage, etc.).
PROFONDEUR_MAX = 200
#: Les systèmes de fichiers n'ont pas tous la même précision de date.
TOLERANCE_MTIME_S = 0.001
#: Un scan « en cours » depuis plus longtemps a forcément été interrompu (redémarrage…).
AGE_ORPHELIN_HEURES = 12


@dataclass
class Resultat:
    scan_id: int | None
    statut: str
    compteurs: Compteurs = field(default_factory=Compteurs)
    message: str = ""


Listing = tuple[dict[str, Element], set[str]]


def comparer(actuels: dict[str, Element], connus: dict[str, Connu],
             illisibles: set[str]) -> tuple[list[Element], list[Element], list[str]]:
    """(ajouts, modifs, disparus) d'un dossier. Un changement de type = disparu + ajout. PURE."""
    ajouts: list[Element] = []
    modifs: list[Element] = []
    disparus: list[str] = []
    for nom, el in actuels.items():
        connu = connus.get(nom)
        if connu is None:
            ajouts.append(el)
        elif connu.est_dossier != el.est_dossier:
            disparus.append(nom)
            ajouts.append(el)
        elif not el.est_dossier and (
                connu.taille != el.taille or connu.mtime is None
                or abs(connu.mtime - el.mtime) > TOLERANCE_MTIME_S):
            modifs.append(el)
    disparus.extend(n for n in connus if n not in actuels and n not in illisibles)
    return ajouts, modifs, disparus


def contient(parent: str, enfant: str) -> bool:
    """`enfant` est-il `parent` ou en dessous ? Comparaison de chemins déjà normalisés."""
    try:
        return os.path.normcase(os.path.commonpath([parent, enfant])) == os.path.normcase(parent)
    except ValueError:  # lecteurs différents sous Windows, absolu contre relatif
        return False


class Source(Protocol):
    """Ce que le scan attend d'une origine de listes de dossiers."""

    async def verifier(self, depot: Depot, emp: Emplacement) -> str | None:
        """Message d'échec si la source est inutilisable (rien ne sera marqué disparu)."""

    async def lister(self, relatif: str, profondeur: int, c: Compteurs) -> Listing | None:
        """Enfants retenus d'un dossier, ou `None` s'il est illisible (rien n'en disparaîtra)."""


class SourceDisque:
    """Le disque du serveur : `os.scandir` + `stat`, jamais le contenu.

    `racine_autorisee` : le montage du NAS. L'API ne voit pas ce montage (il n'existe que dans le
    worker, décision d'architecture n° 5) : c'est donc ICI, au moment de lire, que le chemin réel de
    la racine est confronté au périmètre — un lien posé depuis ne fait pas sortir du NAS.
    """

    def __init__(self, racine: str, exclusions: Exclusions, racine_autorisee: str | None = None) -> None:
        self.racine = racine
        self.exclusions = exclusions
        self.racine_autorisee = racine_autorisee

    async def verifier(self, depot: Depot, emp: Emplacement) -> str | None:
        return await asyncio.to_thread(self._verifier)

    def _verifier(self) -> str | None:
        if self.racine_autorisee is not None:
            autorisee = os.path.realpath(self.racine_autorisee)
            if not contient(autorisee, os.path.realpath(self.racine)):
                return f"la racine n'est pas sous la racine autorisée ({self.racine_autorisee})"
        if not os.path.isdir(self.racine):
            return f"racine introuvable : {self.racine}"
        # On ne suit jamais un lien, pas même à la racine.
        if os.path.normcase(os.path.realpath(self.racine)) != os.path.normcase(os.path.normpath(self.racine)):
            return f"la racine est devenue un lien symbolique : {self.racine}"
        return None

    async def lister(self, relatif: str, profondeur: int, c: Compteurs) -> Listing | None:
        return await asyncio.to_thread(self._lister, relatif, profondeur, c)

    def _lister(self, relatif: str, profondeur: int, c: Compteurs) -> Listing | None:
        absolu = os.path.join(self.racine, *relatif.split("/")) if relatif else self.racine
        try:
            iterateur = os.scandir(absolu)
        except OSError as exc:
            c.nb_erreurs += 1
            log.warning("Dossier illisible ignoré", chemin=absolu, erreur=str(exc))
            return None
        actuels: dict[str, Element] = {}
        illisibles: set[str] = set()
        with iterateur:
            try:
                for e in iterateur:
                    try:
                        # Nom hérité d'un vieil encodage : PostgreSQL le refuserait, et c'est tout le
                        # dossier qui échouerait. On l'écarte et on le compte.
                        e.name.encode("utf-8")
                        if e.is_symlink():
                            continue
                        est_dossier = e.is_dir(follow_symlinks=False)
                        if not est_dossier and not e.is_file(follow_symlinks=False):
                            continue  # socket, périphérique…
                        if self.exclusions.exclut(e.name, chemin_enfant(relatif, e.name), e.path,
                                                  profondeur, est_dossier):
                            continue
                        st = e.stat(follow_symlinks=False)
                    except (OSError, UnicodeEncodeError):
                        c.nb_erreurs += 1
                        illisibles.add(e.name)
                        continue
                    actuels[e.name] = Element(e.name, est_dossier, 0 if est_dossier else st.st_size,
                                              st.st_mtime)
            except OSError as exc:  # partage coupé PENDANT la lecture : dossier tenu pour illisible
                c.nb_erreurs += 1
                log.warning("Lecture interrompue, dossier ignoré", chemin=absolu, erreur=str(exc))
                return None
        return actuels, illisibles


def nom_valide(nom: str) -> bool:
    """Un nom d'élément venu de l'extérieur (agent, import) : jamais un chemin, jamais un piège."""
    return (bool(nom) and nom not in (".", "..") and "/" not in nom and "\\" not in nom
            and "\x00" not in nom and len(nom) <= 1024)


class SourceEnvoi:
    """Les listes déposées en base par un agent de poste ou un import (tables d'envoi).

    Elles viennent de l'extérieur : chaque nom est revalidé (`nom_valide`), et les exclusions
    s'appliquent comme sur le disque. Un dossier absent de l'envoi, ou signalé illisible, est tenu
    pour illisible : rien n'en disparaît.
    """

    def __init__(self, depot: Depot, envoi_id: int, exclusions: Exclusions) -> None:
        self.depot = depot
        self.envoi_id = envoi_id
        self.exclusions = exclusions

    async def verifier(self, depot: Depot, emp: Emplacement) -> str | None:
        if await depot.dossier_envoi(self.envoi_id, "") is None:
            return "envoi sans dossier racine — rien n'a été marqué disparu"
        return None

    async def lister(self, relatif: str, profondeur: int, c: Compteurs) -> Listing | None:
        recu = await self.depot.dossier_envoi(self.envoi_id, relatif)
        if recu is None or recu.illisible:
            c.nb_erreurs += 1
            return None
        actuels: dict[str, Element] = {}
        illisibles = {n for n in recu.illisibles if nom_valide(n)}
        c.nb_erreurs += len(recu.illisibles)
        for el in recu.enfants:
            if not nom_valide(el.nom):
                c.nb_erreurs += 1
                continue
            chemin = chemin_enfant(relatif, el.nom)
            if self.exclusions.exclut(el.nom, chemin, chemin, profondeur, el.est_dossier):
                continue
            actuels[el.nom] = el
        return actuels, illisibles


#: Pause entre deux dossiers : `asyncio.sleep` en vrai ; une fonction ordinaire en test.
Sommeil = Callable[[float], Any]
#: Demande d'arrêt (bouton « Annuler » d'une tâche) : relue entre deux dossiers.
Arret = Callable[[], bool]


class ScanArrete(Exception):
    """Arrêt demandé : le scan est clos « interrompu ». Ce qui a été comparé reste écrit ; rien
    d'autre n'est marqué disparu (un dossier non parcouru n'est jamais comparé)."""


class Scanner:
    def __init__(self, depot: Depot, emplacement: Emplacement, exclusions: Exclusions, *,
                 profondeur_instantane: int = 3, pause_s: float = 0.0, declencheur: str = "manuel",
                 sommeil: Sommeil = asyncio.sleep, source: Source | None = None,
                 racine_autorisee: str | None = None, arret: Arret | None = None) -> None:
        self.depot = depot
        self.emp = emplacement
        self.exclusions = exclusions
        self.source: Source = source or SourceDisque(emplacement.racine, exclusions, racine_autorisee)
        self.profondeur_instantane = profondeur_instantane
        self.pause_s = pause_s
        self.declencheur = declencheur
        self.sommeil = sommeil
        self.arret = arret
        self.c = Compteurs()
        self._instantane: list[LigneInstantane] = []
        self._scan_id = 0

    # ------------------------------------------------------------------ entrée
    async def executer(self, scan_id: int | None = None) -> Resultat:
        """Scanne l'emplacement. `scan_id` : scan déjà ouvert (scan manuel), sinon on l'ouvre.

        Lève `ScanEnCours` si un autre scan de cet emplacement tourne. Toute autre erreur est
        consignée dans le scan (statut « echec »), jamais propagée : la tâche de nuit doit pouvoir
        passer à l'emplacement suivant.
        """
        self.c = Compteurs()
        self._instantane = []
        if scan_id is None:
            scan_id = await self.depot.ouvrir_scan(self.emp.id, self.declencheur)
        self._scan_id = scan_id
        racine = self.emp.racine
        try:
            refus = await self.source.verifier(self.depot, self.emp)
            if refus:
                return await self._fermer("echec", refus)
            premier = await self.source.lister("", 0, self.c)
            if premier is None:
                return await self._fermer("echec", f"racine illisible : {racine}")
            if not premier[0] and await self.depot.a_des_entrees(self.emp.id):
                return await self._fermer("echec", "racine vide alors que l'inventaire connaît des fichiers "
                                                   "(partage démonté ?) — rien n'a été marqué disparu")
            await self._explorer("", 0, premier)
            await self.depot.enregistrer_instantane(self._scan_id, self._instantane)
            partiel = (f"{self.c.nb_erreurs} élément(s) illisible(s) : totaux partiels"
                       if self.c.nb_erreurs else "")
            return await self._fermer("termine", partiel)
        except ScanArrete:
            return await self._fermer("interrompu", "arrêté à la demande — totaux partiels, rien de plus "
                                                    "n'a été marqué disparu")
        except Exception as exc:
            log.exception("Scan en échec", emplacement_id=self.emp.id, scan_id=self._scan_id)
            message = f"{type(exc).__name__} : {str(exc)[:300]}"
            try:
                return await self._fermer("echec", message)
            except Exception:
                log.exception("Impossible de clore le scan", scan_id=self._scan_id)
                return Resultat(self._scan_id, "echec", self.c, message)

    # ---------------------------------------------------------------- interne
    async def _fermer(self, statut: str, message: str = "") -> Resultat:
        await self.depot.fermer_scan(self._scan_id, statut, self.c, message)
        log.info("Scan d'inventaire clos", scan_id=self._scan_id, emplacement_id=self.emp.id, statut=statut,
                 fichiers=self.c.nb_fichiers, ajouts=self.c.nb_ajouts, modifs=self.c.nb_modifs,
                 disparus=self.c.nb_disparus, erreurs=self.c.nb_erreurs, message=message)
        return Resultat(self._scan_id, statut, self.c, message)

    async def _pause(self) -> None:
        r = self.sommeil(self.pause_s)
        if inspect.isawaitable(r):
            await r

    async def _explorer(self, relatif: str, profondeur: int,
                        listing: Listing | None = None) -> tuple[int, int, int] | None:
        """Compare un dossier puis descend. Rend (taille, nb_fichiers, nb_dossiers) du sous-arbre."""
        if self.arret is not None and self.arret():
            raise ScanArrete
        if profondeur > PROFONDEUR_MAX:
            self.c.nb_erreurs += 1
            return None
        if listing is None:
            listing = await self.source.lister(relatif, profondeur, self.c)
            if listing is None:
                return None
        actuels, illisibles = listing
        connus = await self.depot.enfants(self.emp.id, relatif)
        ajouts, modifs, disparus = comparer(actuels, connus, illisibles)
        if disparus:  # d'abord : un changement de type libère le nom avant l'ajout
            self.c.nb_disparus += await self.depot.marquer_disparus(self.emp.id, self._scan_id, relatif, disparus)
        if ajouts:
            await self.depot.ajouter(self.emp.id, self._scan_id, relatif, ajouts)
            self.c.nb_ajouts += len(ajouts)
        if modifs:
            await self.depot.modifier(self.emp.id, self._scan_id, relatif, modifs)
            self.c.nb_modifs += len(modifs)
        if self.pause_s > 0:
            await self._pause()

        taille = nb_fichiers = nb_dossiers = 0
        #: Totaux de sous-dossiers à (ré)écrire — seulement ceux qui ont changé : un rescan sans
        #: changement n'écrit toujours rien.
        totaux_a_ecrire: list[tuple[str, int, int, int]] = []
        for el in actuels.values():
            if el.est_dossier:
                nb_dossiers += 1
                self.c.nb_dossiers += 1
                sous = await self._explorer(chemin_enfant(relatif, el.nom), profondeur + 1)
                connu = connus.get(el.nom)
                if sous is None and connu is not None and connu.totaux:
                    # Illisible cette fois : on compte son dernier total connu, sinon le parent
                    # baisserait à tort — et cette baisse serait enregistrée puis propagée.
                    taille += connu.totaux[0]
                    nb_fichiers += connu.totaux[1]
                    nb_dossiers += connu.totaux[2]
                if sous:
                    taille += sous[0]
                    nb_fichiers += sous[1]
                    nb_dossiers += sous[2]
                    if connu is None or not connu.est_dossier or connu.totaux != sous:
                        totaux_a_ecrire.append((el.nom, *sous))
            else:
                nb_fichiers += 1
                taille += el.taille
                self.c.nb_fichiers += 1
                self.c.volume_octets += el.taille
        if totaux_a_ecrire:
            await self.depot.mettre_a_jour_totaux(self.emp.id, relatif, totaux_a_ecrire)
        if profondeur <= self.profondeur_instantane:
            self._instantane.append(LigneInstantane(relatif, profondeur, taille, nb_fichiers, nb_dossiers))
        return taille, nb_fichiers, nb_dossiers


# --------------------------------------------------------------------------- #
# Tâche de nuit                                                                #
# --------------------------------------------------------------------------- #
def dans_fenetre(heure: int, debut: int, fin: int) -> bool:
    """`debut` inclus, `fin` exclue ; `debut == fin` = toute la journée ; peut passer minuit. PURE."""
    if debut == fin:
        return True
    if debut < fin:
        return debut <= heure < fin
    return heure >= debut or heure < fin


async def planifier_et_scanner(depot: Depot, reglages: ReglagesInventaire, maintenant: datetime,
                               sommeil: Sommeil = asyncio.sleep, arret: Arret | None = None) -> list[Resultat]:
    """Scanne, un par un, les emplacements actifs dont le dernier scan réussi est assez ancien.

    `maintenant` est l'heure LOCALE (fuseau du foyer, avec son fuseau) : c'est elle que la fenêtre
    décrit, et elle se compare aux dates de fin des scans (qui portent aussi leur fuseau).
    """
    if not dans_fenetre(maintenant.hour, reglages.heure_debut, reglages.heure_fin):
        return []
    await depot.interrompre_scans_orphelins(AGE_ORPHELIN_HEURES)
    resultats: list[Resultat] = []
    for emp in await depot.emplacements(actifs_seulement=True):
        if arret is not None and arret():
            break
        if not emp.sur_serveur:  # un poste envoie lui-même son inventaire
            continue
        dernier = await depot.dernier_scan(emp.id, termine_seulement=True)
        if dernier and dernier.get("fin") and \
                maintenant - dernier["fin"] < timedelta(hours=reglages.delai_min_heures):
            continue
        try:
            scan_id = await depot.ouvrir_scan(emp.id, "nuit")
        except ScanEnCours:
            continue
        scanner = Scanner(depot, emp, reglages.exclusions,
                          profondeur_instantane=reglages.profondeur_instantane,
                          pause_s=reglages.pause_ms / 1000, declencheur="nuit", sommeil=sommeil,
                          racine_autorisee=reglages.racine_autorisee or None, arret=arret)
        try:  # un emplacement en échec ne doit pas priver les suivants de leur scan
            resultats.append(await scanner.executer(scan_id))
            await depot.purger_instantanes(emp.id, reglages.instantanes_gardes)
        except Exception:
            log.exception("Scan de nuit en échec", emplacement_id=emp.id)
            resultats.append(Resultat(scan_id, "echec"))
    return resultats
