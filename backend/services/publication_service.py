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


def _utc(d: Any) -> datetime | None:
    """Une date comparable : sans fuseau = UTC (SQLite et certains manifestes n'en portent pas)."""
    if not isinstance(d, datetime):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


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
            gp, ge = _utc(p.get("genere_le")), _utc(ex.get("genere_le"))
            if gp is not None and ge is not None and gp < ge:
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


# ─── Publication d'un manifeste (Lot 3) ───────────────────────────────────────
# Partagée par l'endpoint à jeton (`POST /passerelle/publish`) et par le relevé des dépôts du
# cockpit sur NAS-MATO (`docs_cockpit`, 16/11/2026) : une seule logique de rapprochement et d'écriture.
class PublicationRefusee(Exception):
    """Refus AVANT tout appel à BookStack. `statut` : code HTTP équivalent (403 livre interdit,
    503 BookStack non configuré)."""

    def __init__(self, statut: int, message: str) -> None:
        super().__init__(message)
        self.statut = statut
        self.message = message


def bandeau(projet: str, markdown: str) -> str:
    """Préfixe le contenu d'un bandeau « généré automatiquement » (§6.3) — signale aux humains que la
    page est gérée par la passerelle et qu'une édition manuelle sera écrasée à la prochaine synchro."""
    entete = (f"> ⚙️ _Page générée automatiquement depuis le projet **{projet}** via la passerelle "
              f"Matothèque — ne pas éditer à la main (toute modification sera écrasée à la prochaine "
              f"synchronisation)._\n\n")
    return entete + (markdown or "")


def retirer_bandeau(markdown: str) -> str:
    """Le Markdown d'une page publiée, SANS le bandeau « généré automatiquement » ajouté par `bandeau`."""
    md = markdown or ""
    debut = "> ⚙️ _Page générée automatiquement depuis le projet "
    if md.startswith(debut):
        fin = md.find("\n\n")
        return md[fin + 2:] if fin >= 0 else ""
    return md


