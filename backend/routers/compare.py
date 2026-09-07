"""
Router Compare — /api/generate/compare
========================================
Génération de tableaux comparatifs multi-groupes (candidats / sociétés / contrats…).

**Le template Excel est FACULTATIF.** Les critères de comparaison (les colonnes) peuvent venir,
par ordre de priorité :
  1. des **en-têtes de la ligne 1 d'un template .xlsx** fourni (sa mise en forme est conservée) ;
  2. d'une **saisie libre** (un critère par ligne dans l'UI) ;
  3. à défaut, d'une **déduction par l'IA** à partir des documents eux-mêmes.

**Le format de sortie se choisit APRÈS la génération**, sans relancer l'IA : les valeurs
extraites sont conservées et rendues à la demande en `xlsx` · `pdf` · `docx` · `md`.

⚠️ Orientation du tableau volontairement différente selon le format :
  • `xlsx` = convention tableur → **1 ligne par groupe**, 1 colonne par critère (triable/filtrable) ;
  • `md` / `pdf` / `docx` = lecture comparative → **1 ligne par critère**, 1 colonne par groupe
    (les critères sont nombreux, les groupes peu : c'est ce sens qui se lit en portrait).

Endpoints :
  POST /generate/compare                 → lance la comparaison
  POST /generate/compare/criteres        → propose des critères à partir de documents
  GET  /generate/compare/stream/{id}     → flux SSE de progression
  GET  /generate/compare/resultat/{id}   → tableau extrait (JSON + Markdown)
  GET  /generate/compare/download/{id}   → télécharge (?format=xlsx|pdf|docx|md)
"""

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from logger import get_logger
from models.document import Document
from models.job import Job
from models.template import Template
from services.ollama_service import OllamaService

log = get_logger(__name__)
settings = get_settings()
router = APIRouter()

# Cache en mémoire : job_id → état de la comparaison
_compare_cache: dict[str, dict] = {}
# Structure : {
#   "events": [{"groupe": str, "statut": str, "index": int, "total": int}],
#   "statut": "running" | "complete" | "failed",
#   "colonnes": list[str],            # critères de comparaison retenus
#   "groupes": [{"nom": str, "valeurs": {colonne: valeur}}],
#   "synthese": str | None,           # commentaire IA des écarts
#   "template_id": str | None,
#   "fichiers": {format: bytes},      # rendus déjà produits (cache de téléchargement)
#   "erreur": str | None,
# }

MAX_CHARS_PAR_DOC = 20_000    # Tronquer les gros docs pour tenir dans le contexte
BUDGET_ANALYSE = 60_000       # Contexte max pour l'analyse d'un groupe
BUDGET_CRITERES = 24_000      # Contexte max pour la déduction des critères
MAX_COLONNES = 25

FORMATS = ("xlsx", "pdf", "docx", "md")

# Dernier recours si l'IA ne propose rien d'exploitable : des critères assez génériques pour
# que la comparaison aboutisse quand même (le but du template facultatif est de ne JAMAIS bloquer).
COLONNES_FALLBACK = [
    "Objet",
    "Points clés",
    "Chiffres clés",
    "Dates importantes",
    "Points d'attention",
]


class GroupeRequest(BaseModel):
    nom: str = Field(..., min_length=1, description="Nom du candidat / société / contrat")
    document_ids: list[str] = Field(..., min_items=1)


class CompareRequest(BaseModel):
    groupes: list[GroupeRequest] = Field(..., min_items=2, description="Au moins 2 groupes")
    template_id: str | None = Field(default=None, description="Template Excel — FACULTATIF")
    colonnes: list[str] | None = Field(default=None, description="Critères saisis à la main")
    model: str | None = Field(default=None)
    instructions: str | None = Field(default=None, description="Instructions supplémentaires pour le LLM")
    synthese: bool = Field(default=True, description="Ajouter un commentaire IA des écarts")


class CriteresRequest(BaseModel):
    """Demande de proposition de critères de comparaison à partir de documents."""
    document_ids: list[str] = Field(..., min_items=1)
    instructions: str | None = Field(default=None)
    model: str | None = Field(default=None)


# ─── Utilitaires ─────────────────────────────────────────────────────────────


