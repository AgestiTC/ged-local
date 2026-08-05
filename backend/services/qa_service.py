"""
Q&R — Service « Poser une question » (E8, Phase 1 MVP « emploi »)
================================================================
Répond à une question en langage naturel sur la GED, avec raisonnement entités + dates :
  ① COMPRENDRE  (LLM json) : question → {intent, personnes, organisations, période, type_piece}
  ② RÉCUPÉRER   : recherche par SIGNAUX (pas la phrase brute) — c'est ce qui fait échouer
                  l'Hybride sur une question (gate de pertinence). Réutilise routers/search.
  ③ EXTRAIRE    (LLM json, mis en cache) : pour chaque candidat → {employeur, salarié, période}
  ④ AGRÉGER     (fonctions pures) : employeur-à-une-date · durée = min/max des paies
  ⑤ RÉPONDRE    : **gabarit déterministe** (aucune invention) — la réponse ne cite QUE des faits
                  présents dans des documents ; sinon « je n'ai pas trouvé » + docs approchants.

100 % local (Ollama). Le raisonnement temporel est isolé dans `qa_temporal` (pur, testé).
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict
from datetime import date

from logger import get_logger
from services import qa_temporal as qt
from services.ollama_service import OllamaService

log = get_logger(__name__)

MAX_CANDIDATS = 8           # documents examinés (borne les appels LLM d'extraction ~ le temps de réponse)
TXT_MAX = 6000              # troncature du texte extrait envoyé à l'extraction
_TYPES_DEFAUT = ["fiche de paie", "bulletin de salaire"]

# Cache LRU des faits extraits par document (mémoïse ③ : une même question rejouée, ou deux
# questions partageant un document, ne repaient pas l'appel LLM). Clé = document_id.
_FAITS_CACHE: "OrderedDict[str, dict]" = OrderedDict()
_FAITS_CACHE_MAX = 500

PROMPT_COMPRENDRE = """Tu es un analyseur de questions pour une gestion documentaire française.
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
Un travail/salaire/employeur ⇒ type_piece inclut "fiche de paie". N'invente aucune donnée."""

PROMPT_EXTRAIRE = """Tu extrais des faits d'un document RH français (souvent une fiche de paie).
À partir du NOM et du TEXTE, réponds UNIQUEMENT par un JSON valide :
{
  "est_paie": true/false,
  "employeur": "raison sociale de l'employeur ou null",
  "salarie": "nom du salarié ou null",
  "periode_debut": "AAAA-MM ou null",
  "periode_fin": "AAAA-MM ou null"
}
N'invente rien : si une information n'apparaît pas clairement, mets null. Pour une paie mensuelle,
periode_debut = periode_fin = le mois de paie."""


