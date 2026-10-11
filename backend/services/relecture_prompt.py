"""
Relecture d'un prompt par l'IA locale — « Faire relire par l'IA ».
==================================================================
Demande du 11/10/2026 : un prompt écrit d'un jet (fautes, consignes mêlées, barème à moitié dit)
est mal suivi par un modèle local. L'IA le réécrit STRUCTURÉ (rôle, tâche, règles, format) sans
en changer l'intention, et liste ce qui manque.

Garde-fous :
  - elle ne doit RIEN inventer : un barème, un chiffre, un nom absents deviennent
    « [à préciser : …] », à compléter par l'utilisateur ;
  - le mode de la page compte : en Tableau comparatif, le prompt ne règle que le CONTENU de chaque
    valeur d'un JSON (le format est imposé par Matothèque) — un prompt qui demande des titres ou
    des tableaux y fait échouer l'extraction (constat du 11/10/2026) ;
  - la proposition n'est jamais appliquée d'office : l'utilisateur choisit (côté interface).
"""
from __future__ import annotations

import json
import re

from logger import get_logger

log = get_logger(__name__)

MAX_CHARS_PROMPT = 8_000
TOKENS_REPONSE_MAX = 2_500

# Ce que le prompt pilote, selon le mode de la page Créer.
_CONTEXTE_MODE = {
    "comparatif": (
        "Ce prompt sert au TABLEAU COMPARATIF de candidats : Matothèque l'applique à CHAQUE candidat "
        "séparément et impose déjà le format de sortie (un objet JSON, une valeur par critère ; les "
        "critères viennent de la grille Excel). Le prompt ne doit donc régler que le CONTENU de chaque "
        "valeur (rôle, règles d'évaluation, barème, justification attendue). Il ne doit PAS demander "
        "de titres, de tableau, d'étapes de rédaction, de total ni de classement."
    ),
    "classement": "Ce prompt sert à classer, trier ou noter des éléments à partir de documents.",
    "reference": (
        "Ce texte COMPLÈTE l'analyse d'un document de référence de marché public (CCTP, règlement "
        "de consultation) : Matothèque impose déjà la structure du rapport (points forts, axes "
        "d'amélioration, manques…). Le texte ne doit donner que des consignes de FOND (points à "
        "vérifier, angle d'analyse, exigences à examiner), pas de structure ni de mise en forme."
    ),
    "remplir_template": "Ce prompt complète le remplissage d'un modèle Word à trous à partir de documents.",
    "wiki": "Ce prompt décrit un tutoriel à rédiger pour un wiki.",
    "rapport_libre": "Ce prompt demande un rapport rédigé à partir des documents sélectionnés.",
}


def construire_consigne(texte: str, mode: str | None) -> str:
    contexte = _CONTEXTE_MODE.get(mode or "", _CONTEXTE_MODE["rapport_libre"])
    return f"""Tu es un expert de la rédaction de prompts pour des modèles de langage LOCAUX (7 à 14 milliards de paramètres), qui suivent mieux des consignes courtes, structurées et sans ambiguïté.

Contexte d'utilisation : {contexte}

Voici le prompt écrit par l'utilisateur, entre les balises :
<prompt>
{texte}
</prompt>

=== TA MISSION ===
Réécris ce prompt pour qu'il soit cohérent, structuré et facile à suivre, en français correct :
- garde EXACTEMENT l'intention, le périmètre et toutes les informations de l'utilisateur (références, barèmes, chiffres, noms) ;
- n'invente AUCUNE information : si un élément nécessaire manque (barème, échelle, référence…), écris « [à préciser : …] » à la place ;
- organise-le en sections courtes, dans cet ordre quand c'est pertinent : Rôle · Tâche · Règles · Barème · Format attendu ;
- consignes à l'impératif, une idée par ligne, sans répétition ; corrige l'orthographe ;
- respecte le contexte d'utilisation ci-dessus.

Réponds UNIQUEMENT par un objet JSON, sans texte autour :
{{"prompt": "le prompt réécrit", "remarques": ["ce que tu as changé ou ce que l'utilisateur doit compléter, 2 à 5 puces courtes"]}}"""


def lire_reponse(reponse: str) -> dict | None:
    """`{"prompt", "remarques"}` ; tolère les retours à la ligne bruts (`strict=False`). None si inexploitable."""
    match = re.search(r"\{.*\}", reponse or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(), strict=False)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    prompt = str(data.get("prompt") or "").replace("\\n", "\n").strip()
    if not prompt:
        return None
    remarques = data.get("remarques") or []
    if isinstance(remarques, str):
        remarques = remarques.splitlines()
    remarques = [re.sub(r"^\s*[-*•]\s*", "", str(r)).strip() for r in remarques if str(r).strip()][:6]
    return {"prompt": prompt, "remarques": remarques}


async def relire_prompt(texte: str, mode: str | None, model: str, ollama) -> dict | None:
    """Proposition `{prompt, remarques}`, ou None (réponse inexploitable). Les erreurs d'appel remontent."""
    reponse = await ollama.generate(construire_consigne(texte[:MAX_CHARS_PROMPT], mode),
                                    model=model, num_predict=TOKENS_REPONSE_MAX)
    resultat = lire_reponse(reponse)
    if resultat is None:
        log.warning("Relecture de prompt : réponse IA inexploitable", modele=model)
    return resultat
