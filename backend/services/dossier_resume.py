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

from logger import get_logger
from models.dossier import Ressource
from services import runtime_config
from services.ollama_service import OllamaService

log = get_logger(__name__)

_SYSTEM_CONDENSE = (
    "Tu résumes en français un texte fourni, en 2 à 3 phrases claires. Tu ne dis QUE ce qui "
    "figure dans le texte : aucune information ajoutée, aucune invention."
)

_SYSTEM_DECRIT = (
    "Tu rédiges en français une courte description factuelle d'une ressource documentaire "
    "(livre, film, podcast, article…), en 2 à 3 phrases. RÈGLE ABSOLUE : tu ne dis QUE ce dont "
    "tu es sûr. Si tu n'identifies pas la ressource avec certitude, réponds exactement "
    "« Ressource non identifiée avec certitude — vérifier via la source. » sans inventer de "
    "synopsis, de dates, de personnages ni de noms."
)

_LABELS = {
    "podcast": "podcast", "chaine": "chaîne", "video": "vidéo", "documentaire": "documentaire",
    "emission": "émission", "film": "film", "serie": "série", "livre": "livre", "bd": "BD",
    "article": "article", "etude": "étude", "rapport": "rapport", "association": "association",
    "prompt": "prompt",
}


async def resumer_ressource(r: Ressource) -> str:
    """Retourne un résumé proposé pour la ressource (ne l'enregistre pas)."""
    modele = runtime_config.model_for("enrichissement")

    # Régime CONDENSATION : on privilégie le texte long, sinon une note déjà substantielle.
    texte = (r.contenu or "").strip()
    if not texte and r.note and len(r.note.strip()) > 200:
        texte = r.note.strip()

    if texte:
        prompt = f"Résume ce texte en 2 à 3 phrases :\n\n\"\"\"\n{texte[:6000]}\n\"\"\""
        system = _SYSTEM_CONDENSE
    else:
        # Régime DESCRIPTION : uniquement les métadonnées connues, rien d'autre.
        label = _LABELS.get(r.type, r.type)
        lignes = [f"Type : {label}", f"Titre : {r.titre}"]
        if r.auteur:
            lignes.append(f"Auteur / éditeur : {r.auteur}")
        if r.note:
            lignes.append(f"Note existante : {r.note}")
        prompt = (
            "Décris brièvement la ressource suivante (2 à 3 phrases). Si tu ne la connais pas "
            "avec certitude, dis-le au lieu d'inventer.\n\n" + "\n".join(lignes)
        )
        system = _SYSTEM_DECRIT

    resume = (await OllamaService().generate(prompt=prompt, model=modele, system=system)).strip()
    log.info("Résumé IA généré", ressource=str(r.id), condense=bool(texte), modele=modele,
             nb_chars=len(resume))
    return resume
