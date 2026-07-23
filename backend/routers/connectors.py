"""
Router Connecteurs — /api/connectors
=====================================
Sources externes (cloud / NAS DSM) en LECTURE. Un **compte connecté = une `Source`**
(multi-comptes natif). P0 : créer / tester / parcourir. L'indexation réutilise le
pipeline durable existant (via le connecteur `walk_files`/`fetch_to_temp`).
"""
import base64
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
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


@router.get("/connectors/oauth/start", tags=["Connecteurs"])
async def oauth_start(request: Request, libelle: str = Query(default="Google Drive")) -> dict:
    """
    Démarre la connexion d'un compte Google : renvoie l'URL de consentement à ouvrir dans le
    navigateur. `state` encode le libellé souhaité (round-trip, sans stockage serveur → OK
    en multi-process). Nécessite `gdrive_client_id`/`secret` configurés (Paramètres).
    """
    from services.connectors import gdrive
    redirect = _redirect_uri(request)
    state = base64.urlsafe_b64encode(json.dumps({"libelle": libelle}).encode()).decode()
    try:
        return {"url": gdrive.auth_url(redirect, state), "redirect_uri": redirect}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/connectors/oauth/callback", tags=["Connecteurs"])
async def oauth_callback(request: Request, db: AsyncSession = Depends(get_db),
                         code: str | None = Query(default=None), state: str | None = Query(default=None),
                         error: str | None = Query(default=None)) -> RedirectResponse:
    """
    Callback OAuth Google : échange le `code` contre un refresh_token, crée le compte
    (`Source` type='gdrive', refresh_token chiffré) puis **redirige vers les Paramètres**.
    """
    dest = "/settings?connecteur=gdrive"
    if error or not code:
        return RedirectResponse(url=f"{dest}&statut=refus")
    from services.connectors import gdrive
    from services.crypto import encrypt
    try:
        libelle = "Google Drive"
        if state:
            try:
                libelle = json.loads(base64.urlsafe_b64decode(state).decode()).get("libelle", libelle)
            except Exception:  # noqa: BLE001
                pass
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
