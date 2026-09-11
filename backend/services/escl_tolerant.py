"""
Lecture tolérante d'un document de scanner — contourner un encodage chunked cassé
=================================================================================
Certains scanners eSCL émettent une réponse `Transfer-Encoding: chunked` **mal formée** sur
`/NextDocument` : ils annoncent une taille de fragment puis en écrivent davantage. Le parseur
HTTP de `httpx` (strict, et il a raison de l'être) s'arrête alors sur :

    malformed chunk footer: bytearray(b'\\x81\\x82') (expected b'\\r\\n')

Les deux octets cités sont de l'image : là où la norme attend un retour à la ligne, l'appareil
a mis la suite du JPEG. **Le scan a bien eu lieu, la page est perdue au transport.**

## Pourquoi ne pas assouplir le client HTTP général

Parce qu'un parseur permissif accepte aussi les trames douteuses de tout le reste de
l'application — la GED, les connecteurs, Ollama. On n'affaiblit pas un mécanisme partagé pour
un appareil : on ajoute une **porte de secours locale**, empruntée uniquement quand la porte
principale a claqué, et dont le résultat est **vérifié** avant d'être accepté.

## Comment

En **HTTP/1.0**, qui ne connaît pas le chunked : le corps est « tout jusqu'à la fermeture de
la connexion ». La plupart des appareils répondent alors sans découpage, et le problème
disparaît à la racine plutôt que d'être rattrapé.

Si l'appareil découpe quand même, on décode **avec indulgence** : on suit les tailles
annoncées, et quand le séparateur attendu n'est pas là on continue au lieu d'abandonner.

## Et si on se trompait ?

Un décodage indulgent peut produire des octets plausibles mais faux — une image tronquée, ou
un fragment d'en-tête HTTP collé dans le JPEG. Ce serait pire que l'échec : on rangerait dans
la GED un document illisible **en croyant avoir réussi**. Le résultat est donc **contrôlé
contre le format annoncé** (signature de début, marqueur de fin), et refusé s'il ne
correspond pas. Une page perdue qui se dit perdue vaut mieux qu'une page corrompue.
"""

from __future__ import annotations

import asyncio
import re
import ssl as ssl_module
from urllib.parse import urlsplit

from logger import get_logger

log = get_logger(__name__)

# Plafond de lecture : une page couleur à 600 ppp pèse quelques dizaines de Mo. Au-delà, ce
# n'est plus une page — c'est une réponse qui ne se termine pas, et il vaut mieux le dire.
TAILLE_MAX = 200 * 1024 * 1024

# Signatures : (début attendu, fin attendue ou None). Le contrôle de fin n'a de sens que pour
# les formats qui en portent une — il détecte la troncature, qui est justement le risque ici.
SIGNATURES: dict[str, tuple[bytes, bytes | None]] = {
    "image/jpeg": (b"\xff\xd8\xff", b"\xff\xd9"),
    "image/png": (b"\x89PNG\r\n\x1a\n", b"IEND\xaeB`\x82"),
    "application/pdf": (b"%PDF-", b"%%EOF"),
    "image/tiff": (b"II*\x00", None),
}


class LectureImpossible(Exception):
    """La porte de secours n'a pas rendu un document exploitable."""


def _controler(donnees: bytes, content_type: str) -> None:
    """
    Vérifie que les octets ressemblent au format annoncé — début **et** fin.

    Sans ce contrôle, un décodage indulgent produirait des octets plausibles mais faux, et on
    rangerait dans la GED un document illisible en croyant avoir réussi. L'échec est une
    réponse acceptable ; le faux succès n'en est pas une.
    """
    if not donnees:
        raise LectureImpossible("Réponse vide : aucune donnée reçue du scanner.")

    signature = SIGNATURES.get((content_type or "").split(";")[0].strip().lower())
    if signature is None:
        return  # format non reconnu : on ne prétend pas savoir le valider

    debut, fin = signature
    if not donnees.startswith(debut):
        raise LectureImpossible(
            f"Les données reçues ne commencent pas comme un {content_type} : la trame HTTP du "
            "scanner est trop abîmée pour être rattrapée."
        )
    # La fin est cherchée dans la QUEUE seulement : un JPEG peut contenir 0xFFD9 dans une
    # miniature embarquée, et le trouver au milieu ne dirait rien de la complétude.
    if fin is not None and fin not in donnees[-4096:]:
        raise LectureImpossible(
            f"Le document reçu est tronqué (fin de {content_type} absente). La page n'a pas "
            "été transmise en entier."
        )


def _decouper_entetes(brut: bytes) -> tuple[int, dict[str, str], bytes]:
    separation = brut.find(b"\r\n\r\n")
    if separation < 0:
        raise LectureImpossible("Réponse HTTP incomplète : aucun en-tête exploitable.")
    tete = brut[:separation].decode("latin-1", errors="replace").split("\r\n")
    corps = brut[separation + 4:]

    m = re.match(r"^HTTP/\d\.\d\s+(\d{3})", tete[0] if tete else "")
    if not m:
        raise LectureImpossible("Réponse HTTP illisible : ligne de statut absente.")

    entetes: dict[str, str] = {}
    for ligne in tete[1:]:
        if ":" in ligne:
            cle, _, valeur = ligne.partition(":")
            entetes[cle.strip().lower()] = valeur.strip()
    return int(m.group(1)), entetes, corps


