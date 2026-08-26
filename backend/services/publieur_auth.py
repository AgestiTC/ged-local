"""
Service d'authentification des projets publieurs — passerelle wiki, Lot 2
========================================================================
Chaque projet AgestiTC autorisé à publier possède un **jeton d'API** ; Matothèque n'en stocke que
le **hash SHA-256** (le jeton en clair n'est montré qu'UNE fois, à la création/rotation). À la
publication (Lot 3), le projet présente son jeton en en-tête `Authorization: Bearer …` → on le hache
et on retrouve le projet ACTIF correspondant. Révocation = `actif = false` ; rotation = régénérer.

⚠️ Périmètre : BookStack est un outil du **monde AgestiTC** — le monde **MIS/Geco est exclu PAR LE
CODE** (`est_projet_exclu`), pas seulement par convention. Un projet exclu ne peut pas être enregistré.

NB : les endpoints d'ADMINISTRATION (créer/lister/gérer un projet) reposent sur la confiance réseau
comme le reste de l'API ; c'est l'endpoint de PUBLICATION (Lot 3) qui est protégé par le jeton.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from models.publieur import ProjetPublieur

log = get_logger(__name__)

# Exclusion par le code : 1er segment du nom (séparé par -, _ ou espace) valant « mis » ou « geco ».
_MOTIFS_EXCLUS = ("mis", "geco")


def est_projet_exclu(nom: str) -> bool:
    """True si le nom relève du monde MIS/Geco (exclu de BookStack). Fonction PURE."""
    segments = re.split(r"[\s_-]+", (nom or "").strip().lower())
    return bool(segments and segments[0] in _MOTIFS_EXCLUS)


def generer_jeton() -> str:
    """Jeton d'API aléatoire (256 bits, URL-safe). Montré UNE seule fois."""
    return secrets.token_urlsafe(32)


def hash_jeton(token: str) -> str:
    """Empreinte SHA-256 (hex) d'un jeton — c'est ce qui est stocké, jamais le jeton en clair."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


async def creer_projet(db: AsyncSession, nom: str, livres_autorises: list[str]) -> tuple[ProjetPublieur, str]:
    """
    Enregistre un projet publieur et génère son jeton. Renvoie (projet, jeton EN CLAIR — à copier une
    fois). Lève `ValueError` si le nom est vide, exclu (MIS/Geco), ou déjà pris.
    """
    nom = (nom or "").strip()
    if not nom:
        raise ValueError("Nom de projet vide.")
    if est_projet_exclu(nom):
        raise ValueError(f"Projet « {nom} » exclu : BookStack est réservé au monde AgestiTC (MIS/Geco exclus).")
    deja = (await db.execute(select(ProjetPublieur).where(ProjetPublieur.nom == nom))).scalar_one_or_none()
    if deja:
        raise ValueError(f"Le projet « {nom} » existe déjà (utiliser « régénérer le jeton » pour une rotation).")
    token = generer_jeton()
    projet = ProjetPublieur(
        nom=nom, token_hash=hash_jeton(token),
        livres_autorises=[b.strip() for b in (livres_autorises or []) if b.strip()],
    )
    db.add(projet)
    await db.flush()
    log.info("Projet publieur créé", projet=nom, nb_livres=len(projet.livres_autorises))
    return projet, token


async def regenerer_jeton(db: AsyncSession, nom: str) -> str:
    """Rotation : nouveau jeton pour un projet existant (l'ancien cesse de fonctionner). Renvoie le clair."""
    projet = (await db.execute(select(ProjetPublieur).where(ProjetPublieur.nom == nom))).scalar_one_or_none()
    if not projet:
        raise ValueError(f"Projet « {nom} » introuvable.")
    token = generer_jeton()
    projet.token_hash = hash_jeton(token)
    await db.flush()
    log.info("Jeton de projet régénéré", projet=nom)
    return token


async def authentifier(db: AsyncSession, token: str) -> ProjetPublieur | None:
    """
    Retrouve le projet **actif** dont le jeton correspond ; met à jour `last_used_at`. `None` si le
    jeton est vide, inconnu, ou le projet révoqué (`actif = false`).
    """
    if not token:
        return None
    projet = (await db.execute(
        select(ProjetPublieur).where(
            ProjetPublieur.token_hash == hash_jeton(token), ProjetPublieur.actif.is_(True))
    )).scalar_one_or_none()
    if projet:
        projet.last_used_at = datetime.now(tz=timezone.utc)
        await db.flush()
    return projet


async def lister_projets(db: AsyncSession) -> list[ProjetPublieur]:
    """Tous les projets publieurs (sans le hash de jeton — cf. sérialisation côté router)."""
    return list((await db.execute(select(ProjetPublieur).order_by(ProjetPublieur.nom))).scalars().all())


async def definir(db: AsyncSession, nom: str, *, actif: bool | None = None,
                  livres_autorises: list[str] | None = None) -> ProjetPublieur:
    """Met à jour un projet : (dés)activation (révocation) et/ou liste blanche des livres."""
    projet = (await db.execute(select(ProjetPublieur).where(ProjetPublieur.nom == nom))).scalar_one_or_none()
    if not projet:
        raise ValueError(f"Projet « {nom} » introuvable.")
    if actif is not None:
        projet.actif = actif
    if livres_autorises is not None:
        projet.livres_autorises = [b.strip() for b in livres_autorises if b.strip()]
    await db.flush()
    return projet
