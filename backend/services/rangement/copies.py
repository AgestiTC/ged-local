"""
Copies sur disque : trouver les fichiers identiques de l'inventaire en lisant le moins possible.

Porté de rangement (`app/inventaire/doublons.py`, « copies multiples »), étape 6 du plan rangement +
mails, passé en asynchrone : le dépôt l'est, et les lectures partent dans UN fil dédié, en priorité
basse, pour ne jamais geler la boucle du worker.

C'est le **seul** endroit de l'inventaire qui lit le contenu des fichiers. Avec 15 To sur le NAS,
tout relire prendrait une demi-journée de disques à fond : la recherche procède donc en trois
passes, chacune ne regardant que ce que la précédente n'a pas su départager.

1. **Même taille** — dans la base, sans rien lire. Seuls les fichiers d'au moins
   `inventaire_copies_taille_min_mo` sont retenus.
2. **Empreinte partielle** — SHA-256 de la taille, des 64 premiers Ko et des 64 derniers.
3. **Empreinte complète** — SHA-256 du fichier entier, seulement pour les fichiers dont
   l'empreinte partielle est partagée.

Les empreintes sont gardées en base avec la taille et la date sur lesquelles elles ont été
calculées ; elles ne sont recalculées que si le fichier a changé. D'une nuit à l'autre, la
recherche reprend donc là où elle s'était arrêtée. Les fichiers des postes entrent dans la
comparaison, mais c'est leur agent qui les lit (`agent.demandes`). Les emplacements `smb` sont lus
par le réseau, avec le compte de leur Source (`copies_smb.LecteurSmb`, même formule d'empreinte).

Garde-fous : une **limite de lecture par nuit** (`inventaire_copies_limite_nuit_go`) et la fenêtre
de nuit (hors fenêtre, la passe s'arrête au fichier suivant) ; jamais pendant un scan ; les
exclusions sont revérifiées avant chaque lecture ; un fichier dont la taille ou la date ne
correspond plus à l'inventaire n'est pas lu ; un lien n'est jamais suivi. **Rien n'est supprimé
ni déplacé** — ranger viendra avec l'étape 10.
"""

import asyncio
import contextlib
import hashlib
import os
import stat
import threading
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

from logger import get_logger
from services.rangement.copies_smb import Injoignable, LecteurSmb
from services.rangement.depot import (
    Depot,
    Emplacement,
    Fichier,
    PasseEnCours,
    ResumePasse,
)
from services.rangement.exclusions import Exclusions
from services.rangement.reglages import ReglagesInventaire
from services.rangement.scan import TOLERANCE_MTIME_S, contient, dans_fenetre

log = get_logger(__name__)

#: Octets lus en tête et en queue pour l'empreinte partielle (même valeur que l'agent Go).
TAILLE_BLOC = 64 * 1024
#: Taille des lectures de l'empreinte complète.
TAILLE_LECTURE = 1024 * 1024
#: Nombre de tailles demandées à la base d'un coup (la mémoire reste bornée).
LOT_TAILLES = 500
#: La progression est enregistrée tous les … octets lus.
PAS_AVANCEMENT = 1024 ** 3
#: Une passe « en cours » depuis plus longtemps a forcément été interrompue.
AGE_ORPHELINE_HEURES = 12


class _Change(Exception):
    """Le fichier ne correspond plus à l'inventaire (taille, date, type) : on ne le lit pas."""


class _Ecarte(Exception):
    """Le fichier ne doit pas être lu (lien, hors de l'emplacement)."""


# --------------------------------------------------------------------------- #
# Lecture (synchrone, dans le fil dédié)                                       #
# --------------------------------------------------------------------------- #
def _baisser_priorite() -> None:
    """Le fil des lectures passe en priorité basse (sous Linux, l'entrée-sortie suit le processeur).
    Fil DÉDIÉ : une priorité abaissée ne se relève pas sans droits, on ne la prête à personne."""
    with contextlib.suppress(AttributeError, OSError):
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 10)  # type: ignore[attr-defined]


_LECTEUR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inventaire-copies", initializer=_baisser_priorite)