def _valid_uuid(val: str) -> bool:
    try:
        uuid.UUID(val)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _nettoyer_colonnes(colonnes: list[str] | None) -> list[str]:
    """Nettoie une liste de critères : trim, non vides, dédupliqués, plafonnés."""
    propres: list[str] = []
    vus: set[str] = set()
    for c in colonnes or []:
        if not isinstance(c, str):
            continue
        nom = " ".join(c.split()).strip()
        if not nom or nom.lower() in vus:
            continue
        vus.add(nom.lower())
        propres.append(nom)
        if len(propres) >= MAX_COLONNES:
            break
    return propres


def _lire_colonnes_template(chemin: Path) -> list[str]:
    """Lit les en-têtes de la première ligne du template Excel."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(chemin), read_only=True, data_only=True)
        ws = wb.active
        colonnes = []
        for cell in next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ()):
            if cell and isinstance(cell, str) and cell.strip():
                colonnes.append(cell.strip())
        wb.close()
        return colonnes
    except Exception as e:
        log.warning("Impossible de lire les colonnes du template", erreur=str(e))
        return []


def _contexte_documents(docs: list[Document], budget: int) -> str:
    """Concatène le texte extrait des documents dans la limite d'un budget de caractères."""
    parts: list[str] = []
    chars_restants = budget
    for doc in docs:
        texte = (doc.texte_extrait or "").strip()
        if not texte:
            continue
        if len(texte) > MAX_CHARS_PAR_DOC:
            texte = texte[:MAX_CHARS_PAR_DOC] + "\n[tronqué]"
        entete = f"\n--- {doc.nom} ---\n"
        espace = chars_restants - len(entete)
        if espace <= 0:
            break
        if len(texte) > espace:
            texte = texte[:espace] + "\n[tronqué]"
        parts.append(entete + texte)
        chars_restants -= len(entete) + len(texte)
    return "\n".join(parts) if parts else "(aucun document disponible)"


async def _charger_documents(document_ids: list[str]) -> list[Document]:
    """Charge des documents par lot (session courte, appelable depuis une tâche de fond)."""
    from database import AsyncSessionLocal

    doc_uuids = [uuid.UUID(did) for did in document_ids if _valid_uuid(did)]
    if not doc_uuids:
        return []
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Document).where(Document.id.in_(doc_uuids)))
        return list(result.scalars().all())


# ─── Appels IA ───────────────────────────────────────────────────────────────


async def _deduire_colonnes(
    docs: list[Document],
    instructions: str | None,
    model: str,
    ollama: OllamaService,
) -> list[str]:
    """Demande au LLM de proposer les critères de comparaison pertinents pour ces documents."""
    contexte = _contexte_documents(docs, BUDGET_CRITERES)
    instructions_str = f"\nContexte / attentes de l'utilisateur : {instructions}" if instructions else ""

    prompt = f"""Voici des extraits de documents qui vont être comparés entre eux :

{contexte}

Propose entre 5 et 10 CRITÈRES DE COMPARAISON pertinents pour ce type de document.
Un critère = un libellé court (2 à 4 mots), factuel, comparable d'un document à l'autre.
Exemple pour des contrats d'assurance : "Prime annuelle", "Franchise", "Plafond d'indemnisation",
"Garanties incluses", "Exclusions", "Délai de carence", "Conditions de résiliation".

Retourne UNIQUEMENT un tableau JSON de chaînes, sans texte avant ni après.
Exemple de format attendu : ["Critère 1", "Critère 2", "Critère 3"]{instructions_str}"""

    try:
        reponse = await ollama.generate(prompt, model=model)
        match = re.search(r"\[.*\]", reponse, re.DOTALL)
        if match:
            data = json.loads(match.group())
            colonnes = _nettoyer_colonnes([str(c) for c in data if c])
            if colonnes:
                return colonnes
    except Exception as e:
        log.warning("Déduction des critères impossible", erreur=str(e))

    return list(COLONNES_FALLBACK)