async def publier_manifeste(db: AsyncSession, projet: Any, pages: list[dict], etagere: str | None,
                            service: Any = None, log: Any = None) -> dict[str, Any]:
    """
    Publie/synchronise la doc d'un projet vers BookStack à partir de son **manifeste** (arbre complet).
    `projet` : le `ProjetPublieur` (nom + liste blanche des livres). Déroulé : autorisation des livres
    (liste blanche, ATOMIQUE) → rapprochement (créer/màj/inchangées/retraits) → appels BookStack →
    upsert `publications` → étagère. Une page en échec n'annule pas les autres (`erreurs`).
    Lève `PublicationRefusee` avant tout appel si BookStack n'est pas configuré ou un livre est interdit.
    """
    if service is None:
        from services.bookstack_service import BookStackService
        service = BookStackService()
    if log is None:
        from logger import get_logger
        log = get_logger(__name__)
    if not service.configured:
        raise PublicationRefusee(503, "BookStack non configuré (Réglages → Wiki).")

    # ① Autorisation des livres — ATOMIQUE : un seul livre non déclaré → rejet complet, aucun fantôme.
    livres_demandes = {p["livre"] for p in pages}
    interdits = sorted(livres_demandes - set(projet.livres_autorises or []))
    if interdits:
        raise PublicationRefusee(
            403, f"Livre(s) non autorisé(s) pour « {projet.nom} » : {', '.join(interdits)}. "
                 f"Autorisés : {', '.join(projet.livres_autorises or []) or '(aucun)'}.")

    # ② Rapprochement manifeste ↔ état publié.
    existants = await publications_du_projet(db, projet.nom)   # {cle: Publication}
    existantes = {cle: {"contenu_hash": p.contenu_hash, "genere_le": p.genere_le} for cle, p in existants.items()}
    plan = rapprocher(pages, existantes)

    creees: list[dict] = []
    mises_a_jour: list[dict] = []
    erreurs: list[dict] = []

    async def creer(page: dict) -> dict:
        book = await service.ensure_book(page["livre"])
        cible = {"book_id": book["id"]}
        if page.get("chapitre"):
            cible = {"chapter_id": (await service.ensure_chapter(book["id"], page["chapitre"]))["id"]}
        return await service.create_page(page["titre"], bandeau(projet.nom, page.get("markdown", "")), **cible)

    async def memoriser(page: dict, page_id: Any, url: str | None) -> None:
        await enregistrer_publication(
            db, projet=projet.nom, cle=page["cle"], livre=page["livre"], chapitre=page.get("chapitre"),
            page_id=page_id, url=url, contenu_hash=page["hash"], genere_le=page.get("genere_le"))

    # ③ Créations : ensure_book [borné] → ensure_chapter → create_page → upsert.
    for page in plan["creer"]:
        try:
            cree = await creer(page)
            url = service.page_url(cree)
            await memoriser(page, cree.get("id"), url)
            creees.append({"cle": page["cle"], "livre": page["livre"], "page_id": cree.get("id"), "url": url})
        except Exception as e:  # noqa: BLE001 — une page en échec ne doit pas tout annuler
            log.error("Passerelle : création échouée", projet=projet.nom, cle=page["cle"], erreur=str(e))
            erreurs.append({"cle": page["cle"], "message": str(e)})

    # ④ Mises à jour : update_page sur la MÊME page (page_id mémorisé) → upsert.
    for page in plan["mettre_a_jour"]:
        try:
            pub = existants.get(page["cle"])
            if pub and pub.page_id:
                maj = await service.update_page(pub.page_id, bandeau(projet.nom, page.get("markdown", "")),
                                                name=page["titre"])
                url = service.page_url(maj) if maj else pub.url
                page_id = pub.page_id
            else:   # cas limite (ligne sans page_id) → on (re)crée
                cree = await creer(page)
                url, page_id = service.page_url(cree), cree.get("id")
            await memoriser(page, page_id, url)
            mises_a_jour.append({"cle": page["cle"], "livre": page["livre"], "page_id": page_id, "url": url})
        except Exception as e:  # noqa: BLE001
            log.error("Passerelle : mise à jour échouée", projet=projet.nom, cle=page["cle"], erreur=str(e))
            erreurs.append({"cle": page["cle"], "message": str(e)})

    # ⑤ Étagère : regrouper les livres du projet dans l'étagère demandée (idempotent).
    etagere_ok = None
    if etagere:
        try:
            shelf = await service.ensure_shelf(etagere)
            for livre in sorted(livres_demandes):
                book = await service.ensure_book(livre)
                await service.ensure_book_in_shelf(shelf["id"], book["id"])
            etagere_ok = etagere
        except Exception as e:  # noqa: BLE001 — un souci d'étagère ne doit pas perdre la publication
            log.error("Passerelle : rattachement à l'étagère échoué", projet=projet.nom, etagere=etagere, erreur=str(e))
            erreurs.append({"cle": "(étagère)", "message": f"Rattachement à « {etagere} » échoué : {e}"})

    # ⑥ Adresse de chaque livre (compte rendu : « où lire la doc »).
    livres = []
    for livre in sorted(livres_demandes):
        try:
            livres.append({"livre": livre, "url": service.book_url(await service.ensure_book(livre))})
        except Exception:  # noqa: BLE001 — l'adresse est un confort, jamais une cause d'échec
            livres.append({"livre": livre, "url": None})

    await db.commit()
    log.info("Passerelle : publication", projet=projet.nom, creees=len(creees), mises_a_jour=len(mises_a_jour),
             inchangees=len(plan["inchangees"]), retraits=len(plan["retraits_candidats"]),
             erreurs=len(erreurs), etagere=etagere_ok)
    return {
        "projet": projet.nom,
        "etagere": etagere_ok,
        "livres": livres,
        "creees": creees,
        "mises_a_jour": mises_a_jour,
        "inchangees": plan["inchangees"],
        "retraits_candidats": plan["retraits_candidats"],
        "avertissements": plan["avertissements"],
        "erreurs": erreurs,
    }
