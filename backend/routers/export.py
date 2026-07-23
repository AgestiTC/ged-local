"""
Router Export — /api/export
============================
Export de contenu Markdown en PDF ou DOCX.

Endpoints :
  POST /export/pdf    → Markdown → PDF (weasyprint)
  POST /export/docx   → Markdown → DOCX (python-docx)
"""

from datetime import datetime
from io import BytesIO
from urllib.parse import quote

import markdown
from docx import Document as DocxDocument
from docx.shared import Pt
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from logger import get_logger

log = get_logger(__name__)
router = APIRouter()


def _fichier_reponse(data: bytes, nom_fichier: str, media_type: str) -> Response:
    """
    Renvoie des octets en pièce jointe téléchargeable, SANS écrire sur disque.
    Évite toute dépendance aux droits du montage `storage/exports` (le conteneur tourne en
    uid 10001 ; un montage root donnait « Permission denied » au `doc.save()`). `filename*`
    encode l'UTF-8 pour les accents.
    """
    dispo = f"attachment; filename*=UTF-8''{quote(nom_fichier)}"
    return Response(content=data, media_type=media_type, headers={"Content-Disposition": dispo})


class ExportRequest(BaseModel):
    content: str = Field(..., min_length=1, description="Contenu Markdown à exporter")
    title: str = Field(default="Rapport DocFlow AI", description="Titre du document")


def _nom_export(title: str, extension: str) -> str:
    """Génère un nom de fichier propre pour l'export."""
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title)
    safe = safe.strip().replace(" ", "_")[:50]
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{safe}_{horodatage}.{extension}"


@router.post("/export/pdf")
async def export_pdf(request: ExportRequest):
    """
    Convertit du Markdown en PDF et retourne le fichier.
    Utilise weasyprint via HTML comme intermédiaire.
    """
    try:
        from weasyprint import HTML
    except ImportError:
        raise HTTPException(status_code=500, detail="weasyprint non installé")

    nom_fichier = _nom_export(request.title, "pdf")

    # Convertir Markdown → HTML
    contenu_html = markdown.markdown(
        request.content,
        extensions=["tables", "fenced_code", "nl2br"],
    )

    # Template HTML minimal avec styles CSS
    html_complet = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>{request.title}</title>
  <style>
    body {{
      font-family: 'Helvetica Neue', Arial, sans-serif;
      font-size: 11pt;
      line-height: 1.6;
      color: #1a1a1a;
      max-width: 800px;
      margin: 40px auto;
      padding: 0 20px;
    }}
    h1 {{ font-size: 22pt; color: #1a1a2e; border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }}
    h2 {{ font-size: 16pt; color: #374151; margin-top: 24px; }}
    h3 {{ font-size: 13pt; color: #4b5563; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th, td {{ border: 1px solid #d1d5db; padding: 8px 12px; text-align: left; }}
    th {{ background-color: #f3f4f6; font-weight: 600; }}
    code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 3px; font-size: 10pt; }}
    pre {{ background: #f3f4f6; padding: 16px; border-radius: 6px; overflow-x: auto; }}
    blockquote {{ border-left: 4px solid #d1d5db; padding-left: 16px; color: #6b7280; margin: 16px 0; }}
    @page {{ margin: 2cm; }}
  </style>
</head>
<body>
  <h1>{request.title}</h1>
  {contenu_html}
</body>
</html>"""

    try:
        # write_pdf() sans cible RETOURNE les octets → aucune écriture disque.
        pdf_bytes = HTML(string=html_complet).write_pdf()
    except Exception as e:
        log.error("Erreur génération PDF", erreur=str(e), type_err=type(e).__name__)
        raise HTTPException(status_code=500, detail=f"Erreur génération PDF : {e}")

    log.info("PDF généré", fichier=nom_fichier, octets=len(pdf_bytes))
    return _fichier_reponse(pdf_bytes, nom_fichier, "application/pdf")


@router.post("/export/docx")
async def export_docx(request: ExportRequest):
    """
    Convertit du Markdown en DOCX et retourne le fichier.
    Conversion basique : titres, paragraphes, listes.
    """
    nom_fichier = _nom_export(request.title, "docx")

    try:
        doc = DocxDocument()

        # Titre principal
        titre = doc.add_heading(request.title, level=0)
        titre.style.font.size = Pt(20)

        # Traitement ligne par ligne du Markdown
        lignes = request.content.split("\n")
        i = 0
        while i < len(lignes):
            ligne = lignes[i]

            if ligne.startswith("### "):
                doc.add_heading(ligne[4:].strip(), level=3)
            elif ligne.startswith("## "):
                doc.add_heading(ligne[3:].strip(), level=2)
            elif ligne.startswith("# "):
                doc.add_heading(ligne[2:].strip(), level=1)
            elif ligne.startswith("- ") or ligne.startswith("* "):
                # Liste à puces
                texte = ligne[2:].strip()
                p = doc.add_paragraph(texte, style="List Bullet")
            elif ligne.startswith("> "):
                # Citation
                p = doc.add_paragraph(ligne[2:].strip())
                p.style = doc.styles["Intense Quote"] if "Intense Quote" in doc.styles else p.style
            elif ligne.strip() == "":
                # Ligne vide : espace entre paragraphes
                pass
            elif ligne.startswith("---") or ligne.startswith("==="):
                # Séparateur — ignorer
                pass
            else:
                # Paragraphe normal
                if ligne.strip():
                    doc.add_paragraph(ligne.strip())

            i += 1

        # Sauvegarde EN MÉMOIRE (BytesIO) → aucune écriture disque, aucun droit requis.
        buf = BytesIO()
        doc.save(buf)
        docx_bytes = buf.getvalue()

    except Exception as e:
        log.error("Erreur génération DOCX", erreur=str(e), type_err=type(e).__name__)
        raise HTTPException(status_code=500, detail=f"Erreur génération DOCX : {e}")

    log.info("DOCX généré", fichier=nom_fichier, octets=len(docx_bytes))
    return _fichier_reponse(
        docx_bytes, nom_fichier,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
