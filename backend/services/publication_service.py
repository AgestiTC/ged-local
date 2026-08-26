"""
Service Publication — passerelle wiki, Lot 1 (socle, sans auth ni endpoint)
==========================================================================
Cœur de la passerelle de publication vers BookStack, côté données :

  - `hash_contenu`  : empreinte d'un contenu markdown (déduplication).
  - `rapprocher`    : fonction PURE — compare un MANIFESTE (arbre déclaré par le projet) à ce qui est
                      déjà publié, et produit le PLAN : à créer / à mettre à jour / inchangées /
                      retraits candidats / avertissements (version poussée plus ancienne). Testable
                      sans base ni réseau.
  - helpers DB      : charger les publications d'un projet, upsert d'une ligne `publications`.

L'authentification (Lot 2), l'appel réel à BookStack et l'endpoint manifeste (Lot 3) viendront ensuite
et s'appuieront sur ce socle. Cf. `docs/plan-passerelle-wiki-multiprojets.md`.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.publication import Publication


def hash_contenu(markdown: str) -> str:
    """Empreinte SHA-256 (hex) d'un contenu markdown — base de la déduplication."""
    return hashlib.sha256((markdown or "").encode("utf-8")).hexdigest()


def rapprocher(pages: list[dict], existantes: dict[str, dict]) -> dict[str, Any]:
    """
    Rapproche le MANIFESTE (`pages`) de l'état publié (`existantes`) — fonction PURE.

    Args:
        pages: manifeste du projet — liste de dicts `{cle, livre, chapitre?, titre, markdown, genere_le?}`.
        existantes: état publié, indexé par clé → `{contenu_hash, genere_le}` (extrait de `publications`).

    Returns:
        Plan d'action :
          - `creer`             : pages absentes de l'état publié (à créer dans BookStack) ;
          - `mettre_a_jour`     : pages dont le contenu a changé (hash différent) ;
          - `inchangees`        : clés au hash identique (aucune action) ;
          - `retraits_candidats`: clés publiées MAIS absentes du manifeste (signalées, jamais supprimées d'office) ;
          - `avertissements`    : version poussée plus ancienne que la version publiée (on publie quand même).
        Les entrées `creer`/`mettre_a_jour` portent le champ `hash` (empreinte calculée).
    """
    creer: list[dict] = []
    mettre_a_jour: list[dict] = []
    inchangees: list[str] = []
    avertissements: list[str] = []

    cles_manifeste: set[str] = set()
    for p in pages:
        cle = p["cle"]
        cles_manifeste.add(cle)
        h = hash_contenu(p.get("markdown", ""))
        ex = existantes.get(cle)
        if ex is None:
            creer.append({**p, "hash": h})
        elif ex.get("contenu_hash") == h:
            inchangees.append(cle)
        else:
            mettre_a_jour.append({**p, "hash": h})
            gp, ge = p.get("genere_le"), ex.get("genere_le")
            if isinstance(gp, datetime) and isinstance(ge, datetime) and gp < ge:
                avertissements.append(
                    f"{cle} : version poussée ({gp.isoformat()}) plus ancienne que la version publiée ({ge.isoformat()})"
                )

    retraits_candidats = [cle for cle in existantes if cle not in cles_manifeste]
    return {
        "creer": creer,
        "mettre_a_jour": mettre_a_jour,
        "inchangees": inchangees,
        "retraits_candidats": retraits_candidats,
        "avertissements": avertissements,
    }


# ─── Accès base (thin) ────────────────────────────────────────────────────────
async def publications_du_projet(db: AsyncSession, projet: str) -> dict[str, Publication]:
    """Toutes les publications d'un projet, indexées par `cle`."""
    rows = (await db.execute(select(Publication).where(Publication.projet == projet))).scalars().all()
    return {p.cle: p for p in rows}


async def enregistrer_publication(
    db: AsyncSession, *, projet: str, cle: str, livre: str, contenu_hash: str,
    chapitre: str | None = None, page_id: int | None = None, url: str | None = None,
    genere_le: datetime | None = None,
) -> Publication:
    """
    Upsert d'une ligne `publications` par `(projet, cle)` : met à jour la ligne existante (garde son
    `page_id` si non fourni) ou en crée une. Le commit reste à la charge de l'appelant.
    """
    existante = (await db.execute(
        select(Publication).where(Publication.projet == projet, Publication.cle == cle)
    )).scalar_one_or_none()

    if existante is None:
        pub = Publication(projet=projet, cle=cle, livre=livre, chapitre=chapitre,
                          page_id=page_id, url=url, contenu_hash=contenu_hash, genere_le=genere_le)
        db.add(pub)
        await db.flush()
        return pub

    existante.livre = livre
    existante.chapitre = chapitre
    existante.contenu_hash = contenu_hash
    if page_id is not None:
        existante.page_id = page_id
    if url is not None:
        existante.url = url
    if genere_le is not None:
        existante.genere_le = genere_le
    existante.published_at = datetime.now(tz=timezone.utc)   # republication → horodatée maintenant
    await db.flush()
    return existante