async def _analyser_groupe(
    nom_groupe: str,
    docs: list[Document],
    colonnes: list[str],
    instructions: str | None,
    model: str,
    ollama: OllamaService,
) -> dict[str, str]:
    """
    Appelle le LLM pour extraire les valeurs des colonnes pour un groupe.
    Retourne un dict {colonne: valeur}.
    """
    contexte_docs = _contexte_documents(docs, BUDGET_ANALYSE)
    colonnes_str = ", ".join(f'"{c}"' for c in colonnes)
    instructions_str = f"\nInstructions supplémentaires : {instructions}" if instructions else ""

    prompt = f"""Tu analyses les documents du candidat/société : {nom_groupe}

{contexte_docs}

Extrait les informations suivantes et retourne UNIQUEMENT un objet JSON valide, sans texte avant ni après :
{{
{chr(10).join(f'  "{c}": "valeur"' for c in colonnes)}
}}

Champs à remplir : {colonnes_str}
Si une information est absente ou non trouvée, utilise "N/A".
Ne retourne que le JSON, rien d'autre.{instructions_str}"""

    try:
        reponse = await ollama.generate(prompt, model=model)
        # Extraire le JSON de la réponse
        match = re.search(r'\{.*\}', reponse, re.DOTALL)
        if match:
            data = json.loads(match.group())
            return {c: str(data.get(c, "N/A")) for c in colonnes}
    except Exception as e:
        log.warning("Erreur parsing réponse LLM", groupe=nom_groupe, erreur=str(e))

    return {c: "N/A" for c in colonnes}


async def _synthetiser_ecarts(
    colonnes: list[str],
    groupes_data: list[dict],
    instructions: str | None,
    model: str,
    ollama: OllamaService,
) -> str | None:
    """
    Commente les ÉCARTS entre les groupes — le tableau seul ne dit pas OÙ sont les différences.
    Renvoie du Markdown (liste à puces) ou None si l'appel échoue.
    """
    tableau = _construire_markdown(colonnes, groupes_data, synthese=None, titre=None)
    instructions_str = f"\nAttentes de l'utilisateur : {instructions}" if instructions else ""

    prompt = f"""Voici un tableau comparatif déjà rempli :

{tableau}

Rédige une synthèse COURTE des différences entre les entités comparées.
Contraintes :
- 5 à 8 puces Markdown maximum, commençant par « - » ;
- une puce = un écart CONCRET, chiffré quand c'est possible, en nommant les entités concernées ;
- ignore les critères où tout le monde est identique ou en "N/A" ;
- termine par une puce « Points de vigilance » si quelque chose manque ou semble contradictoire ;
- pas d'introduction, pas de conclusion, pas de titre : uniquement les puces.{instructions_str}"""

    try:
        reponse = await ollama.generate(prompt, model=model)
        texte = (reponse or "").strip()
        return texte or None
    except Exception as e:
        log.warning("Synthèse des écarts impossible", erreur=str(e))
        return None


# ─── Rendus (Markdown / Excel / Word / PDF) ──────────────────────────────────


def _md_cell(valeur) -> str:
    """Échappe une valeur pour une cellule de tableau Markdown."""
    texte = str(valeur if valeur is not None else "").replace("|", "\\|")
    texte = " ".join(texte.split("\n")).strip()
    return texte or "—"


def _construire_markdown(
    colonnes: list[str],
    groupes_data: list[dict],
    synthese: str | None = None,
    titre: str | None = "Tableau comparatif",
) -> str:
    """Tableau Markdown TRANSPOSÉ : 1 ligne = 1 critère, 1 colonne = 1 groupe."""
    noms = [g.get("nom", "?") for g in groupes_data]
    lignes: list[str] = []
    if titre:
        lignes += [f"# {titre}", ""]

    lignes.append("| Critère | " + " | ".join(_md_cell(n) for n in noms) + " |")
    lignes.append("|" + "---|" * (len(noms) + 1))
    for col in colonnes:
        cellules = [_md_cell(g.get("valeurs", {}).get(col, "N/A")) for g in groupes_data]
        lignes.append(f"| **{_md_cell(col)}** | " + " | ".join(cellules) + " |")

    if synthese:
        lignes += ["", "## Synthèse des écarts", "", synthese.strip()]

    return "\n".join(lignes)


