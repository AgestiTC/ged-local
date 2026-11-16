"""
Règles de classement par emplacement — plan « Recevoir la documentation des autres applications »
================================================================================================
Fonctions PURES (choix de la règle, tags) + deux aides base de données :

- `regle_pour(db, chemin)`        → la règle active au préfixe le plus long, ou None ;
- `appliquer(db, doc, regle)`     → pose catégorie / sous-catégorie / tags sur la fiche IA
                                     (la crée si besoin), AVANT l'IA ;
- `classement_fixe(...)`          → ce que l'enrichissement IA doit écrire quand la règle est `fixe`.

Le modèle et la sémantique (`fixe` | `ia`) sont décrits dans `models/regle_classement.py`.
"""
import re
import unicodedata
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from models.metadata import MetadonneeIA
from models.regle_classement import RegleClassement

log = get_logger(__name__)


# ─── Fonctions pures ──────────────────────────────────────────────────────────

def choisir_regle(chemin: str | None, regles: Iterable[RegleClassement]) -> RegleClassement | None:
    """La règle ACTIVE dont le préfixe couvre `chemin`, la plus précise (préfixe le plus long) gagnant."""
    if not chemin:
        return None
    candidates = [r for r in regles if r.actif and r.prefixe_chemin and chemin.startswith(r.prefixe_chemin)]
    return max(candidates, key=lambda r: len(r.prefixe_chemin), default=None)


def sous_dossier(chemin: str, prefixe: str) -> str | None:
    """1ᵉʳ dossier sous le préfixe (`<préfixe>appli/x/doc.md` → `appli`) ; None si le fichier est À la racine."""
    if not chemin.startswith(prefixe):
        return None
    reste = chemin[len(prefixe):].lstrip("/")
    if "/" not in reste:
        return None
    return reste.split("/", 1)[0] or None


def en_tag(texte: str) -> str:
    """Normalise un nom de dossier en tag : minuscules, sans accents, tirets (`Composeur Yealink` → `composeur-yealink`)."""
    t = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def tags_regle(regle: RegleClassement, chemin: str) -> list[str]:
    """Tags imposés par la règle pour ce chemin : ceux de la règle, puis le sous-dossier (sans doublon)."""
    tags = [str(t).strip() for t in (regle.tags or []) if str(t).strip()]
    if regle.tag_depuis_sous_dossier:
        dossier = sous_dossier(chemin, regle.prefixe_chemin)
        tag = en_tag(dossier) if dossier else ""
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def fusionner(tete: list[str], suite: Iterable[str]) -> list[str]:
    """`tete` puis les éléments de `suite` absents de `tete` (ordre conservé)."""
    out = list(tete)
    for t in suite:
        if t and t not in out:
            out.append(t)
    return out


def classement_fixe(regle: RegleClassement, chemin: str, data_ia: dict, ext_tag: str,
                    tags_en_plus: Iterable[str] = ()) -> dict:
    """Valeurs à écrire quand la règle est `fixe` : celles de la règle, l'IA ne comblant que les vides.

    La catégorie de la règle prime ; si la règle n'en fixe pas, celle de l'IA est reprise (sinon le
    document resterait sans catégorie). Les tags sont ceux de la règle (+ tag d'extension en tête,
    + `tags_en_plus`, ex. le tag `appli` de l'en-tête) : les tags de l'IA ne sont PAS ajoutés.
    """
    tags = fusionner(tags_regle(regle, chemin), tags_en_plus)
    if ext_tag and ext_tag not in tags:
        tags = [ext_tag] + tags
    return {
        "categorie": regle.categorie or data_ia.get("categorie"),
        "sous_categorie": regle.sous_categorie or data_ia.get("sous_categorie"),
        "tags": tags,
    }


# ─── Base de données ──────────────────────────────────────────────────────────

async def regle_pour(db: AsyncSession, chemin: str | None) -> RegleClassement | None:
    """La règle applicable à `chemin` (None si aucune). Petite table : lue à chaque appel."""
    if not chemin:
        return None
    regles = (await db.execute(select(RegleClassement).where(RegleClassement.actif.is_(True)))).scalars().all()
    return choisir_regle(chemin, regles)


async def appliquer(db: AsyncSession, doc, regle: RegleClassement, tags_en_plus: Iterable[str] = ()) -> MetadonneeIA:
    """Pose le classement de la règle sur la fiche IA du document (créée si absente), avant l'IA.

    `fixe` : catégorie/sous-catégorie de la règle écrasent l'existant (s'il y en a) ; `ia` : elles ne
    comblent que les vides. Les tags de la règle passent en tête, les tags déjà présents sont gardés.
    """
    tags = fusionner(tags_regle(regle, doc.chemin), tags_en_plus)
    meta = (await db.execute(select(MetadonneeIA).where(MetadonneeIA.document_id == doc.id))).scalar_one_or_none()
    if meta is None:
        meta = MetadonneeIA(
            document_id=doc.id,
            categorie=regle.categorie,
            sous_categorie=regle.sous_categorie,
            tags=tags,
            niveau_confidentialite="normal",
        )
        db.add(meta)
    else:
        if regle.classement == "fixe" or not meta.categorie:
            meta.categorie = regle.categorie or meta.categorie
        if regle.classement == "fixe" or not meta.sous_categorie:
            meta.sous_categorie = regle.sous_categorie or meta.sous_categorie
        meta.tags = fusionner(tags, meta.tags or [])
    await db.flush()
    log.info("Règle de classement appliquée", doc_id=str(doc.id), regle=regle.libelle,
             classement=regle.classement, tags=tags)
    return meta
