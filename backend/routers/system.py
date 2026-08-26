"""
Router Système — /api/version, /api/logs/tail
==============================================
Endpoints d'exploitation imposés par le modèle docker AgestiTC :

  GET /api/version      → version embarquée (source de vérité : fichier VERSION)
  GET /api/logs/tail    → N dernières lignes du fichier de log applicatif

Le liveness probe /healthz (sans préfixe) est défini dans main.py.
"""

import asyncio
import json
import re
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_db
from logger import get_logger
from services import runtime_config
from services.ollama_service import OllamaService
from services.tika_service import TikaService

log = get_logger(__name__)
settings = get_settings()
router = APIRouter()


class ConfigUpdate(BaseModel):
    """Surcharges de configuration éditables (toutes optionnelles)."""
    tika_url: str | None = None
    ollama_url: str | None = None
    n8n_url: str | None = None
    default_model: str | None = None
    vision_model: str | None = None   # modèle vision (fallback OCR / description image)
    extensions: str | None = None   # liste CSV des extensions indexées (perso)
    # BookStack (wiki externe)
    bookstack_url: str | None = None
    bookstack_token_id: str | None = None
    bookstack_token_secret: str | None = None
    # HuggingFace (identifiants chiffrés — stockage local)
    huggingface_token: str | None = None
    huggingface_user: str | None = None
    huggingface_password: str | None = None
    # Connecteurs cloud (OAuth) — identifiants d'app (client_id/secret). Secrets chiffrés.
    gdrive_client_id: str | None = None
    gdrive_client_secret: str | None = None
    oauth_redirect_uri: str | None = None
    dropbox_app_key: str | None = None
    dropbox_app_secret: str | None = None
    # Transcription audio (serveur compatible OpenAI /v1/audio/transcriptions). URL vide = off.
    transcription_url: str | None = None
    transcription_model: str | None = None
    transcription_langue: str | None = None
    transcription_api_key: str | None = None   # secret chiffré (souvent inutile en local)
    usage_models: str | None = None   # JSON {usage: modele} — routage dynamique par usage
    admin_links: str | None = None    # JSON [{section, label, url}] — page Administration
    admin_catalogue: str | None = None  # JSON [{section, label, url}] — services activables (rechargeable)
    acronymes: str | None = None      # JSON [{sigle, definition}] — normalisation de casse
    # Seuils de pertinence de la recherche (cosinus 0-1) — curseur « souple ↔ stricte ».
    search_cos_haut: str | None = None
    search_cos_bas: str | None = None
    # Sauvegarde auto de la base : intervalle en heures (0 = off) + nb de sauvegardes conservées.
    backup_auto_heures: str | None = None
    backup_retention: str | None = None
    rapports_purge_jours: str | None = None
    # Concurrence du worker (réglable à chaud) : budgets GPU (Ollama) et I/O (réseau/disque).
    concurrence_gpu: str | None = None
    concurrence_io: str | None = None


@router.get("/version", tags=["Système"])
async def get_version() -> dict:
    """Retourne la version de l'application (lue depuis le fichier VERSION racine)."""
    return {"name": settings.app_name, "version": settings.app_version}


# ─── Configuration éditable (URLs services + modèle par défaut) ───────────────

def _mask_secrets(config: dict) -> dict:
    """Remplace la valeur des clés secrètes par un masque (ne jamais exposer le secret)."""
    for cle in runtime_config.SECRET_KEYS:
        entry = config.get(cle)
        if entry and entry.get("valeur"):
            entry["valeur"] = "••••••••"        # défini mais masqué
            entry["defini"] = True
        elif entry:
            entry["defini"] = False
    return config


@router.get("/system/config", tags=["Système"])
async def get_config() -> dict:
    """Configuration effective (surcharges base + défauts env, avec la source). Secrets masqués."""
    return {"config": _mask_secrets(runtime_config.all_effective())}


