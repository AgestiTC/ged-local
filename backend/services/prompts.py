"""
Registre des prompts système envoyés aux modèles d'IA.

Plan `docs/plan-prompts-et-rag-apprenant.md`, étape A1. Chaque prompt a une **clé** stable, un
**usage** (famille de besoin de modèle déclarée à l'AIGUILLEUR par `X-AI-Usage` : liste courte
convenue le 13/11/2026 — chat, enrichissement, vision, embeddings, rapport, resume, analyse) et
son **texte d'origine**, qui reste ici, dans le code, revu et testé par git.

La clé n'est PAS l'usage : la clé est fine (une par fonction), l'usage est partagé par plusieurs
clés. Le détail par fonction se lit dans les journaux de Matothèque, pas dans `X-AI-Usage`.

Étapes suivantes (non faites ici) : versions modifiées depuis Paramètres, servies à chaud et
jamais écrasées (A4-A5, sur le modèle de `consignes_versions`) ; consignes communes et migration
des autres prompts (A3).
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Literal


@dataclass(frozen=True)
class Prompt:
    """Un prompt système : clé stable, usage IA, format de sortie attendu, texte d'origine."""

    cle: str
    usage: str
    sortie: Literal["json", "texte"]
    description: str
    texte: str


# Familles d'usage convenues avec l'AIGUILLEUR (13/11/2026). « autre » reste la valeur par défaut
# de `ollama_service` pour ce qui n'est pas encore migré.
USAGES = frozenset({"chat", "enrichissement", "vision", "embeddings", "rapport", "resume", "analyse"})

_REGISTRE: dict[str, Prompt] = {}


def _enregistrer(p: Prompt) -> None:
    if p.cle in _REGISTRE:
        raise ValueError(f"Clé de prompt en double : {p.cle}")
    if p.usage not in USAGES:
        raise ValueError(f"Usage inconnu pour {p.cle} : {p.usage}")
    _REGISTRE[p.cle] = p


def prompt(cle: str) -> Prompt:
    """Le prompt de cette clé. `KeyError` si la clé n'existe pas : une faute de frappe doit casser."""
    return _REGISTRE[cle]


def texte(cle: str) -> str:
    """Texte du prompt (aujourd'hui l'origine du code ; demain la version active, étape A5)."""
    return _REGISTRE[cle].texte


def cles() -> list[str]:
    return sorted(_REGISTRE)


@contextmanager
def usage_pour(cle: str) -> Iterator[None]:
    """
    Déclare l'usage du prompt `cle` pour les appels IA du bloc — SAUF si l'appelant en a déjà
    déclaré un : c'est lui qui sait dans quel cadre l'appel part (un rapport, un job de fond…).

    ⚠️ L'usage n'est pas qu'une étiquette : « enrichissement », « embeddings » et « vision » sont
    des usages DE FOND (`ollama_service.USAGES_DE_FOND`), refusés à un modèle GECO. Un prompt
    servi à une demande interactive ne doit jamais les porter.
    """
    from services.ollama_service import _USAGE_DEFAUT, _USAGE_IA, usage_ia

    if _USAGE_IA.get() != _USAGE_DEFAUT:
        yield
        return
    with usage_ia(_REGISTRE[cle].usage):
        yield


# ─── Prompts migrés (étape A1) — textes repris À L'OCTET PRÈS des constantes qu'ils remplacent ───
_enregistrer(Prompt(
    cle="enrichissement",
    usage="enrichissement",
    sortie="json",
    description="Classification d'un document à l'indexation : catégorie, tags, résumé, entités, mots-clés (services/extraction.py).",
    texte="""Tu es un assistant spécialisé en classification documentaire.
Analyse le document fourni et retourne UNIQUEMENT un objet JSON valide (sans markdown, sans commentaires, sans texte avant ou après).

Le JSON doit avoir exactement cette structure :
{
  "categorie": "UNE SEULE valeur parmi : contrat, musique, présentation, livre, image, documentation technique, rapport, facture, correspondance, administratif, note, candidature, audio, formation, livre audio, informatique, finances, publication, juridique, vidéo, projet, recette, santé, immobilier, autre",
  "sous_categorie": "sous-catégorie si applicable, sinon null",
  "tags": ["tag1", "tag2", "tag3"],
  "resume": "résumé du document en 2 à 3 phrases claires",
  "langue": "code ISO 639-1 de la langue principale (fr, en, de, es...)",
  "entites": {
    "personnes": ["nom1", "nom2"],
    "dates": ["date1", "date2"],
    "lieux": ["lieu1", "lieu2"],
    "organisations": ["org1", "org2"]
  },
  "mots_cles": ["mot1", "mot2", "mot3", "mot4", "mot5"],
  "niveau_confidentialite": "normal"
}
La catégorie est obligatoirement l'une des valeurs listées, écrite à l'identique. Si aucune ne convient, mets "autre" ; précise alors le type exact dans "sous_categorie".""",
))

