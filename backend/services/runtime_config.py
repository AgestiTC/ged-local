"""
Runtime config — surcharge à chaud des paramètres (URLs services, modèle défaut)
================================================================================
Les valeurs en base (table `config`) surchargent l'environnement (`settings`).
Un cache mémoire est chargé au démarrage et mis à jour à chaque écriture, pour
que les services (Tika, Ollama, n8n) lus par requête prennent l'effet immédiatement.
"""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from logger import get_logger
from models.config import Config
from services import pertinence  # défauts des seuils (n'importe runtime_config qu'à l'appel)

log = get_logger(__name__)
settings = get_settings()

def _default_extensions() -> str:
    """Liste d'extensions par défaut (la même que le watcher), en chaîne CSV."""
    from services.folder_watcher import EXTENSIONS_ACCEPTEES  # import local : évite le cycle
    return ",".join(sorted(EXTENSIONS_ACCEPTEES))


# Clés gérées + provenance du défaut (variable d'environnement / config)
_DEFAULTS = {
    "tika_url": lambda: settings.tika_url,
    "ollama_url": lambda: settings.ollama_url,
    "n8n_url": lambda: settings.n8n_url,
    "default_model": lambda: settings.ollama_model_default,
    # Modèle vision (fallback OCR / description d'image quand Tesseract/Tika ne rend rien).
    # Défaut glm-ocr (installé) ; recommandé : qwen2.5vl:7b après `ollama pull qwen2.5vl:7b`.
    "vision_model": lambda: "glm-ocr:latest",
    "extensions": _default_extensions,
    # BookStack (wiki). Le secret est stocké chiffré (enc::…) ; le service le déchiffre.
    "bookstack_url": lambda: settings.bookstack_url,
    "bookstack_token_id": lambda: settings.bookstack_token_id or "",
    "bookstack_token_secret": lambda: settings.bookstack_token_secret or "",
    # HuggingFace (token API et/ou identifiant + mot de passe). Secrets chiffrés en base.
    # Stockage local uniquement — aucune requête réseau HF sans action confirmée par l'utilisateur.
    "huggingface_token": lambda: "",
    "huggingface_user": lambda: "",
    "huggingface_password": lambda: "",
    # Connecteurs cloud (OAuth) — identifiants d'app à créer par l'utilisateur
    # (Google Cloud Console / Dropbox App Console). Secrets chiffrés en base.
    # Le flux OAuth + connecteur seront branchés ensuite (cf. plan connecteurs cloud).
    "gdrive_client_id": lambda: "",
    "gdrive_client_secret": lambda: "",
    # URI de callback OAuth (doit correspondre EXACTEMENT à celle enregistrée dans Google Cloud).
    # Vide = déduite de la requête (dev). À renseigner en prod (derrière un proxy).
    "oauth_redirect_uri": lambda: "",
    "dropbox_app_key": lambda: "",
    "dropbox_app_secret": lambda: "",
    # Transcription audio (parole → texte). Serveur local exposant l'API compatible OpenAI
    # `/v1/audio/transcriptions` (faster-whisper-server, LocalAI…). URL vide = désactivé.
    # La clé d'API (souvent inutile en local) est chiffrée en base.
    "transcription_url": lambda: "",
    "transcription_model": lambda: "Systran/faster-whisper-large-v3",
    "transcription_langue": lambda: "fr",
    "transcription_api_key": lambda: "",
    # Seuils du gate de pertinence de la recherche (cosinus absolu) — cf. services/pertinence.py.
    # Calibrés sur le corpus dev ; à re-valider sur le corpus NAS.
    "search_cos_haut": lambda: str(pertinence.SEUIL_HAUT_DEFAUT),
    "search_cos_bas": lambda: str(pertinence.SEUIL_BAS_DEFAUT),
    # Modèle par USAGE (routage dynamique) : JSON {usage: modele}. Ex. {"rapport": "...",
    # "enrichissement": "...", "embeddings": "...", "vision": "...", "resume_modele": "..."}.
    "usage_models": lambda: "{}",
    # Sauvegarde AUTOMATIQUE de la base (pg_dump) par le worker. Intervalle en heures (0 = désactivé),
    # et nombre de sauvegardes conservées (purge des plus anciennes ; ~0,6-1,5 Go l'unité).
    "backup_auto_heures": lambda: "3",
    "backup_retention": lambda: "8",
    # Purge AUTOMATIQUE de l'historique des rapports : supprime ceux de plus de N jours (0 = jamais).
    # Appliquée par le worker (une fois par jour). Réglable dans Paramètres.
    "rapports_purge_jours": lambda: "0",
    # Taille MAX d'un fichier rapatrié en temporaire pour extraction (Mo). Au-delà, le fichier est
    # RÉFÉRENCÉ sans être téléchargé : un ZIP de 8,9 Go avait saturé le disque du LXC (incident 21/07).
    "index_taille_max_mo": lambda: "2048",
    # Concurrence du worker de jobs, réglable À CHAUD (Paramètres → aucun redéploiement). Deux
    # budgets : `gpu` = tâches Ollama (LLM/vision/embeddings) — plafond bas car VRAM limitée (RTX
    # 4080 16 Go, Ollama sérialise) ; `io` = réseau/disque (synchro NAS, réorganisation) — slots EN
    # PLUS qui tournent à côté du GPU. Le worker les relit toutes les ~10 s.
    "concurrence_gpu": lambda: "2",
    "concurrence_io": lambda: "3",
    # PAUSE de l'IA : « 1 » = le worker ne réclame plus de tâches GPU (Ollama) — enrichissement,
    # analyse, vision, embeddings… Libère Ollama pour un autre usage (ex. projet FOULEE). Les tâches
    # I/O (synchro, réorganisation) continuent. Réglable à chaud depuis Paramètres › Maintenance.
    "ia_pause": lambda: "0",
    # Liens de la page Administration : JSON [{section, label, url}]. Gérés dans Paramètres.
    "admin_links": lambda: json.dumps([
        {"section": "Médical", "label": "Doctolib", "url": "https://www.doctolib.fr"},
        {"section": "Médical", "label": "Mon espace santé", "url": "https://www.monespacesante.fr"},
        {"section": "Gouv", "label": "Impôts", "url": "https://www.impots.gouv.fr"},
        {"section": "Gouv", "label": "ANTS", "url": "https://ants.gouv.fr"},
    ], ensure_ascii=False),
    # Catalogue de services publics ACTIVABLES d'un clic dans l'éditeur de liens Administration :
    # JSON [{section, label, url}]. Piloté par la config (rechargeable / extensible sans rebuild du
    # front). Un service déjà présent dans `admin_links` est détecté par hôte et affiché « activé ».
    "admin_catalogue": lambda: json.dumps([
        {"section": "Gouv", "label": "Service-Public.fr", "url": "https://www.service-public.fr"},
        {"section": "Gouv", "label": "Impôts", "url": "https://www.impots.gouv.fr"},
        {"section": "Gouv", "label": "ANTS — carte grise / permis", "url": "https://ants.gouv.fr"},
        {"section": "Gouv", "label": "FranceConnect", "url": "https://franceconnect.gouv.fr"},
        {"section": "Gouv", "label": "Légifrance", "url": "https://www.legifrance.gouv.fr"},
        {"section": "Gouv", "label": "Mon Compte Formation", "url": "https://www.moncompteformation.gouv.fr"},
        {"section": "Gouv", "label": "ANTAI — avis de contravention", "url": "https://www.antai.gouv.fr"},
        {"section": "Gouv", "label": "Amendes", "url": "https://www.amendes.gouv.fr"},
        {"section": "Gouv", "label": "Chèque énergie", "url": "https://chequeenergie.gouv.fr"},
        {"section": "Gouv", "label": "Mes Droits Sociaux", "url": "https://www.mesdroitssociaux.gouv.fr"},
        {"section": "Gouv", "label": "Géoportail", "url": "https://www.geoportail.gouv.fr"},
        {"section": "Gouv", "label": "Cadastre", "url": "https://www.cadastre.gouv.fr"},
        {"section": "Gouv", "label": "Cartes (cadastre / plans)", "url": "https://cartes.gouv.fr/explorer-les-cartes/"},
        {"section": "Gouv", "label": "data.gouv.fr", "url": "https://www.data.gouv.fr"},
        {"section": "Gouv", "label": "Démarches simplifiées", "url": "https://www.demarches-simplifiees.fr"},
        {"section": "Gouv", "label": "Justice.fr", "url": "https://www.justice.fr"},
        {"section": "Gouv", "label": "Éducation nationale", "url": "https://www.education.gouv.fr"},
        {"section": "Médical", "label": "Mon espace santé", "url": "https://www.monespacesante.fr"},
        {"section": "Médical", "label": "Ameli — Assurance Maladie", "url": "https://www.ameli.fr"},
    ], ensure_ascii=False),
    # Dictionnaire d'acronymes : JSON [{sigle, definition}]. Sert à la normalisation de CASSE
    # des tags/catégories (ces sigles sont forcés en MAJUSCULES). Éditable dans Paramètres.
    "acronymes": lambda: json.dumps([
        {"sigle": "IBAN", "definition": "International Bank Account Number — identifiant de compte bancaire"},
        {"sigle": "RIB", "definition": "Relevé d'Identité Bancaire"},
        {"sigle": "CV", "definition": "Curriculum Vitae"},
        {"sigle": "DPGF", "definition": "Décomposition du Prix Global et Forfaitaire (marchés / BTP)"},
        {"sigle": "TVA", "definition": "Taxe sur la Valeur Ajoutée"},
        {"sigle": "HT", "definition": "Hors Taxes"},
        {"sigle": "TTC", "definition": "Toutes Taxes Comprises"},
        {"sigle": "SIRET", "definition": "Système d'Identification du Répertoire des Établissements"},
        {"sigle": "SIREN", "definition": "Système d'Identification du Répertoire des Entreprises"},
        {"sigle": "RCS", "definition": "Registre du Commerce et des Sociétés"},
        {"sigle": "RGPD", "definition": "Règlement Général sur la Protection des Données"},
        {"sigle": "CDD", "definition": "Contrat à Durée Déterminée"},
        {"sigle": "CDI", "definition": "Contrat à Durée Indéterminée"},
        {"sigle": "SARL", "definition": "Société À Responsabilité Limitée"},
        {"sigle": "SAS", "definition": "Société par Actions Simplifiée"},
        {"sigle": "SASU", "definition": "Société par Actions Simplifiée Unipersonnelle"},
        {"sigle": "URSSAF", "definition": "Union de Recouvrement des cotisations de Sécurité Sociale et d'Allocations Familiales"},
        {"sigle": "CAF", "definition": "Caisse d'Allocations Familiales"},
        {"sigle": "CPAM", "definition": "Caisse Primaire d'Assurance Maladie"},
        {"sigle": "EDF", "definition": "Électricité de France"},
        {"sigle": "SNCF", "definition": "Société Nationale des Chemins de fer Français"},
        {"sigle": "HTML", "definition": "HyperText Markup Language"},
        {"sigle": "CSS", "definition": "Cascading Style Sheets"},
        {"sigle": "PHP", "definition": "PHP: Hypertext Preprocessor"},
        {"sigle": "SQL", "definition": "Structured Query Language"},
        {"sigle": "XML", "definition": "eXtensible Markup Language"},
        {"sigle": "JSON", "definition": "JavaScript Object Notation"},
        {"sigle": "API", "definition": "Application Programming Interface"},
        {"sigle": "URL", "definition": "Uniform Resource Locator"},
        {"sigle": "PV", "definition": "Procès-Verbal"},
        {"sigle": "RH", "definition": "Ressources Humaines"},
    ], ensure_ascii=False),
}

