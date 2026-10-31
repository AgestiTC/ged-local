# Plan — Authentification par personne (SSO du NAS, OpenID Connect)

> **Statut : plan, rien n'est codé** (31/10/2026). Décidé avec l'utilisateur : **un identifiant
> par personne**, servi par le **SSO Server du NAS Synology DS923+** en **OpenID Connect**.
> Réponse au point ouvert de la ROADMAP « Authentification de l'API — à décider » (18/09/2026),
> devenu prioritaire après l'incident Gitea du 31/10/2026 (une application sans authentification
> forte, exposée, a été compromise pendant deux mois).

## Pourquoi

Aujourd'hui, **seul le réseau protège Matothèque** (LAN + VPN ; `ged.tclement.fr` vérifié
inaccessible depuis Internet le 31/10). Quiconque joint l'API peut tout faire : télécharger une
sauvegarde de la base, lire les documents (dont des offres de candidats confidentielles), changer
la configuration (dont `ollama_url`), supprimer. Une seule erreur de proxy suffirait à tout ouvrir.

## Choix d'architecture

| Option | Verdict |
|---|---|
| RADIUS Server (Synology) | ❌ fait pour le réseau (Wi-Fi 802.1X, VPN), pas pour une application web |
| LDAP Server (Synology) | possible, mais Matothèque verrait passer les mots de passe et garderait son propre écran |
| **SSO Server (Synology), OpenID Connect** | ✅ **retenu** : une connexion pour toutes les applications web, Matothèque ne voit jamais le mot de passe, la double authentification se règle une fois sur le NAS |
| Authentik / Keycloak en conteneur | plus riche, mais un service de plus à maintenir et à sécuriser — écarté pour commencer |

Comptes = **ceux du NAS** (DSM) ; **rôles** = **groupes du NAS**. Gitea, BookStack et NetSight
savent aussi se brancher en OpenID Connect : même SSO plus tard, hors de ce plan.
**100 % local** : le SSO tourne sur le NAS, sur le LAN ; aucune dépendance externe à l'exécution.

## Décisions (validées par l'utilisateur le 31/10/2026)

1. **Rôles** : groupes DSM `matotheque-admin` (tout, dont *Paramètres*, sauvegarde, suppressions
   définitives, sources, maintenance, jetons d'automates) et `matotheque-utilisateurs` (GED,
   recherche, Créer, Dossiers, wiki ; ni réglages ni suppression définitive). Un compte du NAS hors
   de ces groupes n'entre pas.
2. **Adresse de référence pour la connexion** : `https://ged.tclement.fr`. La route HTTP du LAN
   (`http://192.168.42.83:3003`) renvoie vers la route TLS pour se connecter (voir « Pièges »).
3. **Durée de session** : 12 h d'inactivité, 7 jours au maximum.
4. **Personnes** : `tclement` → `matotheque-admin` ; Marie-Laure (compte DSM `MLB`) →
   `matotheque-utilisateurs`.
5. **Accès de secours** par commande sur le LXC si le NAS (donc le SSO) est en panne (étape 2).

## Utilisateurs : création et lien avec le SSO

- **Création sur le NAS uniquement** (DSM › Utilisateur et groupe) : compte, mot de passe,
  double authentification, groupe. Matothèque ne stocke ni ne gère aucun mot de passe.
- **Fiche locale créée automatiquement à la première connexion** (*just-in-time*) depuis les
  informations du SSO : `sub`, identifiant, nom, e-mail, groupes → rôle. Mise à jour à chaque
  connexion (un changement de groupe sur le NAS vaut à la connexion suivante).
- **Page *Paramètres › Utilisateurs*** (admins) : personnes, rôle (lu du groupe, non modifiable ici),
  première et dernière connexion, sessions ouvertes ; actions **« Déconnecter partout »** (supprime
  ses sessions) et **« Bloquer dans Matothèque »** (refus même si le SSO accepte — frein d'urgence,
  journalisé). Pas de création de compte dans Matothèque.
- **Retrait d'une personne** : la sortir du groupe sur le NAS (plus de connexion possible), et
  « Déconnecter partout » pour couper les sessions en cours.
- **Comptes DSM réservés au SSO** : un compte créé pour Matothèque (ex. Marie-Laure) ne reçoit
  **aucun droit sur le NAS** (partages sans accès, applications DSM refusées sauf le SSO).

---

## Étape 0 — Préparer le NAS (utilisateur, guidé)

