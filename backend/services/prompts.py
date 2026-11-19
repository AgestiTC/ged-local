"""
Registre des prompts système envoyés aux modèles d'IA.

Plan `docs/plan-prompts-et-rag-apprenant.md`, étape A1. Chaque prompt a une **clé** stable, un
**usage** (famille de besoin de modèle déclarée à l'AIGUILLEUR par `X-AI-Usage` : liste courte
convenue le 13/11/2026 — chat, enrichissement, vision, embeddings, rapport, resume, analyse) et
son **texte d'origine**, qui reste ici, dans le code, revu et testé par git.

La clé n'est PAS l'usage : la clé est fine (une par fonction), l'usage est partagé par plusieurs
clés. Le détail par fonction se lit dans les journaux de Matothèque, pas dans `X-AI-Usage`.

Versions modifiées depuis Paramètres › Prompts (étapes A4-A5) : table `prompts_versions`, jamais
d'écrasement (`texte` NULL = revenir à l'origine), servies à chaud — chaque processus relit la
version active au plus toutes les 2 s (`rafraichir_si_perime`, middleware `reglages_frais` ; ~10 s
dans le worker). Sans version en base, le texte servi est l'origine du code, à l'octet près.
"""
from __future__ import annotations

import asyncio
import re
import string
import time
import unicodedata
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
    #: Champs `{nom}` du gabarit, remplis par `rendre()` (étape A3c). Vide = texte LITTÉRAL : ses
    #: accolades (exemples JSON) ne sont pas doublées et `rendre(cle)` le rend tel quel. Non vide =
    #: gabarit `str.format` : les accolades littérales y sont doublées (`{{ }}`).
    variables: tuple[str, ...] = ()


# Familles d'usage convenues avec l'AIGUILLEUR (13/11/2026). « autre » reste la valeur par défaut
# de `ollama_service` pour ce qui n'est pas encore migré.
USAGES = frozenset({"chat", "enrichissement", "vision", "embeddings", "rapport", "resume", "analyse"})

_REGISTRE: dict[str, Prompt] = {}


def champs_du_gabarit(gabarit: str) -> tuple[str, ...]:
    """Noms des champs `{nom}` / `{nom:spec}` d'un gabarit `str.format`, dans l'ordre, sans doublon."""
    vus: list[str] = []
    for _, nom, _, _ in string.Formatter().parse(gabarit):
        if nom is not None and nom not in vus:
            vus.append(nom)
    return tuple(vus)


def _enregistrer(p: Prompt) -> None:
    if p.cle in _REGISTRE:
        raise ValueError(f"Clé de prompt en double : {p.cle}")
    if p.usage not in USAGES:
        raise ValueError(f"Usage inconnu pour {p.cle} : {p.usage}")
    if p.variables and set(champs_du_gabarit(p.texte)) != set(p.variables):
        raise ValueError(f"Variables déclarées ≠ champs du gabarit pour {p.cle}")
    _REGISTRE[p.cle] = p


def prompt(cle: str) -> Prompt:
    """Le prompt de cette clé. `KeyError` si la clé n'existe pas : une faute de frappe doit casser."""
    return _REGISTRE[cle]


def texte(cle: str) -> str:
    """Texte ACTIF du prompt : la version enregistrée depuis Paramètres (A5), sinon l'origine du code."""
    p = _REGISTRE[cle]
    return _SURCHARGES.get(cle, p.texte)


def rendre(cle: str, **variables) -> str:
    """
    Texte du prompt `cle`, gabarit rempli avec `variables` (étape A3c). Contrôle STRICT : une
    variable manquante lève `KeyError`, une variable en trop `ValueError` — une faute de frappe
    doit casser, pas envoyer un prompt amputé. Sans variable déclarée : le texte tel quel.
    """
    p = _REGISTRE[cle]
    attendues, recues = set(p.variables), set(variables)
    if recues - attendues:
        raise ValueError(f"Variables inconnues pour {cle} : {sorted(recues - attendues)}")
    if attendues - recues:
        raise KeyError(f"Variables manquantes pour {cle} : {sorted(attendues - recues)}")
    if not p.variables:
        return texte(cle)
    actif = _SURCHARGES.get(cle)
    if actif is not None:
        try:
            return actif.format_map(variables)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as e:
            # Contrôlée à l'enregistrement, une version ne devrait pas échouer ici. Si c'est le cas
            # (valeur d'un type inattendu pour un format), on sert l'origine : jamais d'exception
            # chez l'appelant à cause d'une version modifiée.
            _journal().warning("Version de prompt inutilisable au rendu — origine servie",
                               cle=cle, version=_VERSIONS.get(cle), erreur=str(e) or type(e).__name__)
    return p.texte.format_map(variables)


def cles() -> list[str]:
    return sorted(_REGISTRE)


# ─── Versions modifiées depuis Paramètres › Prompts (étapes A4-A5) ───────────────────────────────

LONGUEUR_MIN, LONGUEUR_MAX = 20, 20_000
FRAICHEUR_S = 2.0

# Cache PAR PROCESSUS de la version active de chaque clé modifiée (rechargé depuis la base) :
#  - `_SURCHARGES` : clé → texte servi (seulement les versions actives VALIDES et non « origine ») ;
#  - `_VERSIONS`   : clé → numéro de la version active en base (même « origine » ou ignorée) ;
#  - `_IGNOREES`   : clé → (version, raison) d'une version active qui ne respecte plus le contrat.
_SURCHARGES: dict[str, str] = {}
_VERSIONS: dict[str, int] = {}
_IGNOREES: dict[str, tuple[int, str]] = {}
_charge_le = float("-inf")
_verrou: asyncio.Lock | None = None


def _journal():
    from logger import get_logger
    return get_logger(__name__)


# ─── Consignes communes : garde-fous, pas fragments (décision de Thomas, 19/11/2026) ─────────────
# Le plan prévoyait des fragments partagés (`commun.json_strict`…). Relevé du 19/11 : ces consignes ne
# sont recopiées À L'IDENTIQUE dans aucun prompt — chacune est cousue au sien (clés JSON attendues, « la
# note EN PREMIER », « n'invente aucune valeur (délai, montant…) »). Les factoriser aurait changé le
# texte envoyé de 25 à 30 prompts. On garde donc les textes, et on VÉRIFIE : une version modifiée
# depuis Paramètres doit conserver chaque consigne commune présente dans l'origine de sa clé.

