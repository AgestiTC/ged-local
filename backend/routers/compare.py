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
from collections import OrderedDict
from datetime import datetime
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

# L'état d'une comparaison vit EN BASE (table `jobs`), plus en mémoire. Le calcul tourne dans le
# worker durable (job `comparatif`, services/compare_jobs.py) et écrit sa progression dans
# `jobs.resultat["events"]`. Avant (18/09/2026) : un dict par process uvicorn — avec `--workers 2`,
# le suivi ou le téléchargement tombait une fois sur deux sur l'autre process (« Job introuvable »),
# et ce dict n'était jamais purgé.
#   jobs.parametres = {groupes: [{nom, document_ids}], template_id, colonnes, model, instructions, synthese}
#   jobs.resultat   = {events: [...], colonnes, groupes: [{nom, valeurs, echec_ia?}], synthese,
#                      criteres_par_defaut, groupes_en_echec}

# Rendus déjà produits (xlsx/pdf/docx/md) : purement dérivés de `jobs.resultat`, donc un simple
# cache LRU borné par process suffit — un process qui ne l'a pas le recalcule sans relancer l'IA.
_RENDUS_MAX = 32
_rendus: "OrderedDict[tuple[str, str], bytes]" = OrderedDict()

# Valeur inscrite quand l'IA n'a PAS pu extraire un groupe (réponse sans JSON exploitable). Distincte
# de « N/A », qui veut dire « information absente des documents » : les confondre faisait passer un
# échec de l'IA pour un tableau rempli (même classe de bug que l'enrichissement vide du 16/09).
VALEUR_ECHEC_IA = "⚠ Échec de l'IA"

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
) -> tuple[list[str], bool]:
    """
    Demande au LLM de proposer les critères de comparaison pertinents pour ces documents.
    Rend `(colonnes, par_defaut)` : `par_defaut=True` quand l'IA n'a rien proposé d'exploitable et
    qu'on retombe sur COLONNES_FALLBACK — à dire à l'utilisateur plutôt qu'à lui cacher.
    """
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

    reponse = ""
    try:
        reponse = await ollama.generate(prompt, model=model)
        match = re.search(r"\[.*\]", reponse, re.DOTALL)
        if match:
            data = json.loads(match.group())
            colonnes = _nettoyer_colonnes([str(c) for c in data if c])
            if colonnes:
                return colonnes, False
    except Exception as e:  # noqa: BLE001 — appel ou parse KO : repli explicite ci-dessous
        log.warning("Déduction des critères impossible", erreur=str(e))
        return list(COLONNES_FALLBACK), True

    log.warning("Critères : aucune liste exploitable dans la réponse de l'IA — critères par défaut",
                modele=model, reponse=reponse[:200])
    return list(COLONNES_FALLBACK), True