Installer le paquet **SSO Server** et lui donner l'adresse **`https://sso.tclement.fr`** (URL du
serveur = émetteur des jetons, à l'identique partout). Réseau (avis de la session Migration NPM+,
31/10/2026) : hôte sur **NPMplus** (LXC `.83`) → `https://192.168.42.200:5001`, certificat
`*.tclement.fr` existant (défi DNS), liste d'accès LAN `192.168.42.0/24` + VPN `10.42.99.0/24` ;
**aucun enregistrement DNS public** (service réservé au LAN) : résolution locale
`sso.tclement.fr` → `192.168.42.83` par une **entrée statique du DNS du switch MikroTik CRS112
(`192.168.42.254`)**, le résolveur distribué à tous les postes et aux pairs VPN (avant et après la
bascule RB5009) — `/ip dns static add name=sso.tclement.fr address=192.168.42.83`. Le **LXC 102**
utilise `192.168.42.1` en dur : pour le backend, `extra_hosts: "sso.tclement.fr:192.168.42.83"` dans
le compose de prod (commenté : IP de NPMplus à maintenir), posé à l'activation. Pare-feu DSM : autoriser
`.83` → `.200:5001`. Puis activer **OpenID Connect**, enregistrer l'application
**Matothèque** (adresse de retour `https://ged.tclement.fr/api/auth/callback`, portées
`openid profile email groups`), noter Client ID et Client Secret dans Bitwarden, créer les deux
groupes DSM, y ranger `tclement` (admin) et `MLB` — Marie-Laure — (utilisateurs), retirer à `MLB`
tout droit sur le NAS hors SSO, activer la double authentification sur les comptes. Libellés exacts de DSM 7.2 à
vérifier sur le NAS.

**Acceptation** : la découverte OpenID (`/.well-known/openid-configuration`) du SSO répond depuis le LAN ;
un compte de test appartient à chaque groupe.

## Étape 1 — Implémenter la connexion OpenID Connect (backend)

Réglages en base (`config`) : `oidc_issuer`, `oidc_client_id`, `oidc_client_secret` (**chiffré
Fernet**, `services/crypto.py`), `auth_active` (faux par défaut). Routes `GET /api/auth/login`
(*authorization code* + PKCE + `state` + `nonce`), `GET /api/auth/callback` (vérifie signature via les
clés publiques du SSO, émetteur, audience, expiration, `nonce`), `POST /api/auth/logout`,
`GET /api/auth/me`. **Sessions en base** (table `sessions_auth`) et table `utilisateurs` (`sub`, nom,
e-mail, groupes, connexions) — en base car la prod tourne en `uvicorn --workers 2`. Cookie
`HttpOnly`, `SameSite=Lax`, `Secure` sur la route TLS.

**Acceptation** : tests avec un fournisseur OIDC simulé dans les tests (clés générées, aucun appel
réseau) : jeton valide → session ; signature, émetteur, audience, `nonce` ou expiration faux → refus ;
`state` rejoué → refus.

## Étape 2 — Protéger toutes les routes de l'API (auth + rôles)

Dépendance globale sur `/api/*` : session valide ou jeton d'automate, sinon 401. Liste blanche
explicite : `/api/version`, `/healthz`, `/api/auth/*`, `/api/passerelle/publish` (déjà protégée par
son jeton Bearer). Rôle **admin** exigé sur les routes sensibles (réglages, sauvegarde/restauration,
corbeille définitive, sources, quarantaine des doublons, réorganisation, maintenance, jetons, gestion
de la passerelle). `auth_active = faux` : comportement actuel + bandeau « Authentification
désactivée ». Accès de secours : `python -m outils.auth --suspendre 2h` sur le LXC (journalisé,
réactivation automatique).

**Acceptation** : un test parcourt **toutes** les routes déclarées et échoue si l'une est ouverte hors
liste blanche ; un utilisateur non admin reçoit 403 sur chaque route sensible.

**Exigences de sécurité reportées de la relecture de l'étape 1** (security-reviewer, 31/10/2026) :
1. `PUT/GET /api/system/config` réservés aux **admins** dès que `auth_active` est vrai (clés `oidc_*`,
   `oidc_groupe_*`, `auth_active` comprises) ; passage à faux réservé aux admins et journalisé ; le
   mode `--suspendre` reste local au LXC, jamais exposé par l'API.
2. Liste blanche limitée à `/api/version`, `/healthz`, `/api/auth/login|callback|logout|me`,
   `/api/passerelle/publish` ; le test « toutes les routes » couvre aussi les routeurs montés après
   coup ; aucune route de diagnostic ou de journaux ouverte (`/api/logs/tail`…).
3. **CSRF** sur POST/PUT/PATCH/DELETE : contrôle `Origin` ou `Sec-Fetch-Site` (`SameSite=Lax` ne
   protège pas des sites frères de `tclement.fr`) ; `CORS_ORIGINS` reste une liste explicite.
4. Aucune route `GET` à effet de bord (suppression, lancement de tâche).
5. Rôle et `bloque` relus **en base à chaque requête** ; jamais de confiance dans le frontend.
6. Journaliser les changements de configuration d'authentification (qui, quand), sans secret.
7. **Échec fermé** : session illisible = 401, jamais de bascule silencieuse vers « ouvert » ;
   `auth_active = faux` par défaut doit survivre aux migrations.
