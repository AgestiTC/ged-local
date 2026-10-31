"""
Router Connecteurs — /api/connectors
=====================================
Sources externes (cloud / NAS DSM) en LECTURE. Un **compte connecté = une `Source`**
(multi-comptes natif). P0 : créer / tester / parcourir. L'indexation réutilise le
pipeline durable existant (via le connecteur `walk_files`/`fetch_to_temp`).
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.source import Source

log = get_logger(__name__)
router = APIRouter()


def _redirect_uri(request: Request) -> str:
    """
    URI de callback OAuth — doit correspondre EXACTEMENT à celle enregistrée dans Google Cloud.
    Priorité à la config `oauth_redirect_uri` (recommandé en prod derrière un proxy) ; sinon
    déduite de la requête (utile en dev). Cf. docs/setup-google-drive-oauth.md.
    """
    from services import runtime_config
    forcee = runtime_config.effective("oauth_redirect_uri")
    if forcee:
        return forcee
    return str(request.base_url).rstrip("/") + "/api/connectors/oauth/callback"


COOKIE_OAUTH = "matotheque_oauth"       # lie le `state` au navigateur qui a lancé la connexion
CHEMIN_OAUTH = "/api/connectors/oauth"   # le cookie ne part que vers start/callback
OAUTH_TTL_S = 600
_CONTEXTE_OAUTH = "connecteur-oauth-state"


def _b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode()


def _debase(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def _empreinte_cookie(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _signer_state(libelle: str, secret_nav: str) -> str:
    """`state` = charge utile (nonce, libellé, expiration, empreinte du cookie) + signature HMAC."""
    from services import crypto
    charge = _b64(json.dumps({"n": secrets.token_urlsafe(16), "l": libelle, "e": int(time.time()) + OAUTH_TTL_S,
                              "b": _empreinte_cookie(secret_nav)}).encode())
    sig = _b64(hmac.new(crypto.cle_derivee(_CONTEXTE_OAUTH), charge.encode(), hashlib.sha256).digest())
    return f"{charge}.{sig}"


def _lire_state(state: str | None, secret_nav: str | None) -> str | None:
    """Libellé si le state est authentique, non expiré ET lié à CE navigateur ; sinon None."""
    from services import crypto
    try:
        charge, sig = (state or "").split(".")
        attendue = _b64(hmac.new(crypto.cle_derivee(_CONTEXTE_OAUTH), charge.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig.encode(), attendue.encode()):
            return None
        d = json.loads(_debase(charge))
        if not secret_nav or int(d["e"]) < time.time():
            return None
        if not hmac.compare_digest(d["b"].encode(), _empreinte_cookie(secret_nav).encode()):
            return None
        return str(d["l"])
    except Exception:  # noqa: BLE001 — tout état illisible est refusé
        return None


def _https(request: Request) -> bool:
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return proto == "https" or (not proto and request.url.scheme == "https")


@router.get("/connectors/oauth/start", tags=["Connecteurs"])
async def oauth_start(request: Request, libelle: str = Query(default="Google Drive", max_length=100),
                      db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """
    Démarre la connexion d'un compte Google : renvoie l'URL de consentement à ouvrir dans le
    navigateur. `state` est SIGNÉ (clé dérivée du secret serveur), expire en 10 min et est lié par un
    cookie court à ce navigateur : un lien piégé ne peut pas faire créer un compte de l'attaquant
    (login-CSRF OAuth). Nécessite `gdrive_client_id`/`secret` configurés (Paramètres).
    """
    from services import runtime_config
    from services.connectors import gdrive
    await runtime_config.load(db)   # config fraîche (immunise du cache multi-process)
    redirect = _redirect_uri(request)
    secret_nav = secrets.token_urlsafe(32)
    state = _signer_state(libelle, secret_nav)
    try:
        rep = JSONResponse({"url": gdrive.auth_url(redirect, state), "redirect_uri": redirect})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))
    rep.set_cookie(COOKIE_OAUTH, secret_nav, max_age=OAUTH_TTL_S, httponly=True, samesite="lax",
                   path=CHEMIN_OAUTH, secure=_https(request))
    return rep


@router.get("/connectors/oauth/callback", tags=["Connecteurs"])
async def oauth_callback(request: Request, db: AsyncSession = Depends(get_db),
                         code: str | None = Query(default=None), state: str | None = Query(default=None),
                         error: str | None = Query(default=None)) -> RedirectResponse:
    """
    Callback OAuth Google : échange le `code` contre un refresh_token, crée le compte
    (`Source` type='gdrive', refresh_token chiffré) puis **redirige vers les Paramètres**.
    """
    rep = await _oauth_callback(request, db, code, state, error)
    # Le cookie de liaison n'a servi qu'une fois : effacé quelle que soit l'issue.
    rep.delete_cookie(COOKIE_OAUTH, path=CHEMIN_OAUTH, httponly=True, samesite="lax", secure=_https(request))
    return rep


async def _oauth_callback(request: Request, db: AsyncSession, code: str | None, state: str | None,
                          error: str | None) -> RedirectResponse:
    dest = "/settings?connecteur=gdrive"
    if error or not code:
        return RedirectResponse(url=f"{dest}&statut=refus")
    # AVANT toute création et tout échange du code : le state doit être authentique, frais et lié
    # à ce navigateur.
    libelle = _lire_state(state, request.cookies.get(COOKIE_OAUTH))
    if libelle is None:
        log.warning("Callback OAuth refusé : state invalide, expiré ou non lié à ce navigateur")
        return RedirectResponse(url=f"{dest}&statut=erreur")
    from services import runtime_config
    from services.connectors import gdrive
    from services.crypto import encrypt
    await runtime_config.load(db)   # secret/id à jour même si un autre process a la version en cache
    try:
        toks = await gdrive.exchange_code(code, _redirect_uri(request))
        if not toks.get("refresh_token"):
            # Google ne renvoie le refresh_token qu'au 1er consentement → prompt=consent force.
            return RedirectResponse(url=f"{dest}&statut=sans_refresh")
        email = toks.get("email") or ""
        libelle_complet = f"{libelle} ({email})" if email else libelle
        src = Source(type="gdrive", libelle=libelle_complet,
                     hote="drive.google.com", identifiant=email,
                     secret_chiffre=encrypt(toks["refresh_token"]), chemin_base="root")
        db.add(src)
        await db.commit()
        log.info("Compte Google Drive connecté", email=toks.get("email"))
        return RedirectResponse(url=f"{dest}&statut=ok")
    except Exception as e:  # noqa: BLE001
        log.error("Échec du callback OAuth Google", erreur=str(e))
        return RedirectResponse(url=f"{dest}&statut=erreur")


class ConnecteurCreate(BaseModel):
    type: str = Field(description="Type de connecteur (ex. synology)")
    libelle: str = Field(min_length=1)
    hote: str = Field(min_length=1, description="ID QuickConnect, IP/host(:port) ou URL")
    identifiant: str
    mot_de_passe: str
    chemin_base: str | None = None


def _src_dict(s: Source) -> dict:
    return {"id": str(s.id), "type": s.type, "libelle": s.libelle, "hote": s.hote,
            "identifiant": s.identifiant, "chemin_base": s.chemin_base, "actif": s.actif}


@router.get("/connectors", tags=["Connecteurs"])
async def types_disponibles() -> dict:
    """Types de connecteurs gérés + liste des comptes déjà connectés."""
    from services.connectors import types_supportes
    types = types_supportes()
    return {"types": types}


@router.get("/connectors/comptes", tags=["Connecteurs"])
async def lister_comptes(db: AsyncSession = Depends(get_db)) -> dict:
    """Comptes connectés (sources dont le type est géré par un connecteur)."""
    from services.connectors import types_supportes
    types = set(types_supportes())
    rows = (await db.execute(select(Source))).scalars().all()
    return {"comptes": [_src_dict(s) for s in rows if s.type in types]}


@router.post("/connectors", tags=["Connecteurs"])
async def creer_compte(body: ConnecteurCreate, db: AsyncSession = Depends(get_db)) -> dict:
    """Crée un compte connecté (secret chiffré). Ne l'indexe pas encore."""
    from services.connectors import get_connector
    if not get_connector(body.type):
        raise HTTPException(status_code=422, detail=f"Type de connecteur inconnu : {body.type}")
    from services.crypto import encrypt
    src = Source(type=body.type, libelle=body.libelle, hote=body.hote,
                 identifiant=body.identifiant, secret_chiffre=encrypt(body.mot_de_passe),
                 chemin_base=body.chemin_base)
    db.add(src)
    await db.commit()
    await db.refresh(src)
    log.info("Compte connecteur créé", type=body.type, libelle=body.libelle)
    return _src_dict(src)


