"""
Événement de planning à partir d'un texte libre (IA LOCALE, anti-invention)
===========================================================================
« Entretien prénatal avec la maternité le vendredi 25 septembre de 13h à 14h » →
un titre, une catégorie, une date, un créneau. C'est de la **saisie assistée** : la
proposition remonte à l'écran, l'utilisateur la relit et la corrige, puis enregistre.
Rien n'est écrit en base par ce module.

Une règle gouverne le prompt, et elle tient en une phrase : **n'extraire que ce qui est
écrit**. Un agenda qui invente une heure, une date ou un caractère obligatoire ne se
contente pas d'être faux — il fait manquer un rendez-vous, ou en fait courir un qui
n'existe pas. Le modèle a donc consigne de laisser `null` tout ce dont il n'est pas sûr,
et le nettoyage Python jette tout ce qui ne rentre pas dans le format attendu.

La **date du jour et le terme** lui sont donnés : sans eux, « vendredi prochain » ou
« le 25 septembre » n'ont pas d'année, et il en invente une.

Un **repêchage par expressions régulières** complète les champs que le modèle a laissés
vides (dates « 25/09 », créneaux « de 13h à 14h »). Il ne le contredit jamais : les petits
modèles lisent bien l'intention et ratent souvent le second horaire.
"""

from __future__ import annotations

import json
import re
from datetime import date

from logger import get_logger
from services import runtime_config
from services.jalon_seed import CATEGORIES
from services.ollama_service import OllamaService

log = get_logger(__name__)

_SYSTEM = (
    "Tu transformes une phrase en événement d'agenda. Tu n'inventes RIEN : tu n'extrais que ce "
    "qui est écrit dans le texte. Tout ce dont tu n'es pas certain vaut null. Tu réponds "
    "UNIQUEMENT en JSON valide."
)

_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin",
         "juillet", "août", "septembre", "octobre", "novembre", "décembre"]

_GABARIT = (
    '{"titre": str, "detail": str|null, "categorie": str, "date": "AAAA-MM-JJ"|null, '
    '"heure_debut": "HH:MM"|null, "heure_fin": "HH:MM"|null, "obligatoire": bool}'
)


def _prompt(texte: str, aujourdhui: date, terme: date | None) -> str:
    contexte = [f"Aujourd'hui : {_JOURS[aujourdhui.weekday()]} {aujourdhui.day} "
                f"{_MOIS[aujourdhui.month - 1]} {aujourdhui.year} ({aujourdhui.isoformat()})."]
    if terme:
        contexte.append(f"Date du terme de la grossesse : {terme.isoformat()}.")

    return f"""{" ".join(contexte)}

Transforme le TEXTE ci-dessous en un événement de planning.

Rends UNIQUEMENT un objet JSON de la forme :
{_GABARIT}

Règles :
- "titre" : court (moins de 80 caractères), nominal, SANS la date ni l'heure.
  Exemple : « Entretien prénatal à la maternité ».
- "categorie" parmi : {", ".join(CATEGORIES)}. Déduis-la du sujet ; défaut "preparation".
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
{texte[:4000]}
---"""


def _heure(v) -> str | None:
    """Normalise une heure du modèle en « HH:MM ». Tout le reste est jeté."""
    m = re.fullmatch(r"\s*(\d{1,2})\s*[h:.]?\s*(\d{2})?\s*", str(v or ""))
    if not m:
        return None
    h, mn = int(m.group(1)), int(m.group(2) or 0)
    return f"{h:02d}:{mn:02d}" if h < 24 and mn < 60 else None


_RE_CRENEAU = re.compile(
    r"(?<!\d)(\d{1,2})\s*[h:]\s*(\d{2})?"
    r"(?:\s*(?:à|a|-|–|au?|jusqu'à)\s*(\d{1,2})\s*[h:]\s*(\d{2})?)?",
    re.IGNORECASE)


def _creneau_du_texte(texte: str) -> tuple[str | None, str | None]:
    """Repêche « de 13h à 14h » / « 13:00-14:30 » quand le modèle n'a rien rendu."""
    m = _RE_CRENEAU.search(texte)
    if not m:
        return None, None
    debut = _heure(f"{m.group(1)}:{m.group(2) or '00'}")
    fin = _heure(f"{m.group(3)}:{m.group(4) or '00'}") if m.group(3) else None
    return debut, fin


_RE_DATE_NUM = re.compile(r"(?<!\d)(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?(?!\d)")
_RE_DATE_MOT = re.compile(
    r"(?<!\d)(\d{1,2})(?:er)?\s+(" + "|".join(_MOIS) + r")(?:\s+(\d{4}))?", re.IGNORECASE)