def _sans_terminaison(queue: bytes) -> bytes:
    """
    Retire la terminaison chunked (`0\\r\\n\\r\\n`) restée collée à la fin des données.

    On ne la retire qu'**à la toute fin** et seulement si elle y est : chercher ce motif
    ailleurs risquerait de couper dans l'image, qui peut contenir n'importe quels octets.
    """
    for marqueur in (b"\r\n0\r\n\r\n", b"\r\n0\r\n", b"0\r\n\r\n"):
        if queue.endswith(marqueur):
            return queue[:-len(marqueur)]
    return queue


def _dechunker_indulgent(corps: bytes) -> bytes:
    """
    Décode un corps chunked **sans abandonner sur un séparateur manquant**.

    C'est précisément là que le parseur strict s'arrête. Ici, quand le `\\r\\n` attendu après
    un fragment n'est pas au rendez-vous, on continue à la position courante plutôt que de
    lever : l'appareil a écrit plus que ce qu'il annonçait, et ces octets-là sont l'image.

    Une ligne de taille illisible met fin au décodage — on rend ce qui a été reconstitué,
    et c'est le contrôle de format qui dira si ça tient debout.
    """
    sortie = bytearray()
    i = 0
    while i < len(corps):
        fin_ligne = corps.find(b"\r\n", i)
        if fin_ligne < 0:
            break
        entete = corps[i:fin_ligne].split(b";")[0].strip()
        try:
            taille = int(entete, 16)
        except ValueError:
            # Plus de trame reconnaissable : le reste est pris tel quel, faute de mieux —
            # mais DÉBARRASSÉ de sa terminaison. Sans ça, le « 0\r\n\r\n » final reste collé
            # à la fin de l'image : le fichier n'est plus un JPEG valide, et le contrôle de
            # format le refuserait après avoir pourtant récupéré la bonne page.
            sortie += _sans_terminaison(corps[i:])
            break
        if taille == 0:
            break
        debut = fin_ligne + 2
        sortie += corps[debut:debut + taille]
        i = debut + taille
        # Le séparateur attendu — s'il est là, on l'enjambe ; sinon on reprend sur place.
        if corps[i:i + 2] == b"\r\n":
            i += 2
    return bytes(sortie)


async def lire_document(url: str, *, timeout: float = 60.0) -> tuple[int, str, bytes]:
    """
    Récupère `url` en **HTTP/1.0**, sur une connexion brute, et rend `(statut, type, octets)`.

    HTTP/1.0 ne connaît pas le chunked : le corps est tout ce qui précède la fermeture de la
    connexion. Chez la plupart des appareils, le découpage cassé disparaît donc à la racine
    au lieu d'être rattrapé — et quand il persiste, le décodage indulgent prend le relais.

    Les octets rendus sont **contrôlés** contre le type annoncé (cf. `_controler`).
    """
    parties = urlsplit(url)
    if parties.scheme not in ("http", "https"):
        raise LectureImpossible(f"Adresse de scanner inattendue : {url}")
    hote = parties.hostname or ""
    port = parties.port or (443 if parties.scheme == "https" else 80)
    chemin = parties.path or "/"
    if parties.query:
        chemin += "?" + parties.query

    contexte = None
    if parties.scheme == "https":
        # Les scanners présentent des certificats auto-signés : les refuser rendrait la
        # porte de secours inutilisable exactement là où elle sert. On est sur le LAN, en
        # face d'un appareil désigné par son adresse — le même compromis que le reste du
        # client eSCL.
        contexte = ssl_module.create_default_context()
        contexte.check_hostname = False
        contexte.verify_mode = ssl_module.CERT_NONE

    requete = (
        f"GET {chemin} HTTP/1.0\r\n"
        f"Host: {hote}:{port}\r\n"
        "Accept: */*\r\n"
        "User-Agent: Matotheque-eSCL/1.0\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("latin-1")

    try:
        lecteur, ecrivain = await asyncio.wait_for(
            asyncio.open_connection(hote, port, ssl=contexte), timeout=timeout)
    except (OSError, asyncio.TimeoutError) as e:
        raise LectureImpossible(f"Scanner injoignable en secours ({hote}:{port}) : {e}") from e

    try:
        ecrivain.write(requete)
        await ecrivain.drain()
        morceaux = bytearray()
        while True:
            bloc = await asyncio.wait_for(lecteur.read(65536), timeout=timeout)
            if not bloc:
                break
            morceaux += bloc
            if len(morceaux) > TAILLE_MAX:
                raise LectureImpossible(
                    "Le scanner envoie une réponse qui ne se termine pas "
                    f"(plus de {TAILLE_MAX // (1024 * 1024)} Mo).")
    except asyncio.TimeoutError as e:
        raise LectureImpossible("Le scanner a cessé de répondre pendant le transfert.") from e
    finally:
        ecrivain.close()
        try:
            await ecrivain.wait_closed()
        except OSError:
            pass

    statut, entetes, corps = _decouper_entetes(bytes(morceaux))
    content_type = (entetes.get("content-type") or "application/octet-stream").split(";")[0].strip()

    if statut != 200:
        # 404 (plus de page) et 503 (pas encore prête) sont des réponses NORMALES de la
        # boucle eSCL : on les rend telles quelles, l'appelant sait quoi en faire.
        return statut, content_type, b""

    if "chunked" in (entetes.get("transfer-encoding") or "").lower():
        log.warning("Scanner : corps encore découpé malgré HTTP/1.0, décodage indulgent",
                    hote=hote)
        donnees = _dechunker_indulgent(corps)
    elif entetes.get("content-length", "").isdigit():
        donnees = corps[:int(entetes["content-length"])]
    else:
        donnees = corps

    _controler(donnees, content_type)
    log.info("Document récupéré en secours HTTP/1.0", hote=hote, octets=len(donnees),
             type=content_type)
    return statut, content_type, donnees
