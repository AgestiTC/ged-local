"""
Service OpenID Connect — connexion par le SSO du NAS (étape 1 du plan d'authentification)
==========================================================================================
Réseau (découverte, JWKS, échange du code) isolé dans trois fonctions async que les tests
remplacent : `discover`, `get_jwks`, `exchange_code`. La VALIDATION du jeton d'identité est
une fonction pure (`validate_id_token`) : signature RS256 / ES256 vérifiée avec `cryptography`
(aucune dépendance de plus). `alg` = none ou HS* est refusé : un jeton ne choisit jamais lui-même
son niveau de contrôle.

100 % local : on ne parle qu'à l'émetteur configuré (le SSO du LAN).
"""

import base64
import hashlib
import json
import secrets
import time
from datetime import datetime, timezone

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from logger import get_logger
from services import runtime_config
from services.crypto import decrypt

log = get_logger(__name__)

TOLERANCE_S = 120          # écart d'horloge toléré (exp / iat)
CACHE_S = 300              # durée de vie du cache découverte / JWKS
TIMEOUT_S = 10.0
ALGORITHMES = {"RS256", "ES256"}

_cache: dict[str, tuple[float, dict]] = {}

# Transport HTTP injectable : None en production ; les tests y placent un `httpx.MockTransport`.
_TRANSPORT: httpx.AsyncBaseTransport | None = None

ECHEC_CACHE_S = 30         # un échec de découverte n'est pas retenté avant ce délai (workers non bloqués)
MAX_CHAMP = 255            # taille maxi d'un champ texte venant du SSO
MAX_GROUPES = 100          # nombre maxi de groupes conservés en base


def emetteur_configure() -> str:
    """Émetteur configuré, normalisé (sans « / » final)."""
    return runtime_config.effective("oidc_issuer").strip().rstrip("/")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT_S, transport=_TRANSPORT)


def _https(url: str | None) -> bool:
    """Le secret client et les clés ne doivent jamais transiter en clair."""
    return isinstance(url, str) and url.lower().startswith("https://")


class OidcError(Exception):
    """Échec de connexion. `code` est court et sans détail sensible (renvoyé à l'UI)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


# ─── Réglages ─────────────────────────────────────────────────────────────────

def configure() -> bool:
    """Vrai si l'émetteur et l'identifiant client sont renseignés."""
    return bool(runtime_config.effective("oidc_issuer").strip()
                and runtime_config.effective("oidc_client_id").strip())


def auth_active() -> bool:
    return runtime_config.effective("auth_active").strip().lower() in ("1", "true", "on", "yes")


def client_secret() -> str:
    return decrypt(runtime_config.effective("oidc_client_secret"))


def _entier(cle: str, defaut: int) -> int:
    try:
        v = int(float(runtime_config.effective(cle)))
        return v if v > 0 else defaut
    except (TypeError, ValueError):
        return defaut


def inactivite_s() -> int:
    return _entier("auth_session_inactivite_heures", 12) * 3600


def duree_max_s() -> int:
    return _entier("auth_session_max_jours", 7) * 86400


# ─── Utilitaires ──────────────────────────────────────────────────────────────

def _b64u(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _b64u_enc(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def hacher_jeton(jeton: str) -> str:
    """SHA-256 (hex) : seule empreinte conservée en base pour une session."""
    return hashlib.sha256(jeton.encode()).hexdigest()


def nouveau_jeton() -> str:
    """Jeton de session : 32 octets aléatoires (256 bits), encodés URL-safe."""
    return secrets.token_urlsafe(32)


def pkce_paire() -> tuple[str, str]:
    """(code_verifier, code_challenge S256)."""
    verifier = secrets.token_urlsafe(64)
    return verifier, _b64u_enc(hashlib.sha256(verifier.encode()).digest())


def retour_sur(retour: str | None) -> str:
    """Chemin de retour sûr : relatif au site uniquement (pas de redirection ouverte)."""
    r = (retour or "").strip()
    if (not r.startswith("/") or r.startswith("//") or "\\" in r
            or any(ord(c) < 32 or ord(c) == 127 for c in r) or "://" in r.split("?", 1)[0]):
        return "/"
    return r


def role_depuis_groupes(groupes: list[str]) -> str | None:
    """admin > utilisateur ; aucun des deux groupes = None (refus, aucun compte créé)."""
    if runtime_config.effective("oidc_groupe_admin").strip() in groupes:
        return "admin"
    if runtime_config.effective("oidc_groupe_utilisateurs").strip() in groupes:
        return "utilisateur"
    return None


# ─── Réseau (remplacé par les tests) ──────────────────────────────────────────

async def _get_json(url: str) -> dict:
    async with _client() as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
    if not isinstance(data, dict):
        raise ValueError("réponse inattendue")
    return data


async def discover() -> dict:
    """Document de découverte de l'émetteur (cache court)."""
    issuer = emetteur_configure()
    if not _https(issuer):       # pas de GET aveugle vers une adresse interne en clair
        raise OidcError("sso_indisponible", "émetteur non https")
    cle = f"disco:{issuer}"
    hit = _cache.get(cle)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    echec = _cache.get(f"echec:{issuer}")
    if echec and time.monotonic() - echec[0] < ECHEC_CACHE_S:
        raise OidcError("sso_indisponible", "échec récent mis en cache")
    try:
        doc = await _get_json(f"{issuer}/.well-known/openid-configuration")
    except Exception as e:  # noqa: BLE001
        log.warning("Découverte OIDC impossible", erreur=type(e).__name__)
        _cache[f"echec:{issuer}"] = (time.monotonic(), {})
        raise OidcError("sso_indisponible") from e
    # Le document doit venir de l'émetteur configuré, et ses adresses sensibles être en https.
    if str(doc.get("issuer") or "").rstrip("/") != issuer:
        log.warning("Découverte OIDC : émetteur différent de celui configuré")
        raise OidcError("sso_indisponible")
    if not _https(doc.get("token_endpoint")) or not _https(doc.get("jwks_uri")):
        log.warning("Découverte OIDC : adresse non https refusée")
        raise OidcError("sso_indisponible")
    _cache[cle] = (time.monotonic(), doc)
    return doc


