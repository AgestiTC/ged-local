"""
Router /api/auth — connexion par le SSO du NAS (OpenID Connect, code + PKCE)
============================================================================
login → (SSO) → callback → cookie de session → me / logout. Sessions et tentatives en base.
Étape 1 du plan : AUCUNE route existante n'est protégée ici ; `utilisateur_courant` est fournie
pour l'étape 2. Les journaux ne contiennent jamais de jeton, de code ni de secret.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from logger import get_logger
from models.auth import OidcTentative, SessionAuth, Utilisateur
from services import acces, oidc_service, runtime_config
from services.oidc_service import OidcError

log = get_logger(__name__)
router = APIRouter()

COOKIE = "matotheque_session"
COOKIE_NAVIGATEUR = "matotheque_oidc"   # lie le state au navigateur qui a lancé la connexion
TENTATIVE_TTL = timedelta(minutes=10)
MAJ_ACTIVITE = timedelta(minutes=1)   # au plus une écriture d'activité par minute et par session


def _utc(dt: datetime | None) -> datetime | None:
    """SQLite rend des dates naïves : on les lit comme UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _https(request: Request) -> bool:
    proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    return proto == "https" or (not proto and request.url.scheme == "https")


def _erreur(code: str) -> RedirectResponse:
    return RedirectResponse(f"/?{urlencode({'auth_erreur': code})}", status_code=302)


async def _utilisateur_par_sub(db: AsyncSession, emetteur: str, sub: str) -> Utilisateur | None:
    """Fiche d'un compte : le `sub` n'est unique que PAR émetteur."""
    return (await db.execute(select(Utilisateur).where(
        Utilisateur.emetteur == emetteur, Utilisateur.sub == sub))).scalar_one_or_none()


# ─── Session courante (réutilisée par l'étape 2) ──────────────────────────────

async def _session_valide(request: Request, db: AsyncSession) -> tuple[SessionAuth, Utilisateur] | None:
    """Session du cookie si elle est valide ; sinon (expirée, compte bloqué) la supprime."""
    jeton = request.cookies.get(COOKIE)
    if not jeton:
        return None
    sid = oidc_service.hacher_jeton(jeton)
    # Une seule lecture jointe ; mises à jour et suppressions en SQL direct : pas d'erreur si un
    # logout (autre worker) a supprimé la session entre-temps.
    ligne = (await db.execute(
        select(SessionAuth, Utilisateur).join(Utilisateur, Utilisateur.id == SessionAuth.utilisateur_id)
        .where(SessionAuth.id == sid))).first()
    if ligne is None:
        return None
    sess, user = ligne
    now = oidc_service.maintenant()
    derniere = _utc(sess.derniere_activite)
    inactif = now - derniere > timedelta(seconds=oidc_service.inactivite_s())
    if inactif or now >= _utc(sess.expire_max) or user.bloque:
        await db.execute(delete(SessionAuth).where(SessionAuth.id == sid)
                         .execution_options(synchronize_session=False))
        await db.commit()
        return None
    if now - derniere >= MAJ_ACTIVITE:
        # Conditionnel : si un autre process vient de la rafraîchir, on n'écrit pas deux fois.
        await db.execute(update(SessionAuth).where(
            SessionAuth.id == sid, SessionAuth.derniere_activite < now - MAJ_ACTIVITE)
            .values(derniere_activite=now).execution_options(synchronize_session=False))
        await db.commit()
    return sess, user


async def utilisateur_courant(request: Request, db: AsyncSession = Depends(get_db)) -> Utilisateur | None:
    """Dépendance FastAPI : l'utilisateur de la session, ou None (ne lève jamais)."""
    r = await _session_valide(request, db)
    return r[1] if r else None


# ─── Routes ───────────────────────────────────────────────────────────────────

def _no_store(rep):
    """Réponses d'authentification : jamais mises en cache (par le navigateur ou un proxy)."""
    rep.headers["Cache-Control"] = "no-store"
    return rep


MAX_TENTATIVES = 200   # connexions en cours simultanées (borne la table face à des appels en boucle)


@router.get("/auth/login")
async def login(request: Request, retour: str = "/", db: AsyncSession = Depends(get_db)):
    """Démarre la connexion : tentative en base (state, nonce, PKCE) puis 302 vers le SSO."""
    return _no_store(await _login(request, retour, db))


PORTEES = ("openid", "profile", "email", "groups")


def _portees(disco: dict) -> str:
    """
    Portées demandées : celles qu'on veut ET que le SSO annonce (`scopes_supported`). Le SSO Server
    Synology n'annonce pas « profile » (relevé le 31/10/2026) : la demander risquerait un refus.
    Sans liste annoncée, on demande tout. « openid » est toujours demandé.
    """
    annoncees = disco.get("scopes_supported")
    if not isinstance(annoncees, list):
        return " ".join(PORTEES)
    return " ".join(p for p in PORTEES if p == "openid" or p in annoncees)


def _identifiant(claims: dict) -> object:
    """Identifiant de connexion : « preferred_username » (standard) ou « username » (Synology)."""
    return claims.get("preferred_username") or claims.get("username")


