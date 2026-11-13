"""
Import d'un export CSV de WizTree — pour un disque Windows sans agent.

Porté de rangement (`app/inventaire/wiztree.py`). Ce qui change : l'import est une **tâche du
worker** (`inventaire_import`, classe « fond »), car l'export est un fichier déposé sur le NAS, que
seul le worker voit. La lecture du fichier reste synchrone (module `csv`) et part dans un fil ; les
paquets lus sont versés dans l'envoi par la boucle du worker.

Format relevé sur WizTree 4.33 (export réel, 2026-10-14) :

    \\ufeffGénéré par WizTree 4.33 14/10/2026 23:26:01 (…)          ← ligne d'information, traduite
    Nom de fichier,Taille,Alloué,Modifié le,Attributs,Fichiers,Dossiers,…   ← en-tête, traduit
    "C:\\\\Dossier\\\\",154212,159744,2026/10/14 23:26:00,0,3,4,…         ← la racine, en premier
    "C:\\\\Dossier\\\\Docs\\\\facture, EDF.pdf",4200,8192,2026/10/14 23:26:00,32,0,0

- colonnes lues **par position** (l'en-tête change avec la langue) : chemin complet, taille,
  alloué, date de modification (heure locale, à la seconde), attributs ;
- un dossier se termine par `\\` ; une jonction (attribut 0x400 sur un dossier) est ignorée ;
- l'ordre est un parcours en profondeur : les enfants d'un dossier ne sont PAS contigus. Les
  listes sont donc accumulées puis versées par paquets dans un envoi, que la base rassemble.

**Prudence.** Une ligne illisible, hors de la racine ou à la date inconnue fait **refuser tout
l'import** : sinon, les fichiers de cette ligne passeraient pour disparus. Un nom invalide (« .. »,
« / »…) est seulement écarté, et compté comme illisible (rien n'en disparaît).
"""

import asyncio
import csv
import io
import ntpath
import os
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, tzinfo

from logger import get_logger
from services.rangement import agent, service
from services.rangement.depot import (
    Compteurs,
    Depot,
    DossierEnvoye,
    Element,
    Emplacement,
    EnvoiEnCours,
    ScanEnCours,
)
from services.rangement.erreurs import InventaireRefus
from services.rangement.scan import contient, nom_valide

log = get_logger(__name__)

ATTRIBUT_REPARSE = 0x400
#: Éléments accumulés avant d'être versés dans l'envoi : la mémoire reste bornée.
PAQUET = 20_000
TAILLE_FICHIER_MAX = 4 * 1024 ** 3
FORMATS_DATE = ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M",
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d.%m.%Y %H:%M:%S")
_CHEMIN_WINDOWS = re.compile(r"^[A-Za-z]:\\")


class ImportRefuse(Exception):
    """Export inutilisable : rien n'a été modifié dans l'inventaire."""


@dataclass
class Bilan:
    lignes: int = 0
    dossiers: int = 0
    fichiers: int = 0
    noms_ecartes: int = 0
    jonctions: int = 0
    racine: str = ""
    erreurs: list[str] = field(default_factory=list)


def date_en_secondes(texte: str, fuseau: tzinfo) -> float:
    for fmt in FORMATS_DATE:
        try:
            return datetime.strptime(texte.strip(), fmt).replace(tzinfo=fuseau).timestamp()
        except ValueError:
            continue
    raise ImportRefuse(f"date au format inconnu : « {texte[:40]} »")


def _lignes(flux: io.TextIOBase) -> Iterator[tuple[int, list[str]]]:
    """Les lignes de données, à partir de la racine (les lignes d'information et d'en-tête,
    traduites, sont sautées tant qu'aucun chemin Windows n'apparaît)."""
    vu_racine = False
    for numero, ligne in enumerate(csv.reader(flux), start=1):
        if not ligne:
            continue
        if not vu_racine:
            if not _CHEMIN_WINDOWS.match(ligne[0]):
                if numero > 5:
                    raise ImportRefuse("aucun chemin Windows dans les premières lignes : "
                                       "est-ce un export WizTree ?")
                continue
            vu_racine = True
        yield numero, ligne


def racine_du_fichier(chemin: str) -> str:
    """La racine de l'export (première ligne de données), normalisée comme une racine de poste."""
    with open(chemin, encoding="utf-8-sig", newline="") as f:
        for _, ligne in _lignes(f):
            if not ligne[0].endswith("\\"):
                raise ImportRefuse("la première ligne de l'export doit être un dossier")
            try:
                return agent.racine_windows(ligne[0] if len(ligne[0]) <= 3 else ligne[0].rstrip("\\"))
            except InventaireRefus as exc:
                raise ImportRefuse(exc.message) from None
    raise ImportRefuse("export vide")


