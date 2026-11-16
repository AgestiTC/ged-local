"""
Propositions de modification du wiki (16/11/2026) — voir `models/proposition_wiki.py`.

Décisions de Thomas : tout utilisateur propose, les ADMINISTRATEURS de la Matothèque appliquent ; une page
écrite avec l'éditeur visuel (HTML) est CONVERTIE en Markdown pour être proposée (à l'application, elle
passe en Markdown dans BookStack : l'avant/après le montre). L'auteur est celui de la session SSO, gardé ici
et inscrit sur la page BookStack (étiquette « Modifiée via la Matothèque »).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from logger import get_logger
from models.proposition_wiki import OUVERTS, PropositionWiki

log = get_logger(__name__)

MAX_OCTETS = 1_000_000
MAX_COMMENTAIRE = 2000
#: Étiquette posée sur la page BookStack à l'application : qui a proposé, qui a validé, quand.
ETIQUETTE = "Modifiée via la Matothèque"


class Conflit(Exception):
    """La page a changé dans BookStack depuis la proposition : l'appliquer écraserait ce changement."""


def html_vers_markdown(html: str) -> str:
    """Le HTML d'une page (éditeur visuel de BookStack) en Markdown. Titres `#`, listes `-`."""
    from markdownify import markdownify

    md = markdownify(html or "", heading_style="ATX", bullets="-", strip=["script", "style"])
    lignes = [l.rstrip() for l in md.replace("\r\n", "\n").split("\n")]
    texte, vides = [], 0
    for l in lignes:   # au plus une ligne vide d'affilée
        vides = vides + 1 if not l else 0
        if vides <= 1:
            texte.append(l)
    return "\n".join(texte).strip() + "\n"


def nom_auteur(auteur: dict | None) -> str:
    a = auteur or {}
    nom, ident = a.get("nom"), a.get("identifiant")
    if nom and ident and nom != ident:
        return f"{nom} ({ident})"
    return nom or ident or "inconnu"


async def origine_page(db, page_id: int) -> tuple[str, Any]:
    """(origine, publication) d'une page : `cockpit`, `projet` (passerelle à jeton) ou `bookstack`."""
    from models.publication import Publication
    from services import docs_cockpit

    pub = (await db.execute(select(Publication).where(Publication.page_id == page_id))).scalars().first()
    if pub is None:
        return "bookstack", None
    return ("cockpit" if await docs_cockpit.depose_par_cockpit(db, pub.projet) else "projet"), pub


async def source(db, svc, page_id: int) -> dict:
    """Ce qu'on édite pour proposer : le Markdown de la page (sans bandeau), ou son HTML converti."""
    from services import publication_service

    page = await svc.get_page(page_id)
    origine, pub = await origine_page(db, page_id)
    brut = page.get("markdown") or ""
    if brut.strip():
        markdown, converti = publication_service.retirer_bandeau(brut), False
    else:
        markdown, converti = html_vers_markdown(page.get("html") or ""), True
    return {"page": page, "origine": origine, "pub": pub, "markdown": markdown, "converti": converti}


def _valider(avant: str, propose: str, commentaire: str) -> tuple[str, str]:
    propose = (propose or "").replace("\r\n", "\n")
    commentaire = (commentaire or "").strip()
    if not propose.strip():
        raise ValueError("Le texte proposé est vide.")
    if propose.strip() == (avant or "").strip():
        raise ValueError("Aucune modification : le texte proposé est identique à la page.")
    if len(propose.encode("utf-8")) > MAX_OCTETS:
        raise ValueError("Le texte proposé dépasse 1 Mo.")
    if len(commentaire) > MAX_COMMENTAIRE:
        raise ValueError(f"Le commentaire dépasse {MAX_COMMENTAIRE} caractères.")
    return propose, commentaire


