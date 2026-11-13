"""
Service de l'inventaire : ce qui relie l'API, le worker et le dépôt.

Porté de rangement (`app/inventaire/service.py`). Deux écarts de fond avec l'original :

- **Pas de fil d'arrière-plan** : un scan est une tâche du worker durable (`job_worker`, classe
  « fond »), jamais un fil de l'API — l'état vit en base, et l'API tourne sur plusieurs process.
- **L'API ne voit pas le NAS** : le montage n'existe que dans le worker (décision d'architecture
  n° 5). L'API contrôle donc la racine **sur le texte** (chemin absolu, normalisé, sous la racine
  autorisée, sans « .. ») ; le worker la recontrôle sur le disque au moment de la lire
  (`SourceDisque.verifier` : existence, lien symbolique, chemin réel dans le périmètre).

`fabrique` est un point de substitution : les tests y branchent le dépôt en mémoire.
"""

import os
import posixpath
from collections.abc import Callable
from datetime import datetime

from logger import get_logger
from services.rangement.depot import Compteurs, Depot, DoublonRacine
from services.rangement.erreurs import InventaireRefus
from services.rangement.scan import contient

log = get_logger(__name__)

#: Types de tâche du worker (classe « fond », cf. `job_worker.FOND_TYPES`).
JOB_SCAN = "inventaire_scan"
JOB_NUIT = "inventaire_nuit"
JOB_IMPORT = "inventaire_import"
TYPES_JOB = (JOB_SCAN, JOB_NUIT, JOB_IMPORT)


def _fabrique_postgres() -> Depot | None:
    """Le dépôt PostgreSQL sur le moteur commun ; `None` sous SQLite (pas de tables `inv_*`)."""
    from database import engine
    if not engine.dialect.name.startswith("postgres"):
        return None
    from services.rangement.depot_postgres import DepotPostgres
    return DepotPostgres(engine)


#: Ouvre un dépôt, ou rend `None` si l'inventaire n'a pas de base.
fabrique: Callable[[], Depot | None] = _fabrique_postgres


def racine_normalisee(racine: str, autorisee: str) -> str:
    """Contrôle d'une racine **sur le texte** (côté API, qui ne voit pas le NAS).

    - chemins ABSOLUS exigés, au format du conteneur (« / ») ;
    - aucun segment « .. » : pas de sortie de la racine autorisée par le texte ;
    - le chemin normalisé doit se trouver sous la racine autorisée.
    Le chemin réel (liens) est vérifié par le worker au moment du scan.
    """
    racine = (racine or "").strip()
    autorisee = (autorisee or "").strip()
    if not autorisee.startswith("/"):
        raise InventaireRefus("La racine autorisée (réglage inventaire_racine_autorisee) doit être un "
                              "chemin absolu.", code="racine_autorisee_invalide")
    if not racine.startswith("/"):
        raise InventaireRefus("Le chemin d'un emplacement doit être absolu (ex. /mnt/media/Photos).",
                              code="racine_relative")
    if ".." in racine.split("/") or "\x00" in racine or "\\" in racine:
        raise InventaireRefus("Le chemin ne doit contenir ni « .. » ni « \\ ».", code="racine_invalide")
    normal = posixpath.normpath(racine)
    base = posixpath.normpath(autorisee)
    if not (normal == base or normal.startswith(base.rstrip("/") + "/")):
        raise InventaireRefus(f"Ce dossier n'est pas sous la racine autorisée ({autorisee}).",
                              code="racine_hors_perimetre")
    return normal


async def verifier_chevauchement(depot: Depot, racine: str) -> None:
    """Refuse un emplacement contenu dans un autre, ou qui en contient un : ses fichiers seraient
    inventoriés deux fois. Même racine : `DoublonRacine` (409)."""
    for emp in await depot.emplacements():
        if not emp.sur_serveur:
            continue
        if emp.racine == racine:
            raise DoublonRacine(racine)
        if contient(emp.racine, racine) or contient(racine, emp.racine):
            raise InventaireRefus(f"Chevauche l'emplacement « {emp.libelle} » ({emp.racine}).",
                                  code="emplacements_imbriques")


async def ouvrir_scan_manuel(depot: Depot, emplacement_id: int) -> int:
    """Ouvre le scan (ce qui refuse un doublon tout de suite, 409). Le worker le fera tourner.

    Lève `LookupError` (emplacement inconnu), `ScanEnCours` ou `InventaireRefus`.
    """
    emp = await depot.emplacement(emplacement_id)
    if emp is None:
        raise LookupError(emplacement_id)
    if not emp.sur_serveur:
        raise InventaireRefus("Cet emplacement est inventorié par son poste (ou par un import), pas par "
                              "le serveur.", code="scan_hors_serveur")
    if not emp.actif:
        raise InventaireRefus("Cet emplacement est désactivé.", code="emplacement_inactif")
    return await depot.ouvrir_scan(emp.id, "manuel")


async def clore_en_echec(depot: Depot, scan_id: int, message: str) -> None:
    """Dernier recours : un scan ouvert ne doit jamais rester « en cours » (il bloquerait
    l'emplacement). Rien ne remonte : on est déjà dans l'échec."""
    try:
        await depot.fermer_scan(scan_id, "echec", Compteurs(), message[:300])
    except Exception:
        log.exception("Impossible de clore le scan", scan_id=scan_id)


def maintenant_local() -> datetime:
    """Heure du foyer : la fenêtre de nuit se lit en heure locale, pas en UTC du conteneur."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(os.environ.get("TZ") or "Europe/Paris"))
    except Exception:
        return datetime.now().astimezone()


def chemin_fichier_import(chemin: str, autorisee: str) -> str:
    """Contrôle **sur le texte** du chemin d'un export WizTree (l'API ne voit pas le NAS)."""
    chemin = (chemin or "").strip()
    if not chemin.lower().endswith(".csv"):
        raise InventaireRefus("Le fichier doit être un export CSV de WizTree (.csv).", code="import_pas_csv")
    try:
        return racine_normalisee(chemin, autorisee)
    except InventaireRefus as exc:
        raise InventaireRefus(f"Fichier refusé : {exc.message}", code="import_hors_perimetre") from None
