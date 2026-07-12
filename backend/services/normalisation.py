"""
Normalisation des métadonnées IA — accents + casse (via dictionnaire d'acronymes).
==================================================================================
Fusionne les variantes accent/casse des **catégories** et **tags** :
  - même clé (insensible aux accents ET à la casse) → une seule forme canonique ;
  - forme canonique privilégiée : (1) un ACRONYME connu → MAJUSCULES ; sinon
    (2) la variante la plus accentuée ; sinon (3) la plus fréquente.
Idempotent + sauvegarde préalable (`storage/backup-normalisation.json`) → réexécutable
(bouton « Normaliser les tags/catégories » des Paramètres).
"""
import json
import unicodedata

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from logger import get_logger
from models.metadata import MetadonneeIA
from services import runtime_config

log = get_logger(__name__)

_ACCENTS = set("àâäéèêëïîôöùûüçñÀÂÄÉÈÊËÏÎÔÖÙÛÜÇÑ")
_BACKUP = "/app/storage/backup-normalisation.json"


def _ascore(s: str) -> int:
    """Nombre de caractères accentués (pour préférer la forme accentuée)."""
    return sum(1 for c in s if c in _ACCENTS)


def _cle(s: str) -> str:
    """Clé de regroupement insensible aux accents ET à la casse."""
    return unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()


def _sigles() -> dict:
    """{clé normalisée: SIGLE_MAJUSCULE} depuis le dictionnaire d'acronymes (config)."""
    try:
        data = json.loads(runtime_config.effective("acronymes") or "[]")
    except (ValueError, TypeError):
        data = []
    out: dict = {}
    for a in data:
        sigle = (a.get("sigle") if isinstance(a, dict) else str(a)) or ""
        sigle = sigle.strip()
        if sigle:
            out[_cle(sigle)] = sigle.upper()
    return out


def _canon(variants: dict, sigles: dict) -> str:
    """Forme canonique d'un groupe {valeur: count} : acronyme (MAJ) > accents > fréquence."""
    cle = _cle(next(iter(variants)))
    if cle in sigles:
        return sigles[cle]
    return max(variants.items(), key=lambda kv: (_ascore(kv[0]), kv[1], kv[0]))[0]


async def normaliser_metadonnees(db: AsyncSession) -> dict:
    """Applique la normalisation à toute la table `metadonnees_ia`. Retourne un résumé."""
    sigles = _sigles()
    rows = (await db.execute(select(MetadonneeIA))).scalars().all()

    # 1) Sauvegarde (rollback possible).
    backup = [{"id": str(m.document_id), "categorie": m.categorie,
               "tags": list(m.tags) if m.tags else None} for m in rows]
    try:
        with open(_BACKUP, "w", encoding="utf-8") as f:
            json.dump(backup, f, ensure_ascii=False)
    except OSError as e:  # noqa: BLE001 — non bloquant
        log.warning("Sauvegarde normalisation non écrite", erreur=str(e))

    # 2) Variantes par clé (accent/casse-insensible).
    catv: dict = {}
    tagv: dict = {}

    def _add(store: dict, val: str) -> None:
        k = _cle(val)
        store.setdefault(k, {})
        store[k][val] = store[k].get(val, 0) + 1

    for m in rows:
        if m.categorie:
            _add(catv, m.categorie)
        for t in (m.tags or []):
            _add(tagv, t)

    cat_map = {v: _canon(vs, sigles) for vs in catv.values() for v in vs}
    tag_map = {v: _canon(vs, sigles) for vs in tagv.values() for v in vs}

    # 3) Application (dédup des tags après remappage).
    cat_maj = tags_maj = 0
    for m in rows:
        if m.categorie and cat_map.get(m.categorie, m.categorie) != m.categorie:
            m.categorie = cat_map[m.categorie]
            cat_maj += 1
        if m.tags:
            new: list = []
            seen: set = set()
            for t in m.tags:
                ct = tag_map.get(t, t)
                if ct not in seen:
                    seen.add(ct)
                    new.append(ct)
            if new != list(m.tags):
                m.tags = new
                tags_maj += 1
    await db.commit()

    resume = {
        "docs_categorie_maj": cat_maj,
        "docs_tags_maj": tags_maj,
        "variantes_categories_fusionnees": sum(1 for v, c in cat_map.items() if v != c),
        "variantes_tags_fusionnees": sum(1 for v, c in tag_map.items() if v != c),
        "acronymes_actifs": len(sigles),
        "sauvegarde": _BACKUP,
    }
    log.info("Normalisation métadonnées terminée", **resume)
    return resume