# Clés dont la valeur est un secret : à chiffrer en écriture, à masquer en lecture.
SECRET_KEYS = {"bookstack_token_secret", "huggingface_token", "huggingface_password",
               "gdrive_client_secret", "dropbox_app_secret", "transcription_api_key"}


def ia_en_pause() -> bool:
    """Vrai si l'IA est en pause (le worker ne doit plus réclamer de tâches Ollama/GPU)."""
    return effective("ia_pause").strip().lower() in ("1", "true", "on", "yes")


def effective_extensions() -> set[str]:
    """Ensemble des extensions indexées (config base > défaut), normalisées."""
    raw = effective("extensions")
    return {e.strip().lstrip(".").lower() for e in raw.replace("\n", ",").split(",") if e.strip()}

# Cache mémoire des surcharges (clé → valeur)
_overrides: dict[str, str] = {}


def effective(cle: str) -> str:
    """Valeur effective : surcharge base si présente, sinon défaut env."""
    if cle in _overrides and _overrides[cle]:
        return _overrides[cle]
    default = _DEFAULTS.get(cle)
    return default() if default else ""


def usage_model(usage: str) -> str | None:
    """Modèle configuré pour un USAGE précis (routage dynamique), ou None si non défini."""
    try:
        m = json.loads(effective("usage_models") or "{}")
        return (m.get(usage) or None) if isinstance(m, dict) else None
    except (ValueError, TypeError):
        return None


