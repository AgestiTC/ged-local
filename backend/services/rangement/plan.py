"""
Le plan de classement (module Rangement, étape 9) — « où devrait aller ce dossier ? ».

Conception validée : docs/conception-plan-classement.md (C1 à C10). Ce module ne déplace RIEN.

- **Les partages restent le 1er niveau** : un emplacement du serveur correspond au partage nommé par
  le dernier élément de sa racine (`/mnt/media` → `media`). Un emplacement sans nœuds n'a pas de plan.
- **L'unité placée est le grand dossier** : les éléments à la racine du partage qui ne sont pas des
  nœuds du plan, et ce que contient chaque nœud de 1er niveau. Un dossier part entier.
- **Règles explicites d'abord**, dans l'ordre de priorité ; **l'IA locale propose le reste** (usage
  `classement_plan`), choisie parmi les nœuds existants. Elle ne reçoit que des métadonnées.
- **Une décision humaine est gardée** tant que l'élément n'a pas changé de taille ; s'il a changé,
  la proposition est recalculée (la décision ne valait que pour ce qu'il était).
"""

import fnmatch
import html
import posixpath
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from models.plan_classement import PlanNoeud, PlanProposition, PlanRegle
from services.rangement import series
from services.rangement.carte import famille
from services.rangement.depot import Connu, Depot, Emplacement, chemin_enfant
from services.rangement.scan import contient

log = get_logger(__name__)

A_TRIER = "00-A-TRIER"
TYPES_REGLE = ("famille", "extension", "motif_nom", "motif_chemin")
STATUTS = ("proposee", "validee", "refusee", "en_place", "sans_place")
#: C6 (Thomas, 13/11/2026) : dans `media`, ces dossiers se rangent comme le reste — ce ne sont pas
#: des rubriques du plan.
A_RANGER_MEDIA = ("01.tmp-torrent", "01_Liste")
#: Descriptions de départ des rubriques connues de `media` : l'IA ne choisit bien que si elle sait ce
#: que contient chaque dossier (essai du 13/11/2026 : sans elles, toute vidéo partait dans « Films »).
#: Modifiables ensuite dans l'écran du plan.
DESCRIPTIONS_MEDIA = {
    "films": "Films de cinéma (longs métrages), un dossier par film.",
    "series": "Séries télévisées : un dossier par série, avec ses saisons et épisodes.",
    "dessins animes": "Dessins animés et films d'animation, y compris les longs métrages Disney ou Pixar.",
    "documentaires": "Documentaires (nature, histoire, science), films ou séries.",
    "spetacle": "Spectacles : humoristes, one-man-shows, concerts, théâtre.",
    "film_neveux": "Films choisis pour les enfants de la famille (les neveux).",
    "dvd": "Copies de DVD (images disque, dossiers VIDEO_TS).",
    "ebook": "Livres électroniques (epub, mobi, pdf de livres).",
}
APERCU_MAX = 8
#: Rubriques de `media` rangées par la règle des séries (`<Titre>/S01`), décision du 15/11/2026.
RUBRIQUES_SERIES = frozenset({"series"})


def partage_de(emp: Emplacement) -> str | None:
    """Le partage d'un emplacement du serveur : le dernier élément de sa racine (montage). Emplacement
    SMB : son champ `partage` — le vrai nom du partage, quel que soit le dossier déclaré. Postes : aucun."""
    if emp.est_smb:
        return emp.partage or None
    if not emp.sur_serveur:
        return None
    return posixpath.basename(emp.racine.rstrip("/")) or None


@dataclass
class Candidat:
    chemin: str
    nom: str
    est_dossier: bool
    taille: int
    parent: str
    famille: str | None = None
    extension: str | None = None
    annee: int | None = None
    apercu: list[str] = field(default_factory=list)
    #: Règle des séries : la destination est déjà connue (`Series/<Titre>/S01`), sans règle ni IA.
    serie_dest: str | None = None
    #: Déplacer le CONTENU du dossier (un pack d'épisodes vidé dans `S01`), pas le dossier lui-même.
    contenu: bool = False

    @property
    def lieu(self) -> str:
        """Là où l'élément « est » au sens du plan : son dossier, ou lui-même s'il est vidé."""
        return self.chemin if self.contenu else self.parent