def _annee_la_plus_proche(jour: int, mois: int, aujourdhui: date) -> str | None:
    """
    Année d'une date écrite sans année : celle qui tombe le plus près d'aujourd'hui.

    Un planning contient du passé (« vu le 3 mars ») autant que du futur : forcer l'année
    suivante daterait un rendez-vous d'hier dans onze mois. On prend donc la plus proche
    des trois candidates, ce qui règle aussi le passage de décembre à janvier.
    """
    candidats = []
    for an in (aujourdhui.year - 1, aujourdhui.year, aujourdhui.year + 1):
        try:
            candidats.append(date(an, mois, jour))
        except ValueError:      # 29 février d'une année non bissextile
            continue
    if not candidats:
        return None
    return min(candidats, key=lambda d: abs((d - aujourdhui).days)).isoformat()


def _date_du_texte(texte: str, aujourdhui: date) -> str | None:
    """Repêche « 25/09 », « 25/09/2026 », « 25 septembre » quand le modèle n'a rien rendu."""
    if m := _RE_DATE_NUM.search(texte):
        jour, mois, an = int(m.group(1)), int(m.group(2)), m.group(3)
        if not 1 <= mois <= 12:
            return None
        if not an:
            return _annee_la_plus_proche(jour, mois, aujourdhui)
        annee = int(an)
        annee += 2000 if annee < 100 else 0
        try:
            return date(annee, mois, jour).isoformat()
        except ValueError:
            return None

    if m := _RE_DATE_MOT.search(texte):
        jour = int(m.group(1))
        mois = _MOIS.index(m.group(2).lower()) + 1
        if not m.group(3):
            return _annee_la_plus_proche(jour, mois, aujourdhui)
        try:
            return date(int(m.group(3)), mois, jour).isoformat()
        except ValueError:
            return None

    return None


def _date_valide(v) -> str | None:
    """Date du modèle, gardée seulement si elle est réellement une date ISO."""
    try:
        return date.fromisoformat(str(v).strip()[:10]).isoformat()
    except (ValueError, TypeError):
        return None


def normaliser(data: dict, texte: str, aujourdhui: date) -> dict:
    """
    Proposition propre à partir de la sortie brute du modèle.

    Séparé de l'appel réseau pour être testable sans Ollama — c'est ici que vit tout ce
    qui protège l'agenda (catégorie bornée, date vérifiée, heures rejetées si le jour est
    inconnu), donc c'est ici qu'il faut des tests.
    """
    titre = str(data.get("titre") or "").strip()[:300]
    if not titre:
        # Plutôt que d'échouer : la première ligne du texte fait un titre acceptable, que
        # l'utilisateur voit et corrige. Le reste de l'analyse garde sa valeur.
        titre = (texte.strip().splitlines() or [""])[0][:80]

    categorie = str(data.get("categorie") or "").strip().lower()
    if categorie not in CATEGORIES:
        categorie = "preparation"

    date_reelle = _date_valide(data.get("date")) or _date_du_texte(texte, aujourdhui)
    debut = _heure(data.get("heure_debut"))
    fin = _heure(data.get("heure_fin"))
    if not debut:
        debut, fin_repechee = _creneau_du_texte(texte)
        fin = fin or fin_repechee
    # Une heure sans jour n'a rien à faire dans un agenda : elle laisserait croire à un
    # créneau réservé sur un événement posé au petit bonheur dans son mois.
    if not date_reelle:
        debut = fin = None

    detail = str(data.get("detail") or "").strip() or None
    return {
        "titre": titre,
        "detail": detail[:2000] if detail else None,
        "categorie": categorie,
        "date_reelle": date_reelle,
        "heure_debut": debut,
        # Une fin antérieure au début est une erreur de lecture, pas une durée : on préfère
        # ne rien dire, l'export comptera une heure.
        "heure_fin": fin if (fin and debut and fin > debut) else None,
        "obligatoire": bool(data.get("obligatoire")),
    }


async def analyser_evenement(texte: str, aujourdhui: date, terme: date | None = None) -> dict:
    """
    Propose un événement structuré à partir d'un texte libre. **N'enregistre rien.**

    Lève une exception si l'IA locale est injoignable ou rend un JSON illisible : mieux
    vaut dire « analyse impossible » que présenter un formulaire vide comme un résultat.
    """
    modele = runtime_config.model_for("enrichissement")
    brut = await OllamaService().generate(
        prompt=_prompt(texte, aujourdhui, terme), model=modele, system=_SYSTEM, format="json")

    try:
        data = json.loads(brut)
    except (ValueError, TypeError) as e:
        log.warning("Réponse IA illisible pour un événement", modele=modele, extrait=brut[:200])
        raise ValueError("le modèle n'a pas rendu de JSON exploitable") from e
    if not isinstance(data, dict):
        raise ValueError("le modèle n'a pas rendu d'objet JSON")

    proposition = normaliser(data, texte, aujourdhui)
    log.info("Événement proposé par l'IA", modele=modele, date=proposition["date_reelle"] or "-",
             heure=proposition["heure_debut"] or "-", categorie=proposition["categorie"])
    return proposition
