"""
Agent de poste : ce que le serveur fait pour les PC qui portent l'agent Go (`agent/`).

Porté de rangement (`app/inventaire/agent.py`), étapes 4 et 5 du plan rangement + mails.

L'agent ne décide de rien : à chaque contact, il demande sa **configuration** (quels dossiers
inventorier, s'ils sont dus), envoie les **listes de dossiers** par lots, puis demande quelles
**empreintes** calculer. Tout ce qu'il envoie est revalidé ici, comme une donnée venue de l'extérieur.

- **Un jeton par poste**, de portée `agent`, dans `jetons_api` (décision d'architecture n° 2) : la
  base n'en garde que l'empreinte, il n'est montré qu'une fois. Il n'atteint que `/api/agent/*`.
- **Les racines sont déclarées ici**, par un administrateur ; l'agent refuse en plus celles qui
  sortent de sa propre liste blanche locale.
- **Les listes reçues passent par le même scan** que le NAS (`SourceEnvoi`), dans une tâche du
  worker (classe « fond ») : comparaison, prudence, totaux et instantané sont identiques.
- **Les empreintes** suivent la règle des copies multiples (taille partagée → partielle →
  complète), dans une **limite de lecture par jour** propre à chaque poste.
"""

import json
import math
import ntpath
import re
import zlib
from datetime import date, datetime, timedelta
from typing import Any

from services.rangement import reglages
from services.rangement.depot import (
    Depot,
    DossierEnvoye,
    Element,
    Emplacement,
    EnvoiEnCours,
    Fichier,
    Poste,
    ScanEnCours,
)
from services.rangement.erreurs import InventaireRefus
from services.rangement.exclusions import NOMS_VERROUILLES
from services.rangement.scan import TOLERANCE_MTIME_S, Scanner, SourceEnvoi, nom_valide

VERSION_PROTOCOLE = 1
#: Bornes d'un lot : au-delà, l'agent est fautif (ou malveillant) — refus net.
LOT_MAX_DOSSIERS = 2000
LOT_MAX_ENFANTS = 200_000
#: Taille d'un lot REÇU (compressé ou non), lue en flux : au-delà, refus sans tout charger.
TAILLE_LOT_RECU_MAX = 10 * 1024 * 1024
TAILLE_DECOMPRESSEE_MAX = 64 * 1024 * 1024
#: Demandes d'empreintes rendues à un contact.
DEMANDES_MAX = 200
#: Un envoi resté ouvert plus longtemps est abandonné (l'agent recommencera).
AGE_ENVOI_ABANDONNE_HEURES = 6
#: Bloc lu en tête et en queue pour l'empreinte partielle (même valeur que l'agent Go).
TAILLE_BLOC = 64 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class AgentRefuse(Exception):
    """Demande de l'agent refusée : code HTTP et message."""

    def __init__(self, statut: int, message: str) -> None:
        super().__init__(message)
        self.statut = statut
        self.message = message

#: Bornes des nombres reçus : une taille tient dans un `bigint`.
TAILLE_MAX = 2**63 - 1


def nom_poste_valide(nom: str) -> str:
    nom = (nom or "").strip()[:60]
    if not re.fullmatch(r"[\w .\-]{1,60}", nom):
        raise InventaireRefus("Nom de poste invalide (lettres, chiffres, espace, point, tiret).",
                              code="poste_nom_invalide")
    return nom


async def creer_poste_sans_jeton(depot: Depot, nom: str) -> Poste:
    """Un PC sans agent (import WizTree) : aucun jeton, aucun contact."""
    return await depot.creer_poste(nom_poste_valide(nom), None)


def racine_windows(racine: str) -> str:
    """Une racine de poste : chemin ABSOLU sur un lecteur local (`C:\\…`), normalisé.

    Pas de chemin réseau (`\\\\serveur\\partage`) : le NAS s'inventorie depuis le serveur.
    """
    racine = (racine or "").strip()
    if not re.match(r"^[A-Za-z]:[\\/]", racine):
        raise InventaireRefus("Le dossier doit être un chemin Windows complet sur un disque local, "
                              "par exemple C:\\Users\\Thomas.", code="racine_poste_invalide")
    if ".." in re.split(r"[\\/]", racine):
        raise InventaireRefus("Le chemin ne doit pas contenir « .. ».", code="racine_poste_invalide")
    return ntpath.normpath(racine)


def _sous(parent: str, enfant: str) -> bool:
    p, e = ntpath.normcase(parent).rstrip("\\"), ntpath.normcase(enfant).rstrip("\\")
    return e == p or e.startswith(p + "\\")


