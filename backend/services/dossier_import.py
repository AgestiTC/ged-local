"""
Import IA — transforme une réponse d'IA web en ressources structurées
=====================================================================
L'utilisateur lance un prompt dans une IA connectée au web (Claude, ChatGPT, Perplexity…),
copie la réponse (souvent un tableau markdown), et la colle ici. On la donne à l'**IA LOCALE
(Ollama)** non pas pour chercher, mais pour **PARSER** le texte en ressources structurées.

⚠️ Aucune invention : l'IA locale n'extrait QUE ce qui figure dans le texte fourni (surtout
pour les URL — on ne veut pas de lien inventé). Le résultat est un APERÇU à valider côté UI.
"""

from services.ollama_service import avec_usage  # usage IA déclaré (prompts A3b)
import json

from logger import get_logger
from services import prompts, runtime_config
from services.ollama_service import OllamaService

log = get_logger(__name__)

_TYPES = {
    "podcast", "chaine", "video", "documentaire", "emission", "film", "serie",
    "livre", "bd", "article", "etude", "rapport", "association", "prompt",
}

def _prompt(texte: str) -> str:
    """Gabarit du registre (prompts A3c) ; le prompt système est la clé « dossier.import_ressources »."""
    return prompts.rendre("dossier.import_ressources.utilisateur", texte=texte[:20000])


def _nettoyer(it: dict) -> dict | None:
    """Normalise une ressource brute du LLM (types bornés, champs sûrs). None si inexploitable."""
    if not isinstance(it, dict):
        return None
    titre = str(it.get("titre") or "").strip()
    if not titre:
        return None
    t = str(it.get("type") or "article").strip().lower()
    if t not in _TYPES:
        t = "article"
    tags = it.get("tags") or []
    if not isinstance(tags, list):
        tags = []

    def _opt(v) -> str | None:
        s = str(v).strip() if v is not None else ""
        return s or None

    return {
        "titre": titre[:500],
        "auteur": _opt(it.get("auteur")),
        "type": t,
        "url": _opt(it.get("url")),
        "note": _opt(it.get("note")),
        "groupe": _opt(it.get("groupe")),
        "tags": [str(x).strip() for x in tags if str(x).strip()][:5],
        "langue": "fr",
    }


@avec_usage("analyse")
async def parser_ressources(texte: str) -> list[dict]:
    """Parse le texte collé en liste de ressources (via l'IA locale). Ne crée rien en base."""
    modele = runtime_config.model_for("enrichissement")
    brut = await OllamaService().generate(prompt=_prompt(texte), model=modele,
                                          system=prompts.texte("dossier.import_ressources"), format="json")
    try:
        data = json.loads(brut)
    except (ValueError, TypeError):
        log.warning("Import IA — sortie non-JSON", extrait=brut[:200])
        return []
    items = data.get("ressources") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    out = [r for it in items if (r := _nettoyer(it))]
    log.info("Import IA — ressources extraites", nb=len(out), modele=modele)
    return out
