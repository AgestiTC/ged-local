"""
Garde « destination publique » — refuse qu'une URL saisie par un utilisateur fasse
interroger le RÉSEAU LOCAL par le backend (SSRF).
=====================================================================================
Un flux RSS est une URL libre. Sans garde, `http://192.168.42.200:5000/…` (NAS),
`http://backend:8000/api/…` ou `http://127.0.0.1:…` serait appelé PAR le serveur, depuis
l'intérieur du LAN — et la réponse (ou son message d'erreur) renvoyée à l'écran.

Règle (décision du 31/10/2026) : **toute adresse non publique est refusée**, sans liste
d'exceptions pour l'instant (« on reviendra au cas par cas »). Le contrôle porte sur
TOUTES les adresses que le nom résout, et il est rejoué à chaque saut de redirection
(crochet httpx `request`) : un flux public qui redirige vers le LAN est refusé aussi.

Limite connue : entre notre résolution DNS et celle d'httpx, un serveur DNS hostile
pourrait changer de réponse (rebinding). Le risque est jugé faible ici (DNS local maîtrisé,
action déclenchée par un utilisateur connecté) ; le fermer demanderait d'épingler l'IP
dans le transport.
"""

import asyncio
import ipaddress
import socket

import httpx

_SCHEMAS = ("http", "https")


class DestinationInterdite(ValueError):
    """L'URL vise une adresse non publique (LAN, boucle locale, lien local…) ou un schéma exotique."""


def _publique(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # ::ffff:192.168.1.1 est une adresse IPv4 déguisée : on juge l'IPv4.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def _resoudre(hote: str, port: int) -> set[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(hote, port, type=socket.SOCK_STREAM)
    # sockaddr[0] ; une IPv6 lien-local peut porter un « %zone » qu'ipaddress refuse.
    return {info[4][0].split("%")[0] for info in infos}


async def verifier_url(url: str | httpx.URL) -> None:
    """Lève `DestinationInterdite` si `url` ne vise pas exclusivement des adresses publiques."""
    u = httpx.URL(str(url))
    if u.scheme not in _SCHEMAS:
        raise DestinationInterdite(f"schéma « {u.scheme} » refusé (http ou https seulement)")
    hote = u.host
    if not hote:
        raise DestinationInterdite("URL sans hôte")
    try:
        ipaddress.ip_address(hote)
        adresses = {hote}
    except ValueError:
        try:
            adresses = await _resoudre(hote, u.port or (443 if u.scheme == "https" else 80))
        except socket.gaierror as e:
            raise DestinationInterdite(f"nom « {hote} » introuvable") from e
    if not adresses:
        raise DestinationInterdite(f"nom « {hote} » introuvable")
    for a in adresses:
        if not _publique(ipaddress.ip_address(a)):
            raise DestinationInterdite(
                f"« {hote} » mène au réseau local ({a}) : refusé par sécurité")


async def crochet_requete(request: httpx.Request) -> None:
    """Crochet httpx `event_hooks={"request": [...]}` — appelé avant CHAQUE requête, redirections comprises."""
    await verifier_url(request.url)
