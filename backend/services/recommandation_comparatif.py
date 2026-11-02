"""
Recommandation de l'IA — page 1 des exports du tableau comparatif.
=====================================================================
Demande du 02/11/2026 : « je voulais avoir le candidat en première page avec les recommandations
de l'IA ». Le fichier final s'ouvrait sur le tableau brut ; la décision (qui retenir, pourquoi, à
quoi faire attention) était dispersée entre synthèse et fiches.

L'IA choisit UN candidat parmi ceux comparés, d'après le tableau DÉJÀ rempli (pas les documents :
rien de nouveau n'est lu), le classement calculé s'il existe, et les consignes de l'utilisateur.
Garde-fous :
  - le candidat rendu doit être l'un des candidats comparés (rapproché sans casse ni accents),
    jamais un candidat en « Échec de l'IA » — sinon pas de recommandation, plutôt qu'une fausse ;
  - c'est une PROPOSITION : chaque rendu le dit (« à valider par la commission ») ;
  - jamais de contenu dans les journaux (offres confidentielles) : la forme seulement.
"""
from __future__ import annotations

import json
import re
import unicodedata

from logger import get_logger

log = get_logger(__name__)

ESSAIS = 2
MAX_PUCES = 5
MAX_CHARS_TABLEAU = 12_000
AVERTISSEMENT = "Proposition de l'IA locale, d'après le tableau comparatif — à valider par la commission."


def _cle(texte) -> str:
    sans_accents = unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", sans_accents.lower())


def _texte(valeur) -> str:
    """Texte brut : le modèle met du gras Markdown (**…**), affiché tel quel dans Word, Excel et l'écran."""
    return re.sub(r"(\*\*|__)(.+?)\1", r"\2", str(valeur or "")).strip()


def _liste(valeur) -> list[str]:
    if isinstance(valeur, str):
        valeur = valeur.splitlines()
    if not isinstance(valeur, list):
        return []
    puces = [re.sub(r"^\s*[-*•]\s*", "", _texte(v)).strip() for v in valeur]   # gras d'abord, puce ensuite
    return [p for p in puces if p][:MAX_PUCES]


def construire_prompt(tableau_md: str, noms: list[str], classement_md: str | None,
                      synthese: str | None, instructions: str | None) -> str:
    consignes = (
        "=== CONSIGNES DE L'ANALYSTE (critères de choix, barème) ===\n"
        f"{instructions.strip()}\n"
        "Applique-les au CHOIX ; le format de ta réponse reste l'objet JSON demandé plus bas.\n\n"
    ) if instructions and instructions.strip() else ""
    bloc_classement = f"=== CLASSEMENT CALCULÉ (notes) ===\n{classement_md.strip()}\n\n" if classement_md else ""
    bloc_synthese = f"=== SYNTHÈSE DES ÉCARTS ===\n{synthese.strip()}\n\n" if synthese else ""
    liste_noms = ", ".join(f'"{n}"' for n in noms)
    return f"""{consignes}Voici le tableau comparatif des candidats, déjà rempli :

{tableau_md[:MAX_CHARS_TABLEAU]}

{bloc_classement}{bloc_synthese}=== TA TÂCHE ===
Recommande UN SEUL candidat parmi : {liste_noms}.
Appuie-toi UNIQUEMENT sur le tableau ci-dessus : chaque chiffre, atout ou réserve doit s'y lire.
N'invente rien (pas de plafond, d'exclusion ni de garantie absents du tableau) ; texte simple, sans Markdown.
- « candidat » : le nom EXACT d'un des candidats ci-dessus ;
- « pourquoi » : 2 à 4 phrases, chiffres du tableau à l'appui ;
- « atouts » : 2 à {MAX_PUCES} puces courtes ;
- « vigilance » : 0 à 3 puces (réserves, points à faire préciser avant de signer) ;
- « alternative » : le second choix et en une phrase dans quel cas le préférer, ou "" s'il n'y en a pas.

Réponds UNIQUEMENT par cet objet JSON, sans texte autour :
{{"candidat": "…", "pourquoi": "…", "atouts": ["…"], "vigilance": ["…"], "alternative": "…"}}"""


def lire_recommandation(reponse: str, noms: list[str]) -> dict | None:
    """Recommandation lue, ou None (illisible, ou candidat hors de la liste)."""
    match = re.search(r"\{.*\}", reponse or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(), strict=False)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    par_cle = {_cle(n): n for n in noms}
    candidat = par_cle.get(_cle(data.get("candidat") or ""))
    pourquoi = _texte(data.get("pourquoi"))
    if not candidat or not pourquoi:
        return None
    return {
        "candidat": candidat,
        "pourquoi": pourquoi,
        "atouts": _liste(data.get("atouts")),
        "vigilance": _liste(data.get("vigilance"))[:3],
        "alternative": _texte(data.get("alternative")),
    }