async def proposer(db, svc, page_id: int, propose: str, commentaire: str, auteur: dict, *, nas: Any = None) -> PropositionWiki:
    """Enregistre la proposition ; une page du cockpit est aussi TRANSMISE au projet (fichier sur le NAS)."""
    from services import docs_cockpit

    s = await source(db, svc, page_id)
    page, origine, pub = s["page"], s["origine"], s["pub"]
    propose, commentaire = _valider(s["markdown"], propose, commentaire)
    fichier = None
    if origine == "cockpit":
        fichier = await docs_cockpit.deposer_proposition(
            db, pub, titre=page["name"], page_url=svc.page_url(page), avant=s["markdown"], propose=propose,
            commentaire=commentaire, auteur=auteur, nas=nas)
    statut = {"cockpit": "transmise", "projet": "a_reporter"}.get(origine, "proposee")
    p = PropositionWiki(page_id=page_id, book_id=page.get("book_id"), titre=page["name"], origine=origine,
                        projet=pub.projet if pub else None, cle=pub.cle if pub else None, converti=s["converti"],
                        page_maj_le=str(page.get("updated_at") or "") or None, markdown_avant=s["markdown"],
                        markdown_propose=propose, commentaire=commentaire, auteur=auteur, statut=statut,
                        fichier_nas=fichier)
    db.add(p)
    await db.commit()
    log.info("Wiki : modification proposée", page_id=page_id, origine=origine, statut=statut,
             auteur=auteur.get("identifiant"))
    return p


def _etiquettes(page: dict, p: PropositionWiki, par: str, quand: datetime) -> list[dict]:
    """Les étiquettes de la page, avec la nôtre remplacée (jamais les autres perdues)."""
    gardees = [{"name": t.get("name"), "value": t.get("value") or ""} for t in (page.get("tags") or [])
               if t.get("name") != ETIQUETTE]
    valeur = f"proposé par {nom_auteur(p.auteur)}, validé par {par}, le {quand:%d/%m/%Y}"
    return gardees + [{"name": ETIQUETTE, "value": valeur[:250]}]


async def appliquer(db, svc, p: PropositionWiki, par: str, *, forcer: bool = False) -> PropositionWiki:
    """Écrit la proposition dans BookStack (page écrite dans BookStack seulement). `Conflit` si la page a
    changé depuis la proposition, sauf `forcer`."""
    if p.statut != "proposee" or p.origine != "bookstack":
        raise ValueError("Seule une proposition en attente, sur une page écrite dans BookStack, s'applique ici.")
    page = await svc.get_page(p.page_id)
    if not forcer and p.page_maj_le and str(page.get("updated_at") or "") != p.page_maj_le:
        raise Conflit("La page a été modifiée dans BookStack depuis la proposition : l'appliquer écraserait "
                      "ce changement. Refuser, ou appliquer quand même en connaissance de cause.")
    quand = datetime.now(timezone.utc)
    await svc.update_page(p.page_id, p.markdown_propose, tags=_etiquettes(page, p, par, quand))
    p.statut, p.decide_par, p.decide_le = "appliquee", par, quand
    await db.commit()
    log.info("Wiki : proposition appliquée", page_id=p.page_id, par=par, auteur=p.auteur.get("identifiant"))
    return p


async def cloturer(db, p: PropositionWiki, statut: str, par: str, motif: str | None = None) -> PropositionWiki:
    """Refuser (toute proposition ouverte), ou marquer « reportée dans le projet » (`a_reporter`)."""
    if p.statut not in OUVERTS:
        raise ValueError(f"Cette proposition est déjà « {p.statut} ».")
    if statut == "appliquee" and p.statut != "a_reporter":
        raise ValueError("« Reportée » ne vaut que pour une page publiée par un projet.")
    if statut not in ("refusee", "appliquee"):
        raise ValueError("Statut attendu : refusee ou appliquee.")
    p.statut, p.decide_par, p.decide_le = statut, par, datetime.now(timezone.utc)
    p.motif = (motif or "").strip()[:500] or None
    await db.commit()
    return p


def en_json(p: PropositionWiki) -> dict:
    return {"id": str(p.id), "page_id": p.page_id, "book_id": p.book_id, "titre": p.titre, "origine": p.origine,
            "projet": p.projet, "cle": p.cle, "converti": p.converti, "markdown_avant": p.markdown_avant,
            "markdown_propose": p.markdown_propose, "commentaire": p.commentaire, "auteur": p.auteur,
            "statut": p.statut, "fichier_nas": p.fichier_nas, "decide_par": p.decide_par,
            "decide_le": p.decide_le.isoformat() if p.decide_le else None, "motif": p.motif,
            "created_at": p.created_at.isoformat() if p.created_at else None}