@router.put("/system/config", tags=["Système"])
async def update_config(body: ConfigUpdate, db: AsyncSession = Depends(get_db)) -> dict:
    """Met à jour les surcharges de configuration (persistées en base, effet immédiat)."""
    from services.crypto import encrypt, is_encrypted

    data = {k: v for k, v in body.model_dump().items() if v is not None and v.strip()}
    # Chiffrer les valeurs secrètes avant persistance (jamais en clair en base).
    for cle in runtime_config.SECRET_KEYS:
        if cle in data and not is_encrypted(data[cle]):
            data[cle] = encrypt(data[cle])
    if data:
        await runtime_config.set_many(db, data)
    return {"config": _mask_secrets(runtime_config.all_effective()), "mis_a_jour": list(data.keys())}


@router.post("/system/normaliser-metadata", tags=["Système"])
async def normaliser_metadata(db: AsyncSession = Depends(get_db)) -> dict:
    """
    Normalise la CASSE et les ACCENTS des tags et catégories (fusionne les variantes :
    « présentation »/« presentation », « iban »→« IBAN »…). Sauvegarde préalable
    (`storage/backup-normalisation.json`) → réversible. Utilise le dictionnaire d'acronymes
    (config `acronymes`, éditable dans Paramètres) pour forcer les sigles en majuscules.
    """
    from services.normalisation import normaliser_metadonnees
    resume = await normaliser_metadonnees(db)
    return {"ok": True, "resume": resume}


@router.post("/system/backup-db", tags=["Système"])
async def backup_db() -> dict:
    """Crée une **sauvegarde** de la base (pg_dump, format restaurable) dans `storage/backups/`."""
    from services import backup
    try:
        return {"ok": True, **(await backup.dump())}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Sauvegarde échouée : {exc}")


@router.get("/system/backups", tags=["Système"])
async def list_backups() -> dict:
    """Liste les sauvegardes disponibles."""
    from services import backup
    return {"backups": backup.liste()}


@router.get("/system/backups/{fichier}", tags=["Système"])
async def download_backup(fichier: str):
    """Télécharge un fichier de sauvegarde. Garde-fou anti-traversée : nom simple `*.dump` dans BACKUP_DIR."""
    from fastapi.responses import FileResponse
    from services import backup
    # Sécurité : refuse tout séparateur de chemin / remontée, n'autorise qu'un .dump du dossier de backups.
    if "/" in fichier or "\\" in fichier or ".." in fichier or not fichier.endswith(".dump"):
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    chemin = backup.BACKUP_DIR / fichier
    if not chemin.is_file():
        raise HTTPException(status_code=404, detail="Sauvegarde introuvable")
    return FileResponse(str(chemin), filename=fichier, media_type="application/octet-stream")


# ─── Catalogue de services publics + vérification des liens Administration ─────

class VerifierLiensRequest(BaseModel):
    """Liste d'URLs à sonder. Rien d'autre n'est transmis au réseau."""
    urls: list[str]


def _hote_url(url: str) -> str:
    """Hôte normalisé (minuscule, sans « www. ») pour comparer une URL avant/après redirection."""
    try:
        h = httpx.URL(url if "://" in url else f"https://{url}").host or ""
    except Exception:  # noqa: BLE001
        h = ""
    return h.lower().removeprefix("www.")


@router.get("/system/admin-catalogue", tags=["Système"])
async def get_admin_catalogue() -> dict:
    """
    Catalogue de services publics activables dans l'éditeur de liens Administration.
    Piloté par la config `admin_catalogue` (rechargeable / extensible sans rebuild). 100 % local.
    """
    try:
        cat = json.loads(runtime_config.effective("admin_catalogue") or "[]")
    except ValueError:
        cat = []
    return {"catalogue": cat if isinstance(cat, list) else []}


