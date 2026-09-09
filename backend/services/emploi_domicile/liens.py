"""
Liens du module — ceux qu'on livre, et ceux que l'utilisateur a ajoutés
======================================================================
Le module embarque ses sources officielles (Pajemploi, CESU, CAF…). Mais l'utilisateur
tient déjà **sa** liste dans *Paramètres → Administration — liens* : son département, sa
PMI, sa mutuelle, son portail CAF personnalisé. Ne pas la reprendre obligerait à quitter
l'onglet pour aller chercher un lien qui est déjà rangé dans l'application.

**La liste s'incrémente donc toute seule** : ajouter un lien dans Administration le fait
apparaître ici, s'il est pertinent — aucune saisie en double, aucun réglage.

## Comment on décide qu'un lien est « pertinent »

Par **mots-clés**, sur le libellé, la section et l'URL. C'est une heuristique, et elle est
assumée comme telle : afficher *tous* les liens d'Administration noierait les trois qui
comptent sous les liens médicaux, bancaires et scolaires. La liste des marqueurs vit
ci-dessous, en clair, pour être relue et complétée — pas dans une expression régulière
enfouie.

⚠️ **Aucun accès réseau ici.** On lit une valeur de configuration et on rend des URL ; ce
sont des ancres que l'utilisateur clique. Matothèque ne sort jamais sur le réseau seule.
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from models.config import Config

log = get_logger(__name__)

CLE_ADMIN_LINKS = "admin_links"

# Marqueurs de pertinence pour ce module. Volontairement explicites et en français comme en
# sigles : un lien nommé « Ma CAF » et un lien nommé « caf.fr » doivent tous deux passer.
MARQUEURS = (
    "pajemploi", "cesu", "urssaf", "caf", "msa", "pmi", "monenfant",
    "service-public", "service public", "impots", "impôts", "net-entreprises",
    "assistante maternelle", "assistant maternel", "assmat", "nounou", "creche", "crèche",
    "garde", "petite enfance", "famille", "departement", "département", "conseil general",
    "conseil général", "france travail", "pole emploi", "pôle emploi",
    "particulier employeur", "convention collective", "legifrance", "légifrance",
)


def _pertinent(lien: dict) -> bool:
    champs = " ".join(str(lien.get(c) or "") for c in ("label", "section", "url")).lower()
    return any(m in champs for m in MARQUEURS)


async def liens_administration(db: AsyncSession) -> list[dict]:
    """
    Les liens d'Administration qui concernent l'emploi à domicile.

    Une configuration illisible ne doit pas casser l'onglet : on renvoie une liste vide en
    le journalisant. Un écran de fiches n'a aucune raison de tomber parce qu'un JSON de
    liens a été mal saisi ailleurs.
    """
    ligne = (await db.execute(
        select(Config).where(Config.cle == CLE_ADMIN_LINKS)
    )).scalar_one_or_none()
    if not ligne or not ligne.valeur:
        return []
    try:
        liens = json.loads(ligne.valeur)
    except json.JSONDecodeError:
        log.warning("Liens d'administration illisibles, ignorés", cle=CLE_ADMIN_LINKS)
        return []
    if not isinstance(liens, list):
        return []

    return [
        {"libelle": (l.get("label") or l.get("url") or "").strip(),
         "url": (l.get("url") or "").strip(),
         "section": (l.get("section") or "").strip() or None,
         "origine": "administration"}
        for l in liens
        if isinstance(l, dict) and (l.get("url") or "").strip() and _pertinent(l)
    ]


def fusionner(livres: list[dict], ajoutes: list[dict]) -> list[dict]:
    """
    Liens du module d'abord, puis ceux de l'utilisateur — **dédoublonnés par URL**.

    Le module passe en premier parce qu'il garantit les guichets ; les liens personnels
    complètent. Et si l'utilisateur a déjà rangé « pajemploi.urssaf.fr » dans Administration,
    il ne doit pas le voir deux fois : c'est le même lien, pas deux sources.
    """
    def _norme(url: str) -> str:
        return url.strip().rstrip("/").lower()

    vus = set()
    sortie: list[dict] = []
    for lien in [{**l, "origine": l.get("origine", "module")} for l in livres] + ajoutes:
        cle = _norme(lien["url"])
        if cle in vus:
            continue
        vus.add(cle)
        sortie.append(lien)
    return sortie