def lire(chemin: str, racine: str, fuseau: tzinfo, verser: Callable[[list[DossierEnvoye]], object]) -> Bilan:
    """Lit l'export et verse ses listes de dossiers (`verser(list[DossierEnvoye])`). Synchrone."""
    bilan = Bilan(racine=racine)
    prefixe = ntpath.normcase(racine.rstrip("\\") + "\\")
    paquet: dict[str, list[Element]] = {"": []}
    ecartes: dict[str, list[str]] = {}
    n = 0

    def vider() -> None:
        nonlocal paquet, ecartes, n
        verser([DossierEnvoye(p, False, tuple(els), tuple(ecartes.get(p, ()))) for p, els in paquet.items()]
               + [DossierEnvoye(p, False, (), tuple(noms)) for p, noms in ecartes.items() if p not in paquet])
        paquet, ecartes, n = {}, {}, 0

    with open(chemin, encoding="utf-8-sig", newline="") as f:
        premiere = True
        for numero, ligne in _lignes(f):
            bilan.lignes += 1
            if premiere:  # la racine elle-même
                premiere = False
                continue
            if len(ligne) < 5:
                raise ImportRefuse(f"ligne {numero} : colonnes manquantes")
            complet = ligne[0]
            if not ntpath.normcase(complet).startswith(prefixe):
                raise ImportRefuse(f"ligne {numero} : hors de la racine {racine}")
            try:
                taille, attributs = int(ligne[1]), int(ligne[4] or 0)
            except ValueError:
                raise ImportRefuse(f"ligne {numero} : taille ou attributs illisibles") from None
            if taille < 0 or taille > agent.TAILLE_MAX:
                raise ImportRefuse(f"ligne {numero} : taille impossible")
            est_dossier = complet.endswith("\\")
            relatif = complet[len(prefixe):].rstrip("\\")
            if not relatif:
                continue
            parent_w, _, nom = relatif.rpartition("\\")
            parent = parent_w.replace("\\", "/")
            if est_dossier and attributs & ATTRIBUT_REPARSE:
                bilan.jonctions += 1  # jonction : jamais suivie (son contenu n'est pas listé)
                continue
            if not nom_valide(nom) or not agent.chemin_valide(parent):
                bilan.noms_ecartes += 1
                ecartes.setdefault(parent, []).append(nom[:200])
                continue
            mtime = date_en_secondes(ligne[3], fuseau)
            element = Element(nom, est_dossier, 0 if est_dossier else taille, mtime)
            paquet.setdefault(parent, []).append(element)
            if est_dossier:
                bilan.dossiers += 1
                paquet.setdefault(relatif.replace("\\", "/"), [])  # un dossier vide reste « listé »
            else:
                bilan.fichiers += 1
            n += 1
            if n >= PAQUET:
                vider()
        if premiere:
            raise ImportRefuse("export vide")
    vider()
    return bilan


# --------------------------------------------------------------------------- #
# Service : de la demande à l'inventaire (dans le worker)                      #
# --------------------------------------------------------------------------- #
def valider_fichier(chemin: str, autorisee: str) -> str:
    """Chemin réel du CSV s'il est sous la racine autorisée, existe et a une taille raisonnable.

    Recontrôle **sur le disque** (le texte l'a déjà été par l'API) : un lien ne fait pas sortir du
    périmètre.
    """
    chemin = (chemin or "").strip()
    if not chemin.lower().endswith(".csv"):
        raise InventaireRefus("Le fichier doit être un export CSV de WizTree (.csv).", code="import_pas_csv")
    if not os.path.isabs(chemin) or not autorisee or not os.path.isabs(autorisee):
        raise InventaireRefus("Indiquez le chemin complet du fichier (ex. /mnt/media/…/export.csv).",
                              code="import_chemin_relatif")
    reel = os.path.realpath(chemin)
    if not contient(os.path.realpath(autorisee), reel):
        raise InventaireRefus(f"Le fichier doit se trouver sous {autorisee}.", code="import_hors_perimetre")
    if not os.path.isfile(reel):
        raise InventaireRefus(f"Fichier introuvable : {chemin}", code="import_introuvable")
    try:
        taille = os.path.getsize(reel)
    except OSError:
        raise InventaireRefus(f"Fichier illisible : {chemin}", code="import_illisible") from None
    if taille > TAILLE_FICHIER_MAX:
        raise InventaireRefus("Fichier trop volumineux (4 Go au plus).", code="import_trop_gros")
    return reel


def _racine_lisible(reel: str) -> str:
    try:
        return racine_du_fichier(reel)
    except (ImportRefuse, UnicodeDecodeError, csv.Error, OSError) as exc:
        raise InventaireRefus(f"Export illisible : {exc}", code="import_illisible") from None


