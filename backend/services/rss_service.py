"""
Service Veille RSS — téléchargement et parsing de flux RSS/Atom
===============================================================
Parseur **sans dépendance** (xml.etree) couvrant les deux familles réelles :

  - **RSS 2.0** : `<rss><channel><item>` (+ RSS 1.0/RDF `<rdf:RDF><item>`) ;
  - **Atom**    : `<feed><entry>`.

On extrait par **nom local** de balise (en ignorant les espaces de noms), ce qui
absorbe les préfixes usuels (`dc:`, `content:`, `media:`…) sans code spécifique.

⚠️ **Sortie réseau** : `rafraichir_dossier` fait des requêtes HTTP SORTANTES. Elle
n'est appelée que depuis un endpoint déclenché par l'utilisateur (jamais en tâche
de fond) — voir le bandeau du modèle `models/flux_rss`.
"""

import asyncio
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from models.flux_rss import FluxRss, VeilleItem

log = get_logger(__name__)

# En-tête « poli » : certains serveurs refusent un client sans User-Agent. On annonce aussi
# accepter du flux (content negotiation) + un cookie de consentement Google — YouTube renvoie
# sinon parfois un 404/consentement sur ses flux `videos.xml`.
_HEADERS = {
    "User-Agent": "Matotheque-Veille/1.0 (+local RSS reader)",
    "Accept": "application/atom+xml, application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    "Cookie": "CONSENT=YES+1; SOCS=CAI",
}
# Statuts transitoires : on retente (YouTube 404 sporadiquement ses flux, serveurs surchargés en 5xx).
_STATUTS_RETRY = {404, 425, 429, 500, 502, 503, 504}
_MAX_ITEMS = 40          # plafond d'items conservés par fetch (les plus récents)
_MAX_RESUME = 600        # troncature du résumé (on garde une phrase de présentation)


def _local(tag: str) -> str:
    """Nom local d'une balise : « {http://…/Atom}entry » → « entry »."""
    return tag.rsplit("}", 1)[-1].lower()


def _find(el: ET.Element, nom: str) -> ET.Element | None:
    """Premier enfant (à un niveau) dont le nom local vaut `nom`."""
    for enfant in el:
        if _local(enfant.tag) == nom:
            return enfant
    return None


def _findall(el: ET.Element, nom: str) -> list[ET.Element]:
    return [enfant for enfant in el if _local(enfant.tag) == nom]


