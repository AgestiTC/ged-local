"""
Grille apprise par l'IA locale (04/11/2026 : « il faut que Matothèque soit autonome »)
====================================================================================
Les règles de `grille_analyse.detecter_grille` ne connaissent que les dispositions déjà vues. Pour
une grille d'une forme nouvelle, Matothèque :

1. décrit le classeur à SON IA locale (texte des cellules, cases vides, formules — rien ne sort
   du réseau local) et lui demande OÙ sont les critères, les cases d'avis et de note, et les
   colonnes des candidats ;
2. VÉRIFIE la réponse sur le classeur (`valider`) : une case à remplir doit être vide et sans
   formule, un critère doit avoir un libellé. Réponse invalide = second essai, avec le motif
   renvoyé à l'IA ; sinon refus explicite, jamais une grille remplie au hasard ;
3. MÉMORISE la structure validée, sous l'empreinte de la grille (`empreinte`) : les intitulés de
   la colonne A, sans chiffres. La grille du marché suivant, de même forme (MA26051…), est
   reconnue sans IA.

La structure ne contient que des coordonnées : ni nom de candidat, ni contenu d'offre.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from logger import get_logger
from services.grille_analyse import Bloc, Critere, Grille, NOTE_MAX_DEFAUT, _echelle, _norm, _ouvrir, lire_bareme

log = get_logger(__name__)

CLE_CONFIG = "grilles_apprises"     # table config : liste JSON des structures validées
APPRISES_MAX = 50
LIGNES_PLAN = 80                    # au-delà, une grille d'analyse n'a plus d'en-tête à découvrir
COLONNES_PLAN = 20
TEXTE_PLAN = 60
ESSAIS = 2


# ─── Empreinte : reconnaître la MÊME forme d'un marché à l'autre ─────────────

def empreinte(ws) -> str:
    """
    Hash des intitulés de la colonne A (sans chiffres ni ponctuation) : stable d'un marché à l'autre
    (« MA26049 » / « MA26050 », « n°1 »…), indépendant des noms des candidats (en colonnes).
    """
    morceaux = []
    for r in range(1, min(ws.max_row, LIGNES_PLAN) + 1):
        texte = re.sub(r"[^a-z]+", " ", _norm(ws.cell(row=r, column=1).value)).strip()
        if texte:
            morceaux.append(texte)
    return hashlib.sha256("\n".join(morceaux).encode()).hexdigest()[:24]


# ─── Plan du classeur, pour l'IA ─────────────────────────────────────────────

def plan_classeur(ws) -> str:
    """Une ligne par ligne non vide : `L4: A="Candidats" | B="…" | C=<nombre> | D=<formule>`."""
    lignes = []
    for r in range(1, min(ws.max_row, LIGNES_PLAN) + 1):
        cellules = []
        for c in range(1, min(ws.max_column, COLONNES_PLAN) + 1):
            v = ws.cell(row=r, column=c).value
            if v in (None, ""):
                continue
            lettre = ws.cell(row=r, column=c).column_letter
            if isinstance(v, str) and v.startswith("="):
                cellules.append(f"{lettre}=<formule>")
            elif isinstance(v, (int, float)):
                cellules.append(f"{lettre}=<nombre>")
            else:
                texte = " ".join(str(v).split())[:TEXTE_PLAN]
                cellules.append(f'{lettre}="{texte}"')
        if cellules:
            lignes.append(f"L{r}: " + " | ".join(cellules))
    return "\n".join(lignes)


PROMPT = """Tu analyses la STRUCTURE d'une grille Excel d'analyse des offres d'un marché public.
Ne juge rien : dis seulement OÙ se trouvent les éléments. Voici la feuille « {feuille} », ligne par
ligne (seules les cellules non vides sont listées ; <nombre> et <formule> masquent leur valeur) :

{plan}

=== CE QU'IL FAUT TROUVER ===
- Les CANDIDATS : en général une ligne d'en-tête qui porte leurs noms (une colonne par candidat),
  ou des blocs de colonnes « Avis / Note » par candidat.