def _json(texte: str) -> dict:
    """Parse JSON tolérant (le LLM peut entourer de texte)."""
    try:
        return json.loads(texte)
    except (json.JSONDecodeError, TypeError):
        m = re.search(r"\{.*\}", texte or "", re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return {}
        return {}


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


# ─── ① Compréhension ──────────────────────────────────────────────────────────
async def comprendre(question: str, model: str) -> dict:
    """Question NL → intent structuré (LLM). Résilient : renvoie un intent minimal si l'IA échoue."""
    try:
        rep = await OllamaService().generate(
            f"{PROMPT_COMPRENDRE}\n\nQuestion : {question}", model=model, format="json"
        )
        data = _json(rep)
    except Exception as exc:  # noqa: BLE001 — on dégrade au lieu d'échouer
        log.warning("Q&R : compréhension échouée", erreur=str(exc))
        data = {}
    intent = {
        "intent": str(data.get("intent") or "autre"),
        "personnes": [str(p).strip() for p in (data.get("personnes") or []) if str(p).strip()],
        "organisations": [str(o).strip() for o in (data.get("organisations") or []) if str(o).strip()],
        "type_piece": [str(t).strip() for t in (data.get("type_piece") or []) if str(t).strip()],
        "periode": data.get("periode") if isinstance(data.get("periode"), dict) else {},
    }
    return intent


def cible_periode(intent: dict, question: str) -> tuple[date, date] | None:
    """Plage de dates visée : d'abord l'`intent.periode` (LLM), à défaut parsing FR de la question."""
    per = intent.get("periode") or {}
    deb = qt.parse_date_iso(str(per.get("debut") or ""))
    fin = qt.parse_date_iso(str(per.get("fin") or ""))
    if deb:
        f = fin or deb
        return qt.normaliser_periode(deb.year, deb.month)[0], qt.normaliser_periode(f.year, f.month)[1]
    return qt.periode_depuis_texte(question)


# ─── ② Récupération ciblée ────────────────────────────────────────────────────
def requetes_recherche(intent: dict) -> list[str]:
    """
    Construit les requêtes à partir des SIGNAUX (personnes + type de pièce + organisations),
    JAMAIS de la question brute — c'est ce qui contourne le gate de pertinence. Fonction pure.
    """
    types = intent.get("type_piece") or _TYPES_DEFAUT
    personnes = intent.get("personnes") or []
    orgs = intent.get("organisations") or []
    reqs: list[str] = []
    for t in types[:2]:
        if personnes:
            reqs += [f"{t} {p}" for p in personnes[:2]]
        else:
            reqs.append(t)
        for o in orgs[:1]:
            reqs.append(f"{t} {o}")
    # Dédup en gardant l'ordre.
    vus, uniques = set(), []
    for r in reqs:
        if r.lower() not in vus:
            vus.add(r.lower())
            uniques.append(r)
    return uniques[:4] or _TYPES_DEFAUT[:1]


async def recuperer(intent: dict, db) -> list[dict]:
    """
    Recherche hybride sur les requêtes-signaux, union des candidats, top N. Renvoie des **dicts
    plats** (détachés de la session) pour pouvoir fermer la session avant l'extraction LLM.
    """
    from routers.search import _recherche_fulltext, _recherche_semantique

    scores: dict[str, float] = {}
    cos_abs: dict[str, float] = {}     # cosinus ABSOLU (0-1) → % de pertinence affichable, non relatif
    infos: dict[str, dict] = {}
    for req in requetes_recherche(intent):
        ft = await _recherche_fulltext(req, db, limit=8)
        sem = await _recherche_semantique(req, db, limit=8)
        for res, poids in ((ft, 0.4), (sem, 0.6)):
            maxi = max((s for _, _, s in res), default=1.0) or 1.0
            for doc, meta, s in res:
                did = str(doc.id)
                scores[did] = scores.get(did, 0.0) + poids * (s / maxi)
                if did not in infos:
                    infos[did] = {
                        "id": did, "nom": doc.nom, "extension": doc.extension,
                        "texte": (doc.texte_extrait or "")[:TXT_MAX],
                        "categorie": meta.categorie if meta else None,
                    }
        for doc, _, s in sem:   # meilleur cosinus absolu vu pour ce doc
            did = str(doc.id)
            cos_abs[did] = max(cos_abs.get(did, 0.0), s)
    ordre = sorted(scores, key=lambda d: scores[d], reverse=True)[:MAX_CANDIDATS]
    for did in ordre:
        infos[did]["score"] = round(scores[did], 3)
        # Pertinence 0-100 = cosinus absolu (même signal que la recherche GED), pour un classement
        # honnête des documents approchants quand aucune réponse n'est ancrée.
        infos[did]["pertinence"] = round(cos_abs.get(did, 0.0) * 100)
    return [infos[did] for did in ordre]


# ─── ③ Extraction ancrée (par document, mise en cache) ────────────────────────
def _periode_extraite(deb: str | None, fin: str | None, nom: str) -> tuple[date, date] | None:
    """Période (date,date) à partir des champs LLM (AAAA-MM) ; repli sur le nom de fichier (si année réelle)."""
    d = qt.parse_date_iso(str(deb or ""))
    f = qt.parse_date_iso(str(fin or "")) or d
    if d and f:
        return qt.normaliser_periode(d.year, d.month)[0], qt.normaliser_periode(f.year, f.month)[1]
    pf = qt.periode_fichier(nom)
    return pf if (pf and pf[0].year > 1900) else None


async def extraire_un(cand: dict, model: str) -> dict:
    """Extrait les faits d'UN candidat (cache LRU par document_id). Résilient (faits vides si échec)."""
    did = cand["id"]
    if did in _FAITS_CACHE:
        _FAITS_CACHE.move_to_end(did)
        # ⚠️ Réinjecter "id" : le cache ne stocke que les faits (employeur/période…), pas l'id —
        # l'omettre faisait planter `_doc_sortie` (KeyError 'id') sur toute question rejouant un
        # document déjà analysé → 502 « IA injoignable ? 'id' ». Corrigé.
        return {"id": did, **_FAITS_CACHE[did],
                **{k: cand.get(k) for k in ("nom", "extension", "categorie", "score", "pertinence")}}

    fait = {"est_paie": False, "employeur": None, "salarie": None, "periode": None}
    if cand.get("texte", "").strip():
        try:
            rep = await OllamaService().generate(
                f"{PROMPT_EXTRAIRE}\n\nNOM : {cand['nom']}\nTEXTE :\n{cand['texte']}",
                model=model, format="json",
            )
            d = _json(rep)
            fait = {
                "est_paie": bool(d.get("est_paie")),
                "employeur": (str(d.get("employeur")).strip() or None) if d.get("employeur") else None,
                "salarie": (str(d.get("salarie")).strip() or None) if d.get("salarie") else None,
                "periode": _periode_extraite(d.get("periode_debut"), d.get("periode_fin"), cand["nom"]),
            }
        except Exception as exc:  # noqa: BLE001
            log.warning("Q&R : extraction échouée", doc=cand["nom"], erreur=str(exc))

    _FAITS_CACHE[did] = fait
    if len(_FAITS_CACHE) > _FAITS_CACHE_MAX:
        _FAITS_CACHE.popitem(last=False)
    return {"id": did, **fait, "nom": cand["nom"], "extension": cand["extension"],
            "categorie": cand["categorie"], "score": cand["score"], "pertinence": cand.get("pertinence")}


async def extraire_faits(candidats: list[dict], model: str) -> list[dict]:
    """Extraction de TOUS les candidats en parallèle."""
    import asyncio
    return list(await asyncio.gather(*(extraire_un(c, model) for c in candidats)))


# ─── ④ Agrégation (fonctions PURES) ───────────────────────────────────────────
def _match_org(employeur: str | None, cible: str) -> bool:
    """Correspondance souple d'employeur (inclusion insensible casse dans un sens ou l'autre)."""
    e, c = _norm(employeur), _norm(cible)
    return bool(e and c and (c in e or e in c))


def agreger(intent: dict, faits: list[dict], cible: tuple[date, date] | None) -> dict:
    """Applique la logique métier selon l'intention. Renvoie un dict de résultat structuré."""
    paies = [f for f in faits if f.get("est_paie") and f.get("periode")]
    intent_type = intent.get("intent")

    if intent_type == "duree_emploi":
        org = (intent.get("organisations") or [None])[0]
        concernes = [f for f in paies if (not org or _match_org(f.get("employeur"), org))]
        env = qt.agreger_periodes([f["periode"] for f in concernes])
        # Employeur affiché = celui LU dans les documents (casse correcte, ex. « LAPP MULLER SAS »)
        # plutôt que le texte brut de la question (« lapp muller »). Le plus fréquent l'emporte.
        emps = [f["employeur"] for f in concernes if f.get("employeur")]
        employeur_aff = max(set(emps), key=emps.count) if emps else (org or "cet employeur")
        return {"type": "duree_emploi", "organisation": org, "employeur_affiche": employeur_aff,
                "enveloppe": env, "duree": qt.duree_humaine(*env) if env else "", "documents": concernes}

    # défaut / "employeur_a_date" : employeur des paies couvrant la période demandée
    couvrants = [f for f in paies if cible and qt.couvre(f["periode"], cible)] if cible else paies
    employeurs, vus = [], set()
    for f in couvrants:
        emp = f.get("employeur")
        if emp and _norm(emp) not in vus:
            vus.add(_norm(emp))
            employeurs.append(emp)
    return {"type": "employeur_a_date", "cible": cible, "employeurs": employeurs, "documents": couvrants}


# ─── ⑤ Réponse (gabarit déterministe — anti-hallucination) ────────────────────
def _personne(intent: dict) -> str:
    p = (intent.get("personnes") or [None])[0]
    return (p[:1].upper() + p[1:]) if p else "cette personne"   # « thomas » → « Thomas »


def composer(intent: dict, agrege: dict) -> tuple[str, str]:
    """Compose (texte_reponse, confiance) UNIQUEMENT à partir des faits agrégés. Fonction pure."""
    personne = _personne(intent)
    docs = agrege.get("documents") or []
    n = len(docs)

    if agrege["type"] == "duree_emploi":
        env = agrege.get("enveloppe")
        org = agrege.get("employeur_affiche") or agrege.get("organisation") or "cet employeur"
        if env and n:
            deb, fin = env
            conf = "Élevée" if n >= 2 else "Moyenne"
            return (f"{personne} a travaillé chez **{org}** {agrege['duree']} — "
                    f"de {qt.libelle_periode(deb, deb)} à {qt.libelle_periode(fin, fin)} "
                    f"(d'après {n} fiche{'s' if n > 1 else ''} de paie).", conf)
        return ("", "Faible")

    # employeur_a_date
    employeurs = agrege.get("employeurs") or []
    cible = agrege.get("cible")
    quand = f" en {qt.libelle_periode(*cible)}" if cible else ""
    if len(employeurs) == 1:
        return (f"D'après {n} fiche{'s' if n > 1 else ''} de paie, {personne} travaillait chez "
                f"**{employeurs[0]}**{quand}.", "Élevée")
    if len(employeurs) > 1:
        return (f"{personne} apparaît{quand} chez plusieurs employeurs : "
                f"**{', '.join(employeurs)}** ({n} fiches de paie). À préciser.", "Moyenne")
    return ("", "Faible")


# ─── Orchestrateur ────────────────────────────────────────────────────────────
def _doc_sortie(f: dict) -> dict:
    """Projection d'un fait/candidat pour l'UI (justificatif)."""
    per = f.get("periode")
    return {
        "id": f["id"], "nom": f["nom"], "extension": f["extension"],
        "categorie": f.get("categorie"), "employeur": f.get("employeur"),
        "periode": qt.libelle_periode(*per) if per else None,
        "score": f.get("score"), "pertinence": f.get("pertinence"),
    }


async def repondre(question: str, model: str | None = None) -> dict:
    """
    Chaîne complète Q&R. Renvoie {question, intent, reponse, confiance, documents, faits_bruts}.
    `reponse` vide + confiance « Faible » = aucun fait ancré → l'UI propose un repli honnête.
    """
    import time

    from database import AsyncSessionLocal
    from services import runtime_config

    model = model or runtime_config.model_for("enrichissement")
    t0 = time.monotonic()
    intent = await comprendre(question, model)
    t_comp = time.monotonic()
    cible = cible_periode(intent, question)

    async with AsyncSessionLocal() as db:
        candidats = await recuperer(intent, db)
    t_recup = time.monotonic()

    faits = await extraire_faits(candidats, model)
    t_extr = time.monotonic()

    agrege = agreger(intent, faits, cible)
    reponse, confiance = composer(intent, agrege)

    # Documents justificatifs = ceux qui fondent la réponse ; sinon, les candidats approchants
    # (repli honnête), triés par pertinence décroissante pour le classement en sections.
    fondants = agrege.get("documents") or []
    approchants = sorted(faits, key=lambda f: f.get("pertinence") or 0, reverse=True)
    documents = [_doc_sortie(f) for f in (fondants if reponse else approchants)]

    # Timing PAR PHASE (identifier le poste coûteux : l'extraction domine — N appels LLM sériés GPU).
    ms = lambda a, b: int((b - a) * 1000)  # noqa: E731
    log.info("Q&R", question=question[:80], intent=intent.get("intent"),
             nb_candidats=len(candidats), nb_fondants=len(fondants), confiance=confiance,
             ms_comprendre=ms(t0, t_comp), ms_recuperer=ms(t_comp, t_recup),
             ms_extraction=ms(t_recup, t_extr), ms_total=ms(t0, time.monotonic()))
    return {
        "question": question,
        "intent": intent,
        "reponse": reponse,
        "confiance": confiance,
        "documents": documents,
        "approchant": not bool(reponse),   # True → l'UI affiche « documents approchants »
    }