async def _login(request: Request, retour: str, db: AsyncSession):
    if not oidc_service.configure():
        return JSONResponse({"detail": "Connexion SSO non configurée (Paramètres › Authentification)."},
                            status_code=503)
    try:
        disco = await oidc_service.discover()
        endpoint = disco.get("authorization_endpoint")
        if not isinstance(endpoint, str) or not endpoint:
            raise OidcError("sso_indisponible")
    except OidcError:
        return JSONResponse({"detail": "SSO injoignable."}, status_code=503)

    now = oidc_service.maintenant()
    await db.execute(delete(OidcTentative).where(OidcTentative.creee < now - TENTATIVE_TTL)
                     .execution_options(synchronize_session=False))
    await db.execute(delete(SessionAuth).where(
        (SessionAuth.expire_max < now)
        | (SessionAuth.derniere_activite < now - timedelta(seconds=oidc_service.inactivite_s())))
        .execution_options(synchronize_session=False))
    en_cours = (await db.execute(select(func.count()).select_from(OidcTentative))).scalar_one()
    if en_cours >= MAX_TENTATIVES:
        await db.commit()
        return JSONResponse({"detail": "Trop de tentatives de connexion en cours, réessayez dans quelques minutes."},
                            status_code=429)
    verifier, challenge = oidc_service.pkce_paire()
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    secret_nav = secrets.token_urlsafe(32)
    db.add(OidcTentative(state=state, nonce=nonce, code_verifier=verifier, creee=now,
                         retour=oidc_service.retour_sur(retour),
                         navigateur=hashlib.sha256(secret_nav.encode()).hexdigest()))
    await db.commit()
    params = {
        "response_type": "code",
        "client_id": runtime_config.effective("oidc_client_id"),
        "redirect_uri": runtime_config.effective("oidc_redirect_uri"),
        "scope": _portees(disco),
        "state": state, "nonce": nonce,
        "code_challenge": challenge, "code_challenge_method": "S256",
    }
    sep = "&" if "?" in endpoint else "?"
    rep = RedirectResponse(f"{endpoint}{sep}{urlencode(params)}", status_code=302)
    rep.set_cookie(COOKIE_NAVIGATEUR, secret_nav, max_age=int(TENTATIVE_TTL.total_seconds()), httponly=True,
                   samesite="lax", path="/api/auth", secure=_https(request))
    return rep


@router.get("/auth/callback")
async def callback(request: Request, code: str = "", state: str = "", error: str = "",
                   db: AsyncSession = Depends(get_db)):
    """Retour du SSO : valide, ouvre la session, pose le cookie. Toute erreur → /?auth_erreur=code."""
    rep = _no_store(await _callback(request, code, state, error, db))
    # Le cookie de liaison n'a servi qu'une fois : effacé quelle que soit l'issue.
    rep.delete_cookie(COOKIE_NAVIGATEUR, path="/api/auth", httponly=True, samesite="lax",
                      secure=_https(request))
    return rep


