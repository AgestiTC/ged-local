"""
Contrôle d'accès de l'API — qui a le droit d'appeler quoi (plan d'authentification, étape 2)
=============================================================================================
UN SEUL endroit décide : ce module. Il est branché comme middleware sur TOUTE l'application
(`main.py`), donc avant la lecture du corps de la requête (un anonyme ne peut pas faire stocker un
envoi de 500 Mo) et sans dépendre de ce que chaque routeur a pensé à déclarer. Les routes ajoutées
demain, les docs OpenAPI, les 404 : tout passe par ici.

Ordre des contrôles quand `auth_active` est vrai :
  1. CSRF — écriture (POST/PUT/PATCH/DELETE) portant le cookie de session : l'origine doit être
     la nôtre (sinon 403) ;
  2. liste blanche stricte (correspondance EXACTE du chemin, jamais par préfixe) ;
  3. session lue EN BASE à chaque requête (rôle et `bloque` ne sont jamais mis en cache) ;
  4. rôle : les routes classées « admin » exigent le rôle admin (sinon 403).
ÉCHEC FERMÉ : toute erreur de lecture (base indisponible…) répond 503, jamais « ouvert ».

`auth_active` faux (défaut) : comportement historique, aucun refus.

Accès de secours : `python -m outils.auth --suspendre 2h` (sur le LXC, jamais par l'API) écrit une
échéance en base ; tant qu'elle n'est pas dépassée le contrôle laisse passer. Elle est plafonnée à
`SUSPENSION_MAX` : une valeur corrompue ou posée à la main ne peut pas ouvrir l'API pour des années.
"""

import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from starlette.routing import Match

from logger import get_logger
from models.config import Config
from services import oidc_service, runtime_config

log = get_logger(__name__)

ADMIN = "admin"
UTILISATEUR = "utilisateur"

# Sans session, et SEULEMENT ceux-là. `/api/passerelle/publish` n'est pas « ouverte » : elle exige
# son propre jeton Bearer (dépendance `projet_authentifie`), et n'est pas soumise au CSRF (pas de cookie).
LISTE_BLANCHE = frozenset({
    "/api/version", "/healthz",
    "/api/auth/login", "/api/auth/callback", "/api/auth/logout", "/api/auth/me",
    "/api/passerelle/publish",
})
SANS_CSRF = frozenset({"/api/passerelle/publish"})

METHODES_ECRITURE = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Clé de la suspension de secours dans la table `config`. VOLONTAIREMENT absente de
# `runtime_config._DEFAULTS` : ni lue, ni écrite, ni listée par /api/system/config.
CLE_SUSPENSION = "auth_suspendue_jusqua"
SUSPENSION_MAX = timedelta(hours=24)