def correspond(regle: PlanRegle, c: Candidat) -> bool:
    """La règle s'applique-t-elle à ce candidat ? Fonction PURE."""
    v = (regle.valeur or "").strip()
    if not v:
        return False
    if regle.type == "famille":
        return (c.famille or "").casefold() == v.casefold()
    if regle.type == "extension":
        extensions = {e.strip().lower().lstrip(".") for e in v.split(",") if e.strip()}
        return not c.est_dossier and (c.extension or "") in extensions
    if regle.type == "motif_nom":
        return fnmatch.fnmatchcase(c.nom.casefold(), v.casefold())
    if regle.type == "motif_chemin":
        return fnmatch.fnmatchcase(c.chemin.casefold(), v.casefold())
    return False


def destination(noeud: PlanNoeud, c: Candidat, titres: dict[str, str] | None = None) -> str:
    """Le dossier cible : le nœud, plus son gabarit éventuel (`{annee}`, ou la règle des séries
    `{serie}` → `<nœud>/<Titre>/S01`, le titre rattaché à un dossier de série existant)."""
    if noeud.gabarit == series.GABARIT:
        ep = series.lire(c.nom)
        if ep is not None:
            return f"{noeud.chemin}/{series.dossier_serie(ep.titre, titres or {})}/{series.dossier_saison(ep.saison)}"
        return noeud.chemin
    if noeud.gabarit and "{annee}" in noeud.gabarit and c.annee:
        return f"{noeud.chemin}/{noeud.gabarit.replace('{annee}', str(c.annee))}"
    return noeud.chemin


# --------------------------------------------------------------------------- #
# Les candidats : les grands dossiers de la carte                              #
# --------------------------------------------------------------------------- #
async def _candidat(depot: Depot, emp: Emplacement, chemin: str, connu: Connu, parent: str) -> Candidat:
    c = Candidat(chemin=chemin, nom=connu.nom, est_dossier=connu.est_dossier, parent=parent,
                 taille=(connu.totaux[0] if connu.totaux else 0) if connu.est_dossier else connu.taille)
    if connu.mtime:
        c.annee = datetime.fromtimestamp(connu.mtime, tz=timezone.utc).year
    if connu.est_dossier:
        par_famille: dict[str, int] = {}
        for ext, _nb, octets in await depot.repartition_types(emp.id, chemin):
            par_famille[famille(ext)] = par_famille.get(famille(ext), 0) + octets
        if par_famille:
            c.famille = max(par_famille.items(), key=lambda x: x[1])[0]
        enfants, _total = await depot.enfants_tries(emp.id, chemin, APERCU_MAX)
        c.apercu = [e.nom for e in enfants]
    else:
        c.extension = posixpath.splitext(connu.nom)[1].lower().lstrip(".") or None
        c.famille = famille(c.extension)
    return c


async def _racines_imbriquees(depot: Depot, emp: Emplacement) -> set[str]:
    """Noms, à la racine de `emp`, qui sont eux-mêmes un autre emplacement (ex. `nas-media`)."""
    noms = set()
    for e in await depot.emplacements():
        meme_mode = (e.sur_serveur and emp.sur_serveur) or (e.est_smb and emp.est_smb)
        if e.id == emp.id or not meme_mode or e.racine == emp.racine:
            continue
        if emp.est_smb:  # URI : `contient` (commonpath) réduirait « smb:// » à « smb:/ »
            prefixe = emp.racine.rstrip("/") + "/"
            if not e.racine.casefold().startswith(prefixe.casefold()):
                continue
            relatif = e.racine[len(prefixe):]
        elif contient(emp.racine, e.racine):
            relatif = posixpath.relpath(e.racine, emp.racine)
        else:
            continue
        noms.add(relatif.split("/")[0])
    return noms


@dataclass
class UniteSerie:
    chemin: str
    connu: Connu
    parent: str
    dest: str | None       # None : pas d'épisode reconnu, l'élément suit les règles et l'IA
    contenu: bool


