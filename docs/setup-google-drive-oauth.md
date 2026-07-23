# Prérequis — créer l'app OAuth Google Drive (avant le connecteur)

> À faire **une seule fois** par toi (Google Cloud Console). Une **seule app** suffit pour **tous
> tes comptes Google** (multi-comptes : chaque compte fera son propre consentement → son propre
> jeton → sa propre `Source`). Ensuite je code le connecteur Drive + le flow OAuth et on **teste en réel**.

## Étapes (console.cloud.google.com)

1. **Projet** : crée (ou sélectionne) un projet, ex. « Matotheque ».
2. **Activer l'API Drive** : *APIs & Services → Library* → cherche **Google Drive API** → **Enable**.
3. **Écran de consentement OAuth** : *APIs & Services → OAuth consent screen*
   - Type : **External** (ou Internal si Google Workspace).
   - Nom de l'app : « Matothèque », e-mail de support = le tien.
   - **Scopes** : ajoute `.../auth/drive.readonly` (lecture seule).
   - **Test users** : ajoute **les adresses Google** que tu veux connecter (perso, pro…). *(En mode
     « Testing » seuls ces comptes peuvent se connecter — parfait pour un usage perso/interne.)*
4. **Identifiants** : *APIs & Services → Credentials → Create credentials → OAuth client ID*
   - Type : **Web application**.
   - **Authorized redirect URIs** — ajoute EXACTEMENT (les deux si besoin) :
     - Dev : `http://localhost:8000/api/connectors/oauth/callback`
     - Prod : `https://<ton-domaine>/api/connectors/oauth/callback`
   - Crée → **copie le Client ID et le Client Secret**.

## Ce que tu me renvoies

- **Client ID** (`xxxxx.apps.googleusercontent.com`)
- **Client Secret**
- La (les) **redirect URI** exacte(s) que tu as enregistrée(s)

*(Ils seront stockés **chiffrés** en base — comme les autres secrets. Le secret n'est jamais renvoyé en clair.)*

## Ce que je code ensuite (P1)

- Config `google_oauth_client_id` / `google_oauth_client_secret` (chiffré) dans Paramètres.
- `GET /api/connectors/gdrive/oauth/start` → URL d'autorisation Google (scope `drive.readonly`, `access_type=offline` pour obtenir un **refresh token**).
- `GET /api/connectors/oauth/callback` → échange du code → **crée une `Source`** (refresh token chiffré, compte = e-mail Google).
- Connecteur `gdrive` (interface `SourceConnector`) : Drive API v3 `files.list` (pagination), `files.get?alt=media` (téléchargement), **export** des fichiers Google natifs (Docs→PDF/DOCX, Sheets→XLSX) à l'indexation. Refresh automatique du token.
- Multi-comptes : 1 consentement Google = 1 `Source` → plusieurs comptes gérés côté UI.

> Scope **lecture seule** (`drive.readonly`) — aucune écriture sur ton Drive.

---

## Côté Matothèque (une fois l'app créée) — LIVRÉ v1.31.0

1. **Paramètres → Sources & indexation → Connecteurs cloud** : colle **Client ID** + **Client
   secret**, puis **Enregistre** (secret chiffré en base).
2. **URI de redirection** : en PROD (derrière NPMplus), renseigne aussi `oauth_redirect_uri` avec
   l'URL EXACTE enregistrée dans Google, ex. `https://ged.tclement.fr/api/connectors/oauth/callback`
   (en dev elle est déduite automatiquement). *(Ajoutable via `PUT /api/system/config`.)*
3. **Connecter un compte** : bouton « Connecter un compte Google » → consentement Google →
   retour automatique. Chaque compte = une **Source** `gdrive` (multi-comptes).
4. **Indexer** : bouton « Indexer » sur le compte → tâche durable (comme le NAS). Les documents
   Google natifs (Docs/Sheets/Slides) sont **exportés** (PDF/xlsx/pptx) avant analyse.

⚠️ **Connecteur cloud** = accès réseau sortant vers Google (oauth2.googleapis.com, googleapis.com)
— autorisé par ta demande (hors du « 100 % local » habituel).

### Test de bout en bout (à faire ensemble)
`GET /api/connectors/oauth/start` doit renvoyer une **URL** (et non « Client ID absent »).
Après consentement : un compte apparaît dans la liste → « Indexer » → les fichiers Drive
arrivent dans la GED sous `gdrive://<source>/<id>/<nom>`.
