"""
Titre des épisodes (Rangement) — `Série - S01E01 - Titre.ext`.

Décisions de Thomas (15/11/2026) :
- les titres viennent de **son Plex** (réseau local, déjà en français) ;
- format **`Série - S01E01 - Titre.ext`** (celui que conseille Plex) ; les sous-titres et la fiche
  `.nfo` du même nom suivent ;
- un épisode sans titre connu reçoit quand même un nom propre : `Série - S01E01.ext`.

Ne fait que des PROPOSITIONS (`plan_propositions.nouveau_nom`) : rien n'est renommé sans validation, et
un lot de renommage s'annule comme un lot de rangement. Les fonctions de nommage sont PURES.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

#: Extensions d'une vidéo d'épisode.
VIDEOS = frozenset({"mkv", "mp4", "avi", "m4v", "mov", "wmv", "ts", "mpg", "mpeg", "webm"})
#: Fichiers qui accompagnent une vidéo et portent son nom (ils sont renommés avec elle).
COMPAGNONS = frozenset({"srt", "ass", "ssa", "sub", "idx", "vtt", "nfo"})

# « S01E02 », « s01e02 », « S04E13-E14 », « S04E13E14 ».
_CODE = re.compile(r"S(?P<s>\d{1,2})E(?P<e1>\d{1,3})(?:-?E(?P<e2>\d{1,3}))?", re.IGNORECASE)
# Titre que Plex met quand il n'en connaît pas : « Episode 3 », « Épisode 3 », « Épisode #1.1 » (vu en prod).
_TITRE_VIDE = re.compile(r"^\s*([ée]pisode)\s*#?\s*\d+(\.\d+)?\s*$", re.IGNORECASE)
_INTERDITS = re.compile(r'[*?"<>|]')
# Un titre déjà écrit dans le nom, après le code : « The Gentlemen S01E01 - Raffinement et agressivité.mkv ».
_TITRE_DEJA = re.compile(r"S\d{1,2}E\d{1,3}(?:-?E\d{1,3})?\s+-\s+(?P<titre>.+)$", re.IGNORECASE)


def titre_deja_la(nom: str) -> str | None:
    """Le titre qu'un nom porte déjà après « S01E01 - » (sans l'extension) ; None sinon."""
    m = _TITRE_DEJA.search(posixpath.splitext(nom)[0])
    return titre_utile(m.group("titre")) if m else None


@dataclass(frozen=True)
class Code:
    saison: int
    episodes: tuple[int, ...]

    def texte(self) -> str:
        s = f"S{self.saison:02d}E{self.episodes[0]:02d}"
        return s + (f"-E{self.episodes[-1]:02d}" if len(self.episodes) > 1 else "")


def code_de(nom: str) -> Code | None:
    """Le code d'épisode lu dans un nom de fichier ; None s'il n'y en a pas."""
    m = _CODE.search(nom)
    if m is None:
        return None
    e1 = int(m.group("e1"))
    e2 = int(m.group("e2")) if m.group("e2") else None
    return Code(int(m.group("s")), (e1, e2) if e2 and e2 > e1 else (e1,))


def titre_utile(titre: str | None) -> str | None:
    """Le titre, ou None s'il est vide ou n'est qu'un « Épisode 3 » de remplacement."""
    t = (titre or "").strip()
    return None if not t or _TITRE_VIDE.match(t) else t


def propre(texte: str) -> str:
    """Un morceau de nom de fichier sûr sur un partage SMB : « : » devient « - », « / » devient « - »,
    les caractères interdits par Windows disparaissent, pas de point ni d'espace en fin."""
    t = texte.replace(":", " -").replace("/", "-").replace("\\", "-")
    t = _INTERDITS.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t.rstrip(". ")