def _generer_xlsx(
    template_path: Path | None,
    groupes_data: list[dict],
    colonnes: list[str],
    synthese: str | None,
) -> bytes:
    """
    Rendu tableur : 1 ligne par groupe, 1 colonne par critère.
    Avec template → on remplit le fichier fourni (sa mise en forme est conservée).
    Sans template → feuille créée de zéro, avec une 1ʳᵉ colonne « Candidat / Société ».
    """
    import openpyxl
    from openpyxl.styles import Alignment, Font

    if template_path and template_path.exists():
        wb = openpyxl.load_workbook(str(template_path))
        ws = wb.active
        decalage = 0            # le template porte déjà ses propres colonnes
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Comparatif"
        decalage = 1            # 1ʳᵉ colonne réservée au nom du groupe
        for col_idx, entete in enumerate(["Candidat / Société"] + colonnes, start=1):
            cellule = ws.cell(row=1, column=col_idx, value=entete)
            cellule.font = Font(bold=True)
            cellule.alignment = Alignment(vertical="top", wrap_text=True)
            ws.column_dimensions[cellule.column_letter].width = 26 if col_idx == 1 else 22
        ws.freeze_panes = "B2"

    for row_idx, groupe in enumerate(groupes_data, start=2):
        if decalage:
            ws.cell(row=row_idx, column=1, value=groupe.get("nom", "")).font = Font(bold=True)
        for col_idx, colonne in enumerate(colonnes, start=1 + decalage):
            valeur = groupe.get("valeurs", {}).get(colonne, "N/A")
            cellule = ws.cell(row=row_idx, column=col_idx, value=valeur)
            cellule.alignment = Alignment(vertical="top", wrap_text=True)

    if synthese:
        depart = len(groupes_data) + 4
        titre = ws.cell(row=depart, column=1, value="Synthèse des écarts")
        titre.font = Font(bold=True)
        for i, ligne in enumerate(synthese.strip().split("\n"), start=depart + 1):
            if ligne.strip():
                ws.cell(row=i, column=1, value=ligne.strip())

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _generer_docx(
    colonnes: list[str],
    groupes_data: list[dict],
    synthese: str | None,
    titre: str,
) -> bytes:
    """Rendu Word : un VRAI tableau Word (transposé) — pas du Markdown en texte brut."""
    from docx import Document as DocxDocument

    doc = DocxDocument()
    doc.add_heading(titre, level=0)

    noms = [g.get("nom", "?") for g in groupes_data]
    table = doc.add_table(rows=1, cols=len(noms) + 1)
    table.style = "Table Grid"

    entete = table.rows[0].cells
    entete[0].text = "Critère"
    for i, nom in enumerate(noms, start=1):
        entete[i].text = str(nom)
    for cellule in entete:
        for paragraphe in cellule.paragraphs:
            for run in paragraphe.runs:
                run.bold = True

    for col in colonnes:
        cellules = table.add_row().cells
        cellules[0].text = str(col)
        for paragraphe in cellules[0].paragraphs:
            for run in paragraphe.runs:
                run.bold = True
        for i, groupe in enumerate(groupes_data, start=1):
            cellules[i].text = str(groupe.get("valeurs", {}).get(col, "N/A"))

    if synthese:
        doc.add_heading("Synthèse des écarts", level=1)
        for ligne in synthese.strip().split("\n"):
            texte = ligne.strip()
            if not texte:
                continue
            if texte.startswith(("- ", "* ")):
                doc.add_paragraph(texte[2:].strip(), style="List Bullet")
            else:
                doc.add_paragraph(texte)

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _generer_pdf(contenu_md: str, titre: str) -> bytes:
    """Rendu PDF : Markdown → HTML stylé (feuille de style partagée avec /api/export) → WeasyPrint."""
    import markdown
    from weasyprint import HTML

    from routers.export import _html_document

    contenu_html = markdown.markdown(
        contenu_md,
        extensions=["tables", "fenced_code", "nl2br", "sane_lists"],
    )
    return HTML(string=_html_document(titre, contenu_html)).write_pdf()


# ─── Tâche de fond ───────────────────────────────────────────────────────────


