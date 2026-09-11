"""
Tests — lecture tolérante d'un document de scanner
===================================================
Le défaut observé en production : un scanner qui annonce une taille de fragment puis en écrit
davantage, ce qui arrête net le parseur HTTP strict de `httpx` sur

    malformed chunk footer: bytearray(b'\\x81\\x82') (expected b'\\r\\n')

Les tests montent un **vrai serveur TCP** qui rejoue exactement ce comportement : c'est le
seul moyen de vérifier une porte de secours dont tout l'objet est de contourner la couche
HTTP. Un faux transport httpx ne reproduirait pas le défaut, puisque le défaut EST dans le
décodage de httpx.

Ce qui est testé, et pourquoi :

- **la page cassée est récupérée** — c'est la raison d'être du module ;
- **un document tronqué est REFUSÉ**, pas rendu : ranger dans la GED un fichier illisible en
  croyant avoir réussi serait pire que l'échec d'origine, parce que personne n'irait vérifier ;
- **404 et 503 restent des réponses normales** : la boucle eSCL s'en sert pour savoir qu'il
  n'y a plus de page, ou qu'elle n'est pas prête. Les traiter comme des erreurs casserait le
  scan au lieu de le réparer.
"""

import asyncio

import pytest

from services import escl_tolerant

JPEG = b"\xff\xd8\xff\xe0" + b"CORPS DE L'IMAGE" * 40 + b"\xff\xd9"


async def _serveur(reponse: bytes):
    """Un serveur TCP qui renvoie `reponse` telle quelle, puis ferme. Rend (hôte, port)."""
    async def traiter(lecteur, ecrivain):
        await lecteur.read(4096)          # on consomme la requête sans la lire
        ecrivain.write(reponse)
        await ecrivain.drain()
        ecrivain.close()

    serveur = await asyncio.start_server(traiter, "127.0.0.1", 0)
    port = serveur.sockets[0].getsockname()[1]
    return serveur, f"http://127.0.0.1:{port}/eSCL/ScanJobs/1/NextDocument"


def _chunked_casse(charge: bytes) -> bytes:
    """
    Le défaut réel : la taille annoncée est plus PETITE que les octets écrits.

    Le séparateur `\\r\\n` attendu après le fragment tombe donc au milieu de l'image — et
    c'est exactement l'octet que le message d'erreur de production citait.
    """
    menteuse = len(charge) - 10
    return (b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n"
            + f"{menteuse:x}".encode() + b"\r\n" + charge + b"\r\n0\r\n\r\n")


# ─── La récupération ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_une_page_perdue_par_un_chunked_casse_est_recuperee():
    """La raison d'être du module : le scan a eu lieu, la page ne doit pas être perdue."""
    serveur, url = await _serveur(_chunked_casse(JPEG))
    async with serveur:
        statut, type_doc, octets = await escl_tolerant.lire_document(url)
    assert statut == 200
    assert type_doc == "image/jpeg"
    assert octets.startswith(b"\xff\xd8\xff") and octets.endswith(b"\xff\xd9")


@pytest.mark.asyncio
async def test_une_reponse_saine_avec_content_length_passe_aussi():
    """La porte de secours doit marcher dans le cas normal, pas seulement dans le cassé."""
    reponse = (b"HTTP/1.0 200 OK\r\nContent-Type: image/jpeg\r\n"
               + f"Content-Length: {len(JPEG)}".encode() + b"\r\n\r\n" + JPEG)
    serveur, url = await _serveur(reponse)
    async with serveur:
        _, _, octets = await escl_tolerant.lire_document(url)
    assert octets == JPEG


@pytest.mark.asyncio
async def test_corps_sans_longueur_ni_decoupage_est_lu_jusqu_a_la_fermeture():
    """C'est la sémantique HTTP/1.0, et c'est ce qui fait disparaître le problème à la racine."""
    reponse = b"HTTP/1.0 200 OK\r\nContent-Type: image/jpeg\r\n\r\n" + JPEG
    serveur, url = await _serveur(reponse)
    async with serveur:
        _, _, octets = await escl_tolerant.lire_document(url)
    assert octets == JPEG