async def _analyser_groupe(
    nom_groupe: str,
    docs: list[Document],
    colonnes: list[str],
    instructions: str | None,
    model: str,
    ollama: OllamaService,
) -> tuple[dict[str, str], bool]:
    """
    Appelle le LLM pour extraire les valeurs des colonnes pour un groupe.
    Rend `({colonne: valeur}, ok)`. Si l'IA n'a rien rendu d'exploitable, `ok=False` et chaque
    cellule vaut VALEUR_ECHEC_IA — jamais « N/A », qui signifie « absent des documents ».
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

    reponse = ""
    try:
        reponse = await ollama.generate(prompt, model=model)
        # Extraire le JSON de la réponse
        match = re.search(r'\{.*\}', reponse, re.DOTALL)
        if match:
            data = json.loads(match.group())
            if isinstance(data, dict) and any(c in data for c in colonnes):
                return {c: str(data.get(c, "N/A")) for c in colonnes}, True
    except Exception as e:  # noqa: BLE001 — appel ou parse KO : échec explicite ci-dessous
        log.warning("Comparatif : extraction IA impossible", groupe=nom_groupe, erreur=str(e))
        return {c: VALEUR_ECHEC_IA for c in colonnes}, False

    log.warning("Comparatif : aucune valeur exploitable dans la réponse de l'IA",
                groupe=nom_groupe, modele=model, reponse=reponse[:200])
    return {c: VALEUR_ECHEC_IA for c in colonnes}, False


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


# Le calcul lui-même (critères → groupes → synthèse) est le handler `comparatif` du worker
# durable : services/compare_jobs.py.


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
    colonnes, par_defaut = await _deduire_colonnes(docs, request.instructions, model, OllamaService())
    log.info("Critères proposés", nb_docs=len(docs), colonnes=colonnes, par_defaut=par_defaut)
    return {"colonnes": colonnes, "model": model, "par_defaut": par_defaut}


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

    # Tâche DURABLE : exécutée par le worker (services/compare_jobs.py), état en base → survit à un
    # redémarrage et reste lisible quel que soit le process uvicorn qui sert le suivi ensuite.
    from services import job_worker
    job_id = await job_worker.enqueue(db, "comparatif", {
        "groupes": [{"nom": g.nom, "document_ids": g.document_ids} for g in request.groupes],
        "template_id": request.template_id,
        "model": model,
        "colonnes": colonnes,
        "criteres_auto": not colonnes,
        "instructions": request.instructions,
        "synthese": request.synthese,
    })
    await db.commit()

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

    def _sse(evt: dict) -> str:
        return f"data: {json.dumps(evt)}\n\n"

    async def event_generator():
        """
        Relit l'état EN BASE à chaque tour : n'importe quel process uvicorn peut servir ce flux.
        Un commentaire SSE part toutes les ~15 s pendant l'attente : sans lui, le proxy nginx
        coupe un flux muet au bout de 60 s alors que la tâche attend son tour dans la file GPU.
        """
        from database import AsyncSessionLocal

        position = 0
        attente, max_attente = 0.0, 3600.0   # la file GPU peut être longue (lots d'analyse d'images)
        depuis_signal = 0.0
        attente_annoncee = False

        while attente < max_attente:
            async with AsyncSessionLocal() as db:
                job = await db.get(Job, uuid.UUID(job_id))
                if job is None or job.type != "comparatif":
                    yield _sse({"statut": "failed", "erreur": "Job introuvable"})
                    return
                statut, erreur = job.statut, job.erreur
                resultat = dict(job.resultat or {})

            if statut == "pending" and not attente_annoncee:
                yield _sse({"statut": "criteres", "message": "En file d'attente — d'autres tâches IA passent avant…"})
                attente_annoncee = True

            events = resultat.get("events") or []
            while position < len(events):
                yield _sse(events[position])
                position += 1
                depuis_signal = 0.0

            if statut == "completed":
                yield _sse({
                    "statut": "complete",
                    "colonnes": resultat.get("colonnes") or [],
                    "resultat_url": f"/api/generate/compare/resultat/{job_id}",
                    "download_url": f"/api/generate/compare/download/{job_id}",
                })
                return
            if statut in ("failed", "cancelled"):
                yield _sse({"statut": "failed",
                            "erreur": erreur or ("Comparaison annulée" if statut == "cancelled" else "Comparaison en échec")})
                return

            await asyncio.sleep(1.0)
            attente += 1.0
            depuis_signal += 1.0
            if depuis_signal >= 15:
                yield ": attente\n\n"   # commentaire SSE : garde la connexion ouverte, ignoré par EventSource
                depuis_signal = 0.0

        yield _sse({"statut": "failed", "erreur": "Délai dépassé — la comparaison continue, rouvrez-la plus tard"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _charger_etat(job_id: str, db: AsyncSession) -> dict:
    """État d'une comparaison terminée, lu en base (`jobs.resultat`) — identique sur tout process."""
    if not _valid_uuid(job_id):
        raise HTTPException(status_code=400, detail="ID invalide")

    result = await db.execute(select(Job).where(Job.id == uuid.UUID(job_id)))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable")
    if job.statut == "failed":
        raise HTTPException(status_code=400, detail=job.erreur or "Comparaison en échec")
    if job.statut != "completed" or not job.resultat:
        raise HTTPException(status_code=400, detail="La comparaison n'est pas encore terminée")

    return {
        "colonnes": job.resultat.get("colonnes", []),
        "groupes": job.resultat.get("groupes", []),
        "synthese": job.resultat.get("synthese"),
        "criteres_par_defaut": job.resultat.get("criteres_par_defaut", False),
        "groupes_en_echec": job.resultat.get("groupes_en_echec", []),
        "template_id": (job.parametres or {}).get("template_id"),
    }


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
        "criteres_par_defaut": etat.get("criteres_par_defaut", False),
        "groupes_en_echec": etat.get("groupes_en_echec", []),
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

    cle = (job_id, fmt)
    if cle in _rendus:
        _rendus.move_to_end(cle)
    else:
        try:
            if fmt == "md":
                contenu = _construire_markdown(colonnes, groupes, synthese, titre).encode("utf-8")
            elif fmt == "xlsx":
                template_path = await _template_path_pour(etat, db)
                contenu = _generer_xlsx(template_path, groupes, colonnes, synthese)
            elif fmt == "docx":
                contenu = _generer_docx(colonnes, groupes, synthese, titre)
            else:  # pdf
                contenu_md = _construire_markdown(colonnes, groupes, synthese, titre=None)
                contenu = _generer_pdf(contenu_md, titre)
            _rendus[cle] = contenu
            while len(_rendus) > _RENDUS_MAX:   # borné : l'ancien cache grossissait sans fin
                _rendus.popitem(last=False)
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
    return _fichier_reponse(_rendus[cle], f"comparatif_{horodatage}.{fmt}", media_types[fmt])
