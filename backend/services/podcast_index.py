"""
Retrouver l'URL du flux RSS d'un podcast à partir de son nom
=============================================================
Un podcast **est** un flux RSS, mais presque personne ne connaît l'adresse de ce flux : on
connaît le nom de l'émission, et un lien Spotify, Deezer ou Apple Podcasts. Or ces pages de
plateforme ne sont pas des flux — les y coller donne un échec à la lecture, ce qui s'est
produit chez nous (`flux_url` valant une URL de recherche Deezer).

Ce module interroge l'**annuaire Apple Podcasts** (`itunes.apple.com/search`), qui est de fait
l'index de référence : c'est là que les éditeurs déclarent leur flux, et la recherche renvoie
directement le champ `feedUrl`. Pas de clé d'API, pas de compte.

⚠️ **C'est une sortie Internet**, la seule de ce fichier, et elle n'a lieu que sur un clic.
Ce qui sort : **le nom du podcast** (et son auteur s'il est connu), rien d'autre — aucun
document, aucun tag, aucun identifiant de la GED. Ce qui rentre : des adresses de flux, que
l'utilisateur choisit lui-même. L'appelant doit l'annoncer AVANT le clic, comme pour la veille.
"""

import json
from urllib.parse import urlencode

import httpx

from logger import get_logger

log = get_logger(__name__)

_RECHERCHE = "https://itunes.apple.com/search"
_TIMEOUT = httpx.Timeout(12.0, connect=6.0)

# Hôtes qui servent une PAGE et jamais un flux. Un lien vers eux dans `flux_url` est une
# erreur silencieuse : la lecture échouera en parlant de « format illisible », ce qui envoie
# chercher un problème de réseau là où il n'y a qu'un mauvais champ.
PLATEFORMES_SANS_FLUX = (
    "open.spotify.com", "spotify.com",
    "deezer.com",
    "podcasts.apple.com", "itunes.apple.com",
    "music.amazon", "podcastaddict.com/podcast",
    "youtube.com", "youtu.be",
)


def ressemble_a_une_page(url: str) -> str | None:
    """
    Renvoie le nom de la plateforme si `url` est une page d'écoute plutôt qu'un flux.

    Sert à prévenir, pas à interdire : un éditeur peut toujours héberger son flux sur un
    domaine inattendu, et c'est la lecture réelle qui tranche.
    """
    u = (url or "").lower()
    for hote in PLATEFORMES_SANS_FLUX:
        if hote in u:
            return hote
    return None


async def chercher(titre: str, auteur: str | None = None, limite: int = 6) -> list[dict]:
    """
    Cherche un podcast par son nom dans l'annuaire Apple et renvoie ses flux candidats.

    Plusieurs résultats sont volontairement rendus : « Le Nid » ou « Père » désignent
    plusieurs émissions, et deviner à la place de l'utilisateur mettrait le mauvais flux dans
    sa fiche sans qu'il le sache. On rend de quoi reconnaître — nom, auteur, nombre d'épisodes.
    """
    terme = " ".join(x for x in (titre, auteur) if x).strip()
    if not terme:
        return []

    params = {
        "term": terme,
        "media": "podcast",
        "entity": "podcast",
        "limit": str(max(1, min(limite, 10))),
        "country": "FR",     # l'annuaire est régionalisé ; nos podcasts sont francophones
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        resp = await client.get(f"{_RECHERCHE}?{urlencode(params)}")
        resp.raise_for_status()
        # L'annuaire répond en `text/javascript`, pas en `application/json` : `resp.json()`
        # de httpx se fie à l'en-tête et lèverait. Le corps, lui, est bien du JSON.
        data = json.loads(resp.text)

    candidats = [
        {
            "titre": r.get("collectionName") or r.get("trackName") or "",
            "auteur": r.get("artistName") or "",
            "feed_url": r.get("feedUrl") or "",
            "nb_episodes": r.get("trackCount") or 0,
            "vignette": r.get("artworkUrl100") or "",
            "genre": r.get("primaryGenreName") or "",
        }
        for r in (data.get("results") or [])
    ]
    # Sans `feedUrl`, un résultat n'apporte rien ici — c'est justement ce qu'on est venu chercher.
    candidats = [c for c in candidats if c["feed_url"]]
    log.info("Recherche de flux podcast", terme=terme, resultats=len(candidats))
    return candidats
