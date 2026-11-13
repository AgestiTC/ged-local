"""
Postes de l'inventaire et leurs jetons (étape 5 du plan rangement + mails).

Un poste (PC qui porte l'agent Go) s'authentifie par un jeton de `jetons_api`, de portée `agent`
(décision d'architecture n° 2) : il n'atteint que `/api/agent/*`, la base n'en garde que
l'empreinte, et il n'est montré qu'UNE fois, à sa création. `inv_postes.jeton_id` relie le poste
à son jeton ; « Nouveau jeton » révoque l'ancien aussitôt.

Les jetons d'agent portent un nom unique (horodatage + suffixe aléatoire) : `jetons_api.nom` est
unique, et un nom de jeton révoqué reste réservé.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models.auth import JetonApi
from services import jetons_api
from services.rangement import agent
from services.rangement.depot import Depot, Poste, PosteEnDouble
from services.rangement.erreurs import InventaireRefus

#: Durée de vie d'un jeton de poste. Échu, l'agent est refusé (401) : « Nouveau jeton » le remplace.
JETON_POSTE_JOURS = 730


async def emettre_jeton(db: AsyncSession, nom_poste: str, createur: str | None,
                        createur_id: uuid.UUID | None) -> tuple[JetonApi, str]:
    """Crée un jeton de portée `agent` ; rend (jeton, valeur en clair). Validé tout de suite."""
    clair = jetons_api.nouveau_jeton()
    now = datetime.now(timezone.utc)
    # Suffixe aléatoire : deux émissions dans la même seconde (renouvellement) ne doivent pas se heurter.
    nom = f"Poste — {nom_poste} — {now:%Y-%m-%d %H:%M} — {uuid.uuid4().hex[:6]}"
    jeton = JetonApi(nom=nom, empreinte=jetons_api.empreinte(clair),
                     role="utilisateur", portee=jetons_api.PORTEE_AGENT, createur=createur,
                     createur_id=createur_id, cree=now, expire=now + timedelta(days=JETON_POSTE_JOURS))
    db.add(jeton)
    await db.commit()
    return jeton, clair


async def revoquer_jeton(db: AsyncSession, jeton_id: uuid.UUID | None, par: str | None) -> None:
    if jeton_id is None:
        return
    await db.execute(update(JetonApi).where(JetonApi.id == jeton_id, JetonApi.revoque.is_(None))
                     .values(revoque=datetime.now(timezone.utc), revoque_par=par)
                     .execution_options(synchronize_session=False))
    await db.commit()


async def creer_poste(db: AsyncSession, depot: Depot, nom: str, createur: str | None,
                      createur_id: uuid.UUID | None) -> tuple[Poste, str]:
    """(poste, jeton en clair). Le nom est contrôlé AVANT d'émettre un jeton : pas de jeton orphelin."""
    nom = agent.nom_poste_valide(nom)
    if any(p.nom.casefold() == nom.casefold() for p in await depot.postes()):
        raise InventaireRefus(f"Un poste s'appelle déjà « {nom} ».", code="poste_en_double", statut=409)
    jeton, clair = await emettre_jeton(db, nom, createur, createur_id)
    try:
        poste = await depot.creer_poste(nom, jeton.id)
    except PosteEnDouble as exc:   # course avec une autre création : le jeton ne doit pas survivre
        await revoquer_jeton(db, jeton.id, createur)
        raise InventaireRefus(f"Un poste s'appelle déjà « {nom} ».", code="poste_en_double", statut=409) from exc
    return poste, clair


async def renouveler_jeton(db: AsyncSession, depot: Depot, poste_id: int, createur: str | None,
                           createur_id: uuid.UUID | None) -> str:
    """Nouveau jeton pour ce poste ; l'ancien est révoqué aussitôt. Rend la valeur en clair."""
    poste = await depot.poste(poste_id)
    if poste is None:
        raise LookupError(poste_id)
    jeton, clair = await emettre_jeton(db, poste.nom, createur, createur_id)
    await depot.changer_jeton_poste(poste.id, jeton.id)
    await revoquer_jeton(db, poste.jeton_id, createur)
    return clair
