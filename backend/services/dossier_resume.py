"""
Résumé IA d'une ressource (IA LOCALE, anti-invention)
=====================================================
Génère une courte description d'une ressource de dossier via **Ollama en local**.
Deux régimes, selon ce dont on dispose :

  - **Condensation** — si la ressource porte déjà du texte (`contenu` long, sinon
    `note`), l'IA le RÉSUME. C'est sûr : elle ne fait que raccourcir un texte fourni.
  - **Description** — s'il n'y a que le titre/auteur, l'IA décrit d'après ses propres
    connaissances, avec consigne STRICTE : dire « non identifiée avec certitude »
    plutôt qu'inventer un synopsis, des faits, des dates ou des noms.

⚠️ L'IA locale n'a **aucun accès web** : elle ne va pas chercher le synopsis en ligne
(pour ça, le clic sur la ressource ouvre déjà Babelio/Allociné…). Le résultat est une
PROPOSITION à valider côté UI, jamais écrite d'office.
"""

from services.ollama_service import avec_usage  # usage IA déclaré (prompts A3b)
from logger import get_logger
from models.dossier import Ressource
from services import prompts, runtime_config
from services.ollama_service import OllamaService

log = get_logger(__name__)

# Prompts (système + gabarit) : registre `services/prompts.py`, clés « dossier.resume_condense » et
# « dossier.resume_decrit » (prompts A3c).

_LABELS = {
    "podcast": "podcast", "chaine": "chaîne", "video": "vidéo", "documentaire": "documentaire",
    "emission": "émission", "film": "film", "serie": "série", "livre": "livre", "bd": "BD",
    "article": "article", "etude": "étude", "rapport": "rapport", "association": "association",
    "prompt": "prompt",
}


@avec_usage("resume")
async def resumer_ressource(r: Ressource) -> str:
    """Retourne un résumé proposé pour la ressource (ne l'enregistre pas)."""
    modele = runtime_config.model_for("enrichissement")

    # Régime CONDENSATION : on privilégie le texte long, sinon une note déjà substantielle.
    texte = (r.contenu or "").strip()
    if not texte and r.note and len(r.note.strip()) > 200:
        texte = r.note.strip()

    if texte:
        prompt = prompts.rendre("dossier.resume_condense.utilisateur", texte=texte[:6000])
        system = prompts.texte("dossier.resume_condense")
    else:
        # Régime DESCRIPTION : uniquement les métadonnées connues, rien d'autre.
        label = _LABELS.get(r.type, r.type)
        lignes = [f"Type : {label}", f"Titre : {r.titre}"]
        if r.auteur:
            lignes.append(f"Auteur / éditeur : {r.auteur}")
        if r.note:
            lignes.append(f"Note existante : {r.note}")
        prompt = prompts.rendre("dossier.resume_decrit.utilisateur", fiche="\n".join(lignes))
        system = prompts.texte("dossier.resume_decrit")

    resume = (await OllamaService().generate(prompt=prompt, model=modele, system=system)).strip()
    log.info("Résumé IA généré", ressource=str(r.id), condense=bool(texte), modele=modele,
             nb_chars=len(resume))
    return resume
