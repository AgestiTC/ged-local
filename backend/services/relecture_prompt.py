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

Robustesse (02/11/2026 — « L'IA n'a pas rendu de proposition exploitable » en prod) : ministral-3
rendait `"prompt"` sous forme d'OBJET imbriqué (Rôle / Tâche / Règles / Barème…), long de 3 à 4 000
caractères ; selon le tirage, la réponse était coupée par la limite de tokens ou mal échappée, donc
illisible. Désormais : sortie JSON imposée (`format="json"`), consigne « une seule chaîne de texte »,
un objet rendu malgré tout est remis en texte, marge de tokens relevée, et un second essai.
"""
from __future__ import annotations

import json
import re

from logger import get_logger

log = get_logger(__name__)

MAX_CHARS_PROMPT = 8_000
TOKENS_REPONSE_MAX = 4_000   # un prompt structuré avec barème dépassait 2 500
ESSAIS = 2

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
{{"prompt": "le prompt réécrit", "remarques": ["ce que tu as changé ou ce que l'utilisateur doit compléter, 2 à 5 puces courtes"]}}
La valeur de "prompt" est UNE SEULE CHAÎNE DE TEXTE (sections séparées par des retours à la ligne, par
exemple « Rôle : … »), jamais un objet ni une liste."""


def _en_texte(valeur, niveau: int = 0) -> str:
    """Remet en texte un `prompt` rendu en objet ou en liste (sections, puces), sans rien perdre."""
    retrait = "  " * niveau
    if isinstance(valeur, dict):
        lignes = []
        for cle, v in valeur.items():
            if isinstance(v, (dict, list)):
                lignes += [f"{retrait}{cle} :", _en_texte(v, niveau + 1)]
            else:
                lignes.append(f"{retrait}{cle} : {v}")
        return "\n".join(l for l in lignes if l.strip())
    if isinstance(valeur, list):
        return "\n".join(_en_texte(v, niveau) if isinstance(v, (dict, list)) else f"{retrait}- {v}"
                         for v in valeur if str(v).strip())
    return str(valeur)


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
    brut = data.get("prompt")
    prompt = (_en_texte(brut) if isinstance(brut, (dict, list)) else str(brut or "")).replace("\\n", "\n").strip()
    if not prompt:
        return None
    remarques = data.get("remarques") or []
    if isinstance(remarques, str):
        remarques = remarques.splitlines()
    remarques = [re.sub(r"^\s*[-*•]\s*", "", str(r)).strip() for r in remarques if str(r).strip()][:6]
    return {"prompt": prompt, "remarques": remarques}


async def relire_prompt(texte: str, mode: str | None, model: str, ollama) -> dict | None:
    """Proposition `{prompt, remarques}`, ou None (réponse inexploitable). Les erreurs d'appel remontent."""
    consigne = construire_consigne(texte[:MAX_CHARS_PROMPT], mode)
    for essai in range(1, ESSAIS + 1):
        reponse = await ollama.generate(consigne, model=model, num_predict=TOKENS_REPONSE_MAX, format="json")
        resultat = lire_reponse(reponse)
        if resultat is not None:
            return resultat
        # Jamais le contenu (prompt de l'utilisateur) dans les journaux : la forme seulement.
        log.warning("Relecture de prompt : réponse IA inexploitable", modele=model, essai=essai,
                    nb_chars=len(reponse or ""), finit_par_accolade=(reponse or "").rstrip().endswith("}"))
    return None