# ─── Classification des routes ────────────────────────────────────────────────
#
# (méthode ou "*", modèle de chemin, rôle requis). Le modèle est celui de la ROUTE (`/api/x/{id}`),
# pas le chemin reçu : la route est retrouvée par le routeur lui-même, donc aucun écart possible
# entre ce que le contrôle voit et ce que FastAPI exécute. « /* » à la fin = tout ce qui est
# dessous. PREMIÈRE règle qui correspond gagne : le spécifique AVANT le général.
#
# Une route qu'aucune règle ne couvre est traitée comme ADMIN (en cas de doute, fermé) ET fait
# échouer tests/test_auth_protection.py : on ne livre pas une route sans avoir décidé.
#
# Principe : « utilisateur » = ce que la décision n° 1 du plan accorde (GED, recherche, Créer,
# Dossiers, wiki). Tout ce qui configure, supprime pour de bon, lit des journaux, touche aux
# identifiants, aux sources, à la maintenance ou à des données personnelles sensibles est ADMIN.
# Les marques « prudence » signalent un classement admin par DOUTE (à assouplir si l'usage le demande).
REGLES: list[tuple[str, str, str]] = [
    # — Documentation de l'API : elle liste toute la surface d'attaque —
    ("*", "/api/docs", ADMIN), ("*", "/api/redoc", ADMIN), ("*", "/api/openapi.json", ADMIN),
    ("*", "/docs/oauth2-redirect", ADMIN),
    # /health expose les adresses internes des services (Tika, Ollama, n8n) — prudence.
    ("*", "/health", ADMIN),

    # — Système : quelques lectures/actions d'usage courant, tout le reste admin —
    ("GET", "/api/system/ia/status", UTILISATEUR),      # voyant « IA en pause » de l'en-tête
    ("GET", "/api/system/model-status", UTILISATEUR),   # modèle de rapport chargé ?
    ("POST", "/api/system/warm-model", UTILISATEUR),    # « Préparer le modèle » avant un rapport
    ("*", "/api/system/*", ADMIN),   # config (GET aussi : réglages sensibles), sauvegardes, modèles
                                     # IA (pull/MAJ), diagnostic, antivirus, services (URLs) — prudence
    ("*", "/api/logs/*", ADMIN),     # journaux techniques
    ("*", "/api/audit", ADMIN), ("*", "/api/audit/*", ADMIN),   # journal d'activité

    # — Sources, connecteurs, doublons, réorganisation, passerelle : tout admin —
    ("*", "/api/sources", ADMIN), ("*", "/api/sources/*", ADMIN),         # identifiants SMB, indexation
    ("*", "/api/connectors", ADMIN), ("*", "/api/connectors/*", ADMIN),   # comptes cloud, OAuth
    ("*", "/api/folders", ADMIN), ("*", "/api/folders/*", ADMIN),         # dossiers surveillés + navigation disque
    ("*", "/api/duplicates", ADMIN), ("*", "/api/duplicates/*", ADMIN),   # quarantaine, suppression
    ("*", "/api/organize/*", ADMIN),                                       # réorganisation physique
    ("*", "/api/passerelle/projets", ADMIN), ("*", "/api/passerelle/projets/*", ADMIN),  # jetons des projets
    ("*", "/api/huggingface/*", ADMIN),                                    # catalogue de modèles (sortie internet)

    # — Vie du foyer (intervenants à domicile, impôts, diffusion audio, congés) : ouverts au rôle
    #   utilisateur par décision du 31/10/2026 — c'est la vie commune du foyer. Les RÉGLAGES qui les
    #   font marcher (jeton Home Assistant, clé de chiffrement) restent sous /api/system → admin.
    ("*", "/api/emploi-domicile/*", UTILISATEUR),
    ("*", "/api/fiscalite/*", UTILISATEUR),
    ("*", "/api/maison/*", UTILISATEUR),
    ("*", "/api/conges/*", UTILISATEUR),

    # — Documents : consultation et fiche = utilisateur ; maintenance, lots, suppression de l'index = admin —
    ("DELETE", "/api/documents/{document_id}", ADMIN),    # retire de l'index (embeddings perdus) — l'utilisateur passe par la corbeille
    ("POST", "/api/documents/analyze-batch", ADMIN),
    ("POST", "/api/documents/reenrich-batch", ADMIN),
    ("POST", "/api/documents/purge-duplicates", ADMIN),
    ("*", "/api/documents/maintenance/*", ADMIN),
    ("*", "/api/documents", UTILISATEUR), ("*", "/api/documents/*", UTILISATEUR),
    ("*", "/api/corbeille", UTILISATEUR), ("*", "/api/corbeille/*", UTILISATEUR),   # mise à la corbeille = réversible
    ("*", "/api/extract/*", UTILISATEUR),
    ("*", "/api/upload", UTILISATEUR), ("*", "/api/upload/*", UTILISATEUR),
    ("*", "/api/search", UTILISATEUR), ("*", "/api/search/*", UTILISATEUR),

    # — Tâches : lecture = utilisateur ; purge, démo, annulation = admin (prudence) —
    ("GET", "/api/jobs", UTILISATEUR), ("GET", "/api/jobs/stats", UTILISATEUR),
    ("GET", "/api/jobs/{job_id}", UTILISATEUR),
    ("*", "/api/jobs/*", ADMIN),

    # — Rapports, prompts, templates, consignes : lecture = utilisateur ; modification = admin —
    ("GET", "/api/rapports", UTILISATEUR), ("GET", "/api/rapports/{rapport_id}", UTILISATEUR),
    ("*", "/api/rapports/*", ADMIN),                       # purge / suppression de l'historique — prudence
    ("GET", "/api/prompts", UTILISATEUR), ("POST", "/api/prompts/relire", UTILISATEUR),
    ("*", "/api/prompts", ADMIN), ("*", "/api/prompts/*", ADMIN),   # gestion des presets (Paramètres) — prudence
    ("GET", "/api/templates", UTILISATEUR), ("GET", "/api/templates/*", UTILISATEUR),
    ("*", "/api/templates", ADMIN), ("*", "/api/templates/*", ADMIN),   # upload / suppression — prudence
    ("GET", "/api/consignes/{cle}", UTILISATEUR),
    ("*", "/api/consignes/*", ADMIN),                      # modifier les consignes des IA

    # — Scanner : usage courant = utilisateur ; réglages, profils, scanners = admin —
    ("*", "/api/scan/config", ADMIN),
    ("GET", "/api/scan/profils", UTILISATEUR), ("*", "/api/scan/profils", ADMIN), ("*", "/api/scan/profils/*", ADMIN),
    ("GET", "/api/scan/scanners", UTILISATEUR), ("*", "/api/scan/scanners", ADMIN), ("*", "/api/scan/scanners/*", ADMIN),
    ("*", "/api/scan/*", UTILISATEUR),

    # — Notifications : la génération d'idées d'évolution est un réglage de fonctionnement — prudence —
    ("POST", "/api/notifications/idees/generer", ADMIN),
    ("*", "/api/notifications", UTILISATEUR), ("*", "/api/notifications/*", UTILISATEUR),

    # — Dossiers, wiki, liens : « Dossiers » et « wiki » de la décision n° 1 —
    ("POST", "/api/dossiers/seed/{cle}", ADMIN),           # réinstalle des données d'exemple — prudence
    ("*", "/api/dossiers", UTILISATEUR), ("*", "/api/dossiers/*", UTILISATEUR),
    ("POST", "/api/wiki/index", ADMIN),                    # indexation du wiki
    ("*", "/api/wiki/*", UTILISATEUR),
    ("POST", "/api/links/scan", ADMIN),
    ("*", "/api/links", UTILISATEUR), ("*", "/api/links/*", UTILISATEUR),
    ("*", "/api/bookstack/*", UTILISATEUR),

    # — « Créer » : génération, export, présentations, projets, regroupements, médias, assistant —
    ("*", "/api/generate/*", UTILISATEUR),
    ("*", "/api/export/*", UTILISATEUR),
    ("*", "/api/presentations", UTILISATEUR), ("*", "/api/presentations/*", UTILISATEUR),
    ("*", "/api/projets", UTILISATEUR), ("*", "/api/projets/*", UTILISATEUR),
    ("*", "/api/regroupements", UTILISATEUR), ("*", "/api/regroupements/*", UTILISATEUR),
    ("*", "/api/musique", UTILISATEUR), ("*", "/api/musique/*", UTILISATEUR),
    ("*", "/api/video", UTILISATEUR), ("*", "/api/video/*", UTILISATEUR),
    ("*", "/api/assistant/*", UTILISATEUR),
]


