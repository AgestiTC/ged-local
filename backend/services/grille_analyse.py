"""
Grille d'analyse des offres — remplir le classeur Excel FOURNI, critère par critère.
=====================================================================================
Le tableau comparatif classique met un candidat par ligne et un critère par colonne. Une grille
d'analyse d'offres (RAO de marché public) fait l'inverse : les CRITÈRES sont en lignes (libellé,
documents à analyser, points), et chaque candidat occupe un BLOC de colonnes « Avis · Note sur
10 · Note finale » sous son nom (`{{NOM_SOCIETE}}`). La note finale y est souvent une formule.

Ce module :
  - reconnaît cette disposition (`detecter_grille`) — sans elle, le comparatif garde son
    comportement habituel ;
  - fait évaluer UN critère pour UN candidat par l'IA (`evaluer_critere`) : avis motivé + note ;
  - réécrit le classeur d'origine (`remplir_grille`) : nom, avis et note dans les cellules
    prévues, mise en forme et formules intactes.

Demande du 01/10/2026 : grille `MA26001_RAO_Lot1.xlsx`, offres CES et OTV.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from io import BytesIO
from pathlib import Path

from logger import get_logger

log = get_logger(__name__)

# Cellule écrite quand l'IA n'a rien rendu d'exploitable (même convention que le comparatif :
# un échec ne doit jamais passer pour un avis).
AVIS_ECHEC_IA = "⚠ Échec de l'IA"

LIGNES_ENTETE_MAX = 20          # l'en-tête « Avis / Note » est cherché dans les premières lignes
# Caractères de documents par évaluation. num_ctx = 16 384 tokens, ~3 caractères par token en
# français : 24 000 caractères ≈ 8 000 tokens, le reste pour les consignes et l'AVIS. À 40 000
# (01/10/2026), le prompt remplissait presque tout le contexte : plus de place pour répondre,
# fenêtre glissante, génération sans fin, 504 de la passerelle après 300 s — à chaque critère.
BUDGET_CRITERE = 24_000
MAX_CHARS_PAR_DOC = 12_000
TOKENS_AVIS_MAX = 1_000         # un avis de 3 à 6 phrases + la note : large

_PLACEHOLDER = re.compile(r"\{\{.*?\}\}")


def _norm(texte: object) -> str:
    """Minuscules, sans accents ni espaces superflus — pour comparer des en-têtes."""
    s = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


@dataclass
class Bloc:
    """Colonnes d'un candidat. `nom_cellule` = cellule du nom (souvent fusionnée au-dessus)."""
    nom_cellule: str
    col_avis: int
    col_note: int | None


@dataclass
class Critere:
    ligne: int
    libelle: str            # texte complet de la cellule (titre + sous-critères)
    documents: str          # « Documents analysés » — pièces à lire en priorité
    points: float | None    # « Points par sous critère »

    @property
    def titre(self) -> str:
        """Première ligne du libellé : sert de nom de critère (colonnes, Markdown, PDF)."""
        return (self.libelle.strip().splitlines() or [""])[0].strip()


@dataclass
class Grille:
    feuille: str
    ligne_entete: int
    blocs: list[Bloc] = field(default_factory=list)
    criteres: list[Critere] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Grille":
        return cls(   # les clés en plus (`fichier` : copie du classeur) sont ignorées
            feuille=d["feuille"], ligne_entete=d["ligne_entete"],
            blocs=[Bloc(**b) for b in d.get("blocs", [])],
            criteres=[Critere(**c) for c in d.get("criteres", [])],
        )


def _cellule_haut_gauche(ws, ligne: int, col: int) -> str:
    """Coordonnée de la cellule qui porte la valeur (la 1ʳᵉ d'une plage fusionnée)."""
    for plage in ws.merged_cells.ranges:
        if plage.min_row <= ligne <= plage.max_row and plage.min_col <= col <= plage.max_col:
            return ws.cell(row=plage.min_row, column=plage.min_col).coordinate
    return ws.cell(row=ligne, column=col).coordinate