def nom_episode(serie: str, code: Code, titres: list[str], extension: str) -> str:
    """« Westworld - S01E01 - Le Labyrinthe.mkv » ; plusieurs épisodes dans un fichier : titres joints
    par « & » ; sans titre : « Westworld - S01E01.mkv »."""
    utiles = [propre(t) for t in titres if titre_utile(t)]
    base = f"{propre(serie)} - {code.texte()}"
    if utiles:
        base += " - " + " & ".join(dict.fromkeys(utiles))
    return base[:200].rstrip(". ") + (f".{extension}" if extension else "")


def extension(nom: str) -> str:
    return posixpath.splitext(nom)[1].lower().lstrip(".")


@dataclass(frozen=True)
class Renommage:
    chemin: str          # relatif à l'emplacement
    dossier: str
    nouveau: str
    taille: int
    raison: str
    par: str             # « plex » (titre trouvé) | « regle » (nom propre, sans titre)


def renommages_du_dossier(dossier: str, fichiers: dict[str, int], serie_dossier: str,
                          plex: dict[str, list[tuple[str, int, int, str]]]) -> tuple[list[Renommage], int]:
    """Les renommages d'UN dossier de saison (`Series/Arcane/S01`). PURE.

    `fichiers` : nom → taille ; `plex` : chemin relatif (forme `cle_chemin`) → [(série, saison, épisode,
    titre)] ; `serie_dossier` : nom du dossier de la série, faute de mieux. Rend (renommages, conflits) :
    un nom déjà pris dans le dossier (par un fichier qui ne part pas) n'est jamais écrasé ni suffixé."""
    sortie: list[Renommage] = []
    conflits = 0
    pris = {n.casefold() for n in fichiers}
    for nom in sorted(fichiers):
        if extension(nom) not in VIDEOS:
            continue
        chemin = f"{dossier}/{nom}"
        infos = plex.get(cle_chemin(chemin)) or []
        if infos:
            serie = infos[0][0] or serie_dossier
            code = Code(infos[0][1], tuple(sorted({i[2] for i in infos})))
            if len(code.episodes) > 2:   # Plex rattache 3 épisodes et plus au même fichier : on garde 1er-dernier
                code = Code(code.saison, (code.episodes[0], code.episodes[-1]))
            titres = [i[3] for i in sorted(infos, key=lambda i: i[2])]
            par = "plex" if any(titre_utile(t) for t in titres) else "regle"
        else:
            lu = code_de(nom)
            if lu is None:
                continue   # pas d'épisode reconnu : on ne devine pas
            # Inconnu de Plex : un titre déjà écrit dans le nom est GARDÉ (jamais rogné).
            deja = titre_deja_la(nom)
            serie, code, titres, par = serie_dossier, lu, [deja] if deja else [], "regle"
        nouveau = nom_episode(serie, code, titres, extension(nom))
        if nouveau == nom:
            continue
        lot = [(nom, nouveau)] + [(c, posixpath.splitext(nouveau)[0] + suffixe)
                                  for c, suffixe in compagnons(nom, list(fichiers)).items()]
        if any(n2.casefold() in pris and n2.casefold() != n1.casefold() for n1, n2 in lot):
            conflits += 1
            continue
        raison = "Titre Plex" if par == "plex" else "Nom propre (titre inconnu de Plex)"
        for n1, n2 in lot:
            pris.add(n2.casefold())
            sortie.append(Renommage(f"{dossier}/{n1}", dossier, n2, fichiers[n1], raison, par))
    return sortie, conflits


def cle_chemin(chemin: str) -> str:
    """Forme de comparaison d'un chemin (Plex et le NAS n'écrivent pas toujours pareil les accents)."""
    import unicodedata
    return unicodedata.normalize("NFC", chemin).casefold()