async def declarer_emplacement(depot: Depot, poste_id: int, libelle: str, racine: str,
                               source: str = "agent") -> Emplacement:
    """Un dossier d'un PC : inventorié par son agent (`agent`) ou par un export WizTree (`import`)."""
    if await depot.poste(poste_id) is None:
        raise LookupError(poste_id)
    libelle = (libelle or "").strip()[:100]
    if not libelle:
        raise InventaireRefus("Le libellé est obligatoire.", code="libelle_vide")
    racine = racine_windows(racine)
    for emp in await depot.emplacements():
        if emp.poste_id == poste_id and (_sous(emp.racine, racine) or _sous(racine, emp.racine)):
            raise InventaireRefus(f"Chevauche l'emplacement « {emp.libelle} » ({emp.racine}) de ce poste.",
                                  code="emplacements_imbriques")
    return await depot.creer_emplacement(libelle, racine, source=source, poste_id=poste_id)


def chemin_valide(chemin: Any) -> bool:
    """Chemin relatif « a/b/c » (ou "" pour la racine) dont chaque segment est un nom sûr."""
    if not isinstance(chemin, str) or len(chemin) > 4096:
        return False
    return chemin == "" or all(nom_valide(n) for n in chemin.split("/"))


async def traiter_envoi(depot: Depot, emp: Emplacement, envoi_id: int, scan_id: int, declencheur: str) -> str:
    """Le scan d'un envoi, sur le dépôt donné. Rend le statut du scan. L'envoi est effacé."""
    r = reglages.lire()
    try:
        resultat = await Scanner(depot, emp, r.exclusions, profondeur_instantane=r.profondeur_instantane,
                                 declencheur=declencheur,
                                 source=SourceEnvoi(depot, envoi_id, r.exclusions)).executer(scan_id)
        await depot.purger_instantanes(emp.id, r.instantanes_gardes)
        return resultat.statut
    finally:
        await depot.clore_envoi(envoi_id, "traite")


# --------------------------------------------------------------------------- #
# Identification du poste (le jeton lui-même est vérifié par jetons_api)       #
# --------------------------------------------------------------------------- #
async def poste_du_jeton(depot: Depot, jeton_id: Any, version: str = "") -> Poste:
    """Le poste lié à ce jeton de portée `agent`. Note le contact et la version au passage."""
    poste = await depot.poste_par_jeton(jeton_id)
    if poste is None:
        raise AgentRefuse(403, "Ce jeton n'est lié à aucun poste.")
    if not poste.actif:
        raise AgentRefuse(403, "Ce poste est désactivé.")
    await depot.contact_poste(poste.id, re.sub(r"[^\w.\-+]", "", version or "")[:40])
    return poste


def _emplacements_du_poste(emps: list[Emplacement], poste: Poste) -> list[Emplacement]:
    return [e for e in emps if e.source == "agent" and e.poste_id == poste.id and e.actif]


# --------------------------------------------------------------------------- #
# Configuration envoyée au poste                                               #
# --------------------------------------------------------------------------- #
async def configuration(depot: Depot, poste: Poste, maintenant: datetime) -> dict[str, Any]:
    r = reglages.lire()
    ra = reglages.lire_agent()
    racines = []
    for emp in _emplacements_du_poste(await depot.emplacements(actifs_seulement=True), poste):
        dernier = await depot.dernier_scan(emp.id, termine_seulement=True)
        du = not dernier or not dernier.get("fin") or \
            maintenant - dernier["fin"] >= timedelta(hours=r.delai_min_heures)
        racines.append({"emplacement_id": emp.id, "racine": emp.racine, "inventaire_du": bool(du)})
    return {
        "version_protocole": VERSION_PROTOCOLE,
        "intervalle_min": ra.intervalle_min,
        "lot_max_dossiers": LOT_MAX_DOSSIERS,
        "racines": racines,
        # Élagage côté poste (économise le réseau) ; le serveur refiltre de toute façon. L'agent ne
        # doit JAMAIS élaguer plus que le serveur, sinon des fichiers passeraient pour disparus.
        "exclusions_noms": sorted(NOMS_VERROUILLES),
        "exclusions_motifs": list(r.exclusions.motifs),
    }