def detecter_grille(chemin: Path) -> Grille | None:
    """
    Reconnaît une grille d'analyse : une ligne d'en-tête avec au moins une cellule « Avis »
    suivie d'une « Note … » (hors « note finale »), et une colonne de libellés de critères.
    Rend None pour tout autre classeur — le comparatif classique s'applique alors.
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(chemin))
    except Exception as e:  # noqa: BLE001 — classeur illisible : pas une grille
        log.warning("Grille : classeur illisible", erreur=str(e))
        return None

    for ws in wb.worksheets:
        for ligne in range(1, min(ws.max_row, LIGNES_ENTETE_MAX) + 1):
            entetes = {c: _norm(ws.cell(row=ligne, column=c).value) for c in range(1, ws.max_column + 1)}
            cols_avis = [c for c, v in entetes.items() if v == "avis"]
            if not cols_avis:
                continue

            blocs: list[Bloc] = []
            for i, col_avis in enumerate(cols_avis):
                fin = cols_avis[i + 1] if i + 1 < len(cols_avis) else ws.max_column + 1
                col_note = next((c for c in range(col_avis + 1, fin)
                                 if entetes[c].startswith("note") and "final" not in entetes[c]), None)
                nom = _cellule_haut_gauche(ws, ligne - 1, col_avis) if ligne > 1 else ""
                blocs.append(Bloc(nom_cellule=nom, col_avis=col_avis, col_note=col_note))
            if not any(b.col_note for b in blocs):
                continue

            avant = [c for c in entetes if c < cols_avis[0]]
            col_libelle = next((c for c in avant if entetes[c].startswith(("libelle", "critere"))), None)
            col_docs = next((c for c in avant if "document" in entetes[c]), None)
            col_points = next((c for c in avant if entetes[c].startswith(("point", "ponderation", "coef"))), None)
            if col_libelle is None:
                continue

            criteres: list[Critere] = []
            for r in range(ligne + 1, ws.max_row + 1):
                libelle = ws.cell(row=r, column=col_libelle).value
                if not isinstance(libelle, str) or not libelle.strip():
                    continue
                points = ws.cell(row=r, column=col_points).value if col_points else None
                criteres.append(Critere(
                    ligne=r,
                    libelle=libelle.strip(),
                    documents=str(ws.cell(row=r, column=col_docs).value or "").strip() if col_docs else "",
                    points=float(points) if isinstance(points, (int, float)) else None,
                ))
            if criteres:
                return Grille(feuille=ws.title, ligne_entete=ligne, blocs=blocs, criteres=criteres)
    return None


# ─── Évaluation par l'IA ─────────────────────────────────────────────────────


def _mots_cles(texte: str) -> set[str]:
    return {m for m in re.findall(r"[a-z0-9]+", _norm(texte)) if len(m) >= 4 or m.isdigit()}


def _ordonner_documents(docs: list, indications: str) -> list:
    """Les pièces citées dans « Documents analysés » d'abord (recoupement des mots du nom)."""
    cles = _mots_cles(indications)
    if not cles:
        return list(docs)
    return sorted(docs, key=lambda d: -len(cles & _mots_cles(d.nom)))


def _contexte(docs: list, budget: int) -> str:
    parts: list[str] = []
    reste = budget
    for doc in docs:
        texte = (doc.texte_extrait or "").strip()
        if not texte:
            continue
        texte = texte[:MAX_CHARS_PAR_DOC]
        entete = f"\n--- {doc.nom} ---\n"
        place = reste - len(entete)
        if place <= 200:
            break
        texte = texte[:place]
        parts.append(entete + texte)
        reste -= len(entete) + len(texte)
    return "\n".join(parts) if parts else "(aucun texte exploitable dans les documents de ce candidat)"