async def _run_compare(
    job_id: str,
    groupes: list[GroupeRequest],
    template_path: Path | None,
    colonnes: list[str],
    model: str,
    instructions: str | None,
    avec_synthese: bool,
) -> None:
    """Tâche de fond : (déduire les critères si besoin) → analyser chaque groupe → synthétiser."""
    from database import AsyncSessionLocal

    ollama = OllamaService()
    total = len(groupes)
    groupes_data: list[dict] = []

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
            job = result.scalar_one_or_none()
            if job:
                job.statut = "running"
                job.started_at = datetime.now(tz=timezone.utc)
                await db.commit()

        # Étape 0 — critères déduits par l'IA (ni template, ni saisie manuelle)
        if not colonnes:
            _compare_cache[job_id]["events"].append({
                "statut": "criteres",
                "message": "Détermination des critères de comparaison…",
            })
            echantillon: list[Document] = []
            for groupe in groupes:
                echantillon += await _charger_documents(groupe.document_ids[:2])
            colonnes = await _deduire_colonnes(echantillon, instructions, model, ollama)
            _compare_cache[job_id]["colonnes"] = colonnes
            _compare_cache[job_id]["events"].append({"statut": "criteres", "colonnes": colonnes})
            log.info("Critères déduits par l'IA", job_id=job_id, colonnes=colonnes)

        for idx, groupe in enumerate(groupes, start=1):
            # Émettre "en cours"
            _compare_cache[job_id]["events"].append({
                "groupe": groupe.nom,
                "statut": "running",
                "index": idx,
                "total": total,
            })

            docs = await _charger_documents(groupe.document_ids)

            # Analyser
            valeurs = await _analyser_groupe(
                nom_groupe=groupe.nom,
                docs=docs,
                colonnes=colonnes,
                instructions=instructions,
                model=model,
                ollama=ollama,
            )

            groupes_data.append({"nom": groupe.nom, "valeurs": valeurs})

            # Émettre "terminé"
            _compare_cache[job_id]["events"].append({
                "groupe": groupe.nom,
                "statut": "done",
                "index": idx,
                "total": total,
            })

            log.info("Groupe analysé", job_id=job_id, groupe=groupe.nom, index=idx, total=total)

        # Synthèse des écarts (facultative — le tableau reste exploitable si elle échoue)
        synthese = None
        if avec_synthese:
            _compare_cache[job_id]["events"].append({
                "statut": "synthese",
                "message": "Rédaction de la synthèse des écarts…",
            })
            synthese = await _synthetiser_ecarts(colonnes, groupes_data, instructions, model, ollama)

        _compare_cache[job_id].update({
            "colonnes": colonnes,
            "groupes": groupes_data,
            "synthese": synthese,
            "statut": "complete",
        })
        _compare_cache[job_id]["events"].append({
            "statut": "complete",
            "colonnes": colonnes,
            "resultat_url": f"/api/generate/compare/resultat/{job_id}",
            "download_url": f"/api/generate/compare/download/{job_id}",
        })

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
            job = result.scalar_one_or_none()
            if job:
                job.statut = "completed"
                job.completed_at = datetime.now(tz=timezone.utc)
                job.resultat = {
                    "nb_groupes": total,
                    "colonnes": colonnes,
                    "groupes": groupes_data,
                    "synthese": synthese,
                }
                await db.commit()

        log.info("Tableau comparatif généré", job_id=job_id, nb_groupes=total, nb_criteres=len(colonnes))

    except Exception as e:
        log.error("Erreur rapport comparatif", job_id=job_id, erreur=str(e))
        _compare_cache[job_id]["statut"] = "failed"
        _compare_cache[job_id]["erreur"] = str(e)
        _compare_cache[job_id]["events"].append({"statut": "failed", "erreur": str(e)})

        try:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
                job = result.scalar_one_or_none()
                if job:
                    job.statut = "failed"
                    job.erreur = str(e)
                    job.completed_at = datetime.now(tz=timezone.utc)
                    await db.commit()
        except Exception:
            pass


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/generate/compare/criteres")
async def proposer_criteres(request: CriteresRequest):
    """
    Propose des critères de comparaison à partir d'un échantillon de documents.
    Sert l'option « l'IA propose » de l'étape « Critères de comparaison » : la liste
    renvoyée est **éditable** côté UI avant lancement.
    """
    from services import runtime_config

    docs = await _charger_documents(request.document_ids[:6])
    if not docs:
        raise HTTPException(status_code=404, detail="Aucun document exploitable")

    model = request.model or runtime_config.model_for("rapport")
    colonnes = await _deduire_colonnes(docs, request.instructions, model, OllamaService())
    log.info("Critères proposés", nb_docs=len(docs), colonnes=colonnes)
    return {"colonnes": colonnes, "model": model}