def _vide(connu: Connu) -> bool:
    return connu.est_dossier and connu.totaux is not None and connu.totaux[1] == 0 and connu.totaux[2] == 0


async def titres_existants(depot: Depot, emp: Emplacement, racine: str) -> dict[str, str]:
    """Clé → nom des dossiers de série déjà présents sous `racine` (ceux qui ne sont pas des packs)."""
    return {series.cle(n): n for n, c in (await depot.enfants(emp.id, racine)).items()
            if c.est_dossier and series.lire(n) is None}


async def unites_series(depot: Depot, emp: Emplacement, racine: str) -> list[UniteSerie]:
    """Ce que la règle des séries range sous le nœud `racine` (ex. `Series`) :

    - à sa racine, un pack ou un épisode (`Arcane.S01…`) → `racine/<Titre>/S01` (un pack est vidé) ;
    - dans un dossier de série (`Arcane/`), un pack (`Arcane.S02…`), un épisode isolé ou une saison mal
      nommée (`Saison 2`) → `Arcane/S02` ; un `S01` déjà là est en place ;
    - le reste (`22.11.63/1`, `Livre 1`, une intégrale) n'est pas touché ; un fichier isolé sans épisode
      reconnu suit les règles et l'IA (`dest` None). Un dossier vide n'est jamais proposé.
    """
    sortie: list[UniteSerie] = []
    enfants = await depot.enfants(emp.id, racine)
    titres = {series.cle(n): n for n, c in enfants.items() if c.est_dossier and series.lire(n) is None}
    for nom, connu in sorted(enfants.items()):
        chemin = chemin_enfant(racine, nom)
        ep = series.lire(nom)
        if ep is not None:
            if not _vide(connu):
                dest = f"{racine}/{series.dossier_serie(ep.titre, titres)}/{series.dossier_saison(ep.saison)}"
                sortie.append(UniteSerie(chemin, connu, racine, dest, connu.est_dossier))
            continue
        if not connu.est_dossier:
            sortie.append(UniteSerie(chemin, connu, racine, None, False))
            continue
        for nom2, c2 in sorted((await depot.enfants(emp.id, chemin)).items()):
            if _vide(c2):
                continue
            n = series.saison_de_dossier(nom2) if c2.est_dossier else None
            if n is None:
                ep2 = series.lire(nom2)
                if ep2 is None:
                    continue   # ambigu : pas touché
                n = ep2.saison
            sortie.append(UniteSerie(chemin_enfant(chemin, nom2), c2, chemin,
                                     f"{chemin}/{series.dossier_saison(n)}", c2.est_dossier))
    return sortie


@dataclass
class RenommageSerie:
    chemin: str        # `Series/Quantum.Leap.1989.iNTEGRALE…`
    rubrique: str      # `Series`
    nouveau: str       # `Quantum Leap 1989`
    taille: int


async def dossiers_series_a_renommer(depot: Depot, emp: Emplacement,
                                     racines_series: set[str] | frozenset[str]) -> list[RenommageSerie]:
    """Les dossiers de série au nom « technique » (16/11/2026) : `Series/Quantum.Leap.1989.iNTEGRALE…`
    → `Quantum Leap 1989`. Un nom propre déjà pris par un voisin (casse, accents et ponctuation ignorés)
    n'est jamais proposé : ce serait une fusion, pas un renommage."""
    sortie: list[RenommageSerie] = []
    for rubrique in sorted(racines_series):
        enfants = await depot.enfants(emp.id, rubrique)
        for nom, connu in sorted(enfants.items()):
            if not connu.est_dossier or _vide(connu) or series.lire(nom) is not None:
                continue
            propre = series.nom_propre_serie(nom)
            if propre is None or any(series.cle(n) == series.cle(propre) for n in enfants if n != nom):
                continue
            sortie.append(RenommageSerie(chemin_enfant(rubrique, nom), rubrique, propre,
                                         connu.totaux[0] if connu.totaux else 0))
    return sortie