def model_for(usage: str) -> str:
    """
    Modèle à utiliser pour un usage : **override par usage** > **défaut runtime**
    (`default_model`). Remplace `settings.ollama_model_default` (env) — évite d'appeler un
    modèle supprimé et permet à l'utilisateur de router chaque tâche.
    """
    return usage_model(usage) or effective("default_model")


# ─── Fallback « même famille » (routage dynamique multi-modèles) ──────────────
# Le champ details.family d'Ollama ne distingue pas fiablement vision/texte : on
# classe par MOTIF DE NOM. Un modèle ni embedding ni vision est réputé « texte ».
_VISION_HINTS = ("vl", "llava", "vision", "ocr", "minicpm-v", "moondream", "bakllava")
_EMBED_HINTS = ("embed", "nomic")
_USAGE_FAMILLE = {
    "vision": "vision",
    "embeddings": "embeddings",
    "enrichissement": "texte",
    "rapport": "texte",
    "resume_modele": "texte",
}


def _famille_modele(nom: str) -> str:
    """Famille d'un modèle d'après son nom : 'embeddings' | 'vision' | 'texte'."""
    n = (nom or "").lower()
    if any(h in n for h in _EMBED_HINTS):
        return "embeddings"
    if any(h in n for h in _VISION_HINTS):
        return "vision"
    return "texte"