async def preparer(depot: Depot, nom_pc: str, libelle: str, chemin: str,
                   autorisee: str) -> tuple[Emplacement, str]:
    """Valide la demande, trouve (ou crée) le poste et l'emplacement d'import. Rend (emp, csv)."""
    reel = await asyncio.to_thread(valider_fichier, chemin, autorisee)
    racine = await asyncio.to_thread(_racine_lisible, reel)
    nom_pc = agent.nom_poste_valide(nom_pc)
    # Toutes les validations qui peuvent échouer ont eu lieu AVANT de créer un poste : pour un PC
    # nouveau (aucun emplacement), la déclaration qui suit ne peut ni chevaucher ni doubler — aucun
    # poste vide ne reste donc après une demande refusée.
    poste = next((p for p in await depot.postes() if p.nom.casefold() == nom_pc.casefold()), None)
    if poste is None:
        # Un PC sans agent : poste créé sans jeton (il en recevra un si l'agent arrive, étape 5).
        poste = await agent.creer_poste_sans_jeton(depot, nom_pc)
    existant = next((e for e in await depot.emplacements() if e.poste_id == poste.id and e.source == "import"
                     and ntpath.normcase(e.racine) == ntpath.normcase(racine)), None)
    if existant:
        return existant, reel
    libelle = (libelle or "").strip() or f"{poste.nom} — {racine}"
    emp = await agent.declarer_emplacement(depot, poste.id, libelle, racine, source="import")
    return emp, reel


async def ouvrir(depot: Depot, emp: Emplacement) -> tuple[int, int]:
    """Ouvre l'envoi et le scan de l'import. Rend (envoi_id, scan_id) ; refus si l'un tourne déjà."""
    try:
        envoi_id = await depot.ouvrir_envoi(emp.id)
    except EnvoiEnCours as exc:
        raise InventaireRefus("Un import de cet emplacement est déjà en cours.",
                              code="import_en_cours", statut=409) from exc
    try:
        scan_id = await depot.ouvrir_scan(emp.id, "import")
    except ScanEnCours as exc:
        await depot.clore_envoi(envoi_id, "abandonne")
        raise InventaireRefus("Un scan de cet emplacement est déjà en cours.",
                              code="import_en_cours", statut=409) from exc
    await depot.clore_envoi(envoi_id, "traitement")
    return envoi_id, scan_id


async def executer(depot: Depot, emp: Emplacement, envoi_id: int, scan_id: int, chemin_csv: str) -> str:
    """Lit l'export, puis le scan de l'envoi. Un export refusé : scan en échec, rien de changé."""
    fuseau = service.maintenant_local().tzinfo
    boucle = asyncio.get_running_loop()

    def verser(dossiers: list[DossierEnvoye]) -> None:
        # Appelé depuis le fil de lecture : l'écriture en base se fait dans la boucle du worker, et
        # le fil attend qu'elle soit faite (la mémoire reste bornée à un paquet).
        asyncio.run_coroutine_threadsafe(depot.ajouter_dossiers_envoi(envoi_id, dossiers), boucle).result()

    try:
        bilan = await asyncio.to_thread(lire, chemin_csv, emp.racine, fuseau, verser)
    except (ImportRefuse, UnicodeDecodeError, csv.Error, OSError) as exc:
        await depot.clore_envoi(envoi_id, "abandonne")
        await depot.fermer_scan(scan_id, "echec", Compteurs(), f"export refusé, rien n'a changé : {exc}"[:300])
        log.warning("Import WizTree refusé", emplacement=emp.libelle, erreur=str(exc))
        return "echec"
    log.info("Import WizTree lu", emplacement=emp.libelle, lignes=bilan.lignes, dossiers=bilan.dossiers,
             fichiers=bilan.fichiers, noms_ecartes=bilan.noms_ecartes, jonctions=bilan.jonctions)
    return await agent.traiter_envoi(depot, emp, envoi_id, scan_id, "import")


async def importer(depot: Depot, nom_pc: str, libelle: str, chemin: str, autorisee: str) -> dict:
    """Tout l'import, de la demande à l'inventaire. Rend un résumé pour le résultat de la tâche."""
    emp, reel = await preparer(depot, nom_pc, libelle, chemin, autorisee)
    envoi_id, scan_id = await ouvrir(depot, emp)
    try:
        statut = await executer(depot, emp, envoi_id, scan_id, reel)
    except Exception as exc:
        await depot.clore_envoi(envoi_id, "abandonne")
        await service.clore_en_echec(depot, scan_id, f"import interrompu : {type(exc).__name__}")
        raise
    return {"emplacement_id": emp.id, "scan_id": scan_id, "statut": statut}