class RemarkablePair(BaseModel):
    """Appairage reMarkable : code à usage unique (my.remarkable.com/device/desktop)."""
    code: str = Field(min_length=6, description="Code d'appairage reMarkable (usage unique)")
    libelle: str = Field(default="reMarkable", min_length=1)


@router.post("/connectors/remarkable/pair", tags=["Connecteurs"])
async def remarkable_pair(body: RemarkablePair, db: AsyncSession = Depends(get_db)) -> dict:
    """
    Appaire un compte **reMarkable** via son code à usage unique → device token durable (chiffré),
    puis crée la Source (`type='remarkable'`). Le connecteur générique gère ensuite test/index.
    """
    from services.connectors import remarkable
    from services.crypto import encrypt
    try:
        device_id, device_token = await remarkable.register_device(body.code)
    except remarkable.RemarkableError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — réseau reMarkable indisponible
        raise HTTPException(status_code=502, detail=f"reMarkable injoignable : {exc}")
    src = Source(type="remarkable", libelle=body.libelle.strip(),
                 identifiant=device_id, secret_chiffre=encrypt(device_token))
    db.add(src)
    await db.commit()
    await db.refresh(src)
    log.info("Compte reMarkable appairé", source_id=str(src.id), libelle=body.libelle)
    return _src_dict(src)


