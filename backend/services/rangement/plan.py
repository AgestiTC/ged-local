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


def partage_de(emp: Emplacement) -> str | None:
    """Le partage d'un emplacement du serveur : le dernier élément de sa racine. Postes : aucun."""
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


def destination(noeud: PlanNoeud, c: Candidat) -> str:
    """Le dossier cible : le nœud, plus son gabarit éventuel (`{annee}`)."""
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
        if e.id != emp.id and e.sur_serveur and contient(emp.racine, e.racine):
            relatif = posixpath.relpath(e.racine, emp.racine)
            noms.add(relatif.split("/")[0])
    return noms


async def candidats(depot: Depot, emp: Emplacement, noeuds_racine: set[str]) -> list[Candidat]:
    """Les éléments à placer : ce qui est à la racine sans être un nœud, et le contenu des nœuds de
    1er niveau. Les autres emplacements imbriqués (un autre NAS) ne sont jamais candidats."""
    ailleurs = await _racines_imbriquees(depot, emp)
    sortie: list[Candidat] = []
    for nom, connu in sorted((await depot.enfants(emp.id, "")).items()):
        if nom in ailleurs:
            continue
        if connu.est_dossier and nom in noeuds_racine:
            for nom2, c2 in sorted((await depot.enfants(emp.id, nom)).items()):
                sortie.append(await _candidat(depot, emp, chemin_enfant(nom, nom2), c2, nom))
        else:
            sortie.append(await _candidat(depot, emp, nom, connu, ""))
    return sortie


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
                   arret: Callable[[], bool] | None = None) -> dict:
    """Recalcule les propositions d'un emplacement. Règles d'abord ; l'IA (si fournie) pour le reste."""
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
        select(PlanProposition).where(PlanProposition.emplacement_id == emp.id))).scalars().all()}
    racine = {n.chemin for n in noeuds if "/" not in n.chemin}
    compte = {s: 0 for s in STATUTS} | {"gardees": 0, "ia": 0, "retirees": 0}
    #: L'IA a lâché une fois (injoignable, délai) : on ne l'attend plus pour les suivants. Sans ça, chaque
    #: élément attendait ~25 s ses nouvelles tentatives — 4 min pour 9 dossiers à l'essai du 13/11/2026.
    ia_hors_service: str | None = None
    vus: set[str] = set()
    for c in await candidats(depot, emp, racine):
        if arret is not None and arret():
            break
        vus.add(c.chemin)
        p = existantes.get(c.chemin)
        if p is not None and p.statut in ("validee", "refusee", "rangee") and p.taille == c.taille:
            compte["gardees"] += 1
            continue
        dest = noeud_id = regle_id = None
        par, raison, confiance = None, None, None
        regle = next((r for r in regles if correspond(r, c)), None)
        if regle is not None:
            n = par_id[regle.noeud_id]
            dest, noeud_id, regle_id, par = destination(n, c), n.id, regle.id, "regle"
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
                dest, noeud_id, par = destination(n, c), n.id, "ia"
                compte["ia"] += 1
        if dest is None:
            statut = "sans_place"
        elif dest == c.parent:
            statut = "en_place"
        else:
            statut = "proposee"
        if p is None:
            p = PlanProposition(emplacement_id=emp.id, chemin=c.chemin)
            db.add(p)
        p.est_dossier, p.taille, p.destination, p.noeud_id, p.regle_id = c.est_dossier, c.taille, dest, noeud_id, regle_id
        p.par, p.raison, p.confiance, p.statut = par, raison, confiance, statut
        p.valide_par = p.valide_le = None
        p.calcule_le = datetime.now(timezone.utc)
        compte[statut] += 1
    if arret is None or not arret():
        for chemin, p in existantes.items():   # disparus de la carte : la proposition n'a plus d'objet
            if chemin not in vus:
                await db.delete(p)
                compte["retirees"] += 1
    await db.commit()
    log.info("Plan de classement calculé", emplacement_id=emp.id, ia_hors_service=bool(ia_hors_service), **compte)
    return {"statut": "termine", **compte, "ia_hors_service": ia_hors_service}


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
    proposition.statut = statut
    proposition.valide_par = par
    proposition.valide_le = datetime.now(timezone.utc)
    await db.commit()
    return proposition
