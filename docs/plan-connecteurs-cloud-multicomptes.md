# Plan — Connecteurs cloud multi-comptes (lecture + indexation)

> Objectif (demande user 12/07) : interconnecter Matothèque avec **Dropbox, Google Drive,
> Synology Drive, OneDrive…** en **LECTURE**, avec la possibilité d'enregistrer **plusieurs
> comptes par fournisseur** (ex. 2 Google Drive : perso + pro). Chaque compte/lecteur connecté
> est **indexable dynamiquement** comme une source NAS/SMB actuelle. **Ajout/retrait à chaud.**
>
> Ce plan étend la section « Connecteurs de sources externes » de la ROADMAP en y ajoutant la
> dimension **multi-comptes dynamique** et **Synology Drive**.

## 1. Principe directeur : 1 compte connecté = 1 `Source`

Le modèle `Source` abstrait déjà `type` (`local | smb`). On **réutilise cette abstraction** : un
**compte cloud connecté = une ligne `Source`**. Le multi-comptes est donc **natif** — il suffit
d'autoriser N `Source` du même `type`, chacune avec son **libellé** et ses **secrets/jetons propres**.

**Extensions du modèle `Source`** :
- `type` élargi : `gdrive | dropbox | onedrive | sharepoint | synology | webdav | box | nextcloud`.
- `libelle` : nom lisible choisi par l'utilisateur (« Google Drive — perso », « Dropbox — asso »).
- `compte` : identité distante (email/login) pour distinguer les comptes d'un même fournisseur.
- `secret_chiffre` (déjà là, Fernet) : stocke **jetons OAuth** (access+refresh) OU identifiants
  WebDAV/Synology, en JSON chiffré.