8. Conserver la liaison secret client ↔ émetteur lors de la réécriture de l'écran de réglages.
9. Quand un login aboutit à « accès refusé » (retiré du groupe au NAS) pour une personne connue,
   supprimer ses sessions ; test d'usage unique du `state` sous PostgreSQL à deux workers (étape 6).
Étape 3 : valider `end_session_endpoint` (https seulement) avant d'y naviguer ; renvoyer vers la
route TLS **avant** `/api/auth/login` (le cookie de liaison est propre à l'hôte).

**Livrée en v1.146.0 (éteinte).** 158 routes admin / 150 utilisateur (liste figée,
`tests/data/routes_utilisateur.txt`) / 7 en liste blanche ; middleware `services/acces.py` (échec
fermé, 503 tant que les réglages n'ont jamais été lus) ; CSRF par `Origin`/`Sec-Fetch-Site` ;
`outils.auth --etat | --suspendre | --reprendre | --eteindre` sur le LXC.

**Avant l'ACTIVATION (security-reviewer, 31/10/2026)** :
1. Tester sur la prod la sortie de verrouillage `python -m outils.auth --eteindre`.
2. `CORS_ORIGINS` explicite en prod (`https://ged.tclement.fr,http://192.168.42.83:3003`, sans
   `localhost`) ; une écriture testée par chacune des deux routes ; 403 vérifié pour une origine étrangère.
3. Une première connexion réelle d'un admin par le SSO (la garde d'activation l'exige) ;
   `extra_hosts: sso.tclement.fr:192.168.42.83` dans le compose de prod.
4. Écran « Bloquer / Déconnecter partout » (étape 3), ou `auth_session_max_jours` réduit à 1–2.
5. Suspension de secours documentée : 24 h max, ouvre tout sauf les réglages d'authentification.
6. Recommandé : liste blanche des types servis en aperçu inline (`/documents/{id}/file`,
   couvertures du wiki). ~~Filtre SSRF des flux RSS~~ : **fait en v1.147.0** — toute adresse non
   publique est refusée, redirections comprises (`services/destination_publique.py`) ; un flux du
   LAN à autoriser se décidera au cas par cas (décision du 31/10/2026).

**Décision du 31/10/2026 (v1.147.0)** : l'utilisateur (MLB) accède à emploi à domicile, congés,
fiscalité et maison — 45 routes passées au rôle utilisateur (113 admin / 195 utilisateur / 7 en
liste blanche). Leurs réglages (jeton Home Assistant, etc.) restent sous `/api/system` → admin.

## Étape 3 — Ajouter l'écran de connexion et le menu utilisateur (frontend)

Au premier 401 : écran « Se connecter » vers `/api/auth/login`, retour sur la page d'origine.
En-tête : nom, rôle, « Se déconnecter ». Page *Paramètres › Utilisateurs* (admins) décrite plus
haut, avec « Déconnecter partout » et « Bloquer dans Matothèque ». Éléments admin masqués pour les utilisateurs (le serveur
reste la barrière). Vérifié par la route HTTP comme par la route TLS.

**Acceptation** : `tsc` et vitest passent ; parcours connexion → navigation → déconnexion vérifié en
pile jetable.

## Étape 4 — Implémenter les jetons d'automates

Table `jetons_api` : nom, **empreinte** (jeton montré une seule fois, même modèle que la passerelle
wiki), portée `lecture` / `ecriture`, créateur, dernière utilisation, expiration, révocation ;
gestion dans *Paramètres* (admins). Workflows **n8n** à mettre à jour (ils visent encore l'ancienne
adresse `192.168.42.200:8000`).

**Acceptation** : un jeton révoqué ou expiré est refusé ; un jeton `lecture` reçoit 403 sur une
écriture ; le jeton en clair n'est stocké nulle part.

## Étape 5 — Tracer l'identité dans le journal d'audit

Chaque action qui modifie ou exporte porte l'identité (personne ou jeton) dans le journal d'audit
existant ; durée de conservation à choisir (point ROADMAP « Journaux › Traçabilité »).

**Acceptation** : une suppression, un changement de réglage et un export apparaissent au journal avec
l'auteur.

## Étape 6 — Vérifier de bout en bout et documenter

Pile jetable (`/verify`) avec fournisseur OIDC simulé : connexion, rôles, jetons, journal, déconnexion,
par les deux routes. Puis CHANGELOG, ROADMAP, aide utilisateur. Déploiement **éteint**
(`auth_active = faux`) ; l'activation est une étape applicative faite avec l'utilisateur.

**Acceptation** : parcours vert ; la prod n'est jamais verrouillée au déploiement.

## Pièges connus

- **Deux routes d'accès** (TLS / HTTP du LAN) : cookie `Secure` absent en HTTP, adresse de retour à
  déclarer au SSO → décision n° 2.
- **Multi-process** : sessions et `state` OIDC en base, jamais en mémoire.
- **Horloges** NAS / LXC : tolérance de quelques minutes, NTP vérifié.
- **Ne jamais verrouiller la prod au déploiement.**