@dataclass(frozen=True)
class GardeFou:
    nom: str
    libelle: str
    pourquoi: str
    motif: str   # expression régulière sur la forme normalisée (`_forme`)


GARDE_FOUS: tuple[GardeFou, ...] = (
    GardeFou("json_strict", "Réponse en JSON seul",
             "le code lit la réponse comme un objet JSON : sans cette consigne, le modèle ajoute du texte "
             "autour et la réponse devient illisible. Gardez une phrase comme « Réponds UNIQUEMENT par un "
             "objet JSON ».",
             r"(uniquement|seulement|exclusivement|que le|qu un)\b[^.\n]{0,80}\bjson\b"
             r"|\bjson\b[^.\n]{0,80}(rien d autre|sans texte|sans explication|uniquement|seulement)"),
    GardeFou("ne_rien_inventer", "Ne rien inventer",
             "sans elle, le modèle comble les trous avec des informations plausibles mais fausses. Gardez "
             "une phrase comme « N'invente rien ».",
             r"invent|n ajoutes? aucun|aucune information ajoutee"),
    GardeFou("francais", "Réponse en français",
             "sans elle, certains modèles répondent en anglais. Gardez « en français ».",
             r"\ben francais\b"),
)


def _forme(texte: str) -> str:
    """Minuscules, sans accents, apostrophes et tirets remplacés par des espaces. PURE."""
    s = unicodedata.normalize("NFKD", (texte or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[ \t]+", " ", re.sub(r"['’\-]+", " ", s))


def garde_fous_presents(texte: str) -> tuple[GardeFou, ...]:
    """Consignes communes présentes dans `texte`. PURE."""
    f = _forme(texte)
    return tuple(g for g in GARDE_FOUS if re.search(g.motif, f))


def garde_fous_retires(origine: str, candidat: str) -> list[str]:
    """Raisons de refus : une consigne commune de `origine` absente de `candidat` (vide = rien de retiré)."""
    gardes = {g.nom for g in garde_fous_presents(candidat)}
    return [f"Consigne retirée : « {g.libelle} » — {g.pourquoi}"
            for g in garde_fous_presents(origine) if g.nom not in gardes]


def garde_fous_de(cle: str) -> tuple[GardeFou, ...]:
    """Consignes communes que toute version de `cle` doit garder (celles de son origine)."""
    return garde_fous_presents(_REGISTRE[cle].texte)


def _contrat_forme(cle: str, candidat: str | None) -> list[str]:
    """
    Raisons pour lesquelles `candidat` ne peut pas devenir le texte du prompt `cle` (liste vide =
    accepté). `KeyError` si la clé est inconnue. Contrat :
      - longueur entre LONGUEUR_MIN (hors blancs) et LONGUEUR_MAX caractères ;
      - prompt avec variables : gabarit `str.format` lisible (pas d'accolade orpheline), dont les
        champs sont EXACTEMENT les variables déclarées — ni manquante, ni en trop ; un format
        (`{x:g}`) n'est admis que s'il existe déjà dans l'origine pour cette variable ;
      - prompt sans variable : texte littéral, accolades permises (`rendre` le renvoie tel quel) ;
      - consignes communes de l'origine conservées (`GARDE_FOUS` : JSON seul, ne rien inventer,
        en français) — une version qui en retire une est refusée.
    """
    p = _REGISTRE[cle]
    erreurs: list[str] = []
    if candidat is None or len(candidat.strip()) < LONGUEUR_MIN:
        return [f"Texte trop court : au moins {LONGUEUR_MIN} caractères (hors espaces). "
                "Pour repartir du texte du code, utilisez « Revenir à l'origine »."]
    if len(candidat) > LONGUEUR_MAX:
        erreurs.append(f"Texte trop long : {len(candidat)} caractères (au plus {LONGUEUR_MAX}).")
    if not p.variables:
        return erreurs
    try:
        champs = list(string.Formatter().parse(candidat))
    except ValueError as e:
        erreurs.append(f"Accolade orpheline ou mal formée ({e}). Les variables s'écrivent {{nom}} ; "
                       "une accolade littérale s'écrit doublée : {{ ou }}.")
        return erreurs
    formats_origine: dict[str, set[tuple[str | None, str]]] = {}
    for _, nom, spec, conv in string.Formatter().parse(p.texte):
        if nom is not None:
            formats_origine.setdefault(nom, set()).add((conv, spec or ""))
    vus: list[str] = []
    for _, nom, spec, conv in champs:
        if nom is None:
            continue
        if nom not in vus:
            vus.append(nom)
        forme = (conv, spec or "")
        if nom in p.variables and forme != (None, "") and forme not in formats_origine.get(nom, set()):
            erreurs.append(f"Format non prévu pour {{{nom}}} : écrivez simplement {{{nom}}}.")
    manquantes = [v for v in p.variables if v not in vus]
    en_trop = [v for v in vus if v not in p.variables]
    if manquantes:
        erreurs.append("Variable(s) manquante(s) : " + ", ".join("{" + v + "}" for v in manquantes)
                       + ". Le code les remplit : elles doivent toutes rester dans le texte.")
    if en_trop:
        noms = ", ".join("{" + v + "}" for v in en_trop)
        erreurs.append(f"Variable(s) inconnue(s) : {noms}. Variables permises : "
                       + ", ".join("{" + v + "}" for v in p.variables)
                       + ". Pour écrire une accolade littérale, doublez-la : {{ ou }}.")
    return erreurs


def verifier_contrat(cle: str, candidat: str | None) -> list[str]:
    """Contrat complet (`_contrat_forme` puis consignes communes) ; liste vide = accepté."""
    erreurs = _contrat_forme(cle, candidat)
    if candidat is None or len(candidat.strip()) < LONGUEUR_MIN:
        return erreurs
    return erreurs + garde_fous_retires(_REGISTRE[cle].texte, candidat)


def appliquer_versions_actives(actives: dict[str, tuple[int, str | None]]) -> None:
    """
    Remplace le cache par `actives` (clé → (version, texte|None) de la plus haute version en base).
    Une clé inconnue du code est ignorée ; une version qui ne respecte plus le contrat (le code a
    changé ses variables depuis) est IGNORÉE — l'origine est servie — et journalisée une fois.
    """
    global _SURCHARGES, _VERSIONS, _IGNOREES
    surcharges: dict[str, str] = {}
    versions: dict[str, int] = {}
    ignorees: dict[str, tuple[int, str]] = {}
    for cle, (version, txt) in actives.items():
        if cle not in _REGISTRE:
            continue
        versions[cle] = version
        if txt is None:
            continue
        erreurs = verifier_contrat(cle, txt)
        if erreurs:
            ignorees[cle] = (version, " ".join(erreurs))
            if _IGNOREES.get(cle) != ignorees[cle]:
                _journal().warning("Version de prompt hors contrat — ignorée, origine servie",
                                   cle=cle, version=version, raison=ignorees[cle][1])
            continue
        surcharges[cle] = txt
    _SURCHARGES, _VERSIONS, _IGNOREES = surcharges, versions, ignorees


async def charger(db) -> None:
    """Relit la version active de chaque clé depuis `prompts_versions`. LAISSE REMONTER une erreur de lecture."""
    global _charge_le
    from sqlalchemy import func, select

    from models.prompt_version import PromptVersion

    plus_hautes = (select(PromptVersion.cle, func.max(PromptVersion.version).label("v"))
                   .group_by(PromptVersion.cle).subquery())
    lignes = (await db.execute(
        select(PromptVersion.cle, PromptVersion.version, PromptVersion.texte)
        .join(plus_hautes, (PromptVersion.cle == plus_hautes.c.cle) & (PromptVersion.version == plus_hautes.c.v))
    )).all()
    appliquer_versions_actives({c: (v, t) for c, v, t in lignes})
    _charge_le = time.monotonic()


async def recharger(db=None) -> None:
    """Relit les versions actives MAINTENANT. Ne lève jamais : un échec garde le cache."""
    global _charge_le
    try:
        if db is not None:
            await charger(db)
        else:
            from database import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                await charger(session)
    except Exception as e:  # noqa: BLE001 — la fraîcheur du cache passe après l'appel en cours
        _charge_le = time.monotonic()   # on ne retente qu'après FRAICHEUR_S : pas de martèlement
        _journal().warning("Relecture des prompts impossible — cache conservé",
                           erreur=str(e) or type(e).__name__)


async def rafraichir_si_perime(db=None) -> None:
    """Relit les versions actives si le cache a plus de FRAICHEUR_S secondes (même règle que `runtime_config`)."""
    global _verrou
    if time.monotonic() - _charge_le < FRAICHEUR_S:
        return
    if _verrou is None:
        _verrou = asyncio.Lock()
    async with _verrou:
        if time.monotonic() - _charge_le < FRAICHEUR_S:
            return
        await recharger(db)


def vider_cache() -> None:
    """Oublie toutes les versions (tests) : le texte servi redevient l'origine du code."""
    global _charge_le
    appliquer_versions_actives({})
    _charge_le = float("-inf")


def version_servie(cle: str) -> int:
    """Version servie par CE processus : 0 = origine du code (jamais modifiée, revenue à l'origine,
    ou version active ignorée car hors contrat)."""
    return _VERSIONS.get(cle, 0) if cle in _SURCHARGES else 0


def version_ignoree(cle: str) -> tuple[int, str] | None:
    """(version, raison) si la version active de `cle` est ignorée car hors contrat."""
    return _IGNOREES.get(cle)


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


# ─── Prompts migrés (étape A3c, 18/11/2026) — texte envoyé identique À L'OCTET PRÈS ───────────────
# Vérifié par tests/test_prompts_a3c.py contre la capture faite AVANT la migration
# (tests/donnees/prompts_origine_a3c.json). L'usage de chaque clé est celui que déclare déjà la
# fonction qui envoie (`@avec_usage` ou `with usage_ia(…)`, étape A3b). Les morceaux CONDITIONNELS
# (consignes de l'utilisateur présentes ou non, barème, exigences…) restent bâtis par l'appelant et
# arrivent ici en variables, déjà mis en forme.

_enregistrer(Prompt(
    cle="assistant.pieces",
    usage="analyse",
    sortie="json",
    description="Assistant de dossier : types de pièces attendues pour un besoin (routers/assistant.py, proposer_pieces).",
    texte="""Tu es un assistant de gestion documentaire.
À partir du besoin de l'utilisateur, liste les TYPES DE PIÈCES / DOCUMENTS attendus pour
constituer ce dossier (termes courts et génériques, en français).
Réponds UNIQUEMENT par un JSON valide : {{"pieces": ["...", "...", ...]}}.
Maximum 8 pièces, du plus important au moins important.

Besoin : {besoin}""",
    variables=("besoin",),
))

_enregistrer(Prompt(
    cle="wiki.emplacement",
    usage="analyse",
    sortie="json",
    description="Publication BookStack : titre de page et livre/chapitre où la ranger (routers/bookstack.py, suggest).",
    texte="""Tu organises un wiki de documentation technique (BookStack).

Livres existants :
{lignes_livres}

Chapitres existants :
{lignes_chapitres}

Contenu à publier (extrait) :
\"\"\"
{extrait}
\"\"\"

Tâche : propose un titre de page court et explicite, et le meilleur emplacement.
- Si un livre existant convient thématiquement, renvoie son identifiant dans "book_id".
- Sinon, propose le nom d'un nouveau livre dans "nouveau_livre" (et laisse "book_id" à null).
- Tu peux proposer un nom de chapitre dans "chapitre" (sinon null).
Réponds UNIQUEMENT en JSON avec les clés exactes :
{{"titre": str, "book_id": int|null, "nouveau_livre": str|null, "chapitre": str|null, "raison": str}}""",
    variables=("lignes_livres", "lignes_chapitres", "extrait"),
))

_enregistrer(Prompt(
    cle="comparatif.criteres",
    usage="analyse",
    sortie="json",
    description="Tableau comparatif : critères de comparaison proposés pour les documents (routers/compare.py, _deduire_colonnes).",
    texte="""{consignes}Voici des extraits de documents qui vont être comparés entre eux :

{contexte}

=== TA TÂCHE ===
Propose entre 5 et 10 CRITÈRES DE COMPARAISON pertinents pour ce type de document.
Un critère = un libellé court (2 à 6 mots), factuel, comparable d'un document à l'autre.
Exemple pour des contrats d'assurance : "Prime annuelle", "Franchise", "Plafond d'indemnisation",
"Garanties incluses", "Exclusions", "Délai de carence", "Conditions de résiliation".

Réponds UNIQUEMENT par cet objet JSON, sans texte autour :
{{"criteres": ["Critère 1", "Critère 2", "Critère 3"]}}""",
    variables=("consignes", "contexte"),
))

_enregistrer(Prompt(
    cle="comparatif.colonnes",
    usage="analyse",
    sortie="json",
    description="Tableau comparatif : valeur de chaque critère pour un candidat/groupe (routers/compare.py, _analyser_groupe).",
    texte="""{consignes}{bloc_exigences}Tu analyses les documents du candidat/société : {nom_groupe}

{contexte_docs}

=== FORMAT DE LA RÉPONSE ===
Extrait les informations suivantes et retourne UNIQUEMENT un objet JSON valide, sans texte avant ni après :
{{
{champs}
}}

Champs à remplir : {colonnes_str}
Si une information est absente ou non trouvée, utilise "N/A".
Ne retourne que le JSON, rien d'autre.{rappel}""",
    variables=("consignes", "bloc_exigences", "nom_groupe", "contexte_docs", "champs", "colonnes_str", "rappel"),
))

_enregistrer(Prompt(
    cle="comparatif.ecarts",
    usage="analyse",
    sortie="texte",
    description="Tableau comparatif : synthèse des écarts entre candidats, en puces (routers/compare.py, _synthetiser_ecarts).",
    texte="""Voici un tableau comparatif déjà rempli :

{tableau}

Rédige une synthèse COURTE des différences entre les entités comparées.
Contraintes :
- 5 à 8 puces Markdown maximum, commençant par « - » ;
- une puce = un écart CONCRET, chiffré quand c'est possible, en nommant les entités concernées ;
- ignore les critères où tout le monde est identique ou en "N/A" ;
- termine par une puce « Points de vigilance » si quelque chose manque ou semble contradictoire ;
- pas d'introduction, pas de conclusion, pas de titre : uniquement les puces.{attentes}""",
    variables=("tableau", "attentes"),
))

_enregistrer(Prompt(
    cle="comparatif.fiche",
    usage="analyse",
    sortie="json",
    description="Tableau comparatif : fiche d'un candidat — résumé, points forts/faibles, vigilance (services/fiches_candidats.py, construire_prompt).",
    texte="""Tu es analyste des offres d'un marché public. Voici l'évaluation, critère par critère, de l'offre du candidat « {nom} » :

{evaluation}
{contexte}
=== CONSIGNE ===
Rédige la fiche de synthèse de CE candidat, en t'appuyant UNIQUEMENT sur l'évaluation ci-dessus (n'invente rien) :
- « resume » : 2 à 4 phrases factuelles sur l'offre ;
- « points_forts » : 2 à {max_puces} puces courtes, techniques ou financières ;
- « points_faibles » : 1 à {max_puces} puces courtes (manques, imprécisions, risques) ;
- « vigilance » : 0 à 3 puces (pièces manquantes, réserves, points à faire préciser).
Réponds UNIQUEMENT par un objet JSON, sans texte autour :
{{"resume": "…", "points_forts": ["…"], "points_faibles": ["…"], "vigilance": ["…"]}}""",
    variables=("nom", "evaluation", "contexte", "max_puces"),
))

_enregistrer(Prompt(
    cle="comparatif.recommandation",
    usage="analyse",
    sortie="json",
    description="Tableau comparatif : candidat recommandé, atouts, vigilance (services/recommandation_comparatif.py, construire_prompt).",
    texte="""{consignes}Voici le tableau comparatif des candidats, déjà rempli :

{tableau}

{bloc_classement}{bloc_synthese}=== TA TÂCHE ===
Recommande UN SEUL candidat parmi : {liste_noms}.
Appuie-toi UNIQUEMENT sur le tableau ci-dessus : chaque chiffre, atout ou réserve doit s'y lire.
N'invente rien (pas de plafond, d'exclusion ni de garantie absents du tableau) ; texte simple, sans Markdown.
- « candidat » : le nom EXACT d'un des candidats ci-dessus ;
- « pourquoi » : 2 à 4 phrases, chiffres du tableau à l'appui ;
- « atouts » : 2 à {max_puces} puces courtes ;
- « vigilance » : 0 à 3 puces (réserves, points à faire préciser avant de signer) ;
- « alternative » : le second choix et en une phrase dans quel cas le préférer, ou "" s'il n'y en a pas.

Réponds UNIQUEMENT par cet objet JSON, sans texte autour :
{{"candidat": "…", "pourquoi": "…", "atouts": ["…"], "vigilance": ["…"], "alternative": "…"}}""",
    variables=("consignes", "tableau", "bloc_classement", "bloc_synthese", "liste_noms", "max_puces"),
))

_enregistrer(Prompt(
    cle="grille.critere",
    usage="analyse",
    sortie="json",
    description="Grille d'analyse des offres : note et avis d'un candidat sur un critère (services/grille_analyse.py, evaluer_critere).",
    texte="""Tu es analyste des offres d'un marché public. Candidat évalué : {candidat}.

Critère à noter :
{libelle}
{pieces}{bloc_exigences}{bloc_bareme}
Documents de l'offre du candidat :
{contexte}

=== CONSIGNE ===
Évalue l'offre de « {candidat} » sur le critère ci-dessus, en t'appuyant UNIQUEMENT sur ces documents.
{consigne_note}{rappel_bareme}
- « avis » : 6 phrases AU MAXIMUM (moins de 900 caractères), factuelles, en français — points forts,
  points faibles, éléments manquants, en citant les pièces. Si une pièce attendue est absente, dis-le.
  Pas de titres ni de listes à puces : un paragraphe, c'est le contenu d'une cellule Excel.
{consigne_exigences}{consignes_utilisateur}
Les consignes de l'analyste règlent le CONTENU de l'avis ; elles ne changent pas ce format :
« note » est un NOMBRE seul (ex. 15, jamais « 15/{note_max:g} »), « avis » est du texte.
Réponds UNIQUEMENT par un objet JSON, la note EN PREMIER, sans texte autour : {{"note": 7, "avis": "…"}}""",
    variables=("candidat", "libelle", "pieces", "bloc_exigences", "bloc_bareme", "contexte", "consigne_note",
               "rappel_bareme", "consigne_exigences", "consignes_utilisateur", "note_max"),
))

_enregistrer(Prompt(
    cle="grille.structure",
    usage="analyse",
    sortie="json",
    description="Grille Excel d'analyse : où sont les candidats, les critères, les cases d'avis et de note (services/grille_apprise.py, apprendre).",
    texte="""Tu analyses la STRUCTURE d'une grille Excel d'analyse des offres d'un marché public.
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
- "note_max" : null si l'échelle n'est pas écrite.{rappel}""",
    variables=("feuille", "plan", "rappel"),
))

_enregistrer(Prompt(
    cle="rapport.systeme",
    usage="rapport",
    sortie="texte",
    description="Rapport libre : prompt système (français, Markdown, pas de raisonnement affiché) (services/rapport_jobs.py ; ex-SYSTEM_RAPPORT de routers/generate.py).",
    texte=(
        "Tu es un assistant qui rédige des rapports en FRANÇAIS à partir de documents fournis. "
        "Réponds DIRECTEMENT avec le rapport final, en français, au format Markdown. "
        "N'affiche JAMAIS ton raisonnement, tes étapes de réflexion, ni de préambule "
        "(pas de « thinking process », pas de balises <think>, pas de méta-commentaire). "
        "Commence tout de suite par le contenu demandé."
    ),
))

_enregistrer(Prompt(
    cle="regroupement.defaut",
    usage="rapport",
    sortie="texte",
    description="Analyse d'un regroupement : consigne par défaut quand le groupe n'en a pas (services/regroupement_jobs.py).",
    texte="Analyse et synthétise ces documents de façon structurée.",
))

_enregistrer(Prompt(
    cle="idees.bilan",
    usage="rapport",
    sortie="texte",
    description="Bilan « Idées d'évolution » tiré des instructions complémentaires de la période (services/idees_evolution.py, construire_prompt).",
    texte="""Tu es conseiller produit de Matothèque, une GED 100 % locale qui aide un acheteur public à analyser ses documents de référence (CCTP, règlement de consultation) et les offres des candidats.

Voici les instructions complémentaires que l'acheteur a données sur la période « {periode} » ({nb_demandes} demande(s)) :
{demandes}

Rédige un bilan court, clair et visuel, en t'appuyant UNIQUEMENT sur ces demandes (n'invente aucun besoin).
Pas de tableau Markdown : titres, listes et pictogrammes. Respecte EXACTEMENT cette structure :

# 🔔 Idées d'évolution — {periode}

## 🧭 En bref
Deux phrases : ce que l'acheteur cherche le plus à contrôler.

## 🔁 Ce qui revient souvent
3 à 5 puces : le sujet, puis « ×N » (nombre de demandes qui l'abordent).

## 💡 Idées d'évolution pour Matothèque
3 à 5 idées, classées 🔴 forte valeur · 🟠 utile · 🟢 bonus. Chacune : un titre en gras, puis le bénéfice concret pour l'acheteur.

## 📋 Prompts à enregistrer
1 à 3 consignes réutilisables, rédigées et prêtes à copier, chacune dans un bloc de citation (> …).""",
    variables=("periode", "nb_demandes", "demandes"),
))

_enregistrer(Prompt(
    cle="presentation.slides",
    usage="rapport",
    sortie="json",
    description="Présentation : diapositives (titre + points) bâties depuis des documents (services/presentation_service.py, generer_slides).",
    texte="""Tu es un assistant qui crée des présentations professionnelles claires.
À partir des documents fournis, génère une présentation structurée en diapositives.
Réponds UNIQUEMENT par un objet JSON valide (sans markdown), de la forme :
{{
  "titre": "Titre de la présentation",
  "theme": "un thème en 1-3 mots",
  "slides": [
    {{"titre": "Titre de la diapo", "points": ["point clé 1", "point clé 2", "..."]}}
  ]
}}
Règles : 6 à 12 diapositives, 3 à 6 points par diapo, concis et factuel, en français.
Première diapo = introduction/contexte, dernière = synthèse/conclusion.{consigne}

Documents :
{contexte}""",
    variables=("consigne", "contexte"),
))

_enregistrer(Prompt(
    cle="modele.remplissage",
    usage="rapport",
    sortie="json",
    description="Modèle Word à trous : valeur de chaque champ tirée des documents (services/template_filler.py, TemplateFiller.fill).",
    texte="""\
Tu dois remplir un modèle de document professionnel.

Voici les documents source à analyser :
{contexte}

Instructions supplémentaires : {instructions}

Tu dois retourner un objet JSON contenant les valeurs pour chaque champ du template.
Champs à remplir : {champs}

Règles :
- Retourne UNIQUEMENT un objet JSON valide, sans explication ni markdown
- Si un champ ne peut pas être rempli, utilise une chaîne vide ""
- Sois précis et professionnel dans les valeurs
- Adapte le style au type de document

Réponds avec uniquement le JSON :""",
    variables=("contexte", "instructions", "champs"),
))

_enregistrer(Prompt(
    cle="modeles.resume_hf",
    usage="resume",
    sortie="texte",
    description="Catalogue Hugging Face : ce que fait un modèle, en français, d'après son README (routers/huggingface.py, model_detail).",
    texte="Résume en FRANÇAIS, en 1 à 2 phrases claires, CE QUE FAIT ce modèle d'IA "
    "(sa fonction, ses points forts). Réponds directement, sans introduction ni "
    "formule de politesse.\n\n"
    "Nom : {nom}\nType : {type_pipeline}\n"
    "Description (souvent en anglais) :\n{description}",
    variables=("nom", "type_pipeline", "description"),
))

_enregistrer(Prompt(
    cle="modeles.resume_local",
    usage="resume",
    sortie="texte",
    description="Tableau des modèles : une phrase sur un modèle local non répertorié, d'après ses seuls faits (routers/system.py, _resume_ia).",
    texte="Décris en UNE phrase de moins de 25 mots, en français, à quoi sert ce modèle d'IA locale, "
    "à partir de ces seuls faits. N'évalue NI sa qualité NI sa vitesse, n'invente aucune "
    "information, ne cite aucune source. Réponds par la phrase seule.\n\n"
    "nom : {nom} · {parametres} · {taille_go} Go · {quantisation} · {architecture} · capacités : {capacites}",
    variables=("nom", "parametres", "taille_go", "quantisation", "architecture", "capacites"),
))

_enregistrer(Prompt(
    cle="rangement.dossiers",
    usage="analyse",
    sortie="json",
    description="Réorganisation GED : nom de dossier cible pour chaque catégorie (routers/organize.py, _proposer_dossiers).",
    texte="Tu organises une GED. Voici les catégories de documents détectées :\n"
    "{categories}"
    ".\n\nConsigne utilisateur : "
    "{consigne}"
    ".\n\nRéponds UNIQUEMENT en JSON : "
    '{{"criteres": "<phrase expliquant le rangement>", '
    '"dossiers": {{"<catégorie>": "<NomDossier>"}}}} '
    "où chaque catégorie reçoit un nom de dossier court et lisible (sans accent ni slash).",
    variables=("categories", "consigne"),
))

_enregistrer(Prompt(
    cle="rangement.plan",
    usage="analyse",
    sortie="json",
    description="Rangement du NAS : dossier du plan de classement pour un élément, d'après ses métadonnées (services/rangement/plan.py, proposer_par_ia).",
    texte="Tu ranges le NAS d'une famille. Voici les dossiers cibles possibles (le plan de classement) :\n"
    "{liste}\n\nÉlément à placer :\n"
    "- nom : {nom}\n- chemin actuel : {chemin}\n"
    "- {nature} de {taille}\n"
    "- contenu dominant : {famille}\n"
    "{exemples}{placement}"
    "\nChoisis LE dossier cible le plus adapté, en recopiant exactement un chemin de la liste. "
    "Si rien ne convient, réponds \"{a_trier}\". Réponds UNIQUEMENT en JSON : "
    '{{"destination": "<chemin>", "raison": "<une phrase>", "confiance": <nombre entre 0 et 1>}}',
    variables=("liste", "nom", "chemin", "nature", "taille", "famille", "exemples", "placement", "a_trier"),
))

_enregistrer(Prompt(
    cle="dossier.import_ressources",
    usage="analyse",
    sortie="json",
    description="Dossiers : prompt système de l'import d'une réponse d'IA web en ressources (services/dossier_import.py, parser_ressources).",
    texte=(
        "Tu extrais des ressources documentaires d'un texte fourni. Tu n'inventes RIEN : tu n'extrais "
        "que ce qui est écrit, en particulier les URL. Tu réponds UNIQUEMENT en JSON valide."
    ),
))

_enregistrer(Prompt(
    cle="dossier.import_ressources.utilisateur",
    usage="analyse",
    sortie="json",
    description="Dossiers : gabarit de l'import — texte collé → liste de ressources (services/dossier_import.py, parser_ressources).",
    texte="""Extrais les ressources (podcasts, vidéos/chaînes, documentaires, films, livres, BD, articles,
études, rapports, associations…) présentes dans le TEXTE ci-dessous — c'est souvent un tableau
markdown produit par une IA.

Rends UNIQUEMENT un objet JSON de la forme :
{{"ressources": [{{"titre": str, "auteur": str|null, "type": str, "url": str|null, "note": str|null, "groupe": str|null, "tags": [str]}}]}}

Règles :
- "type" parmi : podcast, chaine, video, documentaire, emission, film, serie, livre, bd, article, etude, rapport, association, prompt. Déduis-le du contexte ; défaut "article".
- "url" : UNIQUEMENT si un lien figure dans le texte. Ne l'invente JAMAIS ; sinon null.
- "note" : la phrase qui décrit ce que la ressource apporte (résumé court).
- "groupe" : la catégorie/section du texte (titre de tableau, de section…) si présente.
- "tags" : 1 à 3 mots-clés.
- N'invente AUCUNE ressource : n'extrais que ce qui figure dans le texte.

TEXTE :
\"\"\"
{texte}
\"\"\"""",
    variables=("texte",),
))

_enregistrer(Prompt(
    cle="dossier.resume_condense",
    usage="resume",
    sortie="texte",
    description="Dossiers : prompt système du résumé d'une ressource qui porte déjà du texte (services/dossier_resume.py, resumer_ressource).",
    texte=(
        "Tu résumes en français un texte fourni, en 2 à 3 phrases claires. Tu ne dis QUE ce qui "
        "figure dans le texte : aucune information ajoutée, aucune invention."
    ),
))

_enregistrer(Prompt(
    cle="dossier.resume_condense.utilisateur",
    usage="resume",
    sortie="texte",
    description="Dossiers : gabarit du résumé d'une ressource qui porte déjà du texte (services/dossier_resume.py, resumer_ressource).",
    texte="Résume ce texte en 2 à 3 phrases :\n\n\"\"\"\n{texte}\n\"\"\"",
    variables=("texte",),
))

_enregistrer(Prompt(
    cle="dossier.resume_decrit",
    usage="resume",
    sortie="texte",
    description="Dossiers : prompt système de la description d'une ressource connue par son seul titre — anti-invention (services/dossier_resume.py, resumer_ressource).",
    texte=(
        "Tu rédiges en français une courte description factuelle d'une ressource documentaire "
        "(livre, film, podcast, article…), en 2 à 3 phrases. RÈGLE ABSOLUE : tu ne dis QUE ce dont "
        "tu es sûr. Si tu n'identifies pas la ressource avec certitude, réponds exactement "
        "« Ressource non identifiée avec certitude — vérifier via la source. » sans inventer de "
        "synopsis, de dates, de personnages ni de noms."
    ),
))

_enregistrer(Prompt(
    cle="dossier.resume_decrit.utilisateur",
    usage="resume",
    sortie="texte",
    description="Dossiers : gabarit de la description d'une ressource (type, titre, auteur, note) (services/dossier_resume.py, resumer_ressource).",
    texte="Décris brièvement la ressource suivante (2 à 3 phrases). Si tu ne la connais pas "
    "avec certitude, dis-le au lieu d'inventer.\n\n{fiche}",
    variables=("fiche",),
))

_enregistrer(Prompt(
    cle="version.diff_resume",
    usage="enrichissement",
    sortie="texte",
    description="Nouvelle version d'un document : changements résumés en une phrase (services/extraction.py, _generate_diff_resume).",
    texte="Tu es un assistant de gestion documentaire.\n"
    "Résume EN UNE SEULE PHRASE les changements entre la version précédente et la nouvelle version d'un document.\n\n"
    "Résumé de l'ancienne version :\n{ancien}\n\n"
    "Extrait du nouveau contenu :\n{extrait}\n\n"
    "Réponds uniquement avec la phrase de résumé, sans introduction ni ponctuation finale.",
    variables=("ancien", "extrait"),
))

_enregistrer(Prompt(
    cle="agenda.evenement",
    usage="analyse",
    sortie="json",
    description="Planning : prompt système — phrase libre → événement, sans rien inventer (services/jalon_ia.py, analyser_evenement).",
    texte=(
        "Tu transformes une phrase en événement d'agenda. Tu n'inventes RIEN : tu n'extrais que ce "
        "qui est écrit dans le texte. Tout ce dont tu n'es pas certain vaut null. Tu réponds "
        "UNIQUEMENT en JSON valide."
    ),
))

_enregistrer(Prompt(
    cle="agenda.evenement.utilisateur",
    usage="analyse",
    sortie="json",
    description="Planning : gabarit — date du jour, catégories et texte → titre, date, créneau (services/jalon_ia.py, analyser_evenement).",
    texte="""{contexte}

Transforme le TEXTE ci-dessous en un événement de planning.

Rends UNIQUEMENT un objet JSON de la forme :
{{"titre": str, "detail": str|null, "categorie": str, "date": "AAAA-MM-JJ"|null, "heure_debut": "HH:MM"|null, "heure_fin": "HH:MM"|null, "obligatoire": bool}}

Règles :
- "titre" : court (moins de 80 caractères), nominal, SANS la date ni l'heure.
  Exemple : « Entretien prénatal à la maternité ».
- "categorie" parmi : {categories}. Déduis-la du sujet ; défaut "preparation".
- "date" : uniquement si le texte donne un jour. Utilise la date du jour ci-dessus pour
  résoudre « vendredi prochain », « le 25 septembre » (choisis l'occurrence la plus proche
  d'aujourd'hui). Si aucun jour n'est donné : null. N'invente JAMAIS de date.
- "heure_debut"/"heure_fin" : uniquement si le texte donne une heure. « de 13h à 14h » →
  "13:00" et "14:00". Une seule heure citée → "heure_fin" vaut null.
- "detail" : ce que le texte dit en plus (lieu, interlocuteur, motif), ou null. Ne répète
  ni le titre ni l'horaire.
- "obligatoire" : true SEULEMENT si le texte dit que c'est obligatoire ou légalement dû.

TEXTE :
---
{texte}
---""",
    variables=("contexte", "categories", "texte"),
))

_enregistrer(Prompt(
    cle="musique.style",
    usage="chat",
    sortie="json",
    description="Musique (ACE-Step) : prompt système — style libre → mots-clés anglais, tempo, tonalité, paroles balisées (services/musique_jobs.py, preparer_style).",
    texte=(
        "Tu prépares une demande pour ACE-Step, un modèle qui compose de la musique. Il ne connaît "
        "AUCUN nom d'artiste : il comprend seulement des mots-clés descriptifs en ANGLAIS, séparés "
        "par des virgules (genre, sous-genre, instruments précis, type et timbre de voix, ambiance, "
        "production). Si on te cite un artiste, décris son style sans le nommer. Réponds UNIQUEMENT "
        'par un objet JSON : {"tags": "...", "bpm": entier, "keyscale": "C major" ou "A minor" '
        '(forme note + major/minor), "paroles": "..."}. Pour "paroles" : reprends le texte fourni MOT '
        "POUR MOT, en ajoutant seulement des balises de structure [Verse], [Chorus], [Bridge], [Outro] "
        "sur des lignes à part ; si aucune parole n'est fournie, renvoie une chaîne vide."
    ),
))

_enregistrer(Prompt(
    cle="musique.style.utilisateur",
    usage="chat",
    sortie="json",
    description="Musique (ACE-Step) : gabarit de la demande — style, langue, paroles (services/musique_jobs.py, preparer_style).",
    texte="Style demandé : {style}\nLangue du chant : {langue}\nParoles :\n{paroles}",
    variables=("style", "langue", "paroles"),
))

_enregistrer(Prompt(
    cle="video.mouvement",
    usage="chat",
    sortie="texte",
    description="Vidéo : prompt système, en anglais — scénario français → description du seul MOUVEMENT (services/video_jobs.py, preparer_mouvement).",
    texte=(
        "You write prompts for an image-to-video model that animates a hand-drawn picture. From the "
        "user's French scenario, write ONE English paragraph describing ONLY the MOTION (what moves, "
        "how), in fewer than 80 words. Do not describe the style. Answer with the paragraph only."
    ),
))

_enregistrer(Prompt(
    cle="prompts.relecture",
    usage="chat",
    sortie="json",
    description="« Faire relire par l'IA » : prompt de l'utilisateur réécrit structuré, sans rien inventer (services/relecture_prompt.py, construire_consigne).",
    texte="""Tu es un expert de la rédaction de prompts pour des modèles de langage LOCAUX (7 à 14 milliards de paramètres), qui suivent mieux des consignes courtes, structurées et sans ambiguïté.

Contexte d'utilisation : {contexte}

Voici le prompt écrit par l'utilisateur, entre les balises :
<prompt>
{texte}
</prompt>

=== TA MISSION ===
Réécris ce prompt pour qu'il soit cohérent, structuré et facile à suivre, en français correct :
- garde EXACTEMENT l'intention, le périmètre et toutes les informations de l'utilisateur (références, barèmes, chiffres, noms) ;
- n'invente AUCUNE information : si un élément nécessaire manque (barème, échelle, référence…), écris « [à préciser : …] » à la place ;
- organise-le en sections courtes, dans cet ordre quand c'est pertinent : {sections} ;
{interdit_format}- consignes à l'impératif, une idée par ligne, sans répétition ; corrige l'orthographe ;
- reste CONCIS : {longueur} caractères au plus (un prompt long est moins bien suivi par un modèle local) ;
- respecte le contexte d'utilisation ci-dessus.

Réponds UNIQUEMENT par un objet JSON, sans texte autour :
{{"prompt": "le prompt réécrit", "remarques": ["ce que tu as changé ou ce que l'utilisateur doit compléter, 2 à 5 puces courtes"]}}
La valeur de "prompt" est UNE SEULE CHAÎNE DE TEXTE (sections séparées par des retours à la ligne, par
exemple « Rôle : … »), jamais un objet ni une liste.""",
    variables=("contexte", "texte", "sections", "interdit_format", "longueur"),
))


# ─── Consignes de base « documents de référence » (étape A6, 18/11/2026) ─────────────────────────
# Origines des deux consignes versionnées par /api/consignes (routers/consignes.py), autrefois dans
# le frontend (utils/promptAnalyseReference.ts). Leurs versions vivent dans `consignes_versions`
# (modal « Consignes de base » de la page Créer), PAS dans `prompts_versions` : ces deux clés ne
# se modifient pas depuis Paramètres › Prompts système (`GEREES_PAR_CONSIGNES`).

_enregistrer(Prompt(
    cle="reference.analyse",
    usage="rapport",
    sortie="texte",
    description="Créer › documents de référence : consigne de base « Analyse » (CCTP, règlement…) — versions via le modal « Consignes de base » (routers/consignes.py).",
    texte="""Tu es un expert de la commande publique, bienveillant et précis. Relis le ou les documents de référence fournis (CCTP, règlement de consultation…) et rédige un retour CONSTRUCTIF sur leur fond et leur forme.

Règles :
- appuie chaque remarque sur le document (article, section ou citation courte) ; n'invente rien ;
- si un élément semble manquer, dis « à vérifier » plutôt que d'affirmer qu'il est absent ;
- ton positif et concret : chaque point faible est accompagné d'une proposition d'amélioration ;
- pas de tableau Markdown : titres, listes, emojis et jauges suffisent.

Respecte EXACTEMENT cette structure :

# 📘 Analyse du document de référence

## 🎯 En bref
2 à 3 phrases sur l'objet du document et son niveau de qualité, puis :
**Note globale : X/10** suivie d'une jauge de 10 cases (▰ pleine, ▱ vide), par exemple ▰▰▰▰▰▰▰▱▱▱

## 📊 Tableau de bord
Une ligne par axe, sous la forme « - **Axe** ▰▰▰▰▱ 4/5 — appréciation en une phrase » :
- **Fond** (exigences techniques, précision du besoin)
- **Forme** (structure, lisibilité, vocabulaire)
- **Pertinence** (adéquation au besoin et au marché)
- **Complétude** (rien d'essentiel ne manque)
- **Mesurabilité** (exigences vérifiables, utilisables pour noter les offres)

## ✅ Points forts
3 à 6 puces : ce qui est réussi, et pourquoi c'est utile.

## 🛠️ Axes d'amélioration
Classés par priorité, 🔴 essentiel · 🟠 utile · 🟢 bonus. Chaque puce : le constat, puis « 👉 Proposition : » une reformulation ou un ajout concret.

## 🧩 Points manquants à vérifier
Ce qu'un document de ce type contient habituellement et qui n'apparaît pas (délais, pénalités, niveaux de service, modalités de contrôle, réversibilité…), uniquement si c'est pertinent pour CE marché.

## 💡 Les 3 actions prioritaires
Trois actions numérotées, courtes et concrètes, pour améliorer le document.""",
))

_enregistrer(Prompt(
    cle="reference.corrigee",
    usage="rapport",
    sortie="texte",
    description="Créer › documents de référence : consigne de base « Version corrigée » — versions via le modal « Consignes de base » (routers/consignes.py).",
    texte="""Tu es un rédacteur expert de la commande publique. À partir du ou des documents de référence fournis (CCTP, règlement de consultation…), propose une VERSION CORRIGÉE : ne réécris que ce qui doit changer, dans le style juridique et administratif du document.

Règles :
- cite chaque passage d'origine à l'identique (article ou section) avant de le réécrire ;
- n'invente aucune valeur (délai, montant, pénalité, quantité) : écris « [à préciser : …] » ;
- garde l'intention de l'acheteur ; formulations claires, vérifiables, sans ambiguïté ;
- pas de tableau Markdown : titres, citations, listes et pictogrammes.

Respecte EXACTEMENT cette structure :

# ✍️ Proposition de version corrigée

> ⚠️ Proposition de l'IA, à relire et valider par l'acheteur. Seuls les passages à modifier sont réécrits.

## 🧭 Synthèse des modifications
Une puce par modification : 🔴 essentiel · 🟠 utile · 🟢 bonus, en une ligne.

## ✏️ Passages réécrits
Pour chaque passage :
### 📍 Article ou section concerné — titre court
**Avant :**
> texte d'origine cité
**Après :**
> texte réécrit, prêt à copier
**Pourquoi :** une phrase.

## ➕ Clauses à ajouter
Pour chaque clause manquante : ### 🆕 titre, puis le texte de la clause rédigé et prêt à copier, avec les « [à préciser : …] » nécessaires.

## ✅ Ce qui peut rester tel quel
2 à 4 puces sur les parties déjà solides.""",
))

#: Clés de consigne (/api/consignes/{cle}) → clé du registre. Leurs versions sont gérées par
#: /api/consignes : Paramètres › Prompts système ne les liste pas et refuse de les versionner — une
#: seule porte d'édition, sinon deux historiques concurrents pour le même texte.
GEREES_PAR_CONSIGNES = {"reference_analyse": "reference.analyse", "reference_corrigee": "reference.corrigee"}

# ─── IA internet (étape A6) ──────────────────────────────────────────────────────────────────────

_enregistrer(Prompt(
    cle="internet.formulation",
    usage="chat",
    sortie="texte",
    description="Page « IA internet » : message système du chat local qui aide à FORMULER un prompt de recherche à copier dans une IA web (routers/generate.py, `consigne_systeme` du chat).",
    texte=(
        "Tu es un assistant qui aide à FORMULER un excellent prompt de recherche documentaire, "
        "destiné à être COPIÉ dans une IA connectée au web (Claude, ChatGPT, Perplexity). Tu n'as PAS "
        "accès à Internet et tu ne fais PAS la recherche toi-même : tu produis LE PROMPT à copier. Le "
        "prompt doit demander une liste de ressources (podcasts, vidéos/chaînes, documentaires, films, "
        "livres, BD, articles, études, rapports, associations) avec, pour CHACUNE : titre, auteur/éditeur, "
        "type, URL si elle est connue (sans jamais inventer d'URL), et une phrase de description. Il doit "
        "exiger un rendu en TABLEAU MARKDOWN (colonnes : Titre | Auteur | Type | URL | Description) facile "
        "à copier. Réponds en français, brièvement, puis termine TOUJOURS par le prompt final seul, dans un "
        "bloc de code."
    ),
))