async def get_jwks(jwks_uri: str, *, forcer: bool = False) -> dict:
    """Clés publiques de l'émetteur (cache court ; `forcer` = relire, rotation de clé)."""
    cle = f"jwks:{jwks_uri}"
    hit = _cache.get(cle)
    if hit and not forcer and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    try:
        jwks = await _get_json(jwks_uri)
        if not isinstance(jwks.get("keys"), list):
            raise ValueError("clés absentes")
    except Exception as e:  # noqa: BLE001
        log.warning("JWKS OIDC indisponible", erreur=type(e).__name__)
        raise OidcError("sso_indisponible") from e
    _cache[cle] = (time.monotonic(), jwks)
    return jwks


async def exchange_code(disco: dict, code: str, code_verifier: str) -> dict:
    """Échange du code d'autorisation contre les jetons (PKCE + secret client)."""
    endpoint = disco.get("token_endpoint")
    if not _https(endpoint):    # avant tout envoi : le secret client ne part jamais en clair
        raise OidcError("sso_indisponible")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": runtime_config.effective("oidc_redirect_uri"),
        "code_verifier": code_verifier,
    }
    client_id = runtime_config.effective("oidc_client_id")
    secret = client_secret()
    # Le secret n'est envoyé qu'à l'émetteur pour lequel il a été saisi.
    if secret and runtime_config.effective("oidc_secret_emetteur").strip().rstrip("/") != emetteur_configure():
        log.warning("Secret client lié à un autre émetteur : échange refusé")
        raise OidcError("sso_indisponible", "secret lié à un autre émetteur")
    auth = None
    methodes = disco.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
    if secret and "client_secret_post" not in methodes and "client_secret_basic" in methodes:
        auth = httpx.BasicAuth(client_id, secret)
    else:
        data["client_id"] = client_id
        if secret:
            data["client_secret"] = secret
    try:
        async with _client() as client:
            r = await client.post(endpoint, data=data, auth=auth)
        if r.status_code != 200:
            log.warning("Échange du code refusé par le SSO", statut=r.status_code)
            raise OidcError("echange_refuse")
        jetons = r.json()
    except OidcError:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("Échange du code impossible", erreur=type(e).__name__)
        raise OidcError("sso_indisponible") from e
    if not isinstance(jetons, dict) or not isinstance(jetons.get("id_token"), str) or not jetons["id_token"]:
        raise OidcError("echange_refuse")
    return jetons


# ─── Validation du jeton d'identité ───────────────────────────────────────────

def _cle_publique(jwk: dict, alg: str):
    kty = jwk.get("kty")
    if jwk.get("use") not in (None, "sig"):
        raise OidcError("jeton_invalide", "clé non destinée à la signature")
    if alg == "RS256" and kty == "RSA":
        n = int.from_bytes(_b64u(jwk["n"]), "big")
        e = int.from_bytes(_b64u(jwk["e"]), "big")
        return rsa.RSAPublicNumbers(e, n).public_key()
    if alg == "ES256" and kty == "EC" and jwk.get("crv") == "P-256":
        x = int.from_bytes(_b64u(jwk["x"]), "big")
        y = int.from_bytes(_b64u(jwk["y"]), "big")
        return ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
    raise OidcError("jeton_invalide", "type de clé incompatible avec l'algorithme")


