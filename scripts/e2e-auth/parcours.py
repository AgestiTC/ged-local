"""
Parcours de bout en bout de l'authentification — étape 6 du plan (docs/plan-authentification.md)
================================================================================================
Joue un NAVIGATEUR devant le vrai nginx du frontend, lui-même devant le backend (2 processus,
PostgreSQL), avec le fournisseur SSO simulé (`idp_simule.py`). Deux routes d'accès :
  - TLS  : `Host: ged.test` + `X-Forwarded-Proto: https` (ce que pose le proxy TLS NPMplus) ;
  - HTTP : `Host: front` sans en-tête (la route directe du LAN).
Les cookies sont gérés à la main pour voir leurs attributs (`Secure`). Comptes FICTIFS.

Sort en erreur au premier contrôle faux ; affiche chaque contrôle passé. Variables : FRONT
(défaut http://front), DOC_ID (document fictif inséré par lancer.sh).
"""

import os
import sys
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

FRONT = os.environ.get("FRONT", "http://front")
DOC_ID = os.environ.get("DOC_ID", "")
TLS = {"Host": "ged.test", "X-Forwarded-Proto": "https", "Origin": "https://ged.test"}
HTTP = {"Host": "front", "Origin": "http://front"}
compteur = 0


def ok(condition: bool, quoi: str, detail: object = "") -> None:
    global compteur
    if not condition:
        print(f"[ÉCHEC] {quoi} {detail}")
        sys.exit(1)
    compteur += 1
    print(f"[OK] {quoi}")


