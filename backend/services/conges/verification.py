"""
Vérification en ligne des règles de congés — les chiffres du code face aux pages officielles
===========================================================================================
Relire à la main service-public et ameli pour chaque durée est exactement le genre de tâche
qu'on repousse — et une durée périmée coûte un droit. Ce module fait la relecture tout seul :
il télécharge les pages de `regles.SOURCES`, et cherche dans chacune les phrases témoins de
`regles.CONTROLES`, construites depuis les constantes du code.

## Ce qu'il fait, et ce qu'il refuse de faire

- Il **constate** : telle phrase est présente, telle autre introuvable, telle page a été mise
  à jour par l'administration après notre dernier relevé. Il ne **corrige jamais** une règle :
  un chiffre lu sur une page ne réécrit pas une durée légale sans relecture humaine.
- Il ne sort **que sur demande**, après confirmation dans l'écran (règle du 100 % local :
  aucun appel réseau non sollicité). Rien n'est planifié.
- Il n'envoie **rien** : de simples GET sur des URL publiques figées dans le code, sans
  paramètre, sans cookie, sans aucune donnée du foyer ni du dossier.

`normaliser` et `controler` sont **purs** (testés sans réseau) ; seul `verifier` sort.
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime, timezone

import httpx

from services.conges import regles

TIMEOUT = 20.0
# User-Agent de navigateur générique : c'est celui avec lequel les pages ont été relevées.
# Il ne dit rien de l'utilisateur.
ENTETES = {"User-Agent": "Mozilla/5.0"}

MOIS = {"janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
        "juillet": 7, "août": 8, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
        "décembre": 12, "decembre": 12}


def normaliser(page: str) -> str:
    """
    Le texte visible d'une page HTML, en minuscules et espaces simples — la forme sous
    laquelle les phrases témoins ont été relevées. Les balises sont remplacées par des espaces
    (« <strong>2 semaines</strong> avant » → « 2 semaines avant »), les espaces insécables et
    l'apostrophe typographique ramenés à leur forme simple.
    """
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t).replace(" ", " ").replace(" ", " ").replace("’", "'")
    return re.sub(r"\s+", " ", t).strip().lower()


def date_verification(texte: str) -> date | None:
    """La mention « Vérifié le 01 juin 2026 » de service-public, si la page en porte une."""
    m = re.search(r"vérifié le (\d{1,2}) ([a-zéû]+) (\d{4})", texte)
    if not m or m.group(2) not in MOIS:
        return None
    try:
        return date(int(m.group(3)), MOIS[m.group(2)], int(m.group(1)))
    except ValueError:
        return None


def controler(textes: dict[str, str], erreurs: dict[str, str],
              maintenant: datetime | None = None) -> dict:
    """
    Le rapport de vérification, à partir des pages déjà téléchargées et normalisées
    (`textes`, par URL) et des échecs de téléchargement (`erreurs`, par URL).

    Une phrase d'une page **injoignable** n'est ni présente ni absente : elle est « non
    vérifiée ». Confondre les deux ferait croire à un changement de loi à chaque coupure réseau.
    """
    controles = []
    for c in regles.CONTROLES:
        texte = textes.get(c.url)
        controles.append({
            "cle": c.cle, "libelle": c.libelle, "url": c.url,
            "ok": None if texte is None else c.phrase in texte,
        })

    pages = []
    for s in regles.SOURCES:
        url = s["url"]
        if not any(c.url == url for c in regles.CONTROLES):
            continue                       # Légifrance : cité, mais pas contrôlé
        texte = textes.get(url)
        verifiee = date_verification(texte) if texte else None
        pages.append({
            "url": url, "libelle": s["libelle"],
            "joignable": texte is not None, "erreur": erreurs.get(url),
            "verifie_le_page": verifiee.isoformat() if verifiee else None,
            # La page a été revue par l'administration APRÈS notre relevé : même si toutes nos
            # phrases y sont encore, autre chose a pu changer — à relire.
            "revue_depuis": bool(verifiee and verifiee > regles.VERIFIE_LE),
        })

    absentes = sum(1 for c in controles if c["ok"] is False)
    non_verifiees = sum(1 for c in controles if c["ok"] is None)
    revues = sum(1 for p in pages if p["revue_depuis"])
    return {
        "le": (maintenant or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
        "regles_verifiees_le": regles.VERIFIE_LE.isoformat(),
        "conforme": absentes == 0 and non_verifiees == 0 and revues == 0,
        "absentes": absentes, "non_verifiees": non_verifiees, "pages_revues": revues,
        "controles": controles, "pages": pages,
    }


async def verifier(client: httpx.AsyncClient | None = None) -> dict:
    """
    Télécharge chaque page contrôlée — une seule fois même si plusieurs contrôles la visent —
    puis rend le rapport. **Seule fonction de ce module qui sorte sur Internet.**
    """
    urls = sorted({c.url for c in regles.CONTROLES})
    textes: dict[str, str] = {}
    erreurs: dict[str, str] = {}
    propre = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, headers=ENTETES)
    try:
        for url in urls:
            try:
                r = await client.get(url)
                r.raise_for_status()
                textes[url] = normaliser(r.text)
            except httpx.HTTPError as e:
                erreurs[url] = f"{type(e).__name__} : {e}"[:200]
    finally:
        if propre:
            await client.aclose()
    return controler(textes, erreurs)
