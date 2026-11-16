"""
Docs du cockpit → BookStack (16/11/2026, décision de Thomas)
=============================================================
Toute la documentation des applications passe par la Matothèque pour aller dans BookStack. Le cockpit
(`gestion-projet-appli`) ne parle jamais à BookStack : il DÉPOSE un manifeste sur NAS-MATO, la
Matothèque le relève, le publie par la passerelle (`publication_service.publier_manifeste`) et le RETIRE.

Contrat (docs/17-docs-ged.md du cockpit) :
- `Partage-Nas-Mato/[GED]/Docs-applications/<projet>/manifeste.json`, format `cockpit-docs/1` ;
  seul `manifeste.json` est lu (`manifeste.json.part` = écriture en cours, ignoré) ;
- après traitement, le manifeste est RETIRÉ (archivé côté Matothèque, puis supprimé du NAS) : c'est ce
  qui fait passer la fiche projet du cockpit de « en attente » à « pris en charge » ;
- compte rendu à côté (décision du 16/11) : `resultat.json` si publié, `erreur.json` si refusé ;
- limites v1 : 300 pages, 1 Mo par page, Markdown seul.

Accès au NAS : la Source SMB déclarée sur `Partage-Nas-Mato/[GED]/Docs-applications` (compte svc-ged,
mot de passe chiffré en base) — la même que l'indexation GED de ce dossier (v1.191.0). Les `.json` ne
sont pas des extensions indexées : la GED ne voit pas ces fichiers de contrôle.

Un refus définitif (projet inconnu, livre non autorisé, manifeste invalide) RETIRE le manifeste avec un
`erreur.json` : le cockpit corrige et redépose. Un échec passager (BookStack non configuré ou injoignable,
NAS coupé) LAISSE le manifeste : il est repris au relevé suivant.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from logger import get_logger

log = get_logger(__name__)

FORMAT = "cockpit-docs/1"
FORMAT_RESULTAT = "cockpit-docs-resultat/1"
MANIFESTE = "manifeste.json"
RESULTAT = "resultat.json"
ERREUR = "erreur.json"
#: Le dossier de dépôt, sous le partage (comparaison sans casse).
PARTAGE = "Partage-Nas-Mato"
DOSSIER = "[GED]/Docs-applications"
#: Le compte du contrat (lecture + suppression sur le dossier de dépôt).
COMPTE = "svc-ged"
MAX_PAGES = 300
MAX_OCTETS_PAGE = 1_000_000
JOB = "docs_cockpit"
#: Propositions de modification faites depuis le lecteur Wiki (16/11/2026), relues par le cockpit.
FORMAT_PROPOSITION = "cockpit-docs-proposition/1"
PROPOSITIONS = "propositions"
MAX_COMMENTAIRE = 2000
INTERVALLE_S = 15 * 60


class Refus(Exception):
    """Refus définitif d'un dépôt : `code` lisible par le cockpit, `message` pour l'humain."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _date(v: Any) -> datetime | None:
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        d = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _texte(v: Any) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def valider(donnees: Any, dossier_projet: str) -> dict:
    """Le manifeste, contrôlé et normalisé (pages prêtes pour `publier_manifeste`). PURE.
    Lève `Refus` au premier défaut."""
    if not isinstance(donnees, dict):
        raise Refus("manifeste_invalide", "Le manifeste n'est pas un objet JSON.")
    if donnees.get("format") != FORMAT:
        raise Refus("format_inconnu", f"Format « {donnees.get('format')} » inconnu : attendu « {FORMAT} ».")
    projet = _texte(donnees.get("projet"))
    if projet is None:
        raise Refus("manifeste_invalide", "Champ « projet » absent.")
    if projet.casefold() != dossier_projet.casefold():
        raise Refus("projet_incoherent",
                    f"Le manifeste annonce le projet « {projet} » mais il est déposé dans « {dossier_projet} ».")
    pages = donnees.get("pages")
    if not isinstance(pages, list) or not pages:
        raise Refus("manifeste_invalide", "Aucune page dans le manifeste.")
    if len(pages) > MAX_PAGES:
        raise Refus("trop_de_pages", f"{len(pages)} pages : {MAX_PAGES} au plus par dépôt.")
    sortie, cles = [], set()
    for i, p in enumerate(pages, start=1):
        if not isinstance(p, dict):
            raise Refus("page_invalide", f"Page n° {i} : ce n'est pas un objet.")
        cle, livre, titre = _texte(p.get("cle")), _texte(p.get("livre")), _texte(p.get("titre"))
        markdown = p.get("markdown")
        manque = [n for n, v in (("cle", cle), ("livre", livre), ("titre", titre)) if v is None]
        if manque or not isinstance(markdown, str):
            raise Refus("page_invalide", f"Page n° {i} : champ(s) manquant(s) {', '.join(manque or ['markdown'])}.")
        if len(markdown.encode("utf-8")) > MAX_OCTETS_PAGE:
            raise Refus("page_trop_grande", f"Page « {cle} » : plus de 1 Mo de Markdown.")
        if cle in cles:
            raise Refus("cle_en_double", f"La clé « {cle} » apparaît deux fois.")
        cles.add(cle)
        chapitre = p.get("chapitre")
        sortie.append({"cle": cle, "livre": livre, "titre": titre, "markdown": markdown,
                       "chapitre": _texte(chapitre) if chapitre is not None else None,
                       "genere_le": _date(p.get("genere_le"))})
    return {"projet": projet, "nom": _texte(donnees.get("nom")), "version": _texte(donnees.get("version")),
            "etagere": _texte(donnees.get("etagere")), "depose_le": _texte(donnees.get("depose_le")),
            "pages": sortie}


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def resultat_json(m: dict, r: dict) -> dict:
    """Le compte rendu d'une publication, pour le cockpit. PURE."""
    return {
        "format": FORMAT_RESULTAT, "statut": "publie" if not r["erreurs"] else "publie_avec_erreurs",
        "projet": m["projet"], "version": m["version"], "depose_le": m["depose_le"], "traite_le": _maintenant(),
        "etagere": r["etagere"], "livres": r["livres"],
        "pages": {"creees": len(r["creees"]), "mises_a_jour": len(r["mises_a_jour"]),
                  "inchangees": len(r["inchangees"]), "total": len(m["pages"])},
        "creees": r["creees"], "mises_a_jour": r["mises_a_jour"],
        "retraits_candidats": r["retraits_candidats"], "avertissements": r["avertissements"],
        "erreurs": r["erreurs"],
    }