# ─── Le refus, qui compte autant ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_un_document_tronque_est_refuse():
    """
    Le garde-fou central. Un décodage indulgent peut rendre des octets plausibles mais faux ;
    les accepter rangerait dans la GED un fichier illisible **en croyant avoir réussi** — et
    personne n'irait vérifier. Une page perdue qui se dit perdue vaut mieux.
    """
    tronque = JPEG[:len(JPEG) // 2]
    reponse = (b"HTTP/1.0 200 OK\r\nContent-Type: image/jpeg\r\n\r\n" + tronque)
    serveur, url = await _serveur(reponse)
    async with serveur:
        with pytest.raises(escl_tolerant.LectureImpossible, match="tronqué"):
            await escl_tolerant.lire_document(url)


@pytest.mark.asyncio
async def test_des_octets_qui_ne_sont_pas_le_format_annonce_sont_refuses():
    """Une trame trop abîmée produit du n'importe quoi : mieux vaut le dire que le ranger."""
    reponse = b"HTTP/1.0 200 OK\r\nContent-Type: image/jpeg\r\n\r\nPAS UNE IMAGE DU TOUT"
    serveur, url = await _serveur(reponse)
    async with serveur:
        with pytest.raises(escl_tolerant.LectureImpossible, match="ne commencent pas"):
            await escl_tolerant.lire_document(url)


@pytest.mark.asyncio
async def test_reponse_vide_refusee():
    reponse = b"HTTP/1.0 200 OK\r\nContent-Type: image/jpeg\r\n\r\n"
    serveur, url = await _serveur(reponse)
    async with serveur:
        with pytest.raises(escl_tolerant.LectureImpossible):
            await escl_tolerant.lire_document(url)


# ─── Ce qui n'est PAS une erreur ──────────────────────────────────────────────────────

@pytest.mark.parametrize("code", [404, 503])
@pytest.mark.asyncio
async def test_404_et_503_restent_des_reponses_normales(code):
    """
    La boucle eSCL s'en sert : 404 = plus de page, 503 = pas encore prête. Les traiter comme
    des erreurs casserait le scan au lieu de le réparer.
    """
    reponse = f"HTTP/1.0 {code} Non\r\nContent-Type: text/plain\r\n\r\n".encode()
    serveur, url = await _serveur(reponse)
    async with serveur:
        statut, _, octets = await escl_tolerant.lire_document(url)
    assert statut == code and octets == b""


@pytest.mark.asyncio
async def test_scanner_injoignable_le_dit_sans_trace_technique():
    """Un port fermé est une panne courante : le message doit rester lisible."""
    with pytest.raises(escl_tolerant.LectureImpossible, match="injoignable"):
        await escl_tolerant.lire_document("http://127.0.0.1:1/NextDocument", timeout=2.0)


# ─── Le décodage indulgent, isolé ─────────────────────────────────────────────────────

def test_le_dechunkage_suit_les_tailles_quand_elles_sont_justes():
    corps = b"5\r\nHELLO\r\n5\r\nWORLD\r\n0\r\n\r\n"
    assert escl_tolerant._dechunker_indulgent(corps) == b"HELLOWORLD"


def test_le_dechunkage_ne_s_arrete_pas_sur_un_separateur_absent():
    """
    C'est précisément là que le parseur strict abandonne. Ici on continue : les octets qui
    occupent la place du séparateur sont de l'image, pas du protocole.
    """
    corps = b"3\r\nABCDEF\r\n0\r\n\r\n"
    resultat = escl_tolerant._dechunker_indulgent(corps)
    assert resultat.startswith(b"ABC"), "le fragment annoncé est lu"
    assert len(resultat) >= 3, "et le décodage ne lève pas"


def test_une_taille_illisible_termine_le_decodage_sans_lever():
    """On rend ce qui a été reconstitué ; c'est le contrôle de format qui tranchera."""
    corps = b"4\r\nABCD\r\nPAS_DU_HEXA\r\n"
    assert escl_tolerant._dechunker_indulgent(corps).startswith(b"ABCD")