# --------------------------------------------------------------------------- #
# Envois                                                                       #
# --------------------------------------------------------------------------- #
def _entier(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


async def _emplacement_du_poste(depot: Depot, poste: Poste, emplacement_id: Any) -> Emplacement:
    emp = await depot.emplacement(emplacement_id) if _entier(emplacement_id) else None
    if emp is None or emp.source != "agent" or emp.poste_id != poste.id or not emp.actif:
        raise AgentRefuse(404, "Emplacement inconnu pour ce poste.")
    return emp


async def _envoi_du_poste(depot: Depot, poste: Poste, envoi_id: int, statut: str) -> dict[str, Any]:
    envoi = await depot.envoi(envoi_id)
    if envoi is None:
        raise AgentRefuse(404, "Envoi inconnu.")
    await _emplacement_du_poste(depot, poste, envoi["emplacement_id"])
    if envoi["statut"] != statut:
        raise AgentRefuse(409, f"Envoi dans l'état « {envoi['statut']} ».")
    return envoi


async def ouvrir_envoi(depot: Depot, poste: Poste, emplacement_id: Any) -> int:
    emp = await _emplacement_du_poste(depot, poste, emplacement_id)
    await depot.abandonner_envois(AGE_ENVOI_ABANDONNE_HEURES)
    try:
        return await depot.ouvrir_envoi(emp.id)
    except EnvoiEnCours as exc:
        raise AgentRefuse(409, "Le précédent envoi de ce dossier est encore en traitement.") from exc


def decompresser(corps: bytes, encodage: str) -> bytes:
    """Corps d'un lot, décompressé SANS dépasser `TAILLE_DECOMPRESSEE_MAX` (bombe gzip)."""
    if encodage.strip().lower() != "gzip":
        if len(corps) > TAILLE_DECOMPRESSEE_MAX:
            raise AgentRefuse(413, "Lot trop gros.")
        return corps
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        sortie = d.decompress(corps, TAILLE_DECOMPRESSEE_MAX + 1)
    except zlib.error as exc:
        raise AgentRefuse(422, "Lot compressé illisible.") from exc
    if len(sortie) > TAILLE_DECOMPRESSEE_MAX or d.unconsumed_tail:
        raise AgentRefuse(413, "Lot trop gros une fois décompressé.")
    return sortie


#: Une date reste une date (±3 000 ans autour de 1970). NaN et l'infini sont refusés —
#: PostgreSQL les garderait.
DATE_MAX_S = 1e11


def _taille_valide(v: Any) -> bool:
    return _entier(v) and 0 <= v <= TAILLE_MAX


def _date_valide(v: Any) -> bool:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(float(v)) and abs(float(v)) <= DATE_MAX_S
    except OverflowError:  # entier JSON gigantesque
        return False


def lire_lot(donnees: bytes) -> list[DossierEnvoye]:
    """Le lot JSON, validé élément par élément. Une structure fausse : refus du lot entier."""
    try:
        lot = json.loads(donnees)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AgentRefuse(422, "Lot : JSON invalide.") from exc
    dossiers = lot.get("dossiers") if isinstance(lot, dict) else None
    if not isinstance(dossiers, list) or len(dossiers) > LOT_MAX_DOSSIERS:
        raise AgentRefuse(422, f"Lot : « dossiers » doit être une liste d'au plus {LOT_MAX_DOSSIERS} éléments.")
    sortie: list[DossierEnvoye] = []
    total = 0
    for d in dossiers:
        if not isinstance(d, dict) or not chemin_valide(d.get("chemin")):
            raise AgentRefuse(422, "Lot : dossier sans chemin valable.")
        enfants_bruts = d.get("enfants", [])
        illisibles = d.get("illisibles", [])
        if not isinstance(enfants_bruts, list) or not isinstance(illisibles, list) \
                or not all(isinstance(n, str) for n in illisibles):
            raise AgentRefuse(422, "Lot : enfants ou illisibles mal formés.")
        total += len(enfants_bruts) + len(illisibles)
        if total > LOT_MAX_ENFANTS:
            raise AgentRefuse(413, "Lot : trop d'éléments.")
        enfants = []
        for e in enfants_bruts:
            if not (isinstance(e, list) and len(e) == 4 and isinstance(e[0], str) and isinstance(e[1], bool)
                    and _taille_valide(e[2]) and _date_valide(e[3])):
                raise AgentRefuse(422, "Lot : élément mal formé (attendu [nom, dossier, taille, date]).")
            enfants.append(Element(e[0], e[1], 0 if e[1] else e[2], float(e[3])))
        sortie.append(DossierEnvoye(d["chemin"], d.get("illisible") is True, tuple(enfants), tuple(illisibles)))
    return sortie


async def recevoir_lot(depot: Depot, poste: Poste, envoi_id: int, corps: bytes, encodage: str) -> int:
    await _envoi_du_poste(depot, poste, envoi_id, "reception")
    dossiers = lire_lot(decompresser(corps, encodage))
    await depot.ajouter_dossiers_envoi(envoi_id, dossiers)
    return len(dossiers)


async def terminer_envoi(depot: Depot, poste: Poste, envoi_id: int) -> tuple[Emplacement, int]:
    """Ouvre le scan de l'envoi et le passe « en traitement ». Rend (emplacement, scan_id) ; c'est
    à l'appelant d'enfiler la tâche du worker qui le traitera (`inventaire_envoi`)."""
    envoi = await _envoi_du_poste(depot, poste, envoi_id, "reception")
    emp = await _emplacement_du_poste(depot, poste, envoi["emplacement_id"])
    try:
        scan_id = await depot.ouvrir_scan(emp.id, "agent")
    except ScanEnCours as exc:
        await depot.clore_envoi(envoi_id, "abandonne")
        raise AgentRefuse(409, "Un scan de cet emplacement est déjà en cours.") from exc
    await depot.clore_envoi(envoi_id, "traitement")
    return emp, scan_id


# --------------------------------------------------------------------------- #
# Empreintes                                                                   #
# --------------------------------------------------------------------------- #
async def demandes(depot: Depot, poste: Poste, jour: date) -> dict[str, Any]:
    """Ce que le poste doit lire maintenant, dans sa limite du jour."""
    ra = reglages.lire_agent()
    limite = ra.lecture_max_jour
    restant = limite - (poste.lecture_octets if poste.lecture_jour == jour else 0)
    tous = await depot.emplacements(actifs_seulement=True)
    actifs = [e.id for e in tous]
    sortie: list[dict[str, Any]] = []
    budget = restant
    for emp in _emplacements_du_poste(tous, poste):
        for f, nature in await depot.empreintes_a_calculer(emp.id, actifs, ra.taille_min_copies, DEMANDES_MAX):
            if len(sortie) >= DEMANDES_MAX:
                break
            cout = f.taille if nature == "complete" else min(f.taille, 2 * TAILLE_BLOC)
            # Un fichier plus gros que toute la limite d'un jour a droit à un jour pour lui seul.
            seul = cout > limite and restant >= limite and not sortie
            if cout > budget and not seul:
                continue
            budget -= cout
            sortie.append({"id": f.id, "emplacement_id": f.emplacement_id, "chemin": f.chemin,
                           "taille": f.taille, "mtime": f.mtime, "nature": nature})
    return {"demandes": sortie, "octets_permis": max(0, restant)}


def _concorde(f: Fichier, r: dict[str, Any]) -> bool:
    taille, mtime = r.get("taille"), r.get("mtime")
    return (_entier(taille) and taille == f.taille and _date_valide(mtime) and f.mtime is not None
            and abs(float(mtime) - f.mtime) <= TOLERANCE_MTIME_S)


async def recevoir_empreintes(depot: Depot, poste: Poste, corps: Any, jour: date) -> int:
    """Enregistre les empreintes calculées par le poste. Rend le nombre retenu.

    Un résultat n'est retenu que pour un fichier de CE poste, à la taille et à la date que
    l'inventaire connaît : sinon le fichier a changé depuis, et l'empreinte ne vaut rien.
    """
    resultats = corps.get("resultats") if isinstance(corps, dict) else None
    if not isinstance(resultats, list) or len(resultats) > DEMANDES_MAX:
        raise AgentRefuse(422, f"« resultats » doit être une liste d'au plus {DEMANDES_MAX} éléments.")
    miens = {e.id for e in _emplacements_du_poste(await depot.emplacements(actifs_seulement=True), poste)}
    retenus = 0
    lus = 0
    for r in resultats:
        if not isinstance(r, dict):
            raise AgentRefuse(422, "Résultat mal formé.")
        octets = r.get("octets_lus", 0)
        if _entier(octets) and 0 < octets <= 1 << 50:
            lus += octets
        f = await depot.fichier(r["id"]) if _entier(r.get("id")) else None
        if f is None or f.emplacement_id not in miens or not _concorde(f, r):
            continue
        partielle, complete = r.get("partielle"), r.get("complete")
        if not isinstance(partielle, str) or not _HEX64.match(partielle):
            continue
        if complete is not None and (not isinstance(complete, str) or not _HEX64.match(complete)):
            continue
        await depot.enregistrer_empreinte(f.id, bytes.fromhex(partielle),
                                          bytes.fromhex(complete) if complete else None, f.taille, f.mtime)
        retenus += 1
    if lus:
        await depot.compter_lecture_poste(poste.id, jour, lus)
    return retenus


def corps_json(donnees: bytes) -> Any:
    try:
        return json.loads(donnees)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AgentRefuse(422, "JSON invalide.") from exc