def _texte(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None and el.text else ""


def _sans_html(s: str) -> str | None:
    """Résumé lisible : balises retirées, espaces compactés, tronqué. None si vide."""
    if not s:
        return None
    txt = re.sub(r"<[^>]+>", " ", s)                       # retire le HTML
    txt = re.sub(r"&[a-zA-Z#0-9]+;", " ", txt)             # entités résiduelles
    txt = re.sub(r"\s+", " ", txt).strip()
    if not txt:
        return None
    return txt[:_MAX_RESUME].rstrip() + ("…" if len(txt) > _MAX_RESUME else "")


def _date(s: str) -> datetime | None:
    """Parse une date RSS (RFC 822) ou Atom (ISO 8601). None si illisible."""
    s = (s or "").strip()
    if not s:
        return None
    try:                                                   # Atom : ISO 8601
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:                                                   # RSS : RFC 822
        d = parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _lien_atom(entry: ET.Element) -> str | None:
    """Lien d'une entrée Atom : `<link rel="alternate">` de préférence, sinon le 1er href."""
    liens = _findall(entry, "link")
    for l in liens:
        if l.get("rel", "alternate") == "alternate" and l.get("href"):
            return l.get("href")
    for l in liens:
        if l.get("href"):
            return l.get("href")
    return None


def parse_feed(contenu: bytes) -> tuple[str | None, list[dict]]:
    """
    Parse un flux brut → (titre du flux, liste d'items).
    Chaque item : {guid, titre, url, auteur, resume, date_pub}. `guid` toujours non vide
    (repli sur le lien puis le titre) pour que la dédup fonctionne même sans <guid>.
    """
    root = ET.fromstring(contenu)          # peut lever ET.ParseError → géré par l'appelant
    racine = _local(root.tag)
    items: list[dict] = []

    if racine == "feed":                   # ─── Atom ───
        titre_flux = _texte(_find(root, "title")) or None
        for entry in _findall(root, "entry"):
            titre = _texte(_find(entry, "title"))
            lien = _lien_atom(entry)
            resume = _texte(_find(entry, "summary")) or _texte(_find(entry, "content"))
            auteur_el = _find(entry, "author")
            auteur = _texte(_find(auteur_el, "name")) if auteur_el is not None else ""
            date_s = _texte(_find(entry, "published")) or _texte(_find(entry, "updated"))
            guid = _texte(_find(entry, "id")) or lien or titre
            if titre or lien:
                items.append({
                    "guid": guid or titre, "titre": titre or "(sans titre)", "url": lien,
                    "auteur": auteur or None, "resume": _sans_html(resume), "date_pub": _date(date_s),
                })
    else:                                  # ─── RSS 2.0 / RDF ───
        channel = _find(root, "channel") or root
        titre_flux = _texte(_find(channel, "title")) or None
        # RSS 2.0 : les <item> sont dans <channel> ; RSS 1.0/RDF : au niveau racine.
        sources = _findall(channel, "item") or _findall(root, "item")
        for it in sources:
            titre = _texte(_find(it, "title"))
            lien = _texte(_find(it, "link"))
            resume = _texte(_find(it, "description")) or _texte(_find(it, "encoded"))
            auteur = _texte(_find(it, "creator")) or _texte(_find(it, "author"))
            date_s = _texte(_find(it, "pubdate")) or _texte(_find(it, "date"))
            guid = _texte(_find(it, "guid")) or lien or titre
            if titre or lien:
                items.append({
                    "guid": guid or titre, "titre": titre or "(sans titre)", "url": lien or None,
                    "auteur": auteur or None, "resume": _sans_html(resume), "date_pub": _date(date_s),
                })

    # Les plus récents d'abord (date connue avant date inconnue), plafonné.
    items.sort(key=lambda i: i["date_pub"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return titre_flux, items[:_MAX_ITEMS]


async def fetch_flux(url: str) -> tuple[str | None, list[dict]]:
    """
    Télécharge et parse un flux. Lève une exception explicite en cas d'échec réseau/format.

    Retente jusqu'à 3 fois sur les statuts TRANSITOIRES (404/429/5xx) : les flux YouTube
    renvoient sporadiquement un 404 sans raison, et un simple nouvel essai passe.
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0),
                                 follow_redirects=True, headers=_HEADERS) as client:
        resp = None
        for tentative in range(3):
            resp = await client.get(url)
            if resp.status_code == 200:
                return parse_feed(resp.content)
            if resp.status_code in _STATUTS_RETRY and tentative < 2:
                await asyncio.sleep(0.8 * (tentative + 1))   # petit backoff
                continue
            break
        resp.raise_for_status()   # statut non-200 définitif → HTTPStatusError (état d'erreur du flux)
        return parse_feed(resp.content)


async def rafraichir_dossier(db: AsyncSession, dossier_id) -> dict:
    """
    Rafraîchit TOUS les flux actifs d'un dossier (action déclenchée par l'utilisateur).
    Pour chaque flux : télécharge, parse, insère les items NOUVEAUX (dédup par guid).
    Robuste flux par flux : un flux en erreur n'interrompt pas les autres.

    Returns un récapitulatif : {nouveaux, flux: [{id, titre, url, nouveaux, etat}]}.
    """
    flux = (await db.execute(
        select(FluxRss).where(FluxRss.dossier_id == dossier_id, FluxRss.actif.is_(True))
    )).scalars().all()

    recap_flux: list[dict] = []
    total_nouveaux = 0

    for f in flux:
        etat = "ok"
        nouveaux = 0
        try:
            titre_flux, items = await fetch_flux(f.url)
            if titre_flux and not f.titre:
                f.titre = titre_flux[:300]
            # Guids déjà connus de CE flux (dédup sans lever d'IntegrityError).
            connus = set((await db.execute(
                select(VeilleItem.guid).where(VeilleItem.flux_id == f.id)
            )).scalars().all())
            for it in items:
                if it["guid"] in connus:
                    continue
                db.add(VeilleItem(
                    flux_id=f.id, dossier_id=dossier_id, guid=it["guid"],
                    titre=it["titre"][:500], url=it["url"], auteur=it["auteur"],
                    resume=it["resume"], date_pub=it["date_pub"],
                ))
                connus.add(it["guid"])
                nouveaux += 1
        except httpx.HTTPStatusError as e:
            etat = f"erreur: HTTP {e.response.status_code}"
        except ET.ParseError:
            etat = "erreur: flux illisible (pas du RSS/Atom ?)"
        except Exception as e:  # noqa: BLE001 — réseau/DNS/timeout : on borne l'échec au flux
            etat = f"erreur: {str(e) or type(e).__name__}"[:200]

        f.dernier_fetch = datetime.now(timezone.utc)
        f.dernier_etat = etat
        total_nouveaux += nouveaux
        recap_flux.append({"id": str(f.id), "titre": f.titre, "url": f.url,
                           "nouveaux": nouveaux, "etat": etat})

    await db.commit()
    log.info("Veille rafraîchie (action utilisateur)", dossier=str(dossier_id),
             flux=len(flux), nouveaux=total_nouveaux)
    return {"nouveaux": total_nouveaux, "flux": recap_flux}