def exclu(exclusions: Exclusions, racine: str, chemin: str, *,
          absolu: Callable[[list[str]], str] | None = None) -> bool:
    """Le fichier ou l'un de ses dossiers est-il exclu par les réglages d'AUJOURD'HUI ?
    `absolu` donne le chemin absolu d'un préfixe (par défaut : sur le disque, sous `racine`)."""
    parties = chemin.split("/")
    for i, nom in enumerate(parties):
        prefixe = parties[:i + 1]
        if exclusions.exclut(nom, "/".join(prefixe),
                             absolu(prefixe) if absolu else os.path.join(racine, *prefixe),
                             i, i < len(parties) - 1):
            return True
    return False


def _ouvrir(racine: str, f: Fichier) -> Any:
    absolu = os.path.join(racine, *f.chemin.split("/"))
    # Un dossier remplacé par un lien depuis le scan ferait sortir de l'emplacement.
    if not contient(os.path.realpath(racine), os.path.realpath(absolu)):
        raise _Ecarte("hors de l'emplacement")
    st = os.lstat(absolu)
    if stat.S_ISLNK(st.st_mode):
        raise _Ecarte("lien symbolique")
    if not stat.S_ISREG(st.st_mode) or st.st_size != f.taille or f.mtime is None \
            or abs(st.st_mtime - f.mtime) > TOLERANCE_MTIME_S:
        raise _Change()
    drapeaux = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    return os.fdopen(os.open(absolu, drapeaux), "rb", buffering=0)


def _verifier_inchange(fichier: Any, f: Fichier) -> None:
    """Modifié PENDANT la lecture : l'empreinte ne vaut rien."""
    st = os.fstat(fichier.fileno())
    if st.st_size != f.taille or f.mtime is None or abs(st.st_mtime - f.mtime) > TOLERANCE_MTIME_S:
        raise _Change()


def empreinte_partielle(fichier: Any, taille: int) -> tuple[bytes, bytes | None, int]:
    """(partielle, complète si le fichier a été lu en entier, octets lus).

    La taille entre dans l'empreinte : deux fichiers qui ne diffèrent qu'au milieu ont la même
    partielle — c'est le rôle de la 3ᵉ passe de les départager.
    """
    tete = fichier.read(TAILLE_BLOC)
    if taille > 2 * TAILLE_BLOC:
        fichier.seek(taille - TAILLE_BLOC)
        queue = fichier.read(TAILLE_BLOC)
        complete = None
    else:  # petit fichier : il est lu en entier, l'empreinte complète est offerte
        queue = fichier.read()
        complete = hashlib.sha256(tete + queue).digest()
    return hacher_partielle(taille, tete, queue), complete, len(tete) + len(queue)


def hacher_partielle(taille: int, tete: bytes, queue: bytes) -> bytes:
    """LA formule de l'empreinte partielle, commune au disque, au SMB et à l'agent Go : changer l'une
    sans les autres rendrait les copies introuvables d'un lieu à l'autre."""
    return hashlib.sha256(taille.to_bytes(8, "big") + tete + queue).digest()


def empreinte_complete(fichier: Any) -> tuple[bytes, int]:
    h = hashlib.sha256()
    lus = 0
    while bloc := fichier.read(TAILLE_LECTURE):
        h.update(bloc)
        lus += len(bloc)
    return h.digest(), lus


def _lire(racine: str, f: Fichier, complete: bool) -> tuple[bytes | None, bytes | None, int]:
    """(partielle, complète, octets lus). Lève `_Change`, `_Ecarte` ou `OSError`."""
    with _ouvrir(racine, f) as fichier:
        if complete:
            totale, lus = empreinte_complete(fichier)
            partielle = f.partielle
        else:
            partielle, totale, lus = empreinte_partielle(fichier, f.taille)
        _verifier_inchange(fichier, f)
    return partielle, totale, lus