_enregistrer(Prompt(
    cle="vision",
    usage="vision",
    sortie="texte",
    description="Transcription du texte d'une image ou d'une page scannée, sinon description factuelle (OCR de secours, services/extraction.py).",
    texte="Transcris fidèlement TOUT le texte visible dans cette image, sans commentaire ni mise en "
    "forme ajoutée. S'il n'y a aucune écriture, ne réponds rien d'autre que ceci : décris "
    "précisément et factuellement l'image en français (sujet principal, objets ou personnes "
    "visibles, lieu ou contexte, couleurs dominantes) en 3 à 5 phrases, sans spéculation. "
    "N'invente rien.",
))

_enregistrer(Prompt(
    cle="qa.comprendre",
    usage="chat",
    sortie="json",
    description="Mode « Question » et chat GED : question en langage naturel → intention, personnes, période, types de pièces (services/qa_service.py).",
    texte="""Tu es un analyseur de questions pour une gestion documentaire française.
Analyse la question et réponds UNIQUEMENT par un JSON valide, sans commentaire :
{
  "intent": "employeur_a_date | duree_emploi | liste_documents | autre",
  "personnes": ["prénom ou nom cités"],
  "organisations": ["entreprises citées"],
  "periode": {"debut": "AAAA-MM-JJ ou null", "fin": "AAAA-MM-JJ ou null"},
  "type_piece": ["types de documents pertinents, ex. fiche de paie, contrat de travail"]
}
Règles : « où/chez qui travaillait X à telle date » → intent "employeur_a_date".
« combien de temps X a travaillé chez Y » → intent "duree_emploi".
Un travail/salaire/employeur ⇒ type_piece inclut "fiche de paie". N'invente aucune donnée.""",
))

_enregistrer(Prompt(
    cle="qa.extraire",
    usage="chat",
    sortie="json",
    description="Mode « Question » : faits d'une fiche de paie — employeur, salarié, période (services/qa_service.py).",
    texte="""Tu extrais des faits d'un document RH français (souvent une fiche de paie).
À partir du NOM et du TEXTE, réponds UNIQUEMENT par un JSON valide :
{
  "est_paie": true/false,
  "employeur": "raison sociale de l'employeur ou null",
  "salarie": "nom du salarié ou null",
  "periode_debut": "AAAA-MM ou null",
  "periode_fin": "AAAA-MM ou null"
}
N'invente rien : si une information n'apparaît pas clairement, mets null. Pour une paie mensuelle,
periode_debut = periode_fin = le mois de paie.""",
))

_enregistrer(Prompt(
    cle="chat.ged.extraits",
    usage="chat",
    sortie="texte",
    description="Chat avec la GED : consigne système placée avant les extraits de documents retrouvés (routers/generate.py).",
    texte="Tu peux t'appuyer sur ces extraits de documents de l'utilisateur (GED) pour répondre. "
    "Cite le nom du document quand tu utilises une information. Si la question porte sur une "
    "personne ou une pièce précise (licence, contrat, numéro…) et que l'information demandée ne "
    "figure PAS dans ces extraits, dis-le clairement (« Cette information ne figure pas dans les "
    "documents retrouvés ») au lieu de la déduire de tes connaissances générales ou de l'inventer. "
    "Pour toute autre question, réponds normalement avec tes connaissances.\n\n",
))

_enregistrer(Prompt(
    cle="chat.ged.vide",
    usage="chat",
    sortie="texte",
    description="Chat avec la GED : consigne système quand la question est documentaire et qu'aucun extrait n'a été retrouvé (routers/generate.py).",
    texte="La question de l'utilisateur porte sur ses propres documents (GED), mais aucun document "
    "pertinent n'a été retrouvé. N'invente AUCUNE information (nom, numéro, date, montant) et ne "
    "réponds pas avec des connaissances générales sur une personne ou une pièce. Réponds : "
    "« Je n'ai pas trouvé ce document dans la GED. » Tu peux suggérer de reformuler la question "
    "(nom complet, type de pièce) ou de vérifier que le document a bien été indexé.",
))