def _correspond(motif: str, chemin: str) -> bool:
    if motif.endswith("/*"):
        base = motif[:-2]
        return chemin == base or chemin.startswith(base + "/")
    return motif == chemin


def classer(methode: str, modele: str) -> str | None:
    """Rôle requis pour une route (méthode + modèle de chemin), ou None si aucune règle ne la couvre."""
    methode = methode.upper()
    for m, motif, role in REGLES:
        if (m == "*" or m == methode) and _correspond(motif, modele):
            return role
    return None


def _modele_de_route(request: Request) -> str | None:
    """Modèle de chemin de la route que le routeur exécutera pour cette requête (None = aucune)."""
    scope = request.scope
    for route in request.app.router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return getattr(route, "path", None)
    return None


# ─── CSRF ─────────────────────────────────────────────────────────────────────

def origines_cors() -> list[str]:
    """Origines autorisées (CORS_ORIGINS, sinon valeurs de développement) — partagée avec le CORS de main.py."""
    env = os.environ.get("CORS_ORIGINS", "")
    if env:
        return [o.strip() for o in env.split(",") if o.strip()]
    return ["http://localhost:3001", "http://localhost:3003", "http://localhost:5173"]


def _origine(url: str) -> str:
    """`scheme://hôte[:port]` en minuscules, sans chemin ni « / » final."""
    p = urlsplit(url.strip())
    return f"{p.scheme}://{p.netloc}".lower() if p.scheme and p.netloc else ""


def _origines_autorisees(request: Request) -> set[str]:
    """
    Origines acceptées pour une écriture authentifiée par cookie :
      - CORS_ORIGINS : en PROD, y mettre au minimum `https://ged.tclement.fr` et, tant que la route LAN
        existe, `http://192.168.42.83:3003` (schéma + hôte + PORT, sans « / » final) ;
      - l'origine de la requête elle-même, déduite de l'en-tête `Host` (port compris : nginx doit le
        transmettre, cf. `proxy_set_header Host $http_host`) et de `X-Forwarded-Proto` ;
      - l'origine de `oidc_redirect_uri` (adresse de référence TLS).
    Les deux dernières suffisent en pratique ; CORS_ORIGINS reste la liste explicite de secours.
    """
    ok = {_origine(o) for o in origines_cors()}
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if proto not in ("http", "https"):
        proto = request.url.scheme
    hote = request.headers.get("host")
    if hote:
        ok.add(f"{proto}://{hote}".lower())          # l'application elle-même
    ok.add(_origine(runtime_config.effective("oidc_redirect_uri")))   # adresse de référence (TLS)
    ok.discard("")
    return ok


