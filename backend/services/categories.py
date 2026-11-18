"""
Liste fermée des catégories de documents (plan prompts + RAG, étape A3 — validée par Thomas le 18/11/2026).
==========================================================================================================
Avant : l'enrichissement inventait ses catégories — 1 142 valeurs pour 78 139 fiches au 18/11/2026
(`livre audio` / `livre_audio` / `livre-audio`, `image` / `photo` / `photographie`…), et le filtre par
catégorie de la GED en était émietté. Désormais :

  - le prompt `enrichissement` donne la liste (`LISTE`) ;
  - toute catégorie lue (réponse de l'IA, fiche existante) est **ramenée** à la liste par `ramener()` :
    forme exacte (casse et accents ignorés), sinon règles de correspondance (`REGLES`), sinon « autre » ;
  - une catégorie **imposée par une règle de classement** (Paramètres › Sources & indexation) reste
    valide telle quelle : c'est un choix de l'utilisateur, pas une invention de l'IA ;
  - le regroupement des fiches existantes se **simule** d'abord, garde l'ancienne valeur
    (`categorie_origine`) pour revenir en arrière, et ne touche jamais une catégorie corrigée à la main
    (`categorie_manuelle`).

Correspondances mesurées sur la production du 18/11/2026 : 92,4 % des fiches tombent dans une des 24
catégories ; le reste est surtout « document » (2 948 fiches), trop vague, qui devient « autre ».
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from models.metadata import MetadonneeIA

log = get_logger(__name__)

AUTRE = "autre"
# Ordre = du plus fréquent au moins fréquent (relevé du 18/11/2026) ; « autre » en dernier.
LISTE: tuple[str, ...] = (
    "contrat", "musique", "présentation", "livre", "image", "documentation technique", "rapport",
    "facture", "correspondance", "administratif", "note", "candidature", "audio", "formation",
    "livre audio", "informatique", "finances", "publication", "juridique", "vidéo", "projet", "recette",
    "santé", "immobilier", AUTRE,
)


def cle(texte: str) -> str:
    """Forme de comparaison : minuscules, sans accents, `_ - '` remplacés par des espaces. PURE."""
    s = unicodedata.normalize("NFKD", (texte or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[_\-'’]+", " ", s)).strip()


# (catégorie de la liste, mots cherchés dans la forme de comparaison). La PREMIÈRE règle qui correspond
# gagne : l'ordre compte (« livre audio » avant « audio » et « livre », « compte rendu » avant « compte »).
# « mot* » = début de mot ; « mot » = mot entier.
REGLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("candidature", ("candidature*", "cv", "curriculum*", "motivation")),
    ("livre audio", ("livre audio", "livres audio", "audiobook*")),
    ("image", ("album photo*", "image*", "photo*", "illustration*", "dessin*", "graphique*", "visuel*",
               "art", "icone*", "logo*", "capture*")),
    ("musique", ("musique*", "musical*", "album*", "piste*", "chanson*", "morceau*")),
    ("audio", ("audio", "sonore*", "son", "auditif*", "podcast*", "enregistrement*")),
    # « multimédia » : trop vague (audio, image ou vidéo) → « autre » (décision de Thomas, 18/11/2026).
    ("vidéo", ("video*", "film*", "serie*", "episode*")),
    ("livre", ("livre*", "roman*", "policier", "ouvrage*", "litterai*", "biographi*", "bande dessinee",
               "poesie", "conte", "contes")),   # pas « conte* » : il prenait « contenu », « contexte »
    ("contrat", ("contrat*", "avenant*", "bail", "convention*")),
    ("rapport", ("compte rendu", "comptes rendus", "proces verbal")),
    ("facture", ("facture*", "devis", "bon de commande")),
    ("finances", ("financ*", "impot*", "fiscal*", "quittance*", "compte", "comptes", "bancaire*", "banque*",
                  "releve*", "paie", "salaire*", "budget*", "comptab*")),
    ("juridique", ("juridique*", "reglement*", "decret*", "loi", "legal*", "jugement*", "licence*", "statuts",
                   "directive*", "politique")),
    ("administratif", ("administrati*", "attestation*", "certificat*", "declaration*", "officiel*",
                       "formulaire*", "avis", "identite", "permis", "diplome*", "procedure*", "decision*")),
    ("correspondance", ("correspondance*", "lettre*", "courrier*", "plis", "courriel*", "email*", "mail*",
                        "communication*", "message*")),
    ("santé", ("sante", "medica*", "ordonnance*", "mutuelle*", "soin*")),
    ("rapport", ("rapport*", "bilan*", "audit*", "etude*", "analyse*", "document scientifique", "conference*")),
    ("présentation", ("presentation*", "diaporama*", "slide*")),
    ("note", ("note*", "memo*")),
    ("formation", ("formation*", "educati*", "exercice*", "examen*", "cours", "scolaire*", "pedagog*",
                   "support", "tutoriel*", "mathemat*", "enseignement*", "apprentissage*")),
    # « contrôle » (scolaire ? technique ? inspection ?) : ambigu → « autre » (décision de Thomas, 18/11/2026).
    ("documentation technique", ("technique*", "documentation*", "manuel*", "guide*", "notice*",
                                 "configuration*", "specification*", "mode d emploi", "reference*",
                                 "referentiel*", "document d aide", "fiche intervention", "diagramme*",
                                 "securite")),
    ("informatique", ("informatique*", "code", "script*", "logiciel*", "developpement*", "programmation*",
                      "base de donnees", "technologi*", "programme*", "source", "requete*", "sql")),
    ("publication", ("publication*", "article*", "annonce*", "catalogue*", "journal", "revue*", "magazine*",
                     "presse", "brochure*", "flyer*", "affiche*", "newsletter*", "dictionnaire*",
                     "bibliographi*", "touristique", "commercial*", "produit*", "offre d emploi")),
    ("recette", ("recette*", "cuisine*")),
    ("projet", ("projet*", "planification*", "planning*", "plan", "travaux", "inventaire*")),
    ("immobilier", ("immobili*", "logement*")),
)
_MOTIFS = tuple((cat, tuple(re.compile(r"\b" + re.escape(m.rstrip("*")) + ("" if m.endswith("*") else r"\b"))
                            for m in mots)) for cat, mots in REGLES)
_PAR_CLE = {cle(c): c for c in LISTE}


def ramener(categorie: str | None, valides_en_plus: frozenset[str] | set[str] = frozenset()) -> str | None:
    """
    Catégorie de la liste pour une catégorie quelconque. Fonction PURE.

    - vide → None (pas de catégorie : l'enrichissement est un échec, cf. `extraction._reponse_valide`) ;
    - forme exacte d'une catégorie de la liste (casse et accents ignorés) → sa forme officielle ;
    - catégorie de `valides_en_plus` (règles de classement) → inchangée ;
    - sinon la première règle qui correspond, sinon « autre ».
    """
    if not categorie or not str(categorie).strip():
        return None
    brute = str(categorie).strip()
    k = cle(brute)
    if k in _PAR_CLE:
        return _PAR_CLE[k]
    if k in {cle(v) for v in valides_en_plus}:
        return brute
    for cat, motifs in _MOTIFS:
        if any(m.search(k) for m in motifs):
            return cat
    return AUTRE


def texte_liste() -> str:
    """La liste telle qu'elle est écrite dans le prompt d'enrichissement."""
    return ", ".join(LISTE)


async def valides_en_plus(db: AsyncSession) -> set[str]:
    """Catégories imposées par les règles de classement : valides même hors de la liste."""
    from models.regle_classement import RegleClassement
    lignes = (await db.execute(select(RegleClassement.categorie).where(RegleClassement.categorie.isnot(None))))
    return {c for (c,) in lignes if c and c.strip()}


# ─── Regroupement des fiches existantes ───────────────────────────────────────────────────────────

async def _plan(db: AsyncSession) -> tuple[dict[str, str], Counter, int]:
    """{ancienne → nouvelle} pour chaque catégorie à changer, nombre de fiches par ancienne, fiches
    corrigées à la main (laissées telles quelles)."""
    en_plus = await valides_en_plus(db)
    lignes = (await db.execute(
        select(MetadonneeIA.categorie, func.count())
        .where(MetadonneeIA.categorie.isnot(None), MetadonneeIA.categorie_manuelle.is_not(True))
        .group_by(MetadonneeIA.categorie)
    )).all()
    manuelles = (await db.execute(select(func.count()).select_from(MetadonneeIA).where(
        MetadonneeIA.categorie_manuelle.is_(True)))).scalar() or 0
    correspondance: dict[str, str] = {}
    nombres: Counter = Counter()
    for ancienne, n in lignes:
        nouvelle = ramener(ancienne, en_plus)
        if nouvelle and nouvelle != ancienne:
            correspondance[ancienne] = nouvelle
            nombres[ancienne] = n
    return correspondance, nombres, manuelles


async def simuler(db: AsyncSession, detail: int = 40) -> dict:
    """Ce que ferait le regroupement — rien n'est écrit."""
    correspondance, nombres, manuelles = await _plan(db)
    par_cible: Counter = Counter()
    for ancienne, n in nombres.items():
        par_cible[correspondance[ancienne]] += n
    total = (await db.execute(select(func.count()).select_from(MetadonneeIA).where(
        MetadonneeIA.categorie.isnot(None)))).scalar() or 0
    return {
        "fiches": total,
        "fiches_changees": sum(nombres.values()),
        "categories_changees": len(correspondance),
        "manuelles_ignorees": manuelles,
        "par_categorie": [{"categorie": c, "fiches": n} for c, n in par_cible.most_common()],
        "exemples": [{"ancienne": a, "nouvelle": correspondance[a], "fiches": n}
                     for a, n in nombres.most_common(detail)],
        "deja_regroupees": (await db.execute(select(func.count()).select_from(MetadonneeIA).where(
            MetadonneeIA.categorie_origine.isnot(None)))).scalar() or 0,
    }


async def regrouper(db: AsyncSession) -> dict:
    """Applique le regroupement. Garde l'ancienne valeur dans `categorie_origine` (la PREMIÈRE seulement :
    relancer ne l'écrase pas). Une requête par catégorie ancienne : quelques centaines au plus."""
    correspondance, nombres, manuelles = await _plan(db)
    fiches = 0
    for ancienne, nouvelle in correspondance.items():
        res = await db.execute(
            update(MetadonneeIA)
            .where(MetadonneeIA.categorie == ancienne, MetadonneeIA.categorie_manuelle.is_not(True))
            .values(categorie=nouvelle,
                    categorie_origine=func.coalesce(MetadonneeIA.categorie_origine, ancienne))
            .execution_options(synchronize_session=False))
        fiches += res.rowcount or 0
    await db.commit()
    resume = {"fiches_changees": fiches, "categories_changees": len(correspondance),
              "manuelles_ignorees": manuelles}
    log.info("Catégories regroupées sur la liste fermée", **resume)
    return resume


async def annuler(db: AsyncSession) -> dict:
    """Rend à chaque fiche regroupée sa catégorie d'avant (sauf si elle a été corrigée à la main depuis)."""
    res = await db.execute(
        update(MetadonneeIA)
        .where(MetadonneeIA.categorie_origine.isnot(None), MetadonneeIA.categorie_manuelle.is_not(True))
        .values(categorie=MetadonneeIA.categorie_origine, categorie_origine=None)
        .execution_options(synchronize_session=False))
    await db.commit()
    log.info("Regroupement des catégories annulé", fiches=res.rowcount or 0)
    return {"fiches_restaurees": res.rowcount or 0}