async def _callback(request: Request, code: str, state: str, error: str, db: AsyncSession):
    if not state:
        return _erreur("etat_invalide")
    # Usage unique ATOMIQUE : le DELETE ... RETURNING tranche entre deux workers (un seul reçoit la
    # ligne), et la suppression est commitée AVANT toute validation, quoi qu'il arrive ensuite.
    res = await db.execute(delete(OidcTentative).where(OidcTentative.state == state).returning(
        OidcTentative.nonce, OidcTentative.code_verifier, OidcTentative.retour, OidcTentative.creee,
        OidcTentative.navigateur))
    tent = res.first()
    await db.commit()
    if tent is None:
        log.warning("Callback OIDC : state inconnu ou rejoué")
        return _erreur("etat_invalide")
    # Le state doit revenir dans le navigateur qui a lancé la connexion (sinon : login CSRF, un
    # attaquant ferait ouvrir à la victime une session sur le compte de l'attaquant).
    cookie_nav = request.cookies.get(COOKIE_NAVIGATEUR, "")
    if not cookie_nav or not hmac.compare_digest(
            hashlib.sha256(cookie_nav.encode()).hexdigest().encode(), tent.navigateur.encode()):
        log.warning("Callback OIDC : state non lié à ce navigateur")
        return _erreur("etat_invalide")
    nonce, verifier, retour, creee = tent.nonce, tent.code_verifier, tent.retour, _utc(tent.creee)
    if oidc_service.maintenant() - creee > TENTATIVE_TTL:
        log.warning("Callback OIDC : tentative expirée")
        return _erreur("etat_expire")
    if error or not code:
        log.warning("Callback OIDC : refus côté SSO")
        return _erreur("sso_refuse")
    if not oidc_service.configure():
        return _erreur("non_configure")

    try:
        disco = await oidc_service.discover()
        jetons = await oidc_service.exchange_code(disco, code, verifier)
        jwks_uri = disco.get("jwks_uri") or ""
        jwks = await oidc_service.get_jwks(jwks_uri)
        id_token = jetons["id_token"]
        kid = oidc_service.entete_jeton(id_token).get("kid")
        if not any(k.get("kid") == kid for k in jwks.get("keys", []) if isinstance(k, dict)):
            jwks = await oidc_service.get_jwks(jwks_uri, forcer=True)  # rotation de clé côté SSO
        claims = oidc_service.validate_id_token(
            id_token, jwks, issuer=oidc_service.emetteur_configure(),
            client_id=runtime_config.effective("oidc_client_id").strip(), nonce=nonce)
    except OidcError as e:
        log.warning("Connexion SSO refusée", code=e.code, detail=str(e))
        return _erreur(e.code)

    groupes = oidc_service.groupes_de(claims)
    role = oidc_service.role_depuis_groupes(groupes)
    if role is None:
        log.warning("Connexion refusée : groupe absent", identifiant=oidc_service.texte_borne(_identifiant(claims)))
        # Exigence 9 : une personne CONNUE qui n'a plus aucun des deux groupes (retirée au NAS) perd
        # ses sessions ouvertes — sinon elles resteraient valides jusqu'à 12 h d'inactivité / 7 jours.
        connu = await _utilisateur_par_sub(db, oidc_service.emetteur_configure(), claims["sub"])
        if connu is not None:
            await db.execute(delete(SessionAuth).where(SessionAuth.utilisateur_id == connu.id)
                             .execution_options(synchronize_session=False))
            await db.commit()
            log.warning("Sessions supprimées : accès retiré", identifiant=connu.identifiant)
        return _erreur("acces_refuse")

    now = oidc_service.maintenant()
    emetteur = oidc_service.emetteur_configure()
    user = await _utilisateur_par_sub(db, emetteur, claims["sub"])
    if user is None:
        # Création dans un savepoint : si une autre connexion du même `sub` s'est glissée entre la
        # lecture et l'insertion (UNIQUE), on relit la fiche au lieu de planter en 500.
        try:
            async with db.begin_nested():
                user = Utilisateur(emetteur=emetteur, sub=claims["sub"], role=role, bloque=False, premiere_connexion=now)
                db.add(user)
                await db.flush()
        except IntegrityError:
            user = await _utilisateur_par_sub(db, emetteur, claims["sub"])
            if user is None:
                return _erreur("sso_indisponible")
    if user.bloque:
        log.warning("Connexion refusée : compte bloqué", identifiant=user.identifiant)
        return _erreur("compte_bloque")
    user.identifiant = oidc_service.texte_borne(_identifiant(claims))
    user.nom = oidc_service.texte_borne(claims.get("name")) or user.identifiant
    user.email = oidc_service.texte_borne(claims.get("email"))
    user.groupes, user.role, user.derniere_connexion = oidc_service.groupes_a_stocker(groupes), role, now
    await db.flush()

    jeton = oidc_service.nouveau_jeton()
    db.add(SessionAuth(id=oidc_service.hacher_jeton(jeton), utilisateur_id=user.id, creee=now,
                       derniere_activite=now, expire_max=now + timedelta(seconds=oidc_service.duree_max_s())))
    await db.commit()
    log.info("Connexion SSO réussie", identifiant=user.identifiant, role=role)

    rep = RedirectResponse(oidc_service.retour_sur(retour), status_code=302)
    rep.set_cookie(COOKIE, jeton, max_age=oidc_service.duree_max_s(), httponly=True,
                   samesite="lax", path="/", secure=_https(request))
    return rep


@router.post("/auth/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Supprime la session, efface le cookie, indique où clore la session côté SSO."""
    jeton = request.cookies.get(COOKIE)
    if jeton:
        await db.execute(delete(SessionAuth).where(SessionAuth.id == oidc_service.hacher_jeton(jeton))
                         .execution_options(synchronize_session=False))
        await db.commit()
    fin = None
    if oidc_service.configure():
        try:
            fin = (await oidc_service.discover()).get("end_session_endpoint")
        except OidcError:
            fin = None
    rep = JSONResponse({"deconnecte": True, "end_session_endpoint": fin})
    rep.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=_https(request))
    return rep


@router.get("/auth/me")
async def me(request: Request, response: Response, db: AsyncSession = Depends(get_db)) -> dict:
    """État d'authentification courant (n'échoue jamais : pas de session = utilisateur null)."""
    _no_store(response)
    user = await utilisateur_courant(request, db)
    etat = {
        "auth_active": oidc_service.auth_active(),
        "utilisateur": None if user is None else {
            "identifiant": user.identifiant, "nom": user.nom, "email": user.email, "role": user.role},
    }
    if etat["auth_active"]:
        # Accès de secours en cours (commande sur le LXC) : l'interface l'affiche en bandeau.
        try:
            fin = await acces.suspension_jusqua(db)
        except Exception:  # noqa: BLE001 — `me` n'échoue jamais ; le contrôle d'accès, lui, échoue fermé
            fin = None
        if fin is not None:
            etat["suspension_jusqua"] = fin.isoformat()
    return etat