async def _en_attente_de_renommage(db: AsyncSession, emp: Emplacement) -> set[str]:
    """Les dossiers de série dont le renommage n'est pas refusé : leurs packs attendent le nouveau nom
    (sinon ils seraient vidés dans l'ancien, puis le renommage échouerait sur un chemin disparu)."""
    return set((await db.execute(select(PlanProposition.chemin).where(
        PlanProposition.emplacement_id == emp.id, PlanProposition.est_dossier.is_(True),
        PlanProposition.nouveau_nom.is_not(None), PlanProposition.statut != "refusee"))).scalars().all())


async def candidats(depot: Depot, emp: Emplacement, noeuds_racine: set[str],
                    racines_series: set[str] | frozenset[str] = frozenset()) -> list[Candidat]:
    """Les éléments à placer : ce qui est à la racine sans être un nœud, et le contenu des nœuds de
    1er niveau. Les autres emplacements imbriqués (un autre NAS) ne sont jamais candidats. Sous un nœud
    rangé par la règle des séries (`racines_series`), ce sont les packs et épisodes (`unites_series`)."""
    ailleurs = await _racines_imbriquees(depot, emp)
    sortie: list[Candidat] = []
    for nom, connu in sorted((await depot.enfants(emp.id, "")).items()):
        if nom in ailleurs:
            continue
        if connu.est_dossier and nom in racines_series:
            for u in await unites_series(depot, emp, nom):
                c = await _candidat(depot, emp, u.chemin, u.connu, u.parent)
                c.serie_dest, c.contenu = u.dest, u.contenu
                sortie.append(c)
        elif connu.est_dossier and nom in noeuds_racine:
            for nom2, c2 in sorted((await depot.enfants(emp.id, nom)).items()):
                sortie.append(await _candidat(depot, emp, chemin_enfant(nom, nom2), c2, nom))
        else:
            sortie.append(await _candidat(depot, emp, nom, connu, ""))
    return sortie


async def chemins_candidats(depot: Depot, emp: Emplacement, noeuds_racine: set[str],
                            racines_series: set[str] | frozenset[str] = frozenset()) -> set[str]:
    """Les chemins de `candidats()`, sans rien calculer d'autre (ni aperçu, ni famille) : de quoi
    savoir vite, après un scan, si un élément nouveau attend une proposition (étape 11)."""
    ailleurs = await _racines_imbriquees(depot, emp)
    sortie: set[str] = set()
    for nom, connu in (await depot.enfants(emp.id, "")).items():
        if nom in ailleurs:
            continue
        if connu.est_dossier and nom in racines_series:
            sortie.update(u.chemin for u in await unites_series(depot, emp, nom))
        elif connu.est_dossier and nom in noeuds_racine:
            sortie.update(chemin_enfant(nom, nom2) for nom2 in (await depot.enfants(emp.id, nom)))
        else:
            sortie.add(nom)
    return sortie


async def nouveaux_elements(db: AsyncSession, depot: Depot, emp: Emplacement) -> list[str]:
    """Éléments à placer qui n'ont encore AUCUNE proposition (arrivés depuis le dernier calcul).
    Emplacement sans plan : aucun."""
    partage = partage_de(emp)
    if not partage:
        return []
    noeuds = (await db.execute(select(PlanNoeud).where(PlanNoeud.partage == partage))).scalars().all()
    if not noeuds:
        return []
    connus = set((await db.execute(select(PlanProposition.chemin).where(
        PlanProposition.emplacement_id == emp.id))).scalars().all())
    racine, racines_series = _racines(noeuds)
    attente = await _en_attente_de_renommage(db, emp)
    return sorted(c for c in await chemins_candidats(depot, emp, racine, racines_series) - connus
                  if posixpath.dirname(c) not in attente)


def _racines(noeuds) -> tuple[set[str], set[str]]:
    """(nœuds de 1er niveau, ceux d'entre eux rangés par la règle des séries)."""
    racine = {n.chemin for n in noeuds if "/" not in n.chemin}
    return racine, {n.chemin for n in noeuds if "/" not in n.chemin and n.gabarit == series.GABARIT}