- `oauth_expire_at` : date d'expiration de l'access token (pour l'état « expiré » + refresh auto).
- `racine` / `dossiers_indexes` : sous-arbre(s) sélectionné(s) à indexer (JSON de chemins/ids distants).
- `actif`, `derniere_synchro`, `intervalle_synchro` (réutilise/rejoint « Indexation dynamique »).

> Aucune table nouvelle : tout tient dans `Source` (+ quelques colonnes). Migration Alembic idempotente.

## 2. Interface commune `SourceConnector`

Un connecteur par `type`, même contrat que `smb_service.py` :

```python
class SourceConnector(Protocol):
    async def test(self, src: Source) -> bool: ...
    async def list_roots(self, src: Source) -> list[dict]: ...          # lecteurs/dossiers racine
    async def browse(self, src: Source, path: str) -> list[dict]: ...    # {nom, dossier, taille, id}
    async def walk_files(self, src: Source, path: str, exts) -> list[dict]: ...  # récursif → {rel/id, taille}
    async def fetch_to_temp(self, src: Source, ref: str) -> str: ...     # télécharge en /tmp (éphémère)
```

- **Registre** `type → connector` (comme le registre de handlers de jobs).
- Le pipeline d'indexation existant (`handler_indexation` → `process_file`) est **inchangé** : il
  appelle `connector.walk_files` puis `connector.fetch_to_temp` (au lieu de `smb_service`), traite le
  fichier en **temporaire local** (fetch éphémère, zéro doublon), puis supprime le temp.
- **LECTURE SEULE** : corbeille/quarantaine/réorg-write **désactivées** pour ces sources (garde-fou).

## 3. Authentification (par fournisseur)

| Fournisseur | Auth | Scope lecture | Notes |
|-------------|------|---------------|-------|
| **Google Drive** | OAuth2 | `drive.readonly` | *prioritaire* (réf.). Refresh token longue durée. |
| **Dropbox** | OAuth2 | `files.content.read` | API v2. |
| **OneDrive / SharePoint** | OAuth2 (MS Graph) | `Files.Read.All` | idem tenant pro. |
| **Box** | OAuth2 | lecture | |
| **Synology Drive / NAS** | **Auth** : (a) **WebDAV** `login+mdp` ; (b) **API DSM FileStation** (`SYNO.API.Auth` + FileStation). **Transport (comment ATTEINDRE le NAS)** : LAN/IP directe · DDNS/port-forward · **QuickConnect** (relais Synology, **sans ouvrir de port**) | lecture | Démarrer par **WebDAV en LAN**. **QuickConnect** = surtout utile hors LAN : on résout l'ID `xxx.quickconnect.to` → adresse relais, puis auth DSM (lib `synology-api` gère la résolution QuickConnect). Combinable avec WebDAV **ou** FileStation. |
| **Nextcloud / ownCloud / kDrive / WebDAV générique** | Basic/App-password | lecture | couvre beaucoup de NAS auto-hébergés. |

**Flux OAuth** (backend) : `POST /connectors/{type}/oauth/start` → URL d'autorisation ; callback
`GET /connectors/oauth/callback` → échange code↔jetons → **crée une `Source`** (jetons chiffrés) +
libellé/compte récupérés du profil distant. **Refresh** automatique quand `oauth_expire_at` proche.

**Non-OAuth** (WebDAV/Synology-WebDAV) : formulaire `URL + login + mot de passe` → `Source` chiffrée.

### 3 bis. Synology — implémentation concrète (réf. `O:\Github\acces-syno`)

**Un client Synology complet existe déjà** dans `O:\Github\acces-syno` (`backend/synology/`) — à **porter**
quasi tel quel pour le connecteur `synology`. Il couvre les 3 briques dont on a besoin :

| Brique | Fichier réf. | Ce qu'il fait → mapping `SourceConnector` |
|--------|--------------|--------------------------------------------|
| **QuickConnect** | `quickconnect.py` | `resolve(qc_id)` interroge `POST https://global.quickconnect.to/Serv.php` (`command=get_server_info`) → candidats **lan / direct / relay** ; `find_reachable()` teste TCP 5001 (timeout court) et renvoie la 1ʳᵉ URL joignable, avec **cache TTL**. → sert à obtenir la `base_url` avant `test/browse/fetch`. |
| **Auth DSM** | `auth.py` | `SYNO.API.Auth` (`method=login`, `session=FileStation`, `format=sid`) → **SID** ; **cache SID** (TTL 900 s) + `logout`. → `SourceConnector.test` + jeton de session réutilisé. |
| **FileStation** | `filestation.py` | `list_entries(path)` (`list_share` à la racine, sinon `list`) → `{name, path, isdir, size}` ; `file_info` (taille) ; `download_file` (**stream** via `SYNO.FileStation.Download`). → `list_roots` / `browse` / `walk_files` / `fetch_to_temp`. |

**Stratégie de connexion** (reprise de leur `settings.yaml` → `connection_priority`) : `lan` → `direct` → `relay`.
En LAN on peut d'ailleurs sauter QuickConnect (IP directe). **Secrets à stocker chiffrés** dans la `Source` :
`{qc_id | base_url, account, password}` (jamais le SID, qui est recalculé et caché).

**Limites notées par acces-syno** (à reprendre) : NAS en CGNAT = **relais uniquement** (débit limité) ; résolveur
QuickConnect **lent (1-3 s)** → cache ; endpoint QC **non officiel** (reverse-engineering) → à monitorer ;
repli DDNS/IP directe si QC indisponible.

> Voir aussi, dans ce repo réf. : `docs/quickconnect-resolver.md`, `docs/api-synology-notes.md`, `scripts/poc_synology.py`.

## 4. API backend

```
GET   /connectors                      # fournisseurs disponibles + capacités (oauth|creds)
POST  /connectors/{type}/oauth/start    # → {authorize_url}
GET   /connectors/oauth/callback        # échange le code → crée la Source
POST  /connectors/webdav                # (type webdav/synology) créer une Source par identifiants
GET   /sources?type=cloud               # liste des comptes connectés (réutilise /sources)
POST  /sources/{id}/roots               # lister lecteurs/dossiers racine (choix des dossiers)
PUT   /sources/{id}/dossiers            # enregistrer les dossiers à indexer
POST  /sources/{id}/index               # indexer (Job durable) — réutilise l'existant
DELETE /sources/{id}                    # déconnecter (révoque + supprime la Source)
```

> `/sources/*` existe déjà pour local/smb → on **réutilise** au maximum (browse/index/delete).

## 5. UI — section « Connecteurs » dans Paramètres

- Liste des **fournisseurs**, chacun dépliable montrant **ses comptes connectés** (N par fournisseur) :
  - par compte : **libellé**, **identité** (email), **état** (🟢 connecté / 🟠 expiré → « Reconnecter »),
    **dossiers indexés**, **dernière synchro**, boutons **Indexer / Synchroniser / Déconnecter**.
  - bouton **« + Ajouter un compte »** par fournisseur → OAuth (popup) ou formulaire identifiants.
- Sélecteur de dossiers distants (réutilise un picker type `SmbFolderPicker`, adapté aux `list_roots/browse`).
- Cohérence visuelle avec la section « Sources NAS/SMB » existante.

## 6. Indexation dynamique

- Chaque **synchro = un Job durable** (worker dédié déjà en place) → pas de gel API.
- **Incrémental** : comparer `date_modification`/hash distant vs indexé ; ne re-fetch que le nouveau/modifié.
- **Périodicité par compte** (`intervalle_synchro`) + bouton « Synchroniser maintenant ».
- Réutilise le futur « Indexation dynamique / n8n / FolderWatcher » (même mécanique).

## 7. Sécurité

- Jetons/identifiants **chiffrés en base** (Fernet, `crypto.py`) ; jamais renvoyés en clair par l'API (masqués).
- **Lecture seule** stricte (aucune écriture distante).
- OAuth : scopes **minimaux** (`*.readonly`), refresh côté backend, révocation à la déconnexion.
- 100 % local ailleurs : toute connexion OAuth = **action réseau confirmée** (cohérent avec la politique projet).

## 8. Phasage proposé

- **P0 — socle** : élargir `Source` (colonnes + type), interface `SourceConnector` + registre, plomberie
  OAuth (start/callback/refresh), section UI « Connecteurs » (liste + multi-comptes + déconnexion).
- **P1 — Google Drive** (référence OAuth) : connecteur complet + indexation bout-en-bout.
- **P2 — WebDAV générique + Synology Drive (via WebDAV)** : couverture large NAS/kDrive/Nextcloud.
- **P3 — Dropbox**, puis **OneDrive/SharePoint (Graph)**, puis **Box**.
- **P4 — Digiposte** (à part, éligibilité API à valider d'abord).

## 9. Points ouverts / à valider

- Google Drive **Shared Drives** (Drive partagés d'équipe) : scope/param supplémentaires.
- Fichiers **Google natifs** (Docs/Sheets) : pas de binaire direct → **export** (PDF/DOCX) à l'indexation.
- Synology : privilégier **WebDAV** (simple) ou l'**API FileStation** (plus riche, paquet requis) ? → WebDAV d'abord.
- Volume : ne pas rapatrier des Go inutiles → **catalogage léger des gros médias** (comme SMB déjà fait).