def _verifier_signature(alg: str, jwk: dict, signing_input: bytes, signature: bytes) -> None:
    try:
        cle = _cle_publique(jwk, alg)
        if alg == "RS256":
            cle.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        else:
            if len(signature) != 64:
                raise OidcError("jeton_invalide", "signature ES256 mal formée")
            r = int.from_bytes(signature[:32], "big")
            s = int.from_bytes(signature[32:], "big")
            cle.verify(encode_dss_signature(r, s), signing_input, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as e:
        raise OidcError("jeton_invalide", "signature invalide") from e
    except (KeyError, ValueError, TypeError) as e:
        raise OidcError("jeton_invalide", "clé illisible") from e


def entete_jeton(id_token: str) -> dict:
    """En-tête (non vérifié) du jeton — pour choisir la clé ; jamais pour décider de la confiance."""
    try:
        h = json.loads(_b64u(id_token.split(".")[0]))
        return h if isinstance(h, dict) else {}
    except Exception as e:  # noqa: BLE001
        raise OidcError("jeton_invalide", "jeton illisible") from e


def validate_id_token(id_token: str, jwks: dict, *, issuer: str, client_id: str,
                      nonce: str, now: float | None = None) -> dict:
    """
    Vérifie un jeton d'identité et rend ses revendications. Lève `OidcError("jeton_invalide")`.
    Contrôles : alg ∈ {RS256, ES256}, kid présent et connu, signature, iss, aud (+azp), exp, iat, nonce, sub.
    """
    now = time.time() if now is None else now
    parts = (id_token or "").split(".")
    if len(parts) != 3:
        raise OidcError("jeton_invalide", "format")
    try:
        header = json.loads(_b64u(parts[0]))
        claims = json.loads(_b64u(parts[1]))
        signature = _b64u(parts[2])
    except Exception as e:  # noqa: BLE001
        raise OidcError("jeton_invalide", "jeton illisible") from e
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise OidcError("jeton_invalide", "jeton illisible")

    alg = header.get("alg")
    if alg not in ALGORITHMES:                   # none, HS256… : refusés
        raise OidcError("jeton_invalide", "algorithme refusé")
    kid = header.get("kid")
    if not kid:
        raise OidcError("jeton_invalide", "kid absent")
    cles = jwks.get("keys") if isinstance(jwks, dict) else None
    if not isinstance(cles, list):
        raise OidcError("jeton_invalide", "JWKS mal formé")
    jwk = next((k for k in cles if isinstance(k, dict) and k.get("kid") == kid), None)
    if jwk is None:
        raise OidcError("jeton_invalide", "kid inconnu")
    _verifier_signature(alg, jwk, f"{parts[0]}.{parts[1]}".encode(), signature)

    iss = claims.get("iss")
    if not isinstance(iss, str) or iss.rstrip("/") != (issuer or "").rstrip("/"):
        raise OidcError("jeton_invalide", "émetteur")
    aud = claims.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    if client_id not in auds:
        raise OidcError("jeton_invalide", "audience")
    if len(auds) > 1 and claims.get("azp") != client_id:
        raise OidcError("jeton_invalide", "azp")
    exp, iat = claims.get("exp"), claims.get("iat")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool) or exp < now - TOLERANCE_S:
        raise OidcError("jeton_invalide", "expiré")
    if iat is not None and (not isinstance(iat, (int, float)) or iat > now + TOLERANCE_S):
        raise OidcError("jeton_invalide", "iat dans le futur")
    attendu = (nonce or "").encode()
    recu = str(claims.get("nonce") or "").encode()      # en octets : compare_digest refuse le non-ASCII en str
    if not attendu or not secrets.compare_digest(recu, attendu):
        raise OidcError("jeton_invalide", "nonce")
    sub = claims.get("sub")
    if not sub or not isinstance(sub, str) or len(sub) > MAX_CHAMP:
        raise OidcError("jeton_invalide", "sub absent ou trop long")
    return claims


def groupes_de(claims: dict) -> list[str]:
    """Groupes (chaînes uniquement) — le rôle se calcule sur cette liste COMPLÈTE."""
    g = claims.get("groups")
    if isinstance(g, str):
        return [g]
    return [x for x in g if isinstance(x, str)] if isinstance(g, list) else []


def groupes_a_stocker(groupes: list[str]) -> list[str]:
    """Version bornée pour la base : nombre limité, groupes trop longs écartés."""
    return [g for g in groupes if len(g) <= MAX_CHAMP][:MAX_GROUPES]


def texte_borne(valeur) -> str | None:
    """Champ texte du SSO prêt à stocker : chaîne uniquement, tronquée à 255 caractères."""
    return valeur[:MAX_CHAMP] if isinstance(valeur, str) and valeur else None


def maintenant() -> datetime:
    return datetime.now(timezone.utc)