@router.post("/system/admin-links/verifier", tags=["Système"])
async def verifier_admin_links(body: VerifierLiensRequest) -> dict:
    """
    Vérifie l'état des liens Administration — **SORTIE RÉSEAU**, sur action confirmée de l'utilisateur
    (bouton « Vérifier les liens », passant par la confirmation « Demandes Mise à jour internet »).
    N'envoie QUE les URLs à tester : jamais un document, un tag, un résumé, un chemin ni un nom de fichier.

    Par URL :
      - `ok`          : le site répond (2xx/3xx sur le même hôte) ;
      - `deplace`     : redirigé vers un AUTRE hôte → `url_finale` proposée (service déplacé) ;
      - `mort`        : 404 / 410 (page supprimée) ;
      - `injoignable` : DNS / timeout / erreur réseau / code ≥ 400.
    """
    async def sonde(client: httpx.AsyncClient, method: str, url: str) -> tuple[int, str]:
        if method == "HEAD":
            r = await client.head(url)
            return r.status_code, str(r.url)
        # GET en streaming : suit les redirections sans télécharger le corps de la page.
        async with client.stream("GET", url) as r:
            return r.status_code, str(r.url)

    async def tester(client: httpx.AsyncClient, url: str) -> dict:
        try:
            code, finale = await sonde(client, "HEAD", url)
            if code in (403, 405, 501):        # HEAD refusé → on retente en GET
                code, finale = await sonde(client, "GET", url)
        except Exception:  # noqa: BLE001
            try:
                code, finale = await sonde(client, "GET", url)
            except Exception:  # noqa: BLE001
                return {"url": url, "statut": "injoignable", "code": None}
        if code in (404, 410):
            return {"url": url, "statut": "mort", "code": code}
        if 200 <= code < 400:
            deplace = _hote_url(finale) != _hote_url(url)
            res = {"url": url, "statut": "deplace" if deplace else "ok", "code": code}
            if deplace:
                res["url_finale"] = finale
            return res
        return {"url": url, "statut": "injoignable", "code": code}

    urls = [u for u in dict.fromkeys(body.urls) if u and u.strip()]
    if not urls:
        return {"resultats": []}
    timeout = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Matotheque LinkCheck)"},
    ) as client:
        resultats = await asyncio.gather(*[tester(client, u) for u in urls])
    return {"resultats": list(resultats)}


# ─── Statut des services (sous /api → fiable derrière le proxy) ───────────────

async def _ping_n8n(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            return (await client.get(f"{url}/healthz")).status_code == 200
    except Exception:
        return False


async def _etat_service(url: str, path: str = "") -> str:
    """3 états : 'ok' (répond <400) · 'busy' (joignable mais lent = occupé) · 'down' (injoignable)."""
    import httpx
    if not url:
        return "down"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=2.0, read=3.0, write=3.0, pool=3.0)) as c:
            r = await c.get(url.rstrip("/") + path)
            return "ok" if r.status_code < 400 else "busy"
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return "down"        # injoignable = PC éteint / pare-feu / DNS
    except httpx.TimeoutException:
        return "busy"        # connecté mais lent = occupé (ex. Ollama charge un modèle)
    except Exception:  # noqa: BLE001
        return "down"


@router.get("/system/services", tags=["Système"])
async def services_status() -> dict:
    """Statut live des services externes (voyant 3 états : ok / busy / down)."""
    tika = TikaService()
    ollama = OllamaService()
    n8n_url = runtime_config.effective("n8n_url")
    from services import clamav_service
    from services.bookstack_service import BookStackService
    clamav_url = f"{settings.clamav_host}:{settings.clamav_port}" if settings.clamav_host else "désactivé"
    bookstack = BookStackService()
    bookstack_ok = await bookstack.check_health() if bookstack.configured else False
    ollama_etat = await _etat_service(ollama.base_url, "/api/tags")
    n8n_etat = await _etat_service(n8n_url)
    from services import transcription_service
    transcription_url = runtime_config.effective("transcription_url") or ""
    transcription_configure = transcription_service.is_enabled()
    return {
        "tika":      {"url": tika.base_url,     "ok": await tika.check_health()},
        "ollama":    {"url": ollama.base_url,   "ok": ollama_etat == "ok", "etat": ollama_etat},
        "n8n":       {"url": n8n_url,            "ok": n8n_etat == "ok", "etat": n8n_etat},
        "clamav":    {"url": clamav_url,         "ok": await clamav_service.check_health()},
        "bookstack": {"url": bookstack.base_url, "ok": bookstack_ok, "configure": bookstack.configured},
        "transcription": {"url": transcription_url, "configure": transcription_configure,
                          "ok": await transcription_service.check_health() if transcription_configure else False},
    }


# ─── Modèles IA disponibles (dynamique depuis Ollama) ─────────────────────────

_UNCENSORED_RE = re.compile(r"uncensored|uncensured|abliterat|dolphin|mythos", re.IGNORECASE)