class Navigateur:
    """Un navigateur sur UNE route : cookies propres, attributs relevés à chaque Set-Cookie."""

    def __init__(self, route: dict):
        self.route = route
        self.cookies: dict[str, str] = {}
        self.attributs: dict[str, str] = {}      # nom → ligne Set-Cookie brute (pour Secure…)
        self.http = httpx.Client(base_url=FRONT, follow_redirects=False, timeout=30)

    def _retenir(self, r: httpx.Response) -> None:
        for ligne in r.headers.get_list("set-cookie"):
            c = SimpleCookie()
            c.load(ligne)
            for nom, morsel in c.items():
                self.attributs[nom] = ligne
                if morsel.value and "max-age=0" not in ligne.lower():
                    self.cookies[nom] = morsel.value
                else:
                    self.cookies.pop(nom, None)

    def req(self, methode: str, chemin: str, **kw) -> httpx.Response:
        entetes = {**self.route, **kw.pop("headers", {})}
        if self.cookies:
            entetes["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        r = self.http.request(methode, chemin, headers=entetes, **kw)
        self._retenir(r)
        return r

    def secure(self, nom: str) -> bool:
        return "secure" in [p.strip().lower() for p in self.attributs.get(nom, "").split(";")]


def se_connecter(nav: Navigateur, compte: str, *, rejouer: bool = False) -> httpx.Response:
    """Login → SSO simulé → callback (ramené sur la route du navigateur). Rend la réponse du callback."""
    r = nav.req("GET", "/api/auth/login?retour=/ged")
    ok(r.status_code == 302, f"{compte} : /api/auth/login redirige vers le SSO", r.status_code)
    autorisation = r.headers["location"] + "&" + urlencode({"utilisateur": compte})
    r_sso = httpx.get(autorisation, verify=False, follow_redirects=False, timeout=30)
    ok(r_sso.status_code == 302, f"{compte} : le SSO renvoie un code", r_sso.text[:200])
    retour = urlsplit(r_sso.headers["location"])
    r_cb = nav.req("GET", f"{retour.path}?{retour.query}")
    if rejouer:
        r_bis = nav.req("GET", f"{retour.path}?{retour.query}")
        ok("auth_erreur=etat_invalide" in r_bis.headers.get("location", ""),
           "le même retour du SSO rejoué est refusé (state à usage unique, 2 processus)", r_bis.headers)
    return r_cb


def erreur_de(r: httpx.Response) -> str:
    return parse_qs(urlsplit(r.headers.get("location", "")).query).get("auth_erreur", [""])[0]


# ─── 1. Authentification éteinte : la porte est ouverte, comme en prod aujourd'hui ───────────────
anonyme = Navigateur(TLS)
ok(anonyme.req("GET", "/api/documents").status_code == 200, "auth éteinte : l'API répond sans session")
r = anonyme.req("PUT", "/api/system/config", json={
    "oidc_issuer": "https://idp:8443", "oidc_client_id": "matotheque-e2e",
    "oidc_client_secret": "secret-e2e", "oidc_redirect_uri": "https://ged.test/api/auth/callback"})
ok(r.status_code == 200, "réglages SSO saisis (auth éteinte)", r.text[:200])
r = anonyme.req("PUT", "/api/system/config", json={"auth_active": "true"})
ok(r.status_code == 400 and "aucun administrateur" in r.text,
   "activation REFUSÉE tant qu'aucun admin ne s'est connecté (on ne s'enferme pas dehors)", r.text[:200])

# ─── 2. Première connexion admin par la route TLS, puis activation ───────────────────────────────
admin = Navigateur(TLS)
r = se_connecter(admin, "tclement-e2e", rejouer=True)
ok(r.status_code == 302 and "matotheque_session" in admin.cookies, "admin connecté (cookie de session posé)", r.headers)
ok(admin.secure("matotheque_session"), "route TLS : cookie de session « Secure »")
r = admin.req("PUT", "/api/system/config", json={"auth_active": "true"})
ok(r.status_code == 200, "authentification ACTIVÉE après la 1re connexion admin", r.text[:200])

# ─── 3. Porte fermée, sur les deux routes ────────────────────────────────────────────────────────
for nom, route in (("TLS", TLS), ("HTTP", HTTP)):
    n = Navigateur(route)
    ok(n.req("GET", "/api/documents").status_code == 401, f"route {nom} : anonyme refusé (401)")
    me = n.req("GET", "/api/auth/me").json()
    ok(me["auth_active"] is True and me["utilisateur"] is None and me["adresse_connexion"] == "https://ged.test",
       f"route {nom} : /me renvoie vers l'adresse de connexion TLS", me)
ok(Navigateur(HTTP).req("GET", "/api/version").status_code == 200, "liste blanche : /api/version reste ouverte")

# ─── 4. Rôles ───────────────────────────────────────────────────────────────────────────────────
mlb = Navigateur(TLS)
se_connecter(mlb, "mlb-e2e")
me = mlb.req("GET", "/api/auth/me").json()
ok(me["utilisateur"]["role"] == "utilisateur" and me["utilisateur"]["identifiant"] == "mlb-e2e",
   "utilisatrice connectée avec le rôle « utilisateur » (groupe DSM)", me)
ok(mlb.req("GET", "/api/documents").status_code == 200, "utilisateur : la GED répond")
ok(mlb.req("GET", "/api/system/config").status_code == 403, "utilisateur : les réglages sont refusés (403)")
ok(admin.req("GET", "/api/system/config").status_code == 200, "admin : les réglages répondent")
intrus = Navigateur(TLS)
r = se_connecter(intrus, "intrus-e2e")
ok(erreur_de(r) == "acces_refuse" and "matotheque_session" not in intrus.cookies,
   "compte hors des deux groupes : accès refusé, aucune session", r.headers)

# ─── 5. CSRF ─────────────────────────────────────────────────────────────────────────────────────
r = admin.req("POST", "/api/prompts", json={"nom": "x", "prompt_text": "y"},
              headers={"Origin": "https://site-etranger.example"})
ok(r.status_code == 403, "écriture depuis une origine étrangère refusée (CSRF)", r.status_code)
r = admin.req("POST", "/api/prompts", json={"nom": "Consigne e2e", "prompt_text": "Résume."})
ok(r.status_code in (200, 201), "admin : écriture depuis l'application acceptée", r.text[:200])
ok(admin.req("DELETE", f"/api/prompts/{r.json()['id']}").status_code in (200, 204), "admin : suppression acceptée")

# ─── 6. Tâches : propriétaire (étape 5) ──────────────────────────────────────────────────────────
r = mlb.req("POST", "/api/generate/report", json={"document_ids": [DOC_ID], "prompt": "Résume.",
                                                  "model": "", "output_format": "markdown"})
ok(r.status_code == 200, "utilisateur : rapport lancé", r.text[:200])
job = r.json()["job_id"]
ok(mlb.req("GET", f"/api/jobs/{job}").json()["parametres"].get("proprietaire") == "mlb-e2e",
   "la tâche porte sa propriétaire")
ok(mlb.req("POST", f"/api/jobs/{job}/cancel").status_code == 200, "sa propriétaire peut l'arrêter")

# ─── 7. Jetons d'automates, utilisés par la route HTTP (n8n) ─────────────────────────────────────
r = admin.req("POST", "/api/auth/jetons", json={"nom": "n8n-e2e", "role": "utilisateur", "portee": "lecture",
                                               "expire_jours": 30})
ok(r.status_code == 201, "admin : jeton d'automate créé", r.text[:200])
jeton, jeton_id = r.json()["jeton"], r.json()["id"]
robot = Navigateur({"Host": "front", "Authorization": f"Bearer {jeton}"})
ok(robot.req("GET", "/api/documents").status_code == 200, "jeton en lecture, route HTTP : la GED répond")
ok(robot.req("POST", "/api/prompts", json={"nom": "x", "prompt_text": "y"}).status_code == 403,
   "jeton en lecture : écriture refusée (403)")
ok(admin.req("POST", f"/api/auth/jetons/{jeton_id}/revoquer").status_code == 200, "admin : jeton révoqué")
ok(robot.req("GET", "/api/documents").status_code == 401, "jeton révoqué : refusé (401)")

# ─── 8. Journal : qui a fait quoi ───────────────────────────────────────────────────────────────
evts = admin.req("GET", "/api/audit?limit=500").json()["events"]
par_auteur = {(e["action"], e.get("auteur")) for e in evts}
ok(any(e["action"] == "ecriture" and e.get("auteur") == "tclement-e2e" and e["message"].startswith("DELETE")
       for e in evts), "journal : la suppression de l'admin est signée tclement-e2e")
ok(("job_annuler", "mlb-e2e") in par_auteur, "journal : annulation signée mlb-e2e")
ok(any(e["action"] == "rapport" and e.get("auteur") == "mlb-e2e" for e in evts),
   "journal : la tâche de rapport est signée de sa propriétaire")
ok(any(a.startswith("auth_jeton") for a, _ in par_auteur), "journal : création / révocation du jeton")

# ─── 9. Blocage, déconnexion ─────────────────────────────────────────────────────────────────────
uid = mlb.req("GET", "/api/auth/me").json()["utilisateur"]["id"]
ok(admin.req("POST", f"/api/auth/utilisateurs/{uid}/bloquer", json={"bloque": True}).status_code == 200,
   "admin : utilisatrice bloquée")
ok(mlb.req("GET", "/api/documents").status_code == 401, "bloquée : sa session est coupée (401)")
ok(erreur_de(se_connecter(Navigateur(TLS), "mlb-e2e")) == "compte_bloque",
   "bloquée : le SSO a beau accepter, Matothèque refuse")
ok(admin.req("POST", f"/api/auth/utilisateurs/{uid}/bloquer", json={"bloque": False}).status_code == 200,
   "admin : utilisatrice débloquée")
ok(admin.req("POST", "/api/auth/logout").status_code == 200, "admin : déconnexion")
ok(admin.req("GET", "/api/documents").status_code == 401, "après déconnexion : refusé (401)")

print(f"\nPARCOURS VERT — {compteur} contrôles.")