async def model_candidates(usage: str) -> list[str]:
    """
    Ordre de modèles à ESSAYER pour un usage (fallback « même famille ») :
      1) le(s) modèle(s) configuré(s) pour l'usage (intention explicite de l'utilisateur) ;
      2) les autres modèles INSTALLÉS de la même famille (les plus petits d'abord = rapides).
    Ne renvoie que des modèles réellement présents dans Ollama → **jamais** d'appel à un
    modèle supprimé (mixtral/mistral legacy, etc.). Retombe sur les modèles configurés seuls
    si Ollama est injoignable.
    """
    from services.ollama_service import OllamaService

    fam = _USAGE_FAMILLE.get(usage, "texte")
    if fam == "vision":
        primaires = [usage_model("vision"), effective("vision_model")]
    elif fam == "embeddings":
        primaires = [usage_model("embeddings"), settings.ollama_model_embedding]
    else:
        primaires = [model_for(usage)]

    try:
        installes = await OllamaService().list_models_detailed()
    except Exception as e:  # noqa: BLE001 — Ollama injoignable : on tente au moins le modèle configuré
        log.warning("Liste modèles Ollama indisponible — fallback limité", usage=usage, erreur=str(e))
        return list(dict.fromkeys(p for p in primaires if p))

    noms = {m["name"] for m in installes if m.get("name")}
    # Autres modèles de la même famille, du plus petit au plus grand (rapidité en secours).
    autres = [
        m["name"] for m in sorted(installes, key=lambda x: x.get("size") or 0)
        if m.get("name") and _famille_modele(m["name"]) == fam
    ]
    # Primaires d'abord (même si l'heuristique les classe autrement : l'utilisateur les a choisis),
    # puis le reste de la famille. Dédup en gardant l'ordre, filtré aux modèles installés.
    ordre = [p for p in primaires if p] + autres
    return [m for m in dict.fromkeys(ordre) if m in noms]


def all_effective() -> dict[str, str]:
    """Toutes les valeurs effectives + indication de la source (base/env)."""
    return {
        cle: {"valeur": effective(cle), "source": "base" if _overrides.get(cle) else "env"}
        for cle in _DEFAULTS
    }


async def load(db: AsyncSession) -> None:
    """Charge les surcharges depuis la base dans le cache mémoire."""
    rows = (await db.execute(select(Config))).scalars().all()
    _overrides.clear()
    for row in rows:
        if row.cle in _DEFAULTS:
            _overrides[row.cle] = row.valeur
    log.info("Runtime config chargée", surcharges=list(_overrides.keys()))


async def set_many(db: AsyncSession, data: dict[str, str]) -> None:
    """Upsert des surcharges en base + mise à jour du cache."""
    for cle, valeur in data.items():
        if cle not in _DEFAULTS:
            continue
        existing = await db.get(Config, cle)
        if existing:
            existing.valeur = valeur
        else:
            db.add(Config(cle=cle, valeur=valeur))
        _overrides[cle] = valeur
    await db.flush()
    log.info("Runtime config mise à jour", cles=list(data.keys()))