def _classe_nom(name: str) -> str:
    """Classe déduite du NOM (fallback local, sans réseau)."""
    n = name.lower()
    return "uncensored" if (_UNCENSORED_RE.search(n) or "hf.co/" in n) else "officiel"


@router.get("/system/model-status", tags=["Système"])
async def model_status(usage: str = Query(default="rapport")) -> dict:
    """
    Le modèle d'un usage (défaut `rapport`) est-il **chargé en mémoire** (génération instantanée)
    ou à froid (il faudra le charger — potentiellement long pour un gros modèle) ?
    """
    from services import runtime_config
    from services.ollama_service import OllamaService
    modele = runtime_config.model_for(usage)
    ollama = OllamaService()
    charge = await ollama.is_loaded(modele) if modele else False
    return {"usage": usage, "modele": modele, "charge": charge}


@router.post("/system/warm-model", tags=["Système"])
async def warm_model(usage: str = Query(default="rapport")) -> dict:
    """
    Pré-charge le modèle d'un usage en mémoire (« Préparer le modèle ») pour que la prochaine
    génération démarre sans attente. Best effort ; renvoie l'état après tentative.
    """
    import time as _time
    from services import runtime_config
    from services.ollama_service import OllamaService
    modele = runtime_config.model_for(usage)
    if not modele:
        raise HTTPException(status_code=400, detail="Aucun modèle configuré pour cet usage")
    ollama = OllamaService()
    t0 = _time.monotonic()
    ok = await ollama.warm(modele)
    return {"usage": usage, "modele": modele, "ok": ok, "charge": ok,
            "duree_ms": int((_time.monotonic() - t0) * 1000)}