# --------------------------------------------------------------------------- #
# Une passe                                                                    #
# --------------------------------------------------------------------------- #
class Passe:
    """Parcourt les tailles partagées, de la plus grande à la plus petite (là où il y a le plus de
    place à gagner), et calcule les empreintes qui manquent, dans la limite donnée."""

    def __init__(self, depot: Depot, emplacements: list[Emplacement], exclusions: Exclusions, *,
                 taille_min: int, restant: int, limite_nuit: int, en_fenetre: Callable[[], bool],
                 passe_id: int, arret: Callable[[], bool] | None = None) -> None:
        self.depot = depot
        #: Racines LISIBLES d'ici : celles du serveur. Les emplacements des postes entrent dans la
        #: comparaison (`ids`) — leurs empreintes viennent de l'agent — sans être lus.
        self.racines = {e.id: e.racine for e in emplacements if e.sur_serveur}
        #: Emplacements lus par SMB : un lecteur (une session) chacun, ouvert au premier besoin.
        self.smb = {e.id: LecteurSmb(e, exclusions) for e in emplacements if e.est_smb}
        self.ids = sorted(e.id for e in emplacements)
        self.exclusions = exclusions
        self.taille_min = taille_min
        #: Octets encore permis cette nuit, au début de la passe.
        self.restant = restant
        self.limite_nuit = limite_nuit
        self.en_fenetre = en_fenetre
        self.passe_id = passe_id
        self.arret = arret
        self.resume = ResumePasse()
        self._dernier_avancement = 0

    async def executer(self) -> str:
        """Rend le statut de fin : `termine`, `limite`, `hors_fenetre` ou `interrompu`."""
        try:
            return await self._executer()
        finally:
            for lecteur in self.smb.values():
                await lecteur.fermer()

    async def _executer(self) -> str:
        sous: int | None = None
        while tailles := await self.depot.tailles_en_double(self.ids, self.taille_min, sous, LOT_TAILLES):
            for taille in tailles:
                arret = await self._traiter_taille(taille)
                if arret:
                    return arret
            sous = tailles[-1]
        return "limite" if self.resume.nb_reportes else "termine"

    async def _traiter_taille(self, taille: int) -> str | None:
        fichiers = await self.depot.fichiers_de_taille(self.ids, taille)
        for f in fichiers:  # passe 2
            if not f.partielle_valide:
                arret = await self._lire(f, complete=False)
                if arret:
                    return arret
        groupes: dict[bytes, list[Fichier]] = defaultdict(list)
        for f in fichiers:
            if f.partielle_valide and f.partielle is not None:
                groupes[f.partielle].append(f)
        for groupe in groupes.values():  # passe 3
            if len(groupe) < 2:
                continue
            for f in groupe:
                if not f.complete_valide:
                    arret = await self._lire(f, complete=True)
                    if arret:
                        return arret
        return None

    def _permis(self, cout: int) -> bool:
        reste = self.restant - self.resume.octets_lus
        if cout <= reste:
            return True
        # Un fichier plus gros que toute la limite d'une nuit ne passerait jamais : il a droit à une
        # nuit entière pour lui seul, à condition que rien n'ait encore été lu.
        return cout > self.limite_nuit and self.restant >= self.limite_nuit and self.resume.octets_lus == 0

    async def _lire(self, f: Fichier, *, complete: bool) -> str | None:
        lecteur = self.smb.get(f.emplacement_id)
        if f.emplacement_id not in self.racines and lecteur is None:  # poste : c'est l'agent qui le lit
            return None
        if self.arret is not None and self.arret():
            return "interrompu"
        if not self.en_fenetre():
            return "hors_fenetre"
        if self.restant - self.resume.octets_lus < 2 * TAILLE_BLOC:
            return "limite"
        cout = f.taille if complete else min(f.taille, 2 * TAILLE_BLOC)
        if not self._permis(cout):
            self.resume.nb_reportes += 1
            return None
        try:
            if lecteur is not None:
                if lecteur.exclu(f.chemin):
                    return None
                partielle, totale, lus = await lecteur.lire(f, complete)
            else:
                racine = self.racines[f.emplacement_id]
                if exclu(self.exclusions, racine, f.chemin):
                    return None
                boucle = asyncio.get_running_loop()
                partielle, totale, lus = await boucle.run_in_executor(_LECTEUR, _lire, racine, f, complete)
        except Injoignable:  # partage absent pour cette passe : déjà journalisé une fois
            self.resume.nb_erreurs += 1
            return None
        except _Change:
            self.resume.nb_changes += 1
            return None
        except _Ecarte:
            return None
        except OSError as exc:
            self.resume.nb_erreurs += 1
            log.warning("Copies sur disque : lecture impossible", chemin=f.chemin, erreur=type(exc).__name__)
            return None
        await self._compter(lus)
        if partielle is None:  # impossible : la passe 3 ne lit que des partielles valables
            return None
        await self.depot.enregistrer_empreinte(f.id, partielle, totale, f.taille, f.mtime)
        f.partielle, f.complete, f.emp_taille, f.emp_mtime = partielle, totale, f.taille, f.mtime
        if complete:
            self.resume.nb_completes += 1
        else:
            self.resume.nb_partielles += 1
        return None

    async def _compter(self, lus: int) -> None:
        self.resume.octets_lus += lus
        if self.resume.octets_lus - self._dernier_avancement >= PAS_AVANCEMENT:
            await self.depot.avancer_passe(self.passe_id, self.resume.octets_lus)
            self._dernier_avancement = self.resume.octets_lus