async def calculer(db, depot, emp, bibliotheques) -> dict:
    """Propositions de renommage des épisodes rangés (`<rubrique séries>/<Titre>/Sxx/`) d'un emplacement.

    Une décision humaine (validée, refusée, déjà renommée) est gardée tant que le nom proposé ne change
    pas ; les propositions encore ouvertes qui n'ont plus d'objet sont retirées."""
    from sqlalchemy import select

    from models.plan_classement import PlanNoeud, PlanProposition
    from services.rangement import plan, series
    from services.rangement.plex import relatif

    partage = plan.partage_de(emp)
    rubriques = {n.chemin.casefold(): n.chemin for n in (await db.execute(select(PlanNoeud).where(
        PlanNoeud.partage == partage, PlanNoeud.gabarit == series.GABARIT))).scalars().all() if "/" not in n.chemin}
    if not rubriques:
        return {"statut": "ignore", "message": "aucune rubrique de séries dans le plan de cet emplacement"}
    index: dict[str, list[tuple[str, int, int, str]]] = {}
    for b in bibliotheques:
        for e in b.episodes:
            rel = relatif(e.fichier, b.dossiers, rubriques)
            if rel:
                index.setdefault(cle_chemin(rel), []).append((e.serie, e.saison, e.episode, e.titre))

    voulus: list[Renommage] = []
    conflits = 0
    for rubrique in rubriques.values():
        for nom_serie, c in sorted((await depot.enfants(emp.id, rubrique)).items()):
            if not c.est_dossier or series.lire(nom_serie) is not None:
                continue   # un pack pas encore rangé : la règle des séries passe d'abord
            for nom_saison, c2 in sorted((await depot.enfants(emp.id, f"{rubrique}/{nom_serie}")).items()):
                n = series.saison_de_dossier(nom_saison) if c2.est_dossier else None
                if n is None or nom_saison != series.dossier_saison(n):
                    continue   # seulement les saisons déjà rangées (`S01`)
                dossier = f"{rubrique}/{nom_serie}/{nom_saison}"
                fichiers = {k: v.taille for k, v in (await depot.enfants(emp.id, dossier)).items() if not v.est_dossier}
                r, k = renommages_du_dossier(dossier, fichiers, nom_serie, index)
                voulus += r
                conflits += k

    existantes = {p.chemin: p for p in (await db.execute(select(PlanProposition).where(
        PlanProposition.emplacement_id == emp.id, PlanProposition.nouveau_nom.is_not(None)))).scalars().all()}
    compte = {"proposees": 0, "gardees": 0, "avec_titre": 0, "sans_titre": 0, "conflits": conflits, "retirees": 0}
    vus = set()
    for r in voulus:
        vus.add(r.chemin)
        p = existantes.get(r.chemin)
        if p is not None and p.nouveau_nom == r.nouveau and p.statut in ("validee", "refusee", "rangee"):
            compte["gardees"] += 1
            continue
        if p is None:
            p = PlanProposition(emplacement_id=emp.id, chemin=r.chemin)
            db.add(p)
        p.est_dossier, p.taille, p.destination, p.nouveau_nom, p.contenu = False, r.taille, r.dossier, r.nouveau, False
        p.noeud_id = p.regle_id = None
        p.par, p.raison, p.confiance, p.statut = r.par, r.raison, 1.0, "proposee"
        p.valide_par = p.valide_le = None
        compte["proposees"] += 1
        compte["avec_titre" if r.par == "plex" else "sans_titre"] += 1
    for chemin, p in existantes.items():
        if chemin not in vus and p.statut == "proposee":
            await db.delete(p)
            compte["retirees"] += 1
    await db.commit()
    return {"statut": "termine", **compte}


def compagnons(video: str, voisins: list[str]) -> dict[str, str]:
    """Les fichiers du même dossier qui portent le nom de la vidéo (`X.mkv` → `X.fr.srt`, `X.nfo`) :
    nom actuel → suffixe à garder (`.fr.srt`)."""
    tige = posixpath.splitext(video)[0]
    sortie: dict[str, str] = {}
    for v in voisins:
        if v == video or not v.startswith(tige + ".") or extension(v) not in COMPAGNONS:
            continue
        sortie[v] = v[len(tige):]
    return sortie