def erreur_json(projet: str, code: str, message: str, *, definitif: bool) -> dict:
    """Le compte rendu d'un refus (définitif : manifeste retiré) ou d'un échec passager. PURE."""
    return {"format": FORMAT_RESULTAT, "statut": "refuse" if definitif else "en_attente",
            "projet": projet, "code": code, "message": message, "traite_le": _maintenant(),
            "manifeste_retire": definitif}


# --------------------------------------------------------------------------- #
# Accès au NAS                                                                 #
# --------------------------------------------------------------------------- #
def _normaliser(chemin: str | None) -> str:
    return (chemin or "").replace("\\", "/").strip("/")


def _cible() -> str:
    return f"{PARTAGE}/{DOSSIER}".casefold()


async def trouver_source(db) -> Any | None:
    """La Source SMB active déclarée sur le dossier de dépôt (ou sur un dossier qui le contient)."""
    from sqlalchemy import select

    from models.source import Source

    sources = (await db.execute(select(Source).where(Source.type == "smb", Source.actif.is_(True)))).scalars().all()
    cible = _cible()
    exacte = [s for s in sources if _normaliser(s.chemin_base).casefold() == cible]
    if exacte:
        return exacte[0]
    englobantes = [s for s in sources if _normaliser(s.chemin_base)
                   and cible.startswith(_normaliser(s.chemin_base).casefold() + "/")]
    if englobantes:
        return englobantes[0]
    # Une Source créée par l'écran couvre TOUT le serveur (pas de dossier de base) : celle du compte
    # svc-ged, que le contrat désigne (16/11/2026 : sans ce repli, la Source n'était jamais trouvée).
    serveur = [s for s in sources if not _normaliser(s.chemin_base)
               and (s.identifiant or "").strip().casefold() == COMPTE.casefold()]
    return serveur[0] if serveur else None