@router.post("/generate/compare", status_code=202)
async def start_compare(
    request: CompareRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Lance la génération du tableau comparatif en arrière-plan.

    `template_id` et `colonnes` sont tous deux FACULTATIFS : sans l'un ni l'autre,
    les critères sont déduits des documents par l'IA au début du traitement.
    """
    template_path: Path | None = None
    colonnes: list[str] = []

    if request.template_id:
        try:
            template_uuid = uuid.UUID(request.template_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="template_id invalide")

        result = await db.execute(select(Template).where(Template.id == template_uuid))
        template = result.scalar_one_or_none()
        if not template:
            raise HTTPException(status_code=404, detail="Template non trouvé")

        template_path = Path(template.chemin_fichier)
        if not template_path.exists():
            raise HTTPException(status_code=404, detail="Fichier template introuvable sur le disque")

        colonnes = _lire_colonnes_template(template_path)
        if not colonnes:
            raise HTTPException(status_code=400, detail="Le template ne contient aucune colonne en ligne 1")

    elif request.colonnes:
        colonnes = _nettoyer_colonnes(request.colonnes)
        if not colonnes:
            raise HTTPException(status_code=400, detail="Aucun critère de comparaison valide")

    from services import runtime_config
    model = request.model or runtime_config.model_for("rapport")

    # Créer le job
    job = Job(
        type="rapport",
        statut="pending",
        parametres={
            "type": "comparatif",
            "nb_groupes": len(request.groupes),
            "template_id": request.template_id,
            "model": model,
            "colonnes": colonnes,
            "criteres_auto": not colonnes,
        },
    )
    db.add(job)
    await db.flush()
    job_id = str(job.id)

    # Initialiser le cache
    _compare_cache[job_id] = {
        "events": [],
        "statut": "running",
        "colonnes": colonnes,
        "groupes": [],
        "synthese": None,
        "template_id": request.template_id,
        "fichiers": {},
        "erreur": None,
    }

    # Lancer en arrière-plan (asyncio.create_task — compatible avec workers=1)
    asyncio.create_task(_run_compare(
        job_id=job_id,
        groupes=request.groupes,
        template_path=template_path,
        colonnes=colonnes,
        model=model,
        instructions=request.instructions,
        avec_synthese=request.synthese,
    ))

    log.info(
        "Comparaison lancée",
        job_id=job_id, nb_groupes=len(request.groupes),
        colonnes=colonnes, criteres_auto=not colonnes,
    )
    return {
        "job_id": job_id,
        "statut": "en_attente",
        "nb_groupes": len(request.groupes),
        "colonnes": colonnes,
        "criteres_auto": not colonnes,
        "stream_url": f"/api/generate/compare/stream/{job_id}",
    }


@router.get("/generate/compare/stream/{job_id}")
async def stream_compare(job_id: str):
    """
    Flux SSE de progression de la comparaison.

    Événements émis :
      {"statut": "criteres", "message": "…"} puis {"statut": "criteres", "colonnes": [...]}
      {"groupe": "Société A", "statut": "running", "index": 1, "total": 3}
      {"groupe": "Société A", "statut": "done",    "index": 1, "total": 3}
      {"statut": "synthese", "message": "…"}
      {"statut": "complete", "colonnes": [...], "resultat_url": "…", "download_url": "…"}
      {"statut": "failed",   "erreur": "..."}
    """
    if not _valid_uuid(job_id):
        raise HTTPException(status_code=400, detail="ID invalide")

    async def event_generator():
        position = 0
        max_attente = 600   # 10 minutes
        attente = 0

        while attente < max_attente:
            cache = _compare_cache.get(job_id)
            if cache is None:
                yield f"data: {json.dumps({'statut': 'failed', 'erreur': 'Job introuvable'})}\n\n"
                return

            events = cache["events"]
            # Envoyer les nouveaux événements
            while position < len(events):
                yield f"data: {json.dumps(events[position])}\n\n"
                position += 1

            # Terminer si fini
            if cache["statut"] in ("complete", "failed"):
                return

            await asyncio.sleep(0.5)
            attente += 0.5

        yield f"data: {json.dumps({'statut': 'failed', 'erreur': 'Timeout'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _charger_etat(job_id: str, db: AsyncSession) -> dict:
    """
    État d'une comparaison terminée : cache mémoire d'abord, sinon `jobs.resultat` en base
    (le cache est perdu au redémarrage du backend — le tableau, lui, reste téléchargeable).
    """
    if not _valid_uuid(job_id):
        raise HTTPException(status_code=400, detail="ID invalide")

    cache = _compare_cache.get(job_id)
    if cache:
        if cache["statut"] == "failed":
            raise HTTPException(status_code=400, detail=cache.get("erreur") or "Comparaison en échec")
        if cache["statut"] != "complete":
            raise HTTPException(status_code=400, detail="La comparaison n'est pas encore terminée")
        return cache

    result = await db.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable")
    if job.statut != "completed" or not job.resultat:
        raise HTTPException(status_code=400, detail="La comparaison n'est pas encore terminée")

    _compare_cache[job_id] = {
        "events": [],
        "statut": "complete",
        "colonnes": job.resultat.get("colonnes", []),
        "groupes": job.resultat.get("groupes", []),
        "synthese": job.resultat.get("synthese"),
        "template_id": (job.parametres or {}).get("template_id"),
        "fichiers": {},
        "erreur": None,
    }
    return _compare_cache[job_id]


@router.get("/generate/compare/resultat/{job_id}")
async def resultat_compare(job_id: str, db: AsyncSession = Depends(get_db)):
    """Tableau extrait : colonnes, valeurs par groupe, synthèse et rendu Markdown prêt à afficher."""
    etat = await _charger_etat(job_id, db)
    colonnes = etat.get("colonnes") or []
    groupes = etat.get("groupes") or []
    return {
        "job_id": job_id,
        "colonnes": colonnes,
        "groupes": groupes,
        "synthese": etat.get("synthese"),
        "markdown": _construire_markdown(colonnes, groupes, etat.get("synthese")),
        "formats": list(FORMATS),
    }


async def _template_path_pour(etat: dict, db: AsyncSession) -> Path | None:
    """Retrouve le fichier template d'un job (s'il en avait un) pour régénérer le .xlsx."""
    template_id = etat.get("template_id")
    if not template_id or not _valid_uuid(template_id):
        return None
    result = await db.execute(select(Template).where(Template.id == uuid.UUID(template_id)))
    template = result.scalar_one_or_none()
    if not template:
        return None
    chemin = Path(template.chemin_fichier)
    return chemin if chemin.exists() else None


@router.get("/generate/compare/download/{job_id}")
async def download_compare(
    job_id: str,
    format: str = Query(default="xlsx", description="xlsx | pdf | docx | md"),
    db: AsyncSession = Depends(get_db),
):
    """
    Télécharge le tableau comparatif dans le format demandé.
    Les valeurs sont déjà extraites : changer de format ne relance JAMAIS l'IA.
    """
    fmt = (format or "xlsx").lower().strip()
    if fmt not in FORMATS:
        raise HTTPException(status_code=400, detail=f"Format inconnu : {fmt} (attendu : {', '.join(FORMATS)})")

    etat = await _charger_etat(job_id, db)
    colonnes = etat.get("colonnes") or []
    groupes = etat.get("groupes") or []
    if not colonnes or not groupes:
        raise HTTPException(status_code=500, detail="Tableau vide — rien à exporter")

    synthese = etat.get("synthese")
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    titre = "Tableau comparatif"

    cache_fichiers = etat.setdefault("fichiers", {})
    if fmt not in cache_fichiers:
        try:
            if fmt == "md":
                cache_fichiers[fmt] = _construire_markdown(colonnes, groupes, synthese, titre).encode("utf-8")
            elif fmt == "xlsx":
                template_path = await _template_path_pour(etat, db)
                cache_fichiers[fmt] = _generer_xlsx(template_path, groupes, colonnes, synthese)
            elif fmt == "docx":
                cache_fichiers[fmt] = _generer_docx(colonnes, groupes, synthese, titre)
            else:  # pdf
                contenu_md = _construire_markdown(colonnes, groupes, synthese, titre=None)
                cache_fichiers[fmt] = _generer_pdf(contenu_md, titre)
        except ImportError as e:
            log.error("Dépendance manquante pour l'export", format=fmt, erreur=str(e))
            raise HTTPException(status_code=500, detail=f"Dépendance manquante pour l'export {fmt} : {e}")
        except Exception as e:
            log.error("Erreur export comparatif", format=fmt, erreur=str(e), type_err=type(e).__name__)
            raise HTTPException(status_code=500, detail=f"Erreur export {fmt} : {e}")

    media_types = {
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pdf": "application/pdf",
        "md": "text/markdown; charset=utf-8",
    }

    from routers.export import _fichier_reponse
    return _fichier_reponse(cache_fichiers[fmt], f"comparatif_{horodatage}.{fmt}", media_types[fmt])