- Les CRITÈRES à évaluer par l'IA : une ligne par critère, avec un libellé, dont les cases des
  candidats sont VIDES. Ignore les lignes déjà remplies (<nombre>), calculées (<formule>), les
  titres de section et les lignes de total / note finale / classement.
- Pour chaque critère : la case de l'AVIS (texte) et la case de la NOTE de chaque candidat. La note
  est parfois sur la même ligne (colonne « Note »), parfois sur la ligne suivante (« Note … sur 25 »).
  Indique l'échelle (« sur 25 » → 25) si elle est écrite.

Réponds UNIQUEMENT par cet objet JSON (numéros de ligne et de colonne : 1 = A, 2 = B…) :
{{"ligne_noms": 4,
  "candidats": [{{"col_avis": 2, "col_note": 2}}],
  "criteres": [{{"ligne": 17, "colonne_libelle": 1, "ligne_note": 18, "note_max": 25}}]}}
- "ligne_noms" : ligne où sont écrits les noms des candidats (null s'il n'y en a pas) ;
- "ligne_note" : null si la note est sur la même ligne que le critère ;
- "note_max" : null si l'échelle n'est pas écrite.{rappel}"""


# ─── Validation sur le classeur ──────────────────────────────────────────────

def _vide(ws, r: int, c: int) -> bool:
    return ws.cell(row=r, column=c).value in (None, "")


def valider(ws, structure: dict | None) -> Grille:
    """Structure proposée → Grille, ou ValueError avec le motif (renvoyé à l'IA au second essai)."""
    if not isinstance(structure, dict):
        raise ValueError("la réponse n'est pas un objet JSON")
    max_r, max_c = ws.max_row, ws.max_column

    def entier(v, nom: str, maxi: int) -> int:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v or not 1 <= int(v) <= maxi:
            raise ValueError(f"« {nom} » = {v!r} n'est pas un numéro valide (1 à {maxi})")
        return int(v)

    ligne_noms = structure.get("ligne_noms")
    ligne_noms = entier(ligne_noms, "ligne_noms", max_r) if ligne_noms is not None else None

    blocs: list[Bloc] = []
    for b in structure.get("candidats") or []:
        if not isinstance(b, dict):
            continue
        col_avis = entier(b.get("col_avis"), "col_avis", max_c)
        col_note = entier(b["col_note"], "col_note", max_c) if b.get("col_note") is not None else None
        nom_cellule, nom = "", ""
        if ligne_noms:
            cellule = ws.cell(row=ligne_noms, column=col_avis)
            nom_cellule = cellule.coordinate
            nom = str(cellule.value).strip() if cellule.value not in (None, "") else ""
        if any(x.col_avis == col_avis for x in blocs):
            continue
        blocs.append(Bloc(nom_cellule=nom_cellule, col_avis=col_avis, col_note=col_note, nom=nom))
    if not blocs:
        raise ValueError("aucune colonne de candidat")

    def est_ligne_de_note(r: int, col: int) -> bool:
        """« Note … sur 25 » aux cases vides : la ligne de NOTE d'un critère, jamais un critère."""
        return _norm(ws.cell(row=r, column=col).value).startswith("note") and all(
            _vide(ws, r, b.col_note or b.col_avis) for b in blocs)

    # Une ligne proposée à tort (déjà remplie, calculée, total, ligne de note…) est ÉCARTÉE, pas
    # fatale : mesuré le 04/11/2026, l'IA locale trouve les bons critères mais y ajoute volontiers
    # des lignes de formules ou de notes. Refus seulement s'il ne reste AUCUN critère valide.
    criteres: list[Critere] = []
    ecartes: list[str] = []
    for c in structure.get("criteres") or []:
        if not isinstance(c, dict):
            continue
        try:
            ligne = entier(c.get("ligne"), "ligne", max_r)
            col_lib = entier(c.get("colonne_libelle") or 1, "colonne_libelle", max_c)
            ligne_note = entier(c["ligne_note"], "ligne_note", max_r) if c.get("ligne_note") is not None else None
            libelle = ws.cell(row=ligne, column=col_lib).value
            if not isinstance(libelle, str) or not libelle.strip():
                raise ValueError(f"ligne {ligne} : pas de libellé de critère en colonne {col_lib}")
            if _norm(libelle).startswith(("total", "note finale", "classement", "notation finale")):
                raise ValueError(f"ligne {ligne} : « {libelle.strip()[:40]} » est un total, pas un critère")
            if _norm(libelle).startswith("note"):
                raise ValueError(f"ligne {ligne} : « {libelle.strip()[:40]} » est une ligne de note, pas un critère")
            # Note annoncée sur la même ligne, mais la ligne suivante est « Note … » : c'est elle.
            if ligne_note in (None, ligne) and ligne < max_r and est_ligne_de_note(ligne + 1, col_lib):
                ligne_note = ligne + 1
            if ligne_note == ligne:
                ligne_note = None
            for b in blocs:
                if not _vide(ws, ligne, b.col_avis):
                    raise ValueError(f"ligne {ligne} : la case d'avis colonne {b.col_avis} n'est pas vide "
                                     "(déjà remplie ou calculée)")
                if b.col_note and not _vide(ws, ligne_note or ligne, b.col_note) and \
                        (ligne_note or b.col_note != b.col_avis):
                    raise ValueError(f"ligne {ligne_note or ligne} : la case de note colonne {b.col_note} n'est pas vide")
        except ValueError as err:
            ecartes.append(str(err))
            continue
        note_max = c.get("note_max")
        note_max = float(note_max) if isinstance(note_max, (int, float)) and not isinstance(note_max, bool) \
            and 0 < note_max <= 1000 else None
        if ligne_note:   # l'échelle écrite sur la ligne de note fait foi (« sur 25 »)
            note_max = _echelle(_norm(ws.cell(row=ligne_note, column=col_lib).value)) or note_max
        if any(x.ligne == ligne for x in criteres):
            continue
        criteres.append(Critere(ligne=ligne, libelle=libelle.strip(), documents="", points=note_max,
                                ligne_note=ligne_note, note_max=note_max))
    if not criteres:
        raise ValueError(ecartes[0] if ecartes else "aucun critère")
    if ecartes:
        log.info("Grille : lignes proposées écartées", nb=len(ecartes), premier=ecartes[0])

    # Noms des candidats : si l'IA n'a pas dit où ils sont, la ligne la plus proche AU-DESSUS du
    # premier critère dont toutes les colonnes de candidats portent du texte.
    if ligne_noms is None:
        for r in range(min(c.ligne for c in criteres) - 1, 0, -1):
            valeurs = [ws.cell(row=r, column=b.col_avis).value for b in blocs]
            if all(isinstance(v, str) and v.strip() and not v.startswith("=") for v in valeurs):
                ligne_noms = r
                break
        if ligne_noms:
            for b in blocs:
                cellule = ws.cell(row=ligne_noms, column=b.col_avis)
                b.nom_cellule, b.nom = cellule.coordinate, str(cellule.value).strip()
    grille_max = max((c.note_max for c in criteres if c.note_max), default=NOTE_MAX_DEFAUT)
    return Grille(feuille=ws.title, ligne_entete=ligne_noms or 1, blocs=blocs, criteres=criteres,
                  note_max=grille_max, bareme=[])


# ─── Mémoire : structures validées ───────────────────────────────────────────

def structure_de(grille: Grille, colonne_libelle: dict[int, int] | None = None) -> dict:
    """Coordonnées seulement (ni nom de candidat, ni contenu) — ce qui est mémorisé."""
    return {
        "ligne_noms": grille.ligne_entete if any(b.nom_cellule for b in grille.blocs) else None,
        "candidats": [{"col_avis": b.col_avis, "col_note": b.col_note} for b in grille.blocs],
        "criteres": [{"ligne": c.ligne, "colonne_libelle": (colonne_libelle or {}).get(c.ligne, 1),
                      "ligne_note": c.ligne_note, "note_max": c.note_max} for c in grille.criteres],
    }


def reconnaitre(chemin: Path, apprises: list[dict]) -> Grille | None:
    """Grille d'une forme déjà apprise (même empreinte), revalidée sur CE classeur ; None sinon."""
    if not apprises:
        return None
    try:
        wb = _ouvrir(chemin)
    except Exception:  # noqa: BLE001 — classeur illisible : rien à reconnaître
        return None
    for ws in wb.worksheets:
        e = empreinte(ws)
        for a in apprises:
            if a.get("empreinte") != e:
                continue
            try:
                grille = valider(ws, a.get("structure") or {})
            except ValueError as err:
                log.info("Grille apprise ne s'applique plus", erreur=str(err))
                continue
            grille.bareme = [b for b in lire_bareme(wb) if 0 <= b["note"] <= grille.note_max]
            return grille
    return None


async def charger(db) -> list[dict]:
    """Structures apprises (table config) ; [] si aucune ou illisible."""
    from sqlalchemy import select
    from models.config import Config
    ligne = (await db.execute(select(Config).where(Config.cle == CLE_CONFIG))).scalar_one_or_none()
    try:
        return list(json.loads(ligne.valeur)) if ligne else []
    except (ValueError, TypeError):
        return []


async def memoriser(db, ws, grille: Grille, colonne_libelle: dict[int, int], modele: str) -> None:
    from sqlalchemy import select
    from models.config import Config
    e = empreinte(ws)
    apprises = [a for a in await charger(db) if a.get("empreinte") != e]
    apprises.insert(0, {
        "empreinte": e, "feuille": ws.title, "structure": structure_de(grille, colonne_libelle),
        "nb_criteres": len(grille.criteres), "modele": modele,
        "appris_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    valeur = json.dumps(apprises[:APPRISES_MAX], ensure_ascii=False)
    ligne = (await db.execute(select(Config).where(Config.cle == CLE_CONFIG))).scalar_one_or_none()
    if ligne:
        ligne.valeur = valeur
    else:
        db.add(Config(cle=CLE_CONFIG, valeur=valeur))
    await db.commit()


# ─── Apprentissage par l'IA locale ───────────────────────────────────────────

def _lire_json(reponse: str) -> dict | None:
    m = re.search(r"\{.*\}", reponse or "", re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(), strict=False)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


async def apprendre(chemin: Path, ollama, model: str, db=None) -> tuple[Grille | None, str]:
    """
    Fait analyser la structure par l'IA locale, la valide, la mémorise (si `db`).
    Rend `(grille, message)` ; grille None = échec, `message` dit pourquoi.
    """
    from services import cause_echec_ia
    try:
        wb = _ouvrir(chemin)
    except Exception as e:  # noqa: BLE001
        return None, f"classeur illisible ({type(e).__name__})"

    motif = "classeur vide"
    for ws in wb.worksheets:
        plan = plan_classeur(ws)
        if not plan:
            continue
        rappel = ""
        for essai in range(1, ESSAIS + 1):
            try:
                reponse = await ollama.generate(PROMPT.format(feuille=ws.title, plan=plan, rappel=rappel),
                                                model=model, format="json", num_predict=2_000)
            except Exception as e:  # noqa: BLE001
                motif = cause_echec_ia.cause_erreur(e)
                log.warning("Grille : apprentissage IA impossible", cause=motif)
                break
            structure = _lire_json(reponse)
            try:
                grille = valider(ws, structure)
            except ValueError as err:
                motif = str(err)
                log.info("Grille : structure proposée invalide", essai=essai, motif=motif)
                rappel = (f"\n\nTA RÉPONSE PRÉCÉDENTE ÉTAIT FAUSSE : {motif}. Corrige-la en relisant "
                          "le plan ci-dessus (une case à remplir est forcément VIDE).")
                continue
            grille.bareme = [b for b in lire_bareme(wb) if 0 <= b["note"] <= grille.note_max]
            colonnes = {int(c["ligne"]): int(c.get("colonne_libelle") or 1)
                        for c in (structure.get("criteres") or []) if isinstance(c, dict)}
            if db is not None:
                await memoriser(db, ws, grille, colonnes, model)
            log.info("Grille apprise par l'IA", feuille=ws.title, nb_criteres=len(grille.criteres),
                     nb_candidats=len(grille.blocs), essai=essai)
            return grille, f"structure apprise par l'IA locale ({model})"
    return None, motif