async def passages_pertinents(critere: Critere, docs: list, budget: int = BUDGET_CRITERE) -> str | None:
    """
    Les passages des documents du candidat les plus proches du critère (recherche sémantique
    sur les morceaux indexés, préfixe 1024-d). Un mémoire technique de 100 000 caractères ne
    tient pas dans le contexte : en prendre le début ratait les chapitres utiles. None si les
    vecteurs manquent (documents non vectorisés, Ollama indisponible) → repli sur `_contexte`.
    """
    from sqlalchemy import text

    from database import AsyncSessionLocal
    from routers.search import _embed_query
    from utils.vectors import matryoshka_prefix

    if not docs:
        return None
    requete = f"{critere.libelle}\n{critere.documents}"[:4000]
    vecteur = matryoshka_prefix(await _embed_query(requete))
    if vecteur is None:
        return None
    noms = {str(d.id): d.nom for d in docs}
    qs = "[" + ",".join(str(v) for v in vecteur) + "]"
    try:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(text("""
                SELECT CAST(document_id AS TEXT), chunk_index, chunk_text
                FROM embeddings
                WHERE embedding_small IS NOT NULL AND document_id = ANY(CAST(:ids AS uuid[]))
                ORDER BY embedding_small <=> CAST(:qs AS vector)
                LIMIT 120
            """), {"qs": qs, "ids": list(noms)})).fetchall()
    except Exception as e:  # noqa: BLE001 — base sans pgvector (tests) ou colonne absente : repli
        log.warning("Grille : recherche de passages impossible", erreur=str(e) or type(e).__name__)
        return None
    if not rows:
        return None

    retenus, reste = [], budget
    for did, idx, extrait in rows:
        extrait = (extrait or "").strip()
        if not extrait or len(extrait) + 80 > reste:
            continue
        retenus.append((did, idx, extrait))
        reste -= len(extrait) + 80
    # Relus dans l'ordre des documents : des passages d'un même mémoire se lisent mieux à la suite.
    retenus.sort(key=lambda r: (noms.get(r[0], ""), r[1]))
    parts, courant = [], None
    for did, idx, extrait in retenus:
        if did != courant:
            parts.append(f"\n--- {noms.get(did, '?')} (extraits) ---")
            courant = did
        parts.append(f"[…] {extrait}")
    return "\n".join(parts)


def _note(valeur: object) -> float | None:
    try:
        return None if valeur is None else max(0.0, min(10.0, float(str(valeur).replace(",", "."))))
    except ValueError:
        return None


def _nettoyer_avis(avis: str) -> str:
    """Avis lisible dans une cellule Excel : sans gras Markdown, sans lignes vides en série."""
    avis = avis.replace("\\n", "\n").replace("**", "")   # « \n » littéraux d'un JSON mal échappé
    lignes = [ligne.strip() for ligne in avis.splitlines()]
    propre: list[str] = []
    for ligne in lignes:
        if ligne or (propre and propre[-1]):
            propre.append(ligne)
    return "\n".join(propre).strip()


def _lire_reponse(reponse: str) -> tuple[str, float | None] | None:
    """
    Lit `{"avis": …, "note": …}`. Tolérant : le 01/10/2026, ministral-3 a rendu 6 avis sur 6
    avec des retours à la ligne BRUTS dans la chaîne (JSON strict invalide) — tout était jeté
    alors que le contenu était bon. `strict=False` les accepte ; à défaut (guillemets non
    échappés, réponse tronquée), les deux champs sont relevés à la main.
    """
    texte = reponse or ""
    data = None
    match = re.search(r"\{.*\}", texte, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(), strict=False)
        except json.JSONDecodeError:
            data = None
    if isinstance(data, dict):
        avis, note = str(data.get("avis") or ""), _note(data.get("note"))
    else:
        m_note = re.search(r'"note"\s*:\s*"?(-?\d+(?:[.,]\d+)?)', texte)
        m_avis = re.search(r'"avis"\s*:\s*"(.*?)"\s*,\s*"note"', texte, re.DOTALL)
        if m_avis:
            avis = m_avis.group(1)
        else:   # réponse coupée avant la note : on garde l'avis jusqu'où il va
            m_avis = re.search(r'"avis"\s*:\s*"(.*)', texte, re.DOTALL)
            avis = re.sub(r'"?\s*\}?\s*(```)?\s*$', "", m_avis.group(1)) if m_avis else ""
        note = _note(m_note.group(1)) if m_note else None
    avis = _nettoyer_avis(avis)
    if not avis and note is None:
        return None
    return avis, note