async def recommander(tableau_md: str, groupes: list[dict], classement_md: str | None,
                      synthese: str | None, instructions: str | None, model: str, ollama) -> dict | None:
    """Recommandation, ou None (moins de deux candidats exploitables, ou IA sans réponse utile)."""
    noms = [g.get("nom") for g in groupes if g.get("nom") and not g.get("echec_ia")]
    if len(noms) < 2:
        return None
    prompt = construire_prompt(tableau_md, noms, classement_md, synthese, instructions)
    for essai in range(1, ESSAIS + 1):
        try:
            reponse = await ollama.generate(prompt, model=model, format="json")
        except Exception as e:  # noqa: BLE001 — la recommandation est un plus : le tableau reste
            log.warning("Recommandation : appel IA impossible", essai=essai, erreur=str(e) or type(e).__name__)
            continue
        reco = lire_recommandation(reponse, noms)
        if reco is not None:
            return reco
        log.warning("Recommandation : réponse IA inexploitable", essai=essai, modele=model,
                    longueur=len(reponse or ""))
    return None


# ─── Rendus (page 1 des exports) ─────────────────────────────────────────────

SAUT_DE_PAGE_HTML = '<div style="page-break-after: always"></div>'


def recommandation_markdown(reco: dict | None, saut_de_page: bool = False) -> str:
    if not reco:
        return ""
    lignes = ["## Candidat recommandé", "", f"### {reco['candidat']}", "", reco["pourquoi"], ""]
    if reco.get("atouts"):
        lignes += ["**Atouts**", ""] + [f"- {a}" for a in reco["atouts"]] + [""]
    if reco.get("vigilance"):
        lignes += ["**Points de vigilance**", ""] + [f"- {v}" for v in reco["vigilance"]] + [""]
    if reco.get("alternative"):
        lignes += [f"**Alternative** : {reco['alternative']}", ""]
    lignes += [f"*{AVERTISSEMENT}*"]
    if saut_de_page:
        lignes += ["", SAUT_DE_PAGE_HTML]
    return "\n".join(lignes)


def ajouter_recommandation_docx(doc, reco: dict | None) -> None:
    """Page 1 du Word : recommandation, puis saut de page avant le tableau."""
    if not reco:
        return
    doc.add_heading("Candidat recommandé", level=1)
    doc.add_heading(reco["candidat"], level=2)
    doc.add_paragraph(reco["pourquoi"])
    for titre, puces in (("Atouts", reco.get("atouts")), ("Points de vigilance", reco.get("vigilance"))):
        if puces:
            doc.add_paragraph().add_run(titre).bold = True
            for p in puces:
                doc.add_paragraph(p, style="List Bullet")
    if reco.get("alternative"):
        para = doc.add_paragraph()
        para.add_run("Alternative : ").bold = True
        para.add_run(reco["alternative"])
    doc.add_paragraph().add_run(AVERTISSEMENT).italic = True
    doc.add_page_break()


def ajouter_feuille_recommandation(wb, reco: dict | None) -> None:
    """Classeur : feuille « Recommandation » placée EN PREMIER et ouverte par défaut."""
    if not reco:
        return
    from openpyxl.styles import Alignment, Font

    ws = wb.create_sheet("Recommandation", 0)
    ws.column_dimensions["A"].width = 110
    lignes: list[tuple[str, Font | None]] = [
        ("Candidat recommandé", Font(bold=True, size=14)),
        (reco["candidat"], Font(bold=True, size=12)),
        ("", None),
        (reco["pourquoi"], None),
    ]
    for titre, puces in (("Atouts", reco.get("atouts")), ("Points de vigilance", reco.get("vigilance"))):
        if puces:
            lignes += [("", None), (titre, Font(bold=True))] + [(f"• {p}", None) for p in puces]
    if reco.get("alternative"):
        lignes += [("", None), (f"Alternative : {reco['alternative']}", None)]
    lignes += [("", None), (AVERTISSEMENT, Font(italic=True))]
    for i, (texte, police) in enumerate(lignes, start=1):
        cellule = ws.cell(row=i, column=1, value=texte)
        cellule.alignment = Alignment(wrap_text=True, vertical="top")
        if police:
            cellule.font = police
    for feuille in wb.worksheets:   # une seule feuille sélectionnée, sinon Excel les groupe
        feuille.sheet_view.tabSelected = feuille is ws
    wb.active = 0
