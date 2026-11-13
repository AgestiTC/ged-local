"""
Postes et envois de l'inventaire — ce dont l'import WizTree (étape 4) a déjà besoin.

Porté en partie de rangement (`app/inventaire/agent.py`). L'étape 5 du plan rangement + mails y
ajoutera l'API de l'agent Go (configuration, lots compressés, empreintes) ; ici, seulement :

- la validation d'une racine Windows et d'un chemin relatif reçu de l'extérieur ;
- la création d'un poste **sans jeton** (un PC inventorié par import, pas encore par un agent :
  son jeton de portée `agent` viendra de `jetons_api` à l'étape 5) ;
- la déclaration d'un emplacement de poste, sans chevauchement sur le même PC ;
- le traitement d'un envoi par le même scan que le NAS (`SourceEnvoi`).
"""

import ntpath
import re
from typing import Any

from services.rangement import reglages
from services.rangement.depot import Depot, Emplacement, Poste
from services.rangement.erreurs import InventaireRefus
from services.rangement.scan import Scanner, SourceEnvoi, nom_valide

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