# --------------------------------------------------------------------------- #
# Modèle de départ                                                             #
# --------------------------------------------------------------------------- #
async def charger_modele_media(db: AsyncSession, depot: Depot, emp: Emplacement) -> dict:
    """Modèle de départ de `media` (C5, C6) : ses dossiers de 1er niveau deviennent des nœuds
    VERROUILLÉS (Plex les lit par leur nom), plus `00-A-TRIER` ; trois règles de départ. Idempotent :
    ce qui existe déjà n'est pas recréé."""
    partage = partage_de(emp)
    if partage is None:
        raise ValueError("Seul un emplacement du serveur a un plan de classement.")
    existants = {n.chemin: n for n in (await db.execute(
        select(PlanNoeud).where(PlanNoeud.partage == partage))).scalars().all()}
    ailleurs = await _racines_imbriquees(depot, emp)
    crees = 0

    def noeud(nom: str, verrouille: bool, description: str | None) -> PlanNoeud:
        nonlocal crees
        if nom in existants:
            return existants[nom]
        n = PlanNoeud(partage=partage, nom=nom, chemin=nom, verrouille=verrouille, origine="modele",
                      description=description)
        db.add(n)
        existants[nom] = n
        crees += 1
        return n

    noeud(A_TRIER, False, "Ce qui n'a pas encore sa place.")
    for nom, connu in sorted((await depot.enfants(emp.id, "")).items()):
        if connu.est_dossier and nom not in ailleurs and nom not in A_RANGER_MEDIA and not nom.startswith("."):
            n = noeud(nom, True, DESCRIPTIONS_MEDIA.get(nom.casefold()))
            if n.description is None and nom.casefold() in DESCRIPTIONS_MEDIA:   # modèle rechargé
                n.description = DESCRIPTIONS_MEDIA[nom.casefold()]
            if nom.casefold() in RUBRIQUES_SERIES and not n.gabarit:   # règle de nommage (15/11/2026)
                n.gabarit = series.GABARIT
    await db.flush()

    regles_crees = 0
    deja = {(r.type, r.valeur) for r in (await db.execute(select(PlanRegle))).scalars().all()}
    depart = [
        ("motif_nom", "*[sS][0-9][0-9][eE][0-9][0-9]*", "Series", 10, "Un épisode (S01E02) va dans les séries."),
        ("extension", "epub,mobi,azw3,cbz,cbr", "Ebook", 20, "Les livres électroniques."),
        ("famille", "Logiciels", A_TRIER, 90, "Un logiciel n'a rien à faire dans la médiathèque."),
    ]
    for type_, valeur, cible, priorite, description in depart:
        n = existants.get(cible)
        if n is None or (type_, valeur) in deja:
            continue
        db.add(PlanRegle(priorite=priorite, type=type_, valeur=valeur, noeud_id=n.id, active=True,
                         origine="modele", description=description,
                         valide_par="conception validée (13/11/2026)", valide_le=datetime.now(timezone.utc)))
        regles_crees += 1
    await db.commit()
    return {"partage": partage, "noeuds_crees": crees, "regles_creees": regles_crees}


# --------------------------------------------------------------------------- #
# L'IA locale : propose parmi les nœuds existants                              #
# --------------------------------------------------------------------------- #
ProposeurIA = Callable[[Candidat, list[PlanNoeud]], Awaitable[tuple[str | None, str, float]]]


def _taille_lisible(octets: int) -> str:
    v, u = float(octets), 0
    unites = ("o", "Ko", "Mo", "Go", "To")
    while v >= 1024 and u < len(unites) - 1:
        v /= 1024
        u += 1
    return f"{v:.1f} {unites[u]}"