class AccesNas:
    """Lecture/écriture/suppression dans le dossier de dépôt, avec le compte de la Source."""

    def __init__(self, src: Any, secret: str | None) -> None:
        from services import smb_service

        self.smb = smb_service
        self.src = src
        self.secret = secret
        self.partage = PARTAGE
        self.base = DOSSIER

    def _args(self) -> tuple:
        return (self.src.identifiant, self.secret, self.src.domaine)

    def chemin(self, *morceaux: str) -> str:
        return posixpath.join(self.base, *morceaux)

    async def lister(self, relatif: str = "") -> list[dict]:
        return await self.smb.browse(self.src.hote, self.partage, self.chemin(relatif) if relatif else self.base,
                                     *self._args())

    async def lire(self, relatif: str) -> bytes:
        tmp = await self.smb.fetch_to_temp(self.src.hote, self.partage, self.chemin(relatif), *self._args())
        try:
            return Path(tmp).read_bytes()
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    async def ecrire(self, relatif: str, contenu: str) -> None:
        await self.smb.store_text(self.src.hote, self.partage, self.chemin(relatif), contenu, *self._args())

    async def supprimer(self, relatif: str) -> None:
        await self.smb.delete_file(self.src.hote, self.partage, self.chemin(relatif), *self._args())

    async def creer_dossier(self, relatif: str) -> None:
        await self.smb.ensure_dir(self.src.hote, self.partage, self.chemin(relatif), *self._args())


SANS_SOURCE = (f"Aucune Source SMB active sur « {PARTAGE}/{DOSSIER} » : la déclarer (Paramètres › Sources "
               "de fichiers, compte svc-ged).")


async def acces_nas(db) -> AccesNas | None:
    """L'accès au dossier de dépôt avec la Source trouvée ; None s'il n'y en a pas."""
    from services import crypto

    src = await trouver_source(db)
    if src is None:
        return None
    return AccesNas(src, crypto.decrypt(src.secret_chiffre) if src.secret_chiffre else None)


def _archiver(dossier_archives: Path, projet: str, brut: bytes) -> Path:
    """Garde une copie du manifeste traité côté Matothèque (le NAS n'en garde pas)."""
    d = dossier_archives / projet
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"manifeste-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.json"
    f.write_bytes(brut)
    return f


def _dossier_archives() -> Path:
    """Sur un volume MONTÉ (`storage/exports`) : `/app/storage` lui-même ne l'est pas en prod, une archive
    posée à côté disparaissait au redéploiement (16/11/2026)."""
    from config import get_settings
    return Path(get_settings().storage_exports) / "docs-cockpit"