@router.get("/system/models", tags=["Système"])
async def list_models(
    check_updates: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Liste les modèles Ollama installés (nom + taille). Si `check_updates=true`,
    ajoute `update: true|false|null` (registre Ollama) ET **persiste la classe**
    (officiel/uncensored) en base. Sans vérif, on **relit la classe persistée** (ou déduite
    du nom si jamais vérifiée) — pas de re-devinette.
    """
    import asyncio

    from models.model_meta import ModelMeta

    try:
        ollama = OllamaService()
        modeles = await ollama.list_models_detailed()
        if check_updates and modeles:
            verdicts = await asyncio.gather(
                *(ollama.check_update(m["name"], m.get("digest", "")) for m in modeles),
                return_exceptions=True,
            )
            for m, v in zip(modeles, verdicts):
                m["update"] = None if isinstance(v, BaseException) else v
            # Persister la classe seulement si le registre a bien répondu (au moins un verdict
            # non-nul) — sinon un souci réseau classerait tout en « uncensored » à tort.
            if any(m.get("update") in (True, False) for m in modeles):
                for m in modeles:
                    # update None (hors registre) = import perso → uncensored ; sinon nom/registre.
                    classe = "uncensored" if m.get("update") is None else _classe_nom(m["name"])
                    existing = await db.get(ModelMeta, m["name"])
                    if existing:
                        existing.classe = classe
                    else:
                        db.add(ModelMeta(name=m["name"], classe=classe))
                await db.commit()

        # Attacher la classe PERSISTÉE (ou fallback nom si jamais vérifiée).
        rows = (await db.execute(select(ModelMeta))).scalars().all()
        metamap = {r.name: r.classe for r in rows}
        from services import model_catalog
        for m in modeles:
            m["classe"] = metamap.get(m["name"]) or _classe_nom(m["name"])
            # Descriptif + évaluation (icône « i » + tableau comparatif). Connu → base, sinon dérivé.
            m["info"] = model_catalog.decrire(m["name"], m.get("size", 0), m.get("parametres"))

        # `defaut` = `default_model` (compat). ⚠️ Ce N'EST PAS forcément le modèle appliqué :
        # la génération route par USAGE (`model_for("rapport")`). L'interface affichait
        # « Auto : llama3.1 » alors qu'un rapport partait sur Qwen3.6-35B (43 Go) — l'utilisateur
        # croyait lancer un modèle rapide et se heurtait à un délai d'attente. On expose donc
        # le modèle réellement retenu POUR CHAQUE USAGE.
        return {
            "models": modeles,
            "defaut": runtime_config.effective("default_model"),
            "par_usage": {u: runtime_config.model_for(u)
                          for u in ("rapport", "chat", "enrichissement", "vision", "embeddings")},
        }
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("Liste des modèles indisponible", erreur=str(exc))
        raise HTTPException(status_code=503, detail=f"Ollama injoignable : {exc}")


class PullRequest(BaseModel):
    """Modèle à télécharger / mettre à jour."""
    name: str


@router.post("/system/models/pull", tags=["Système"])
async def pull_model(body: PullRequest):
    """
    Met à jour (ou télécharge) un modèle via `ollama pull`, en streaming NDJSON
    (chaque ligne = progression). Le front lit le flux pour afficher l'avancement.
    """
    from fastapi.responses import StreamingResponse

    async def _stream():
        try:
            async for line in OllamaService().pull_stream(body.name):
                yield line + "\n"
        except Exception as exc:
            import json as _json
            yield _json.dumps({"error": str(exc)}) + "\n"

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


# ─── Test de connexion par service ────────────────────────────────────────────

@router.post("/system/test/{service}", tags=["Système"])
async def test_service(service: str, body: ConfigUpdate | None = None) -> dict:
    """
    Teste la connexion à un service (tika | ollama | n8n).
    Si une URL est fournie dans le body, teste CELLE-CI (avant de sauvegarder) ;
    sinon teste l'URL effective courante.
    """
    overrides = body.model_dump() if body else {}
    if service == "tika":
        url = overrides.get("tika_url") or runtime_config.effective("tika_url")
        ok = await TikaService(base_url=url).check_health()
        return {"service": "tika", "url": url, "ok": ok}
    if service == "ollama":
        url = overrides.get("ollama_url") or runtime_config.effective("ollama_url")
        ok = await OllamaService(base_url=url).check_health()
        return {"service": "ollama", "url": url, "ok": ok}
    if service == "n8n":
        url = overrides.get("n8n_url") or runtime_config.effective("n8n_url")
        ok = False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{url}/healthz")
                ok = resp.status_code == 200
        except Exception:
            ok = False
        return {"service": "n8n", "url": url, "ok": ok}
    if service == "transcription":
        # Serveur de transcription (compatible OpenAI). Teste l'URL fournie (avant sauvegarde)
        # ou l'URL effective. Un simple GET /v1/models ou /health suffit à valider la joignabilité.
        url = (overrides.get("transcription_url") or runtime_config.effective("transcription_url") or "").strip().rstrip("/")
        if not url:
            return {"service": "transcription", "url": "", "ok": False, "erreur": "URL non configurée"}
        ok = False
        for chemin in ("/v1/models", "/health", "/"):
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.get(f"{url}{chemin}")
                if resp.status_code < 500:
                    ok = True
                    break
            except Exception:  # noqa: BLE001
                continue
        return {"service": "transcription", "url": url, "ok": ok}
    if service == "bookstack":
        from services.bookstack_service import BookStackService
        url = overrides.get("bookstack_url") or runtime_config.effective("bookstack_url")
        token_id = overrides.get("bookstack_token_id") or runtime_config.effective("bookstack_token_id")
        # Secret : si fourni dans le formulaire (et pas le masque), on teste celui-ci ;
        # sinon on retombe sur le secret stocké (déchiffré par le service).
        secret_override = overrides.get("bookstack_token_secret")
        if not secret_override or secret_override.strip() in ("", "••••••••"):
            secret_override = None
        bookstack = BookStackService(base_url=url, token_id=token_id, token_secret=secret_override)
        ok = await bookstack.check_health()
        return {"service": "bookstack", "url": url, "ok": ok, "configure": bookstack.configured}
    if service == "huggingface":
        # ⚠️ Appel réseau vers huggingface.co (confirmé côté UI). N'envoie QUE le token.
        from services.crypto import decrypt, is_encrypted
        raw = overrides.get("huggingface_token")
        if not raw or raw.strip() in ("", "••••••••"):
            raw = runtime_config.effective("huggingface_token")
        if not raw:
            return {"service": "huggingface", "ok": False, "erreur": "Aucun token HuggingFace configuré"}
        token = decrypt(raw) if is_encrypted(raw) else raw
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://huggingface.co/api/whoami-v2",
                    headers={"Authorization": f"Bearer {token}"},
                )
            if resp.status_code == 200:
                d = resp.json()
                return {"service": "huggingface", "ok": True,
                        "user": d.get("name") or d.get("fullname"), "type": d.get("type")}
            return {"service": "huggingface", "ok": False, "erreur": f"HTTP {resp.status_code} (token invalide ?)"}
        except Exception as exc:  # noqa: BLE001
            return {"service": "huggingface", "ok": False, "erreur": str(exc)}
    raise HTTPException(status_code=400, detail="Service inconnu (tika | ollama | n8n | bookstack | huggingface)")


def _tail(path: Path, n: int) -> tuple[list[str], dict]:
    """
    `n` dernières lignes + DIAGNOSTIC du fichier.

    ⚠️ Avant, cette fonction renvoyait `[]` aussi bien pour un fichier **absent**, **illisible**
    que **vide** → la page Logs était incapable de signaler qu'elle était aveugle (la prod n'a
    produit aucun log pendant des jours sans que rien ne l'indique). On renvoie donc l'état.
    """
    diag: dict = {"existe": False, "taille_octets": 0, "lisible": False, "erreur": None}
    if not path.exists():
        diag["erreur"] = "fichier absent"
        return [], diag
    diag["existe"] = True
    try:
        taille = path.stat().st_size
        diag["taille_octets"] = taille
        # Lecture par la FIN : on ne charge que les derniers Ko. `readlines()` chargeait TOUT le
        # fichier en mémoire (261 Mo constatés) juste pour afficher 100 lignes.
        bloc = min(taille, max(n, 1) * 2048 + 8192)      # ~2 Ko par ligne, large marge
        with path.open("rb") as f:
            f.seek(taille - bloc)
            brut = f.read(bloc)
        texte = brut.decode("utf-8", errors="replace")
        lignes = texte.splitlines()
        if bloc < taille and lignes:
            lignes = lignes[1:]      # 1re ligne probablement tronquée par le seek
        diag["lisible"] = True
        if not lignes:
            diag["erreur"] = "fichier vide"
        return lignes[-n:], diag
    except OSError as exc:
        diag["erreur"] = f"lecture impossible : {exc}"
        return [], diag


@router.get("/logs/tail", tags=["Système"])
async def logs_tail(
    lines: int = Query(default=100, ge=1, le=2000, description="Nombre de lignes à retourner"),
) -> dict:
    """
    Retourne les dernières lignes du log applicatif.

    NOTE : le modèle prévoit une protection « admin » sur cet endpoint.
    DocFlow AI n'a pas encore d'authentification ; la protection devra être
    ajoutée en même temps que le module auth (cf. ROADMAP).
    """
    from logger import etat_fichier_log

    etat = etat_fichier_log()      # le handler fichier a-t-il vraiment été branché ?
    log_file = settings.log_file
    if not log_file:
        return {"lines": [], "count": 0, "source": None, "diagnostic": {
            "actif": False, "erreur": "LOG_FILE non configuré",
            "conseil": "Définir LOG_FILE (ex. /app/logs/docflow-backend.log) et monter ./logs.",
        }}

    path = Path(log_file)
    tail, diag = _tail(path, lines)
    # « aveugle » = on ne peut RIEN montrer alors que des logs devraient exister.
    aveugle = not tail and (not etat.get("actif") or not diag.get("existe") or diag.get("taille_octets") == 0)
    conseil = None
    if aveugle:
        if not etat.get("actif"):
            conseil = ("Le handler fichier n'est PAS actif : les logs partent uniquement sur la sortie "
                       "standard (docker logs). Vérifie les droits du montage ./logs (conteneur = uid 10001) "
                       "puis redémarre le service.")
        elif not diag.get("existe"):
            conseil = "Le fichier n'existe pas encore — il sera créé au prochain message journalisé."
        else:
            conseil = "Le fichier existe mais est vide (aucun message écrit depuis le démarrage)."
    return {
        "lines": tail, "count": len(tail), "source": str(path),
        "diagnostic": {**diag, "actif": etat.get("actif"), "erreur_handler": etat.get("erreur"),
                       "aveugle": aveugle, "conseil": conseil},
    }