async def proposer_par_ia(c: Candidat, noeuds: list[PlanNoeud]) -> tuple[str | None, str, float]:
    """(chemin du nœud, raison, confiance). L'IA ne reçoit que des métadonnées, jamais le contenu."""
    from services import runtime_config
    from services.ollama_service import OllamaService
    from utils.json_ia import lire_objet

    liste = "\n".join(f"- {n.chemin}" + (f" : {n.description}" if n.description else "") for n in noeuds)
    prompt = (
        "Tu ranges le NAS d'une famille. Voici les dossiers cibles possibles (le plan de classement) :\n"
        f"{liste}\n\nÉlément à placer :\n"
        f"- nom : {c.nom}\n- chemin actuel : {c.chemin}\n"
        f"- {'dossier' if c.est_dossier else 'fichier'} de {_taille_lisible(c.taille)}\n"
        f"- contenu dominant : {c.famille or 'inconnu'}\n"
        + (f"- exemples de contenu : {', '.join(c.apercu)}\n" if c.apercu else "")
        # Sans cette ligne, l'IA déplaçait « Le Roi Lion » de Dessins Animes vers Films (essai du 13/11).
        + (f"- il est DÉJÀ rangé dans « {c.parent} » : garde ce dossier, sauf s'il y est clairement mal placé.\n"
           if c.parent else "- il traîne à la racine du partage : il n'est rangé nulle part.\n")
        + "\nChoisis LE dossier cible le plus adapté, en recopiant exactement un chemin de la liste. "
        f"Si rien ne convient, réponds \"{A_TRIER}\". Réponds UNIQUEMENT en JSON : "
        '{"destination": "<chemin>", "raison": "<une phrase>", "confiance": <nombre entre 0 et 1>}'
    )
    texte = await OllamaService().generate(prompt, model=runtime_config.model_for("classement_plan"), format="json")
    donnees = lire_objet(texte, strict=False) or {}
    dest = str(donnees.get("destination") or "").strip()
    # Le modèle recopie parfois toute la ligne de la liste (« Films : Films de cinéma… ») : le chemin seul.
    dest = dest.lstrip("-• ").split(" : ")[0].strip().strip("/")
    if c.parent and (dest == c.chemin or dest.startswith(c.parent + "/")):
        dest = c.parent   # l'IA a désigné l'élément lui-même ou un chemin sous son dossier : il y reste
    if dest not in {n.chemin for n in noeuds}:
        return None, f"réponse de l'IA hors du plan : « {dest[:80]} »", 0.0
    try:
        confiance = max(0.0, min(1.0, float(donnees.get("confiance") or 0)))
    except (TypeError, ValueError):
        confiance = 0.0
    return dest, html.unescape(str(donnees.get("raison") or ""))[:300], confiance   # « L&#39;élément » vu à l'essai