async def evaluer_critere(
    candidat: str,
    critere: Critere,
    docs: list,
    instructions: str | None,
    model: str,
    ollama,
    contexte: str | None = None,
) -> tuple[str, float | None, bool]:
    """
    Rend `(avis, note sur 10, ok)`. Échec → `(AVIS_ECHEC_IA, None, False)`, jamais une note inventée.
    `contexte` = passages déjà choisis (`passages_pertinents`) ; à défaut, début des pièces citées.
    """
    if not contexte:
        contexte = _contexte(_ordonner_documents(docs, critere.documents), BUDGET_CRITERE)
    pieces = f"\nPièces à examiner en priorité :\n{critere.documents}\n" if critere.documents else ""
    consignes_utilisateur = f"\nConsignes de l'analyste : {instructions}\n" if instructions else ""
    # Les consignes sont répétées APRÈS les documents : en cas de dépassement de contexte, Ollama
    # coupe le DÉBUT du prompt — ce qui a déjà vidé 1 220 enrichissements (16/09/2026).
    prompt = f"""Tu es analyste des offres d'un marché public. Candidat évalué : {candidat}.

Critère à noter :
{critere.libelle}
{pieces}
Documents de l'offre du candidat :
{contexte}

=== CONSIGNE ===
Évalue l'offre de « {candidat} » sur le critère ci-dessus, en t'appuyant UNIQUEMENT sur ces documents.
- « avis » : 3 à 6 phrases factuelles en français — points forts, points faibles, éléments manquants,
  en citant les pièces. Si une pièce attendue est absente, dis-le.
- « note » : nombre de 0 à 10 (décimales autorisées) reflétant la qualité de l'offre sur CE critère.
{consignes_utilisateur}
Réponds UNIQUEMENT par un objet JSON, sans texte autour : {{"avis": "…", "note": 7}}"""

    reponse = ""
    try:
        reponse = await ollama.generate(prompt, model=model, num_predict=TOKENS_AVIS_MAX)
        lu = _lire_reponse(reponse)
        if lu:
            return lu[0] or AVIS_ECHEC_IA, lu[1], True
    except Exception as e:  # noqa: BLE001 — appel KO : échec explicite ci-dessous
        log.warning("Grille : évaluation IA impossible", candidat=candidat, critere=critere.titre, erreur=str(e))
        return AVIS_ECHEC_IA, None, False
    log.warning("Grille : réponse IA inexploitable", candidat=candidat, critere=critere.titre,
                modele=model, reponse=reponse[:200])
    return AVIS_ECHEC_IA, None, False


# ─── Rendu ───────────────────────────────────────────────────────────────────


def remplir_grille(chemin: Path, grille: Grille, groupes: list[dict]) -> bytes:
    """
    Écrit nom / avis / note de chaque candidat dans SON bloc (1ᵉʳ groupe → 1ᵉʳ bloc…).
    `groupes[i]` = {nom, evaluations: {str(ligne): {avis, note}}}. Les cellules à formule
    (note finale) ne sont jamais écrasées ; un nom déjà saisi (sans `{{…}}`) est conservé.
    """
    import openpyxl
    from openpyxl.styles import Alignment

    wb = openpyxl.load_workbook(str(chemin))
    ws = wb[grille.feuille]

    for bloc, groupe in zip(grille.blocs, groupes):
        if bloc.nom_cellule:
            cellule = ws[bloc.nom_cellule]
            actuel = cellule.value
            if actuel is None or (isinstance(actuel, str) and (_PLACEHOLDER.search(actuel) or not actuel.strip())):
                cellule.value = groupe.get("nom", "")

        evaluations = groupe.get("evaluations") or {}
        for critere in grille.criteres:
            ev = evaluations.get(str(critere.ligne))
            if not ev:
                continue
            c_avis = ws.cell(row=critere.ligne, column=bloc.col_avis)
            if not (isinstance(c_avis.value, str) and c_avis.value.startswith("=")):
                c_avis.value = ev.get("avis")
                c_avis.alignment = Alignment(vertical="top", wrap_text=True)
            if bloc.col_note and ev.get("note") is not None:
                c_note = ws.cell(row=critere.ligne, column=bloc.col_note)
                if not (isinstance(c_note.value, str) and c_note.value.startswith("=")):
                    c_note.value = ev["note"]

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def valeur_lisible(avis: str, note: float | None) -> str:
    """Cellule des rendus Markdown / PDF / Word : la note d'abord, puis l'avis."""
    if note is None:
        return avis
    return f"{note:g}/10 — {avis}"
