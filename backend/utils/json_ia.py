"""
Lecture tolérante de l'objet JSON renvoyé par un modèle d'IA.

Plan `docs/plan-prompts-et-rag-apprenant.md`, étape A2 : remplace six implémentations qui
faisaient la même chose avec de petites différences (extraction, présentation, modèle DOCX,
mode Question, assistant, grille apprise).

Un modèle entoure souvent son JSON : bloc ```json, phrase d'introduction, liste autour de
l'objet. On essaie, dans l'ordre, la réponse entière, le contenu d'un bloc ```json, puis le
premier `{` jusqu'au dernier `}` ; on rend le premier candidat qui est un **objet**.

Ce que fait l'appelant d'un échec (lever, rendre `{}`, abandonner) reste son affaire : cette
fonction rend `None`, elle ne décide pas.
"""
from __future__ import annotations

import json
import re

_BLOC = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_OBJET = re.compile(r"\{.*\}", re.DOTALL)


def lire_objet(texte: str | None, *, strict: bool = True) -> dict | None:
    """
    Le premier objet JSON lisible dans `texte`, ou `None`.

    `strict=False` accepte les caractères de contrôle (sauts de ligne bruts) dans les chaînes,
    ce que certains modèles produisent dans de longues valeurs.
    """
    t = (texte or "").strip()
    if not t:
        return None
    candidats = [t]
    if m := _BLOC.search(t):
        candidats.append(m.group(1))
    if m := _OBJET.search(t):
        candidats.append(m.group(0))
    for candidat in candidats:
        try:
            data = json.loads(candidat, strict=strict)
        except ValueError:   # JSONDecodeError en hérite
            continue
        if isinstance(data, dict):
            return data
    return None