# --------------------------------------------------------------------------- #
# Calcul des propositions                                                      #
# --------------------------------------------------------------------------- #
async def calculer(db: AsyncSession, depot: Depot, emp: Emplacement, *, ia: ProposeurIA | None = None,
                   arret: Callable[[], bool] | None = None, nouveaux_seulement: bool = False) -> dict:
    """Recalcule les propositions d'un emplacement. Règles d'abord ; l'IA (si fournie) pour le reste.
    `nouveaux_seulement` (après un scan, étape 11) : ne traite que les éléments sans proposition, et ne
    retire rien — l'IA n'est pas réinterrogée sur ce qu'elle a déjà proposé."""
    partage = partage_de(emp)
    noeuds = list((await db.execute(select(PlanNoeud).where(PlanNoeud.partage == partage))).scalars().all()) \
        if partage else []
    if not noeuds:
        return {"statut": "ignore", "message": "aucun plan de classement pour ce partage"}
    par_id = {n.id: n for n in noeuds}
    regles = [r for r in (await db.execute(select(PlanRegle).where(PlanRegle.active.is_(True))
                                           .order_by(PlanRegle.priorite, PlanRegle.id))).scalars().all()
              if r.noeud_id in par_id]
    existantes = {p.chemin: p for p in (await db.execute(
        select(PlanProposition).where(PlanProposition.emplacement_id == emp.id,
                                      PlanProposition.nouveau_nom.is_(None)))).scalars().all()}
    racine, racines_series = _racines(noeuds)
    titres: dict[str, dict[str, str]] = {}   # nœud séries → ses dossiers de série existants

    async def titres_de(n: PlanNoeud) -> dict[str, str]:
        if n.chemin not in titres:
            titres[n.chemin] = await titres_existants(depot, emp, n.chemin)
        return titres[n.chemin]

    noeud_series = {n.chemin: n for n in noeuds if n.chemin in racines_series}
    compte = {s: 0 for s in STATUTS} | {"gardees": 0, "ia": 0, "retirees": 0, "renommages_series": 0,
                                        "attente_renommage": 0}
    #: L'IA a lâché une fois (injoignable, délai) : on ne l'attend plus pour les suivants. Sans ça, chaque
    #: élément attendait ~25 s ses nouvelles tentatives — 4 min pour 9 dossiers à l'essai du 13/11/2026.
    ia_hors_service: str | None = None
    attente = await _renommer_dossiers_series(db, depot, emp, noeud_series, compte, nouveaux_seulement)
    vus: set[str] = set()
    for c in await candidats(depot, emp, racine, racines_series):
        if arret is not None and arret():
            break
        if c.parent in attente:
            # Son dossier de série va être renommé : le pack attend le nouveau nom (il sera proposé
            # au calcul qui suit le rangement). Une proposition ouverte vers l'ancien nom est retirée.
            compte["attente_renommage"] += 1
            continue
        vus.add(c.chemin)
        p = existantes.get(c.chemin)
        if nouveaux_seulement and p is not None:
            continue
        if p is not None and p.statut in ("validee", "refusee", "rangee") and p.taille == c.taille:
            compte["gardees"] += 1
            continue
        dest = noeud_id = regle_id = None
        par, raison, confiance = None, None, None
        regle = None if c.serie_dest else next((r for r in regles if correspond(r, c)), None)
        if c.serie_dest:
            n = noeud_series[c.serie_dest.split("/")[0]]
            dest, noeud_id, par, confiance = c.serie_dest, n.id, "regle", 1.0
            raison = f"Règle des séries : {c.serie_dest.split('/', 1)[1]}" + (
                " (le pack est vidé dans la saison)" if c.contenu else "")
        elif regle is not None:
            n = par_id[regle.noeud_id]
            dest, noeud_id, regle_id, par = destination(n, c, await titres_de(n)), n.id, regle.id, "regle"
            raison = regle.description or f"règle « {regle.type} = {regle.valeur} »"
            confiance = 1.0
        elif ia is not None and ia_hors_service:
            raison = ia_hors_service
        elif ia is not None:
            try:
                chemin_ia, raison, confiance = await ia(c, noeuds)
            except Exception as exc:  # noqa: BLE001 — une IA indisponible laisse l'élément sans place
                log.warning("Plan de classement : IA indisponible, règles seules pour la suite",
                            chemin=c.chemin, erreur=str(exc))
                ia_hors_service = f"IA indisponible pendant le calcul ({type(exc).__name__}) : à relancer"
                chemin_ia, raison, confiance = None, ia_hors_service, None
            if chemin_ia is not None:
                n = next(x for x in noeuds if x.chemin == chemin_ia)
                dest, noeud_id, par = destination(n, c, await titres_de(n)), n.id, "ia"
                compte["ia"] += 1
        # Un pack ou un épisode (dossier) envoyé vers une saison est VIDÉ dedans (ses fichiers gardent leur nom).
        if dest is not None and not c.contenu and c.est_dossier and noeud_id in par_id \
                and par_id[noeud_id].gabarit == series.GABARIT and series.lire(c.nom) is not None:
            c.contenu = True
        if dest is None:
            statut = "sans_place"
        elif dest == c.lieu:
            statut = "en_place"
        else:
            statut = "proposee"
        if p is None:
            p = PlanProposition(emplacement_id=emp.id, chemin=c.chemin)
            db.add(p)
        p.est_dossier, p.taille, p.destination, p.noeud_id, p.regle_id = c.est_dossier, c.taille, dest, noeud_id, regle_id
        p.par, p.raison, p.confiance, p.statut = par, raison, confiance, statut
        p.contenu = c.contenu
        p.valide_par = p.valide_le = None
        p.calcule_le = datetime.now(timezone.utc)
        compte[statut] += 1
    if not nouveaux_seulement and (arret is None or not arret()):
        for chemin, p in existantes.items():   # disparus de la carte : la proposition n'a plus d'objet
            if chemin not in vus and not p.nouveau_nom:   # un renommage d'épisode a son propre calcul
                await db.delete(p)
                compte["retirees"] += 1
    await db.commit()
    log.info("Plan de classement calculé", emplacement_id=emp.id, ia_hors_service=bool(ia_hors_service), **compte)
    return {"statut": "termine", **compte, "ia_hors_service": ia_hors_service}