# --------------------------------------------------------------------------- #
# La passe de la nuit (ou à la demande)                                        #
# --------------------------------------------------------------------------- #
def debut_nuit(maintenant: datetime, heure_debut: int) -> datetime:
    """Début de la fenêtre en cours : la limite de lecture se compte depuis ce moment."""
    debut = maintenant.replace(hour=heure_debut, minute=0, second=0, microsecond=0)
    return debut if debut <= maintenant else debut - timedelta(days=1)


def taille_lisible(octets: int) -> str:
    valeur, unites = float(octets), ("o", "Ko", "Mo", "Go", "To")
    i = 0
    while valeur >= 1024 and i < len(unites) - 1:
        valeur /= 1024
        i += 1
    return f"{valeur:.1f} {unites[i]}".replace(".0 ", " ").replace(".", ",")


async def executer(depot: Depot, r: ReglagesInventaire, *, taille_min: int, limite_nuit: int,
                   horloge: Callable[[], datetime], a_la_demande: bool = False,
                   arret: Callable[[], bool] | None = None) -> dict[str, Any]:
    """Une passe des copies. La nuit : seulement dans la fenêtre. À la demande : à toute heure, mais
    dans la même limite de lecture (comptée depuis le début de la dernière nuit)."""
    maintenant = horloge()
    if not a_la_demande and not dans_fenetre(maintenant.hour, r.heure_debut, r.heure_fin):
        return {"statut": "ignore", "message": "hors de la fenêtre de nuit"}
    if await depot.scan_en_cours():
        return {"statut": "ignore", "message": "un scan est en cours : reporté"}
    await depot.interrompre_passes_orphelines(AGE_ORPHELINE_HEURES)
    restant = limite_nuit - await depot.octets_lus_depuis(debut_nuit(maintenant, r.heure_debut))
    if restant < 2 * TAILLE_BLOC:
        return {"statut": "ignore", "message": "limite de lecture de la nuit atteinte"}
    emplacements = await depot.emplacements(actifs_seulement=True)
    if not emplacements:
        return {"statut": "ignore", "message": "aucun emplacement"}
    try:
        passe_id = await depot.ouvrir_passe()
    except PasseEnCours:
        return {"statut": "ignore", "message": "une passe est déjà en cours"}

    def en_fenetre() -> bool:
        return a_la_demande or dans_fenetre(horloge().hour, r.heure_debut, r.heure_fin)

    passe = Passe(depot, emplacements, r.exclusions, taille_min=taille_min, restant=restant,
                  limite_nuit=limite_nuit, passe_id=passe_id, en_fenetre=en_fenetre, arret=arret)
    message = ""
    try:
        statut = await passe.executer()
    except Exception as exc:  # noqa: BLE001 — consigné dans la passe, pas avalé
        log.exception("Passe des copies en échec", passe_id=passe_id)
        statut, message = "echec", f"{type(exc).__name__} : {str(exc)[:300]}"
    s = passe.resume
    if not message and (s.nb_erreurs or s.nb_changes):
        message = f"{s.nb_erreurs} fichier(s) illisible(s), {s.nb_changes} modifié(s) depuis le scan"
    try:
        await depot.fermer_passe(passe_id, statut, s, message)
    except Exception:  # noqa: BLE001 — la base est tombée : la passe restera orpheline, nettoyée plus tard
        log.exception("Impossible de clore la passe des copies", passe_id=passe_id)
    log.info("Passe des copies close", passe_id=passe_id, statut=statut, lus=taille_lisible(s.octets_lus),
             partielles=s.nb_partielles, completes=s.nb_completes, message=message)
    return {"statut": statut, "passe_id": passe_id, "octets_lus": s.octets_lus,
            "partielles": s.nb_partielles, "completes": s.nb_completes, "message": message}