def origine_ok(request: Request) -> bool:
    """
    La requête d'écriture vient-elle de l'application ? `Origin` décide s'il est présent ; sinon
    `Referer` ; sinon seul `Sec-Fetch-Site: same-origin` (envoyé par les navigateurs) suffit.
    `SameSite=Lax` seul ne protège pas des sites frères de tclement.fr.
    """
    autorisees = _origines_autorisees(request)
    origin = request.headers.get("origin")
    if origin is not None:
        return origin.strip().lower() in autorisees      # « null » n'y est jamais
    referer = request.headers.get("referer")
    if referer:
        return _origine(referer) in autorisees
    return request.headers.get("sec-fetch-site", "").strip().lower() == "same-origin"


# ─── Suspension de secours ────────────────────────────────────────────────────

def lire_echeance(valeur: str | None, maintenant: datetime | None = None) -> datetime | None:
    """Échéance valide (future, plafonnée) ou None. Toute valeur illisible = pas de suspension."""
    if not valeur:
        return None
    try:
        fin = datetime.fromisoformat(valeur.strip())
    except ValueError:
        return None
    if fin.tzinfo is None:
        fin = fin.replace(tzinfo=timezone.utc)
    now = maintenant or datetime.now(timezone.utc)
    if fin <= now or fin > now + SUSPENSION_MAX + timedelta(minutes=1):
        return None
    return fin


async def suspension_jusqua(db) -> datetime | None:
    """Fin de la suspension de secours si elle est active, sinon None (lue EN BASE, jamais en cache)."""
    valeur = (await db.execute(select(Config.valeur).where(Config.cle == CLE_SUSPENSION))).scalar_one_or_none()
    return lire_echeance(valeur)


# ─── Le contrôle ──────────────────────────────────────────────────────────────

def _refus(code: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=code, headers={"Cache-Control": "no-store"})


@asynccontextmanager
async def _session_base(request: Request):
    """Session de base du contrôle ; respecte `dependency_overrides[get_db]` (tests)."""
    from database import get_db
    fabrique = request.app.dependency_overrides.get(get_db, get_db)
    async with asynccontextmanager(fabrique)() as db:
        yield db


async def controle_acces(request: Request, call_next):
    """Middleware HTTP : voir l'en-tête du module."""
    request.state.utilisateur = None
    chemin = request.scope["path"]

    # 0. Démarrage à froid : si les réglages n'ont JAMAIS pu être lus en base, on ignore si
    #    l'authentification est active (le défaut « faux » ouvrirait l'API) : refus, sauf sondes de vie.
    #    `reglages_frais` (middleware extérieur) retente la lecture toutes les 2 s.
    if not runtime_config._charge_reussi and chemin not in ("/healthz", "/api/version"):
        return _refus(503, "Réglages indisponibles")

    if not oidc_service.auth_active():
        return await call_next(request)
    methode = request.method.upper()

    # 1. CSRF : seulement pour une écriture authentifiée PAR COOKIE (un appel par jeton n'en porte pas).
    if (methode in METHODES_ECRITURE and chemin not in SANS_CSRF
            and request.cookies.get("matotheque_session") and not origine_ok(request)):
        log.warning("Écriture refusée : origine non autorisée", chemin=chemin, methode=methode)
        return _refus(403, "Origine de la requête non autorisée")

    # 2. Liste blanche : correspondance exacte.
    if chemin in LISTE_BLANCHE:
        return await call_next(request)

    # 3. Session et suspension, lues en base. ÉCHEC FERMÉ.
    try:
        from routers import auth as auth_router
        async with _session_base(request) as db:
            fin_suspension = await suspension_jusqua(db)
            courante = await auth_router._session_valide(request, db)
    except Exception as e:  # noqa: BLE001 — jamais « ouvert » sur une erreur
        log.error("Contrôle d'accès impossible — requête refusée", chemin=chemin, erreur=type(e).__name__)
        return _refus(503, "Authentification momentanément indisponible")
    user = courante[1] if courante else None
    request.state.utilisateur = user

    if fin_suspension is not None:
        rep = await call_next(request)
        rep.headers["X-Auth-Suspendue"] = fin_suspension.isoformat()
        return rep

    if user is None or user.role not in (ADMIN, UTILISATEUR):
        return _refus(401, "Authentification requise")

    # 4. Rôle. Route inconnue du routeur (404/405) : session suffit, il n'y a rien à protéger.
    modele = _modele_de_route(request)
    if modele is not None:
        role = classer(methode, modele) or ADMIN       # non classée = admin
        if role == ADMIN and user.role != ADMIN:
            log.warning("Accès refusé : réservé aux administrateurs", chemin=modele, methode=methode,
                        identifiant=user.identifiant)
            return _refus(403, "Réservé aux administrateurs")
    return await call_next(request)
