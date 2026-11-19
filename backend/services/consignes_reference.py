"""
Consignes « documents de référence » — rendu du prompt final et garde-fou (étape A6, 18/11/2026)
================================================================================================
Deux consignes de BASE, modifiables et versionnées par /api/consignes (routers/consignes.py) :
l'analyse (fond, forme, pertinence, manques, points forts) et la version corrigée (passages
réécrits, clauses à ajouter). Leurs textes d'ORIGINE sont dans le registre (`services/prompts.py`,
clés `reference.analyse` et `reference.corrigee`) ; avant A6, ils étaient dans le frontend
(`utils/promptAnalyseReference.ts`), qui assemblait aussi le prompt final.

Ce que Matothèque ajoute lui-même, HORS de la partie modifiable : les critères de notation (lus
dans la grille ou saisis) et les instructions complémentaires de l'acheteur — une consigne
modifiée ne peut donc pas les perdre.

Le rendu est IDENTIQUE, à l'octet près, à celui de l'ancien code frontend pour les mêmes entrées
(tests/test_prompts_a6.py, fixture capturée avant la migration).
"""
from __future__ import annotations

import re

from services import prompts

#: Clé de consigne (/api/consignes/{cle}) → clé du registre des prompts.
CLES = prompts.GEREES_PAR_CONSIGNES

MIN_CHARS, MAX_CHARS = 200, 20_000
MIN_SECTIONS = 3

SUFFIXE_INSTRUCTIONS = (
    "\n\nInstructions complémentaires de l'acheteur (à respecter, sans changer la structure ci-dessus) :\n"
)

# Blancs retirés par `String.prototype.trim()` (WhiteSpace + LineTerminator d'ECMAScript). Python
# `str.strip()` n'en retire pas exactement autant (il garde U+FEFF, retire U+001C-U+001F et U+0085) :
# on reproduit le trim du frontend pour que le rendu reste identique à l'octet près.
_BLANCS_JS = ("\t\n\v\f\r            "
              "      　﻿")


def trim_js(texte: str) -> str:
    """Équivalent de `texte.trim()` en JavaScript."""
    return texte.strip(_BLANCS_JS)


def origine(cle: str) -> str:
    """Texte d'origine (celui du code) de la consigne `cle`. `KeyError` si la clé est inconnue."""
    return prompts.prompt(CLES[cle]).texte


def _analyse(corps: str, criteres: list[str]) -> str:
    if not criteres:
        return corps
    liste = "\n".join(f"- {c}" for c in criteres)
    return (f"{corps}\n\nLes offres seront notées sur ces critères :\n{liste}\n"
            "Ajoute, juste avant « 💡 Les 3 actions prioritaires », la section suivante :\n"
            "## 🔗 Cohérence avec les critères de notation\n"
            "Pour chaque critère : ✅ exigences claires et mesurables · ⚠️ à préciser · ❌ rien pour "
            "l'évaluer — avec une phrase d'explication.")


def _corrigee(corps: str, criteres: list[str]) -> str:
    if not criteres:
        return corps
    return (f"{corps}\n\nLes offres seront notées sur : {' ; '.join(criteres)}. "
            "Les exigences liées à ces critères doivent devenir claires et mesurables.")


def rendre(cle: str, corps: str, criteres: list[str], instructions: str = "") -> str:
    """
    Prompt final : la consigne de base `corps` (d'origine ou modifiée), les critères de notation
    s'il y en a, puis les instructions complémentaires si elles ne sont pas vides.
    """
    base = _corrigee(corps, criteres) if cle == "reference_corrigee" else _analyse(corps, criteres)
    complement = trim_js(instructions)
    return f"{base}{SUFFIXE_INSTRUCTIONS}{complement}" if complement else base


def verifier(texte: str, cle: str | None = None) -> list[str]:
    """
    Garde-fou avant d'enregistrer une consigne modifiée : liste des problèmes (vide = accepté).
    Longueur, puis STRUCTURE : au moins MIN_SECTIONS titres « ## » (le rendu visuel et l'export
    reposent sur eux), puis — si `cle` est donnée — les consignes communes de son origine
    (`prompts.GARDE_FOUS`, ici « n'invente rien »), comme pour Paramètres › Prompts système.
    """
    t = texte.strip()
    problemes: list[str] = []
    if len(t) < MIN_CHARS:
        problemes.append(f"Texte trop court ({len(t)} caractères, {MIN_CHARS} au minimum).")
    elif len(t) > MAX_CHARS:
        problemes.append(f"Texte trop long ({len(t)} caractères, {MAX_CHARS} au maximum).")
    sections = len(re.findall(r"^##\s", t, flags=re.MULTILINE))
    if sections < MIN_SECTIONS:
        problemes.append(f"Seulement {sections} section(s) « ## » : la structure du rapport sert au rendu "
                         f"visuel et à l'export — gardez-en au moins {MIN_SECTIONS}.")
    if cle is not None:
        problemes += prompts.garde_fous_retires(origine(cle), t)
    return problemes