async def _get_src_conn(source_id: str, db: AsyncSession):
    from services.connectors import get_connector
    try:
        src = await db.get(Source, uuid.UUID(source_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="ID invalide")
    if not src:
        raise HTTPException(status_code=404, detail="Compte introuvable")
    conn = get_connector(src.type)
    if not conn:
        raise HTTPException(status_code=422, detail=f"Type '{src.type}' sans connecteur")
    return src, conn


@router.post("/connectors/{source_id}/test", tags=["Connecteurs"])
async def tester(source_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Teste la connexion (auth + joignabilité)."""
    src, conn = await _get_src_conn(source_id, db)
    try:
        ok = await conn.test(src)
        return {"ok": ok}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Connexion impossible : {exc}")


@router.get("/connectors/{source_id}/browse", tags=["Connecteurs"])
async def parcourir(source_id: str, chemin: str = Query(default="/"),
                    db: AsyncSession = Depends(get_db)) -> dict:
    """Liste un dossier distant (racine = partages)."""
    src, conn = await _get_src_conn(source_id, db)
    try:
        return {"chemin": chemin, "entrees": await conn.browse(src, chemin)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Navigation impossible : {exc}")


@router.post("/connectors/{source_id}/index", tags=["Connecteurs"])
async def indexer(source_id: str, chemin: str = Query(default="/", description="Dossier distant à indexer"),
                  db: AsyncSession = Depends(get_db)) -> dict:
    """Met en file une **indexation durable** du compte (tâche `index_connector`)."""
    src, _ = await _get_src_conn(source_id, db)
    from services import job_worker
    job_id = await job_worker.enqueue(db, "index_connector",
                                      {"source_id": str(src.id), "chemin": chemin}, document_id=None)
    await db.commit()
    log.info("Indexation connecteur mise en file", source_id=str(src.id), chemin=chemin, job_id=job_id)
    return {"job_id": job_id, "statut": "pending", "chemin": chemin}