# --------------------------------------------------------------------------- #
# Le relevé                                                                    #
# --------------------------------------------------------------------------- #
async def traiter_projet(db, nas: Any, projet_dossier: str, *, publier=None, archives: Path | None = None) -> dict:
    """Traite le dépôt d'UN projet (son `manifeste.json` doit être présent). Rend un bilan court."""
    from sqlalchemy import select

    from models.publieur import ProjetPublieur
    from services import publication_service, publieur_auth

    publier = publier or publication_service.publier_manifeste
    archives = archives or _dossier_archives()
    brut = await nas.lire(posixpath.join(projet_dossier, MANIFESTE))

    async def retirer(compte_rendu: dict, nom: str) -> None:
        # Compte rendu D'ABORD (le cockpit le trouve dès qu'il voit le manifeste parti), puis l'autre
        # compte rendu, périmé, et enfin le manifeste — seulement s'il n'a pas été remplacé entre-temps.
        await nas.ecrire(posixpath.join(projet_dossier, nom), json.dumps(compte_rendu, ensure_ascii=False, indent=2))
        autre = ERREUR if nom == RESULTAT else RESULTAT
        if any(e["nom"] == autre for e in await nas.lister(projet_dossier)):
            await nas.supprimer(posixpath.join(projet_dossier, autre))
        _archiver(archives, projet_dossier, brut)
        if await nas.lire(posixpath.join(projet_dossier, MANIFESTE)) == brut:
            await nas.supprimer(posixpath.join(projet_dossier, MANIFESTE))
        else:
            log.info("Docs cockpit : nouveau dépôt arrivé pendant le traitement, gardé pour le relevé suivant",
                     projet=projet_dossier)

    try:
        try:
            donnees = json.loads(brut.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Refus("manifeste_illisible", f"Le manifeste n'est pas un JSON UTF-8 valide ({exc}).") from exc
        m = valider(donnees, projet_dossier)
        if publieur_auth.est_projet_exclu(m["projet"]):
            raise Refus("projet_exclu", f"« {m['projet']} » relève de MIS/Geco : jamais publié dans BookStack.")
        projet = (await db.execute(select(ProjetPublieur).where(ProjetPublieur.nom == m["projet"]))).scalar_one_or_none()
        if projet is None or not projet.actif:
            raise Refus("projet_inconnu",
                        f"Le projet « {m['projet']} » n'est pas déclaré (ou est désactivé) dans la passerelle "
                        "de la Matothèque : Paramètres › Passerelle BookStack, avec ses livres autorisés.")
        try:
            r = await publier(db, projet, m["pages"], m["etagere"])
        except publication_service.PublicationRefusee as exc:
            if exc.statut == 403:
                raise Refus("livre_non_autorise", exc.message) from exc
            await nas.ecrire(posixpath.join(projet_dossier, ERREUR),
                             json.dumps(erreur_json(m["projet"], "bookstack_indisponible", exc.message, definitif=False),
                                        ensure_ascii=False, indent=2))
            return {"projet": projet_dossier, "statut": "en_attente", "message": exc.message}
    except Refus as exc:
        await retirer(erreur_json(projet_dossier, exc.code, exc.message, definitif=True), ERREUR)
        log.warning("Docs cockpit : dépôt refusé", projet=projet_dossier, code=exc.code, message=exc.message)
        return {"projet": projet_dossier, "statut": "refuse", "code": exc.code, "message": exc.message}
    if not projet.depot_cockpit:   # ses pages se corrigent désormais par une proposition
        projet.depot_cockpit = True
        await db.commit()
    await retirer(resultat_json(m, r), RESULTAT)
    return {"projet": projet_dossier, "statut": "publie", "creees": len(r["creees"]),
            "mises_a_jour": len(r["mises_a_jour"]), "inchangees": len(r["inchangees"]), "erreurs": len(r["erreurs"])}


async def relever(db, *, nas: Any = None, publier=None, archives: Path | None = None) -> dict:
    """Le relevé : chaque sous-dossier de projet qui contient un `manifeste.json` est traité."""
    if nas is None:
        nas = await acces_nas(db)
        if nas is None:
            return {"statut": "ignore", "message": SANS_SOURCE}
    try:
        dossiers = [e["nom"] for e in await nas.lister() if e["dossier"] and not e["nom"].startswith((".", "#", "@"))]
    except Exception as exc:  # noqa: BLE001 — NAS coupé, droits : on réessaie au relevé suivant
        log.warning("Docs cockpit : dossier de dépôt illisible", erreur=str(exc) or type(exc).__name__)
        return {"statut": "echec", "message": f"Dossier de dépôt illisible ({type(exc).__name__})."}
    bilans = []
    for d in sorted(dossiers):
        try:
            if not any(e["nom"] == MANIFESTE and not e["dossier"] for e in await nas.lister(d)):
                continue
            bilans.append(await traiter_projet(db, nas, d, publier=publier, archives=archives))
        except Exception as exc:  # noqa: BLE001 — un projet en panne n'arrête pas les autres
            log.error("Docs cockpit : traitement échoué", projet=d, erreur=str(exc) or type(exc).__name__)
            bilans.append({"projet": d, "statut": "echec", "message": str(exc) or type(exc).__name__})
    if bilans:
        log.info("Docs cockpit : relevé", depots=len(bilans),
                 publies=sum(b["statut"] == "publie" for b in bilans),
                 refuses=sum(b["statut"] == "refuse" for b in bilans))
    return {"statut": "termine", "depots": bilans}


# --------------------------------------------------------------------------- #
# Tâche du worker + planification                                              #
# --------------------------------------------------------------------------- #
from services import job_worker  # noqa: E402 — après les définitions : aucune dépendance circulaire


@job_worker.register(JOB)
async def _handler(ctx: job_worker.JobContext) -> dict:
    """Relève les dépôts du cockpit. Classe `io` (SMB + BookStack, jamais Ollama) : à toute heure."""
    from database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        return await relever(db)


async def planifier() -> str | None:
    """Enfile un relevé s'il n'y en a pas déjà un en file ou en cours (verrou : un seul process)."""
    from sqlalchemy import text

    from database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        if not (await db.execute(text("SELECT pg_try_advisory_xact_lock(hashtext('docs_cockpit'))"))).scalar():
            return None
        deja = (await db.execute(text(
            "SELECT 1 FROM jobs WHERE type = :t AND statut IN ('pending','running') LIMIT 1"), {"t": JOB})).scalar()
        if deja:
            await db.commit()
            return None
        job_id = await job_worker.enqueue(db, JOB, {"cible": "docs-applications"})
        await db.commit()
        return job_id


# --------------------------------------------------------------------------- #
# Proposer une modification (16/11/2026)                                       #
# --------------------------------------------------------------------------- #
# Une page publiée par le cockpit ne se corrige PAS dans BookStack (le dépôt suivant l'écraserait) : la
# source est le `.md` du projet. Depuis le lecteur Wiki, tout utilisateur PROPOSE une modification ;
# elle est déposée à côté du manifeste (`<projet>/propositions/…json`), avec son AUTEUR (session SSO).
# Le cockpit la montre (avant / après) et l'applique — ou la refuse — dans le projet.
async def depose_par_cockpit(db, projet: str) -> bool:
    """Ce projet a-t-il déjà été publié par un dépôt du cockpit ? (marqué en base par le relevé)"""
    from sqlalchemy import select

    from models.publieur import ProjetPublieur

    return bool((await db.execute(select(ProjetPublieur.depot_cockpit).where(
        ProjetPublieur.nom == projet))).scalar())


def nom_proposition(cle: str, quand: datetime) -> str:
    """`docs-guide-usage-20261116T153650Z.json` — lisible, unique à la seconde. PURE."""
    slug = re.sub(r"[^a-z0-9]+", "-", cle.casefold()).strip("-")[:80] or "page"
    return f"{slug}-{quand:%Y%m%dT%H%M%S}Z.json"


def proposition_json(*, projet: str, cle: str, livre: str, chapitre: str | None, titre: str, page_id: int,
                     page_url: str | None, hash_publie: str | None, avant: str, propose: str,
                     commentaire: str, auteur: dict, quand: datetime) -> dict:
    """La proposition, telle que le cockpit la lit. PURE."""
    return {
        "format": FORMAT_PROPOSITION, "projet": projet, "cle": cle, "livre": livre, "chapitre": chapitre,
        "titre": titre, "page_id": page_id, "page_url": page_url,
        # Empreinte du contenu publié au moment de la proposition : si le `.md` a changé depuis, le
        # cockpit sait que « avant » n'est plus le texte du projet (proposition à revoir, pas à appliquer).
        "hash_publie": hash_publie,
        "auteur": auteur, "propose_le": quand.isoformat(timespec="seconds"),
        "commentaire": commentaire, "markdown_avant": avant, "markdown_propose": propose,
    }


async def deposer_proposition(db, pub: Any, *, titre: str, page_url: str | None, avant: str, propose: str,
                              commentaire: str, auteur: dict, nas: Any = None) -> str:
    """Dépose la proposition dans `<projet>/propositions/`. Rend son chemin (relatif au dossier de dépôt).
    `ValueError` lisible si elle est vide, trop grande, ou si le NAS n'est pas joignable par une Source."""
    propose = propose.replace("\r\n", "\n")
    commentaire = (commentaire or "").strip()
    if propose.strip() == (avant or "").strip():
        raise ValueError("Aucune modification : le texte proposé est identique à la page.")
    if not propose.strip():
        raise ValueError("Le texte proposé est vide.")
    if len(propose.encode("utf-8")) > MAX_OCTETS_PAGE:
        raise ValueError("Le texte proposé dépasse 1 Mo.")
    if len(commentaire) > MAX_COMMENTAIRE:
        raise ValueError(f"Le commentaire dépasse {MAX_COMMENTAIRE} caractères.")
    if nas is None:
        nas = await acces_nas(db)
        if nas is None:
            raise ValueError(SANS_SOURCE)
    quand = datetime.now(timezone.utc)
    dossier = posixpath.join(pub.projet, PROPOSITIONS)
    chemin = posixpath.join(dossier, nom_proposition(pub.cle, quand))
    contenu = proposition_json(projet=pub.projet, cle=pub.cle, livre=pub.livre, chapitre=pub.chapitre, titre=titre,
                               page_id=pub.page_id, page_url=page_url, hash_publie=pub.contenu_hash, avant=avant,
                               propose=propose, commentaire=commentaire, auteur=auteur, quand=quand)
    await nas.creer_dossier(dossier)
    await nas.ecrire(chemin, json.dumps(contenu, ensure_ascii=False, indent=2))
    log.info("Docs cockpit : modification proposée", projet=pub.projet, cle=pub.cle,
             auteur=auteur.get("identifiant") or auteur.get("nom"))
    return chemin
