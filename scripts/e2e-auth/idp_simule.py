"""
Fournisseur OpenID Connect SIMULÉ — banc de l'étape 6 du plan d'authentification
================================================================================
Joue le rôle du SSO Server du NAS dans une pile jetable : découverte, autorisation (code + PKCE
S256), échange du code (secret client en Basic, comme Synology), JWKS, jeton d'identité RS256.
Comptes 100 % FICTIFS ; le « navigateur » choisit qui se connecte par `&utilisateur=<nom>` ajouté
à l'URL d'autorisation (pas d'écran de mot de passe : ce n'est pas ce qu'on teste).

Servi en HTTPS (certificat auto-signé produit au démarrage, SAN = IDP_HOTE) : Matothèque refuse
tout émetteur en http. Le certificat est écrit dans `/certs/idp.pem` pour que le backend lui fasse
confiance. Lancement : `python idp_simule.py` (variables IDP_HOTE, IDP_PORT, CLIENT_ID,
CLIENT_SECRET, REDIRECT_URI).
"""

import base64
import datetime as dt
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

HOTE = os.environ.get("IDP_HOTE", "idp")
PORT = int(os.environ.get("IDP_PORT", "8443"))
EMETTEUR = f"https://{HOTE}:{PORT}"
CLIENT_ID = os.environ.get("CLIENT_ID", "matotheque-e2e")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "secret-e2e")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "https://ged.test/api/auth/callback")
KID = "cle-e2e-1"

# Comptes fictifs, groupes à la manière de DSM.
COMPTES = {
    "tclement-e2e": {"groups": ["administrators", "matotheque-admin"], "name": "Admin E2E"},
    "mlb-e2e": {"groups": ["matotheque-utilisateurs"], "name": "Utilisatrice E2E"},
    "intrus-e2e": {"groups": ["users"], "name": "Hors groupe E2E"},
}

CLE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CODES: dict[str, dict] = {}   # code → tentative (usage unique)
app = FastAPI(title="IdP simulé (e2e)")


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def entier_b64u(n: int) -> str:
    return b64u(n.to_bytes((n.bit_length() + 7) // 8, "big"))


def jeton_identite(utilisateur: str, nonce: str) -> str:
    maintenant = int(time.time())
    entete = {"alg": "RS256", "kid": KID, "typ": "JWT"}
    revendications = {
        "iss": EMETTEUR, "aud": CLIENT_ID, "sub": f"sub-{utilisateur}", "nonce": nonce,
        "iat": maintenant, "exp": maintenant + 300,
        "username": utilisateur,                       # claim Synology (pas preferred_username)
        "groups": COMPTES[utilisateur]["groups"], "name": COMPTES[utilisateur]["name"],
        "email": f"{utilisateur}@exemple.invalid",
    }
    signe = f"{b64u(json.dumps(entete).encode())}.{b64u(json.dumps(revendications).encode())}"
    signature = CLE.sign(signe.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signe}.{b64u(signature)}"


@app.get("/.well-known/openid-configuration")
def decouverte() -> dict:
    return {
        "issuer": EMETTEUR,
        "authorization_endpoint": f"{EMETTEUR}/authorize",
        "token_endpoint": f"{EMETTEUR}/token",
        "jwks_uri": f"{EMETTEUR}/jwks",
        "scopes_supported": ["openid", "email", "groups"],      # comme Synology : pas « profile »
        "response_types_supported": ["code"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }


@app.get("/jwks")
def jwks() -> dict:
    pub = CLE.public_key().public_numbers()
    return {"keys": [{"kty": "RSA", "kid": KID, "use": "sig", "alg": "RS256",
                      "n": entier_b64u(pub.n), "e": entier_b64u(pub.e)}]}


@app.get("/authorize")
def autoriser(request: Request):
    q = request.query_params
    utilisateur = q.get("utilisateur", "")
    if q.get("client_id") != CLIENT_ID or q.get("redirect_uri") != REDIRECT_URI:
        raise HTTPException(400, "client_id ou redirect_uri inconnus")
    if q.get("response_type") != "code" or q.get("code_challenge_method") != "S256":
        raise HTTPException(400, "flux non pris en charge")
    if utilisateur not in COMPTES:
        raise HTTPException(400, "compte inconnu (paramètre utilisateur)")
    code = secrets.token_urlsafe(24)
    CODES[code] = {"utilisateur": utilisateur, "nonce": q.get("nonce", ""),
                   "challenge": q.get("code_challenge", ""), "redirect_uri": q["redirect_uri"]}
    return RedirectResponse(f"{REDIRECT_URI}?{urlencode({'code': code, 'state': q.get('state', '')})}", 302)


@app.post("/token")
def echanger(authorization: str = Header(default=""), grant_type: str = Form(...), code: str = Form(...),
             redirect_uri: str = Form(...), code_verifier: str = Form(...)):
    attendu = "Basic " + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    if not secrets.compare_digest(authorization, attendu):
        return JSONResponse({"error": "invalid_client"}, status_code=401)
    tentative = CODES.pop(code, None)                   # usage unique
    if grant_type != "authorization_code" or tentative is None or redirect_uri != tentative["redirect_uri"]:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    if b64u(hashlib.sha256(code_verifier.encode()).digest()) != tentative["challenge"]:
        return JSONResponse({"error": "invalid_grant", "error_description": "PKCE"}, status_code=400)
    return {"access_token": secrets.token_urlsafe(16), "token_type": "Bearer", "expires_in": 300,
            "id_token": jeton_identite(tentative["utilisateur"], tentative["nonce"])}


def certificat() -> tuple[str, str]:
    """Certificat auto-signé pour HOTE ; le PEM public va dans /certs/idp.pem (confiance du backend)."""
    cle = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nom = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOTE)])
    maintenant = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(nom).issuer_name(nom).public_key(cle.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(maintenant - dt.timedelta(minutes=5)).not_valid_after(maintenant + dt.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(HOTE)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(cle, hashes.SHA256()))
    os.makedirs("/certs", exist_ok=True)
    with open("/certs/idp.pem", "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open("/tmp/idp.key", "wb") as f:
        f.write(cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                  serialization.NoEncryption()))
    return "/certs/idp.pem", "/tmp/idp.key"


if __name__ == "__main__":
    pem, cle_tls = certificat()
    uvicorn.run(app, host="0.0.0.0", port=PORT, ssl_certfile=pem, ssl_keyfile=cle_tls, log_level="warning")