async def _renommer_dossiers_series(db: AsyncSession, depot: Depot, emp: Emplacement,
                                    noeud_series: dict[str, PlanNoeud], compte: dict,
                                    nouveaux_seulement: bool) -> set[str]:
    """Propose le renommage des dossiers de série au nom technique (un renommage SUR PLACE, comme un
    titre d'épisode : `nouveau_nom`, destination = la rubrique). Une décision humaine est gardée tant
    que le nom proposé ne change pas. Rend les dossiers dont le renommage n'est pas refusé."""
    voulus = await dossiers_series_a_renommer(depot, emp, set(noeud_series))
    existantes = {p.chemin: p for p in (await db.execute(select(PlanProposition).where(
        PlanProposition.emplacement_id == emp.id, PlanProposition.est_dossier.is_(True),
        PlanProposition.nouveau_nom.is_not(None)))).scalars().all()}
    attente: set[str] = set()
    for r in voulus:
        p = existantes.get(r.chemin)
        garder = p is not None and (nouveaux_seulement or (
            p.nouveau_nom == r.nouveau and p.statut in ("validee", "refusee", "rangee")))
        if not garder:
            if p is None:
                p = PlanProposition(emplacement_id=emp.id, chemin=r.chemin)
                db.add(p)
            p.est_dossier, p.taille, p.destination, p.nouveau_nom, p.contenu = True, r.taille, r.rubrique, r.nouveau, False
            p.noeud_id, p.regle_id = noeud_series[r.rubrique].id, None
            p.par, p.confiance, p.statut = "regle", 1.0, "proposee"
            p.raison = (f"Règle des séries : le dossier porte un nom de téléchargement, il devient « {r.nouveau} ». "
                        "Ses saisons seront proposées après le renommage.")
            p.valide_par = p.valide_le = None
            p.calcule_le = datetime.now(timezone.utc)
            compte["renommages_series"] += 1
        if p.statut != "refusee":
            attente.add(r.chemin)
    if not nouveaux_seulement:
        chemins = {r.chemin for r in voulus}
        for chemin, p in existantes.items():
            if chemin not in chemins and p.statut == "proposee":
                await db.delete(p)
                compte["retirees"] += 1
    await db.flush()
    return attente


async def decider(db: AsyncSession, proposition: PlanProposition, statut: str, par: str | None,
                  destination_corrigee: str | None = None) -> PlanProposition:
    """Valider, refuser ou corriger (= valider vers un autre nœud) une proposition."""
    if statut not in ("validee", "refusee"):
        raise ValueError("statut attendu : validee ou refusee")
    if destination_corrigee is not None:
        emp_partage = (await db.execute(select(PlanNoeud.partage).where(
            PlanNoeud.id == proposition.noeud_id))).scalar() if proposition.noeud_id else None
        q = select(PlanNoeud).where(PlanNoeud.chemin == destination_corrigee)
        if emp_partage:
            q = q.where(PlanNoeud.partage == emp_partage)
        n = (await db.execute(q)).scalars().first()
        if n is None:
            raise ValueError(f"« {destination_corrigee} » n'est pas un dossier du plan.")
        proposition.destination, proposition.noeud_id = n.chemin, n.id
        proposition.par, proposition.raison = "humain", "corrigé à la main"
        proposition.contenu = False   # corrigé vers une rubrique : l'élément part entier
    proposition.statut = statut
    proposition.valide_par = par
    proposition.valide_le = datetime.now(timezone.utc)
    await db.commit()
    return proposition
